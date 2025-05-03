"""
Versione ottimizzata di StreamReceiver che implementa un sistema di streaming
a bassa latenza con gestione diretta dei frame per il processore di scansione.
Questa versione è progettata specificamente per l'integrazione con il nuovo
ScanFrameProcessor in-memory.
"""

import logging
import time
import threading
import cv2
import json
import numpy as np
from typing import Dict, Any, Optional, Callable, Set
import zmq
from PySide6.QtCore import QObject, Signal, Slot, QTimer, QMutex, QMutexLocker, QThread

# Configurazione logging
logger = logging.getLogger(__name__)


class StreamReceiver(QObject):
    """
    Gestore principale per la ricezione di stream video.
    Versione ottimizzata per l'integrazione con ScanFrameProcessor in-memory.
    """
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

        # Riferimento al processore di frame (opzionale)
        self._frame_processor = None

        # Flag per abilitare il routing diretto dei frame (ottimizzazione)
        self._direct_routing = True

        # Thread pool per decompressione
        self._decode_thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        self._pending_decodes = {}

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
        """Avvia la ricezione dello stream."""
        if self._is_receiving:
            logger.warning("StreamReceiver già avviato")
            return

        try:
            # Prima assicurati che non ci siano thread attivi
            self.stop()

            # Crea e avvia un nuovo thread
            self._receiver_thread = StreamReceiverThread(self.ip_address, self.port)

            # Passa il processore di frame al thread per routing diretto
            if self._frame_processor:
                self._receiver_thread.set_frame_processor(self._frame_processor)
                self._receiver_thread.set_direct_routing(self._direct_routing)

            # Collega i segnali
            self._receiver_thread.frame_decoded.connect(self._on_frame_decoded)
            self._receiver_thread.scan_frame_received.connect(self._on_scan_frame_received)
            self._receiver_thread.connection_state_changed.connect(self._on_connection_state_changed)
            self._receiver_thread.error_occurred.connect(self._on_error)

            # Avvia il thread
            self._receiver_thread.start()
            self._is_receiving = True

            logger.info(f"StreamReceiver avviato per {self.ip_address}:{self.port}")

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

    def stop(self):
        """
        Ferma la ricezione dello stream in modo sicuro e pulito,
        assicurando il rilascio di tutte le risorse.
        """
        logger.info("Arresto StreamReceiver...")

        if not self._is_receiving:
            logger.debug("StreamReceiver già arrestato")
            return

        try:
            # Pulisci i segnali prima di arrestare il thread
            # Questo previene callback indesiderate durante l'arresto
            if self._receiver_thread:
                try:
                    self._receiver_thread.frame_decoded.disconnect()
                    self._receiver_thread.scan_frame_received.disconnect()
                    self._receiver_thread.connection_state_changed.disconnect()
                    self._receiver_thread.error_occurred.disconnect()
                except Exception as e:
                    # È normale se i segnali sono già disconnessi
                    logger.debug(f"Errore nella disconnessione dei segnali: {e}")

            # Ferma il thread di ricezione
            if self._receiver_thread and self._receiver_thread.isRunning():
                # Prima imposta il flag di stop
                self._receiver_thread.stop()

                # Attendi la terminazione con timeout
                if not self._receiver_thread.wait(3000):  # 3 secondi di timeout
                    logger.warning("Timeout nell'arresto del thread di streaming, forzando terminazione")
                    # Come ultima risorsa, termina il thread
                    self._receiver_thread.terminate()
                    self._receiver_thread.wait(1000)  # Attendi ancora un secondo

            # Assicurati che il thread sia completamente terminato prima di nullificarlo
            if self._receiver_thread:
                if self._receiver_thread.isRunning():
                    logger.warning("Thread di streaming ancora in esecuzione dopo l'arresto")
                else:
                    logger.debug("Thread di streaming terminato correttamente")

                # Nullifica il riferimento
                self._receiver_thread = None

            # Reimposta lo stato
            self._is_receiving = False
            self._cameras_active.clear()

            logger.info("StreamReceiver arrestato con successo")

        except Exception as e:
            logger.error(f"Errore nell'arresto dello StreamReceiver: {e}")
            # Reimposta comunque lo stato
            self._is_receiving = False
            self._cameras_active.clear()
            self._receiver_thread = None

    def is_active(self) -> bool:
        """Verifica se lo streaming è attivo."""
        return self._is_receiving and self._receiver_thread and self._receiver_thread.isRunning()

    def cameras_active(self) -> set:
        """Restituisce l'insieme delle camere attivamente rilevate."""
        if self._receiver_thread:
            return self._receiver_thread.cameras_active
        return set()

    @Slot(int, np.ndarray, float)
    def _on_frame_decoded(self, camera_index: int, frame: np.ndarray, timestamp: float):
        """Gestisce un frame decodificato."""
        # Aggiorna l'insieme delle camere attive
        self._cameras_active.add(camera_index)

        # Propaga il segnale
        self.frame_received.emit(camera_index, frame, timestamp)

    def _on_raw_frame_received(self, camera_index, frame_data, header):
        """Callback invocata quando arriva un frame raw (compresso)"""
        # Invia al thread pool per decompressione
        future = self._decode_thread_pool.submit(
            self._decompress_frame, frame_data, header
        )
        # Traccia la richiesta
        self._pending_decodes[future] = (camera_index, header)

        # Callback quando completato
        future.add_done_callback(self._on_frame_decompressed)

    def _on_frame_decompressed(self, future):
        """Callback invocata quando un frame è stato decompresso"""
        camera_index, header = self._pending_decodes.pop(future)
        try:
            frame = future.result()
            if frame is not None:
                # Emetti segnale con frame decompresso
                self.frame_decoded.emit(camera_index, frame, header.get('timestamp', 0))
        except Exception as e:
            logger.error(f"Errore decompressione: {e}")

    def _decompress_frame(self, frame_data, header):
        """Decompressione in thread parallelo"""
        try:
            # Decodifica efficiente
            buffer = np.frombuffer(frame_data, dtype=np.uint8)
            return cv2.imdecode(buffer, cv2.IMREAD_UNCHANGED)
        except Exception as e:
            logger.error(f"Errore decodifica: {e}")
            return None

    @Slot(int, np.ndarray, dict)
    def _on_scan_frame_received(self, camera_index: int, frame: np.ndarray, frame_info: dict):
        """Gestisce un frame di scansione ricevuto."""
        # Aggiorna l'insieme delle camere attive
        self._cameras_active.add(camera_index)

        # Propaga il segnale
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
        # Assicurati che il segnale error venga emesso con l'argomento error_message
        self.error.emit(error_message)

    def get_performance_stats(self) -> dict:
        """
        Restituisce statistiche sulle prestazioni del ricevitore.

        Returns:
            Dizionario con statistiche di performance
        """
        if self._receiver_thread:
            return self._receiver_thread.get_performance_stats()
        return {
            "status": "inactive",
            "error": "Ricevitore non attivo"
        }


class StreamReceiverThread(QThread):
    """
    Thread dedicato per ricevere lo stream video senza buffering.
    Versione ottimizzata per ridurre latenza e migliorare la sincronizzazione.
    """
    frame_decoded = Signal(int, np.ndarray, float)  # camera_index, frame, timestamp
    scan_frame_received = Signal(int, np.ndarray, dict)  # camera_index, frame, frame_info
    connection_state_changed = Signal(bool)  # connected
    error_occurred = Signal(str)  # error_message

    def __init__(self, host: str, port: int):
        """
        Inizializza il thread di ricezione ZMQ ottimizzato per bassa latenza.

        Args:
            host: Indirizzo IP del server
            port: Porta per lo streaming
        """
        super().__init__()
        self.host = host
        self.port = port
        self._running = False
        self._context = None
        self._socket = None
        self._last_activity = 0
        self._connected = False
        self._received_cameras = set()
        self._frame_counters = {0: 0, 1: 0}
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 5
        self._mutex = QMutex()
        self._max_queue_size = 2  # Buffer minimo per evitare blocchi

        # Proprietà per il routing diretto
        self._frame_processor = None
        self._direct_routing = False

        # Statistiche di prestazioni
        self._processing_times = []
        self._max_times_history = 50
        self._frames_processed = 0
        self._start_time = time.time()

        # Controllo di flusso
        self._processing_lag = 0.0
        self._frame_interval = 0.0
        self._last_frame_time = 0
        self._adaptive_mode = True
        self._frame_drop_threshold = 50  # ms
        self._low_latency_mode = True

    def run(self):
        """Loop principale ottimizzato del thread con priorità alla bassa latenza."""
        # Aumenta priorità thread
        try:
            import os
            os.nice(-10)  # Aumenta priorità (Linux/macOS)
        except:
            pass  # Ignora se non supportato

        reconnect_delay = 1.0  # Delay iniziale in secondi

        # Reset delle statistiche
        self._frames_processed = 0
        self._start_time = time.time()
        self._processing_times = []

        while self._reconnect_attempts <= self._max_reconnect_attempts:
            try:
                # Inizializza ZeroMQ
                self._context = zmq.Context()
                self._socket = self._context.socket(zmq.SUB)

                # Configurazione aggressiva per bassa latenza
                self._socket.setsockopt(zmq.LINGER, 0)  # Non attendere alla chiusura
                self._socket.setsockopt(zmq.RCVHWM, self._max_queue_size)  # Buffer minimo!
                self._socket.setsockopt(zmq.SUBSCRIBE, b"")  # Sottoscrivi a tutto
                self._socket.setsockopt(zmq.RCVTIMEO, 100)  # 100ms timeout (più aggressivo)

                # Opzioni avanzate TCP
                try:
                    self._socket.setsockopt(zmq.TCP_NODELAY, 1)  # Disabilita Nagle
                except:
                    pass

                # Connetti all'endpoint
                endpoint = f"tcp://{self.host}:{self.port}"
                logger.info(f"Connessione a {endpoint} con buffer={self._max_queue_size}...")
                self._socket.connect(endpoint)

                # Inizializza stato
                with QMutexLocker(self._mutex):
                    self._running = True
                    self._last_activity = time.time()
                    self._connected = True
                    self._reconnect_attempts = 0

                self.connection_state_changed.emit(True)

                # Loop principale con controllo di flusso aggressivo
                while self._running:
                    try:
                        # Misuriamo il tempo di inizio elaborazione
                        process_start_time = time.time()

                        # Controllo di flusso aggressivo: salta frame se in ritardo
                        if self._adaptive_mode and self._processing_lag > self._frame_drop_threshold:
                            try:
                                # Consumiamo il messaggio ma lo scartiamo
                                msg = self._socket.recv(zmq.NOBLOCK)
                                if self._socket.getsockopt(zmq.RCVMORE):
                                    self._socket.recv(zmq.NOBLOCK)
                                continue  # Passa al frame successivo
                            except zmq.ZMQError as e:
                                if e.errno != zmq.EAGAIN:
                                    logger.error(f"Errore ZMQ: {e}")
                                # Continua il loop normale se non ci sono messaggi

                        # Attendi l'header con timeout breve
                        try:
                            header_data = self._socket.recv()
                        except zmq.Again:
                            # Timeout normale, controlla inattività
                            self._check_inactivity()
                            continue

                        # Aggiorna timestamp di attività
                        with QMutexLocker(self._mutex):
                            self._last_activity = time.time()
                            if not self._connected:
                                self._connected = True
                                self.connection_state_changed.emit(True)

                        # Verifica ulteriori dati
                        if not self._socket.getsockopt(zmq.RCVMORE):
                            logger.warning("Ricevuto header senza dati del frame")
                            continue

                        # Ricevi i dati del frame senza copie non necessarie
                        frame_data = self._socket.recv(copy=False)

                        # Decodifica header usando approccio veloce
                        try:
                            header = json.loads(header_data.decode('utf-8', errors='ignore'))
                            camera_index = header.get("camera")
                            timestamp = header.get("timestamp")
                            format_str = header.get("format", "jpeg")
                            is_scan_frame = header.get("is_scan_frame", False)
                        except:
                            continue

                        # Aggiorna statistiche della camera
                        with QMutexLocker(self._mutex):
                            if camera_index not in self._received_cameras:
                                self._received_cameras.add(camera_index)
                            self._frame_counters[camera_index] = self._frame_counters.get(camera_index, 0) + 1

                        # Decodifica il frame solo se necessario
                        # In molti casi possiamo passare direttamente i dati JPEG
                        if self._direct_routing and self._frame_processor and is_scan_frame:
                            # Per scan frame, decodifichiamo sempre il frame
                            try:
                                # Decodifica efficiente
                                buffer = np.frombuffer(frame_data.buffer, dtype=np.uint8)
                                frame = cv2.imdecode(buffer, cv2.IMREAD_UNCHANGED)

                                # Routing diretto al processor
                                if hasattr(self._frame_processor, 'process_frame'):
                                    self._frame_processor.process_frame(camera_index, frame, header)
                                    # Non emettiamo segnali QT per risparmiare overhead
                                else:
                                    # Fallback a segnali
                                    self.scan_frame_received.emit(camera_index, frame, header)
                            except Exception as e:
                                logger.error(f"Errore nel processing diretto: {e}")
                                continue
                        else:
                            # Frame normale di streaming
                            try:
                                # Decodifica efficiente
                                buffer = np.frombuffer(frame_data.buffer, dtype=np.uint8)
                                frame = cv2.imdecode(buffer, cv2.IMREAD_UNCHANGED)

                                # Incrementa contatore
                                self._frames_processed += 1

                                # Emetti segnale
                                self.frame_decoded.emit(camera_index, frame, timestamp)
                            except Exception as e:
                                logger.error(f"Errore nella decodifica: {e}")
                                continue

                        # Misurazione del tempo di elaborazione per il controllo di flusso
                        process_end_time = time.time()
                        process_time = process_end_time - process_start_time
                        process_time_ms = process_time * 1000

                        # Aggiorna il lag con media mobile
                        alpha = 0.3  # Fattore di smorzamento
                        self._processing_lag = (1 - alpha) * self._processing_lag + alpha * process_time_ms

                        # Adatta soglia di scarto
                        if self._adaptive_mode:
                            if self._processing_lag > self._frame_drop_threshold * 2:
                                self._frame_drop_threshold = min(150, self._frame_drop_threshold * 1.2)
                            elif self._processing_lag < self._frame_drop_threshold / 2:
                                self._frame_drop_threshold = max(20, self._frame_drop_threshold * 0.9)

                    except zmq.ZMQError as e:
                        if e.errno == zmq.EAGAIN:
                            continue
                        logger.error(f"Errore ZMQ: {e}")
                        break  # Usciamo per riconnessione
                    except Exception as e:
                        logger.error(f"Errore nella ricezione: {e}")
                        time.sleep(0.01)  # Pausa minima

                # Se usciti dal loop in modo pulito
                if not self._running:
                    break

            except Exception as e:
                logger.error(f"Errore nella connessione: {e}")
                self._cleanup_socket()
                self._reconnect_attempts += 1
                current_delay = min(reconnect_delay * (2 ** (self._reconnect_attempts - 1)), 10.0)
                time.sleep(current_delay)

        # Pulizia finale
        self._cleanup_socket()
        with QMutexLocker(self._mutex):
            self._connected = False
        self.connection_state_changed.emit(False)
        logger.info("Thread di ricezione terminato")

    def _check_inactivity(self):
        """Verifica l'inattività della connessione."""
        current_time = time.time()
        with QMutexLocker(self._mutex):
            inactivity_time = current_time - self._last_activity
            if inactivity_time > 5.0 and self._connected:
                if inactivity_time > 10.0:
                    self._connected = False
                    self.connection_state_changed.emit(False)

    def set_frame_processor(self, processor):
        """
        Imposta un processore di frame per routing diretto.

        Args:
            processor: Istanza di ScanFrameProcessor
        """
        self._frame_processor = processor

    def set_direct_routing(self, enabled: bool):
        """
        Abilita o disabilita il routing diretto dei frame.

        Args:
            enabled: True per abilitare, False per disabilitare
        """
        with QMutexLocker(self._mutex):
            self._direct_routing = enabled

    def _cleanup_socket(self):
        """Pulisce il socket e il contesto ZMQ in modo sicuro."""
        try:
            if self._socket:
                self._socket.close()
                self._socket = None
            if self._context:
                self._context.term()
                self._context = None
        except:
            pass

    def stop(self):
        """Ferma il thread di ricezione in modo sicuro."""
        with QMutexLocker(self._mutex):
            self._running = False

        # Termina e pulisci risorse
        self._cleanup_socket()