#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
StreamReceiver ottimizzato per la ricezione di flussi video a latenza ultra-bassa.
Implementa tecniche avanzate di buffering, threading e pipeline di decodifica
per garantire zero-lag nella visualizzazione e nell'elaborazione dei frame.
"""

import logging
import time
import threading
import cv2
import json
import uuid
import numpy as np
import concurrent.futures
from typing import Dict, Any, Optional, Callable, Set, Deque
from collections import deque
import zmq
from PySide6.QtCore import QObject, Signal, Slot, QTimer, QMutex, QMutexLocker, QThread

# Configurazione logging
logger = logging.getLogger(__name__)

# Dimensione buffer di decodifica ottimale
DECODE_POOL_SIZE = max(4, cv2.getNumberOfCPUs())


class ZeroLatencyDecoder:
    """
    Decoder ottimizzato per decodifica JPEG parallela a bassissima latenza.
    Implementa pipeline con prefetch intelligente e prioritizzazione dinamica.
    """

    def __init__(self, max_workers=None):
        """
        Inizializza il decoder parallelo.

        Args:
            max_workers: Numero massimo di thread per la decodifica
        """
        self.max_workers = max_workers or DECODE_POOL_SIZE
        self._thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers)
        self._pending_futures = {}
        self._mutex = QMutex()

        # Coda di alta priorità (più recente = più importante)
        self._priority_queue = deque(maxlen=4)

        # Performance stats
        self._decode_times = deque(maxlen=50)

        # Preallocazione buffer per evitare frammentazione memoria
        self._preallocated_buffers = {}

        logger.info(f"ZeroLatencyDecoder inizializzato con {self.max_workers} worker")

    def decode_frame(self, frame_data, camera_idx, timestamp,
                     priority=False, callback=None):
        """
        Decodifica un frame in modo asincrono.

        Args:
            frame_data: Dati JPEG compressi
            camera_idx: Indice camera
            timestamp: Timestamp del frame
            priority: Se True, decodifica con alta priorità
            callback: Funzione chiamata al completamento
        """
        with QMutexLocker(self._mutex):
            # Per frame ad alta priorità, cancella lavori pendenti meno importanti
            if priority and self._pending_futures:
                # Solo per la stessa camera
                for fut, info in list(self._pending_futures.items()):
                    if info['camera_idx'] == camera_idx and not info['priority']:
                        fut.cancel()
                        del self._pending_futures[fut]

            # Crea buffer di decodifica ottimale
            if isinstance(frame_data, bytes) or isinstance(frame_data, bytearray):
                if camera_idx not in self._preallocated_buffers:
                    # Preloca molteplici buffer per camera per evitare contesa
                    self._preallocated_buffers[camera_idx] = [
                        np.empty((1024, 1024, 3), dtype=np.uint8)
                        for _ in range(4)
                    ]

                # Preleva buffer libero
                buffer_index = timestamp % 4  # Round-robin tra buffer
                buffer = self._preallocated_buffers[camera_idx][buffer_index]

                # Submit in thread pool
                future = self._thread_pool.submit(
                    self._decode_jpeg_optimized, frame_data, buffer, camera_idx
                )

                # Salva info future
                self._pending_futures[future] = {
                    'camera_idx': camera_idx,
                    'timestamp': timestamp,
                    'callback': callback,
                    'priority': priority,
                    'start_time': time.time()
                }

                # Setup callback
                future.add_done_callback(self._on_decode_completed)

    def _decode_jpeg_optimized(self, jpeg_data, output_buffer, camera_idx):
        """
        Decodifica JPEG ottimizzata con minimo overhead.

        Args:
            jpeg_data: Dati JPEG compressi
            output_buffer: Buffer preallocato
            camera_idx: Indice camera per debugging

        Returns:
            Frame decodificato
        """
        start_time = time.time()

        try:
            # Alloca buffer esattamente della dimensione necessaria
            buffer = np.frombuffer(jpeg_data, dtype=np.uint8)

            # Imdecode con flag performance
            frame = cv2.imdecode(buffer, cv2.IMREAD_UNCHANGED)

            # Misura tempo di decodifica
            decode_time = (time.time() - start_time) * 1000
            with QMutexLocker(self._mutex):
                self._decode_times.append(decode_time)

            # Verifica che la decodifica sia riuscita
            if frame is None or frame.size == 0:
                logger.warning(f"Decodifica fallita per camera {camera_idx}")
                return None

            return frame

        except Exception as e:
            logger.error(f"Errore nella decodifica per camera {camera_idx}: {e}")
            return None

    def _on_decode_completed(self, future):
        """Callback chiamata quando una decodifica è completata."""
        try:
            # Estrai frame
            frame = future.result()

            with QMutexLocker(self._mutex):
                if future not in self._pending_futures:
                    return  # Può accadere se cancellato

                info = self._pending_futures.pop(future)
                camera_idx = info['camera_idx']
                timestamp = info['timestamp']
                callback = info['callback']

                # Calcola latenza di decodifica
                decode_latency = (time.time() - info['start_time']) * 1000

                # Callback con frame decodificato
                if callback and frame is not None:
                    try:
                        callback(camera_idx, frame, timestamp, decode_latency)
                    except Exception as e:
                        logger.error(f"Errore nella callback di decodifica: {e}")

        except concurrent.futures.CancelledError:
            # Normale per task cancellati
            pass
        except Exception as e:
            logger.error(f"Errore in _on_decode_completed: {e}")

    def get_stats(self):
        """Restituisce statistiche di decodifica."""
        with QMutexLocker(self._mutex):
            decode_times = list(self._decode_times)
            pending_count = len(self._pending_futures)

        if decode_times:
            avg_decode_time = sum(decode_times) / len(decode_times)
            max_decode_time = max(decode_times)
        else:
            avg_decode_time = 0
            max_decode_time = 0

        return {
            'avg_decode_time_ms': avg_decode_time,
            'max_decode_time_ms': max_decode_time,
            'pending_decodes': pending_count,
            'decoder_workers': self.max_workers
        }

    def shutdown(self):
        """Cleanup e chiusura."""
        self._thread_pool.shutdown(wait=False)
        logger.info("ZeroLatencyDecoder shutdown")


class StreamReceiver(QObject):
    """
    Gestisce la ricezione di stream video con focus su zero-latenza.
    Ottimizzato per l'integrazione diretta con ScanFrameProcessor.
    """

    # Segnali
    frame_received = Signal(int, np.ndarray, float)  # camera_index, frame, timestamp
    scan_frame_received = Signal(int, np.ndarray, dict)  # camera_index, frame, frame_info
    connected = Signal()
    disconnected = Signal()
    error = Signal(str)  # error_message

    def __init__(self, ip_address: str, port: int):
        """
        Inizializza il ricevitore di stream.

        Args:
            ip_address: Indirizzo IP del server
            port: Porta per lo streaming
        """
        super().__init__()
        self.ip_address = ip_address
        self.port = port
        self._receiver_thread = None
        self._is_receiving = False
        self._cameras_active = set()

        # Decoder ottimizzato per latenza minima
        self._decoder = ZeroLatencyDecoder()

        # Riferimento al processore di frame
        self._frame_processor = None

        # Flag per routing diretto e altre ottimizzazioni
        self._direct_routing = True
        self._request_dual_camera = True
        self._low_latency_mode = True

        # Buffer frame circolari per ogni camera
        self._frame_buffers = {}
        self._last_frame_time = {}

        # Statistiche
        self._stats = {
            'received_frames': 0,
            'dropped_frames': 0,
            'decode_queue': 0,
            'decode_time_ms': 0,
            'end_to_end_latency_ms': 0
        }

        # Inizializza flag di stato
        self._stream_initialized = False

    def set_frame_processor(self, processor):
        """
        Imposta un processore di frame per l'invio diretto dei dati,
        bypassando i segnali Qt per migliorare le prestazioni.

        Args:
            processor: Istanza di ScanFrameProcessor
        """
        self._frame_processor = processor
        logger.info("Frame processor impostato per routing diretto")

    def start(self):
        """Avvia la ricezione dello stream con recovery automatico."""
        if self._is_receiving:
            logger.warning("StreamReceiver già avviato")
            return

        try:
            # Prima assicurati che non ci siano thread attivi
            self.stop()

            # Crea e avvia un nuovo thread
            self._receiver_thread = StreamReceiverThread(
                self.ip_address,
                self.port,
                direct_routing=self._direct_routing,
                request_dual_camera=self._request_dual_camera,
                low_latency_mode=self._low_latency_mode
            )

            # Passa il processore di frame al thread per routing diretto
            if self._frame_processor:
                try:
                    self._receiver_thread.set_frame_processor(self._frame_processor)
                    logger.info("Frame processor impostato nel thread")
                except Exception as e:
                    logger.error(f"Errore nell'impostazione del frame processor: {e}")

            # Collega i segnali
            self._receiver_thread.frame_decoded.connect(self._on_frame_decoded)
            self._receiver_thread.scan_frame_received.connect(self._on_scan_frame_received)
            self._receiver_thread.connection_state_changed.connect(self._on_connection_state_changed)
            self._receiver_thread.error_occurred.connect(self._on_error)

            # Avvia il thread
            self._receiver_thread.start()
            self._is_receiving = True

            logger.info(f"StreamReceiver avviato per {self.ip_address}:{self.port}")

            # Imposta flag di inizializzazione
            self._stream_initialized = True

        except Exception as e:
            logger.error(f"Errore nell'avvio dello StreamReceiver: {e}")
            self.error.emit(f"Errore nell'avvio dello streaming: {str(e)}")
            self._is_receiving = False

    def enable_direct_routing(self, enabled: bool):
        """
        Abilita o disabilita il routing diretto dei frame al processore.

        Args:
            enabled: True per abilitare il routing diretto, False per disabilitarlo
        """
        self._direct_routing = enabled
        if self._receiver_thread:
            self._receiver_thread.set_direct_routing(enabled)

        if enabled:
            logger.info("Routing diretto dei frame abilitato per alte prestazioni")
        else:
            logger.info("Routing diretto disabilitato, utilizzo segnali Qt standard")

    def request_dual_camera(self, enabled: bool):
        """
        Specifica se richiedere streaming da entrambe le camere.

        Args:
            enabled: True per richiedere dual camera
        """
        self._request_dual_camera = enabled
        if self._receiver_thread:
            self._receiver_thread.request_dual_camera(enabled)

    def set_low_latency_mode(self, enabled: bool):
        """
        Imposta modalità a bassa latenza con ottimizzazione aggressive.

        Args:
            enabled: True per abilitare modalità bassa latenza
        """
        self._low_latency_mode = enabled
        if self._receiver_thread:
            self._receiver_thread.set_low_latency_mode(enabled)

    def stop(self):
        """Ferma la ricezione dello stream e libera le risorse."""
        logger.info("Arresto StreamReceiver...")

        if not self._is_receiving:
            logger.debug("StreamReceiver già arrestato")
            return

        try:
            # Pulisci i segnali prima di arrestare il thread
            if self._receiver_thread:
                try:
                    self._receiver_thread.frame_decoded.disconnect()
                    self._receiver_thread.scan_frame_received.disconnect()
                    self._receiver_thread.connection_state_changed.disconnect()
                    self._receiver_thread.error_occurred.disconnect()
                except Exception as e:
                    logger.debug(f"Errore nella disconnessione dei segnali: {e}")

            # Ferma il thread di ricezione
            if self._receiver_thread and self._receiver_thread.isRunning():
                # Prima imposta il flag di stop
                self._receiver_thread.stop()

                # Attendi la terminazione con timeout
                if not self._receiver_thread.wait(3000):  # 3 secondi di timeout
                    logger.warning("Timeout nell'arresto del thread di streaming, forzando terminazione")
                    self._receiver_thread.terminate()
                    self._receiver_thread.wait(1000)  # Attendi ancora un secondo

            # Cleanup decoder
            if hasattr(self, '_decoder') and self._decoder:
                self._decoder.shutdown()

            # Reset stato
            self._is_receiving = False
            self._cameras_active.clear()
            self._receiver_thread = None

            logger.info("StreamReceiver arrestato con successo")

        except Exception as e:
            logger.error(f"Errore nell'arresto dello StreamReceiver: {e}")
            self._is_receiving = False
            self._cameras_active.clear()
            self._receiver_thread = None

    def is_active(self) -> bool:
        """Verifica se lo streaming è attivo."""
        return self._is_receiving and self._receiver_thread and self._receiver_thread.isRunning()

    def is_initialized(self) -> bool:
        """Verifica se lo streaming è stato inizializzato."""
        return self._stream_initialized

    def cameras_active(self) -> set:
        """Restituisce l'insieme delle camere attive."""
        if self._receiver_thread:
            return self._receiver_thread.cameras_active
        return set()

    @Slot(int, np.ndarray, float)
    def _on_frame_decoded(self, camera_index: int, frame: np.ndarray, timestamp: float):
        """Gestisce un frame decodificato."""
        # Aggiorna l'insieme delle camere attive
        self._cameras_active.add(camera_index)

        # Calcola latenza end-to-end
        latency_ms = (time.time() - timestamp) * 1000
        self._stats['end_to_end_latency_ms'] = latency_ms

        # Log periodico prestazioni
        if camera_index == 0 and self._stats['received_frames'] % 100 == 0:
            logger.debug(f"Latenza streaming: {latency_ms:.1f}ms, " +
                         f"Frames: {self._stats['received_frames']}")

        # Propaga il segnale
        self.frame_received.emit(camera_index, frame, timestamp)

        # Incrementa contatore
        self._stats['received_frames'] += 1

    @Slot(int, np.ndarray, dict)
    def _on_scan_frame_received(self, camera_index: int, frame: np.ndarray, frame_info: dict):
        """Gestisce un frame di scansione ricevuto."""
        # Aggiorna l'insieme delle camere attive
        self._cameras_active.add(camera_index)

        # Routing diretto al processore se configurato
        if self._direct_routing and self._frame_processor:
            if hasattr(self._frame_processor, 'process_frame'):
                # Invia direttamente al processore per minimizzare latenza
                self._frame_processor.process_frame(camera_index, frame, frame_info)
                return

        # Fallback: propaga il segnale
        self.scan_frame_received.emit(camera_index, frame, frame_info)

    @Slot(bool)
    def _on_connection_state_changed(self, connected: bool):
        """Gestisce il cambiamento dello stato della connessione."""
        if connected:
            logger.info("StreamReceiver connesso")
            self.connected.emit()
        else:
            logger.info("StreamReceiver disconnesso")
            self.disconnected.emit()
            self._cameras_active.clear()

    @Slot(str)
    def _on_error(self, error_message: str):
        """Gestisce un errore."""
        logger.error(f"Errore nello StreamReceiver: {error_message}")
        self.error.emit(error_message)

    def get_performance_stats(self) -> dict:
        """Ottiene statistiche dettagliate sulle prestazioni."""
        stats = self._stats.copy()

        # Aggiungi statistiche di decodifica
        if hasattr(self, '_decoder') and self._decoder:
            stats.update(self._decoder.get_stats())

        # Aggiungi statistiche thread
        if self._receiver_thread:
            thread_stats = self._receiver_thread.get_performance_stats()
            stats.update(thread_stats)

        stats['is_active'] = self.is_active()
        stats['cameras_active'] = len(self._cameras_active)

        return stats


class StreamReceiverThread(QThread):
    """
    Thread dedicato ottimizzato per la ricezione di stream video ZMQ.
    Implementa tecniche avanzate per ridurre la latenza e il jitter.
    """

    # Segnali
    frame_decoded = Signal(int, np.ndarray, float)  # camera_index, frame, timestamp
    scan_frame_received = Signal(int, np.ndarray, dict)  # camera_index, frame, frame_info
    connection_state_changed = Signal(bool)  # connected
    error_occurred = Signal(str)  # error_message

    def __init__(self, host: str, port: int, direct_routing=True,
                 request_dual_camera=True, low_latency_mode=True):
        """
        Inizializza il thread ricevitore ZMQ.

        Args:
            host: Indirizzo del server
            port: Porta di streaming
            direct_routing: Se abilitare routing diretto frames
            request_dual_camera: Se richiedere stream da entrambe le camere
            low_latency_mode: Se attivare ottimizzazioni aggressive latenza
        """
        super().__init__()
        self.host = host
        self.port = port
        self._running = False
        self._context = None
        self._socket = None
        self._connected = False
        self.cameras_active = set()

        # Lock per thread safety
        self._mutex = QMutex()

        # Zero-copy ottimizzato se supportato
        self._use_zero_copy = True

        # Decoder ottimizzato
        self._decoder = ZeroLatencyDecoder()

        # Configurazione
        self._direct_routing = direct_routing
        self._request_dual_camera = request_dual_camera
        self._low_latency_mode = low_latency_mode
        self._frame_processor = None

        # Statistiche
        self._frames_received = 0
        self._processing_lag = 0.0
        self._frame_times = {}

        # Strategia scarto frame intelligente
        self._frame_history = {}

    def set_direct_routing(self, enabled):
        """Imposta routing diretto."""
        with QMutexLocker(self._mutex):
            self._direct_routing = enabled

    def request_dual_camera(self, enabled):
        """Richiede streaming dual camera."""
        with QMutexLocker(self._mutex):
            self._request_dual_camera = enabled

    def set_low_latency_mode(self, enabled):
        """Imposta modalità bassa latenza."""
        with QMutexLocker(self._mutex):
            self._low_latency_mode = enabled

    def set_frame_processor(self, processor):
        """Imposta processore frame per routing diretto."""
        self._frame_processor = processor

    def stop(self):
        """Ferma il thread di ricezione."""
        with QMutexLocker(self._mutex):
            self._running = False

        logger.info("Richiesta arresto StreamReceiverThread")

    def run(self):
        """
        Loop principale di ricezione con ottimizzazioni bassa latenza.
        Implementa:
        - Controllo di flusso adattivo
        - Frame skipping intelligente
        - Pipelining decodifica-elaborazione
        - Prioritizzazione frame recenti
        """
        logger.info(f"Avvio thread di ricezione ZMQ per {self.host}:{self.port}")

        try:
            # Aumenta priorità thread se possibile
            self._set_thread_priority_high()

            # Reset stato
            self._frames_received = 0
            self._frame_history = {}
            self._frame_times = {}

            # Segnala l'avvio
            with QMutexLocker(self._mutex):
                self._running = True

            # Loop principale con recovery automatico
            while self._running:
                try:
                    # Inizializza ZMQ
                    self._init_zmq_socket()

                    # Segnala connessione
                    with QMutexLocker(self._mutex):
                        self._connected = True
                    self.connection_state_changed.emit(True)

                    # Invio config iniziale
                    self._send_stream_config()

                    # Loop di ricezione
                    self._receive_loop()

                except zmq.ZMQError as e:
                    logger.error(f"ZMQ error: {e}")
                    # Breve attesa prima di riconnettere
                    time.sleep(2.0)
                except Exception as e:
                    logger.error(f"Errore nel thread ricevitore: {e}")
                    time.sleep(2.0)
                finally:
                    # Cleanup
                    self._cleanup_socket()

                    # Segnala disconnessione
                    with QMutexLocker(self._mutex):
                        if self._connected:
                            self._connected = False
                            self.connection_state_changed.emit(False)

                    # Se ancora running, attendi e ritenta
                    if self._running:
                        logger.info("Riconnessione in 2 secondi...")
                        time.sleep(2.0)

        except Exception as e:
            logger.error(f"Errore fatale nel thread ricevitore: {e}")
            self.error_occurred.emit(f"Errore fatale: {str(e)}")

        finally:
            # Cleanup finale
            self._cleanup_socket()

            # Cleanup decoder
            if self._decoder:
                self._decoder.shutdown()

            logger.info("Thread ricevitore terminato")

    def _set_thread_priority_high(self):
        """Aumenta priorità del thread per bassa latenza."""
        try:
            # Imposta priorità alta (system specific)
            self.setPriority(QThread.HighestPriority)

            # In sistemi Unix, prova anche con nice
            try:
                import os
                os.nice(-20)  # Massima priorità
                logger.info("Priorità thread ricevitore aumentata (nice)")
            except:
                # Ignora se non supportato
                pass

            logger.info("Thread ricevitore impostato ad alta priorità")
        except Exception as e:
            logger.debug(f"Impossibile impostare priorità thread: {e}")

    def _init_zmq_socket(self):
        """Inizializza socket ZMQ ottimizzato per bassa latenza."""
        # Cleanup se necessario
        self._cleanup_socket()

        # Crea nuovo contesto
        self._context = zmq.Context()

        # Configura socket
        self._socket = self._context.socket(zmq.SUB)
        self._socket.setsockopt(zmq.LINGER, 0)  # No linger
        self._socket.setsockopt(zmq.SUBSCRIBE, b"")  # Sottoscrivi a tutto

        # Timeout più breve per rilevare disconnessioni rapidamente
        self._socket.setsockopt(zmq.RCVTIMEO, 2000)  # 2s timeout

        # Configurazione per bassa latenza
        self._socket.setsockopt(zmq.CONFLATE, 0)  # No conflation in bassa latenza

        # Buffer minimo per evitare ritardi
        if self._low_latency_mode:
            # In modalità bassa latenza limita dimensioni buffer
            self._socket.setsockopt(zmq.RCVHWM, 4)  # Limita buffer ricezione
            self._socket.setsockopt(zmq.RCVBUF, 65536)  # 64KB buffer
        else:
            # Modalità bilanciata
            self._socket.setsockopt(zmq.RCVHWM, 8)
            self._socket.setsockopt(zmq.RCVBUF, 262144)  # 256KB buffer

        # Opzioni TCP per bassa latenza
        try:
            self._socket.setsockopt(zmq.TCP_NODELAY, 1)
            logger.debug("TCP_NODELAY abilitato")
        except:
            pass

        # Connetti all'endpoint
        endpoint = f"tcp://{self.host}:{self.port}"
        logger.info(f"Connessione a {endpoint}...")
        self._socket.connect(endpoint)

        logger.info("Socket ZMQ inizializzato")

    def _send_stream_config(self):
        """Invia configurazione iniziale al server."""
        try:
            # Trova socket di comando
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((self.host, self.port))
            local_ip = s.getsockname()[0]
            s.close()

            # Usa altro socket ZMQ per inviare configurazione
            config_context = zmq.Context()
            config_socket = config_context.socket(zmq.REQ)
            config_socket.setsockopt(zmq.LINGER, 0)
            config_socket.setsockopt(zmq.RCVTIMEO, 5000)
            config_socket.setsockopt(zmq.SNDTIMEO, 5000)

            # Connetti alla porta di comando
            cmd_port = self.port - 1  # Assumendo che porta comando = porta stream - 1
            config_socket.connect(f"tcp://{self.host}:{cmd_port}")

            # Invia configurazione
            config = {
                "command": "STREAM_CONFIG",
                "client_ip": local_ip,
                "dual_camera": self._request_dual_camera,
                "low_latency": self._low_latency_mode,
                "quality": 92 if self._low_latency_mode else 95,
                "request_id": str(uuid.uuid4())
            }

            config_socket.send_json(config)

            # Attendi risposta con timeout
            try:
                response = config_socket.recv_json()
                logger.info(f"Configurazione stream accettata: {response}")
            except zmq.Again:
                logger.warning("Timeout invio configurazione stream, continuo comunque")

            # Cleanup
            config_socket.close()

        except Exception as e:
            logger.warning(f"Errore invio configurazione stream: {e}")

    def _receive_loop(self):
        """Loop principale di ricezione ottimizzato."""
        frame_count = 0
        skipped_count = 0
        last_report_time = time.time()
        last_camera_check = time.time()
        active_cameras = set()

        # Diagnostica iniziale
        is_debugging = logger.getEffectiveLevel() <= logging.DEBUG

        # Loop principale
        while self._running:
            try:
                # Timestamp prima della ricezione per misurare lag
                pre_recv_time = time.time()

                # Controllo di flusso adattivo
                if self._processing_lag > 50 and self._low_latency_mode:
                    # Stiamo accumulando troppo lag - controllo flusso aggressivo
                    try:
                        # Ricevi e scarta senza processare
                        self._socket.recv(zmq.NOBLOCK)
                        if self._socket.getsockopt(zmq.RCVMORE):
                            self._socket.recv(zmq.NOBLOCK)

                        # Incrementa contatore frame scartati
                        skipped_count += 1
                        continue
                    except zmq.ZMQError as e:
                        # Non ci sono frame da scartare, continua normalmente
                        if e.errno != zmq.EAGAIN:
                            raise

                # Ricevi header
                header_data = self._socket.recv()

                # Controlla ulteriori dati
                if not self._socket.getsockopt(zmq.RCVMORE):
                    logger.warning("Ricevuto header senza dati del frame")
                    continue

                # Ricevi dati frame (ottimizzati per bassa latenza)
                if self._use_zero_copy:
                    # Zero-copy con buffer diretto per evitare copia
                    frame_data = self._socket.recv(copy=False)
                    frame_bytes = frame_data.buffer
                else:
                    # Fallback a ricezione normale
                    frame_bytes = self._socket.recv()

                # Decodifica header
                try:
                    # Tentativo di decodifica binaria efficiente
                    import struct
                    if len(header_data) >= 14:  # Formato compatto header
                        # Formato |camera_idx|is_scan_flag|timestamp|sequence|
                        header_unpacked = struct.unpack('!BBdI', header_data)
                        camera_index = header_unpacked[0]
                        is_scan_frame = bool(header_unpacked[1])
                        timestamp = header_unpacked[2]
                        sequence = header_unpacked[3]

                        header = {
                            "camera": camera_index,
                            "timestamp": timestamp,
                            "sequence": sequence,
                            "is_scan_frame": is_scan_frame,
                            "format": "jpeg"
                        }
                    else:
                        # Fallback a JSON
                        header_str = header_data.decode('utf-8', errors='ignore')
                        header = json.loads(header_str)
                        camera_index = header.get("camera", 0)
                        timestamp = header.get("timestamp", time.time())
                        is_scan_frame = header.get("is_scan_frame", False)
                except Exception as e:
                    logger.error(f"Errore decodifica header: {e}")
                    continue

                # Aggiorna contatore e timestamp
                frame_count += 1
                self._frames_received += 1

                # Tracciamento camera attiva
                active_cameras.add(camera_index)
                self.cameras_active = active_cameras

                # Decisione priorità in base a tipo frame
                is_high_priority = is_scan_frame or camera_index == 0  # Priorità camera sinistra e frame scan

                # Decodifica frame con priorità
                self._decoder.decode_frame(
                    frame_bytes,
                    camera_index,
                    timestamp,
                    priority=is_high_priority,
                    callback=self._frame_decoded_callback if not is_scan_frame else self._scan_frame_decoded_callback
                )

                # Misura lag di elaborazione
                process_end_time = time.time()
                loop_time_ms = (process_end_time - pre_recv_time) * 1000

                # Media mobile per lag di elaborazione
                alpha = 0.3
                self._processing_lag = (1 - alpha) * self._processing_lag + alpha * loop_time_ms

                # Aggiorna frame times per questa camera
                self._frame_times[camera_index] = (timestamp, process_end_time)

                # Report periodico prestazioni
                current_time = time.time()
                if current_time - last_report_time > 5.0:
                    # Calcola FPS
                    interval = current_time - last_report_time
                    fps = frame_count / interval

                    # Log a livello INFO per essere sempre visibile
                    logger.info(f"Streaming: {fps:.1f} FPS, camere={len(active_cameras)}, " +
                                f"skipped={skipped_count}, lag={self._processing_lag:.1f}ms")

                    # Reset contatori
                    frame_count = 0
                    skipped_count = 0
                    last_report_time = current_time

                # Verifica periodica camere attive
                if current_time - last_camera_check > 3.0:
                    # Controlla camere mancanti
                    if self._request_dual_camera and len(active_cameras) < 2:
                        missing = set([0, 1]) - active_cameras
                        logger.warning(f"Camere mancanti: {missing}")

                        # Forza reinvio config
                        self._send_stream_config()

                    # Reset per prossimo check
                    last_camera_check = current_time

            except zmq.Again:
                # Timeout normale, continua
                pass
            except zmq.ZMQError as e:
                if e.errno == zmq.ETERM:
                    # Contesto terminato, esci dal loop
                    logger.info("Contesto ZMQ terminato")
                    break
                logger.error(f"ZMQ error: {e}")
                # Attendi un attimo prima di riprovare
                time.sleep(0.1)
            except Exception as e:
                logger.error(f"Errore nel loop di ricezione: {e}")
                time.sleep(0.1)

    def _frame_decoded_callback(self, camera_idx, frame, timestamp, decode_latency_ms=0):
        """Callback per frame standard decodificato."""
        try:
            if not self._running:
                return

            # Verifica qualità frame
            if frame is None or frame.size == 0:
                return

            # Routing normale via Signal
            self.frame_decoded.emit(camera_idx, frame, timestamp)

        except Exception as e:
            logger.error(f"Errore in frame_decoded_callback: {e}")

    def _scan_frame_decoded_callback(self, camera_idx, frame, timestamp, decode_latency_ms=0):
        """Callback per frame di scan decodificato con priorità massima."""
        try:
            if not self._running:
                return

            # Verifica qualità frame
            if frame is None or frame.size == 0:
                return

            # Prepara info frame
            frame_info = {
                "camera_index": camera_idx,
                "timestamp": timestamp,
                "is_scan_frame": True,
                "pattern_index": int(timestamp * 100) % 24,  # Stima pattern index da timestamp
                "decode_latency_ms": decode_latency_ms
            }

            # Routing diretto per minimizzare latenza
            if self._direct_routing and self._frame_processor:
                if hasattr(self._frame_processor, 'process_frame'):
                    self._frame_processor.process_frame(camera_idx, frame, frame_info)
                    return

            # Fallback a routing tramite signal
            self.scan_frame_received.emit(camera_idx, frame, frame_info)

        except Exception as e:
            logger.error(f"Errore in scan_frame_decoded_callback: {e}")

    def _cleanup_socket(self):
        """Pulisce il socket ZMQ."""
        try:
            if self._socket:
                self._socket.close()
                self._socket = None
        except Exception as e:
            logger.debug(f"Errore nella chiusura del socket: {e}")

        # Non chiudiamo il contesto, causa problemi in riconnessione
        # Lo gestiamo con terminazione thread

    def get_performance_stats(self):
        """Restituisce statistiche dettagliate sulle prestazioni."""
        stats = {
            'frames_received': self._frames_received,
            'processing_lag_ms': self._processing_lag,
            'cameras_active': len(self.cameras_active),
        }

        # Calcola latenze per camera
        for camera_idx, (ts, recv_time) in self._frame_times.items():
            latency = recv_time - ts
            stats[f'camera{camera_idx}_latency_ms'] = latency * 1000

        return stats