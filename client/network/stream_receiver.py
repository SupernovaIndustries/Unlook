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
import concurrent.futures
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
                try:
                    self._receiver_thread.set_frame_processor(self._frame_processor)
                    logger.info("Frame processor impostato nel thread")
                except Exception as e:
                    logger.error(f"Errore nell'impostazione del frame processor: {e}")
                    # Non propagare l'errore, continua con l'avvio

            # Imposta direct routing
            try:
                self._receiver_thread.set_direct_routing(self._direct_routing)
                logger.info(f"Direct routing {'abilitato' if self._direct_routing else 'disabilitato'} nel thread")
            except Exception as e:
                logger.error(f"Errore nell'impostazione del direct routing: {e}")
                # Non propagare l'errore, continua con l'avvio

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
        self.cameras_active = set()
        self._frame_counters = {0: 0, 1: 0}
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 10  # Aumentato il numero di tentativi
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

        # Parametri di riconnessione migliorati
        self._inactivity_timeout = 15.0  # Aumentato il timeout per inattività
        self._reconnect_delay_base = 0.5  # Ritardo base per riconnessione
        self._reconnect_delay_max = 5.0  # Ritardo massimo per riconnessione

    # Miglioramenti al metodo run() della classe StreamReceiverThread

    def run(self):
        """Loop principale ottimizzato del thread con diagnostica migliorata."""
        try:
            import os
            os.nice(-10)  # Aumenta priorità (Linux/macOS)
            logger.info("Priorità thread aumentata per performance realtime")
        except:
            logger.info("Impossibile aumentare priorità thread (funzionalità sistema specifico)")

        # Reset delle variabili di stato
        self._frames_processed = 0
        self._received_cameras = set()  # CORREZIONE: Inizializza questa variabile
        self._start_time = time.time()
        self._processing_times = []
        self._first_frame_received = {0: False, 1: False}

        logger.info(f"Avvio thread di ricezione ZMQ per {self.host}:{self.port}")

        reconnect_delay = 1.0
        while self._reconnect_attempts <= self._max_reconnect_attempts:
            try:
                # Inizializza ZeroMQ
                self._context = zmq.Context()
                self._socket = self._context.socket(zmq.SUB)

                # Configurazione per bassa latenza
                self._socket.setsockopt(zmq.LINGER, 0)  # Non attendere alla chiusura
                self._socket.setsockopt(zmq.RCVHWM, 10)  # Buffer maggiore (era 2)
                self._socket.setsockopt(zmq.SUBSCRIBE, b"")  # Sottoscrivi a tutto
                self._socket.setsockopt(zmq.RCVTIMEO, 1000)  # 1000ms timeout (era 100ms)

                # Opzioni TCP avanzate
                try:
                    self._socket.setsockopt(zmq.TCP_NODELAY, 1)  # Disabilita Nagle
                    logger.info("TCP_NODELAY abilitato per riduzione latenza")
                except:
                    logger.info("TCP_NODELAY non supportato su questa piattaforma")

                # Connetti all'endpoint
                endpoint = f"tcp://{self.host}:{self.port}"
                logger.info(f"Connessione a {endpoint} con buffer=10, timeout=1000ms...")
                self._socket.connect(endpoint)

                # Inizializza stato
                with QMutexLocker(self._mutex):
                    self._running = True
                    self._last_activity = time.time()
                    self._connected = True
                    self._reconnect_attempts = 0

                self.connection_state_changed.emit(True)
                logger.info("Connessione ZMQ stabilita, inizio ricezione frame")

                # Contatori per i log
                frame_count_by_camera = {0: 0, 1: 0}
                last_stats_time = time.time()

                # Aumenta frequenza log iniziale
                log_interval = 1.0  # Prima fase: log ogni secondo
                detailed_header_log = True  # Modalità debug estesa

                logger.info("Entrando nel loop principale di ricezione ZMQ")
                while self._running:
                    try:
                        # Timestamp preciso di inizio elaborazione
                        process_start_time = time.time()

                        # Controllo di flusso meno aggressivo
                        if self._adaptive_mode and self._processing_lag > 200:  # Prima era 50ms
                            try:
                                # Consumiamo il messaggio ma lo scartiamo
                                msg = self._socket.recv(zmq.NOBLOCK)
                                if self._socket.getsockopt(zmq.RCVMORE):
                                    self._socket.recv(zmq.NOBLOCK)
                                logger.debug("Frame scartato per lag eccessivo")
                                continue
                            except zmq.ZMQError as e:
                                if e.errno != zmq.EAGAIN:
                                    logger.error(f"Errore ZMQ: {e}")

                        # Attendi l'header
                        try:
                            header_data = self._socket.recv()
                            if detailed_header_log:
                                # Log esteso per i primi header
                                logger.info(
                                    f"Header ricevuto: {len(header_data)} bytes, primi byte: {header_data[:20]}")
                                detailed_header_log = False  # Disattiva dopo il primo
                            else:
                                logger.debug(f"Header ricevuto: {len(header_data)} bytes")
                        except zmq.Again:
                            # Timeout normale, controlla inattività
                            self._check_inactivity()
                            # Periodicamente riporta i timeout per debug
                            current_time = time.time()
                            if current_time - last_stats_time > log_interval:
                                logger.info(
                                    f"Timeout ricezione header - nessun frame ricevuto negli ultimi {log_interval:.1f}s")
                                last_stats_time = current_time
                                # Aumenta gradualmente l'intervallo di log dopo la fase iniziale
                                if log_interval < 5.0:
                                    log_interval += 1.0
                            continue
                        except zmq.ZMQError as e:
                            logger.error(f"Errore ZMQ nella ricezione header: {e}")
                            time.sleep(0.1)  # Pausa breve
                            continue

                        # Aggiorna timestamp attività
                        with QMutexLocker(self._mutex):
                            self._last_activity = time.time()
                            if not self._connected:
                                self._connected = True
                                self.connection_state_changed.emit(True)

                        # Verifica ulteriori dati
                        if not self._socket.getsockopt(zmq.RCVMORE):
                            logger.warning("Ricevuto header senza dati del frame")
                            continue

                        # Ricevi i dati del frame
                        try:
                            frame_data = self._socket.recv(copy=False)
                            logger.debug(f"Frame data ricevuto: {len(frame_data.buffer)} bytes")
                        except zmq.ZMQError as e:
                            logger.error(f"Errore nella ricezione del frame: {e}")
                            continue

                        # CORREZIONE: Usa struttura per decodificare header binario C
                        try:
                            import struct
                            if len(header_data) >= 14:  # 1B + 1B + 8B + 4B
                                # Formato |camera_idx|is_scan_flag|timestamp|sequence|
                                header_unpacked = struct.unpack('!BBdI', header_data)
                                camera_index = header_unpacked[0]
                                is_scan_frame = bool(header_unpacked[1])
                                timestamp = header_unpacked[2]
                                sequence = header_unpacked[3]

                                # IMPORTANTE: prima log dettagliato, poi versione compatta
                                if not self._first_frame_received.get(camera_index, False):
                                    logger.info(
                                        f"Header decodificato: camera={camera_index}, timestamp={timestamp:.6f}, "
                                        f"sequence={sequence}, is_scan={is_scan_frame}")
                                else:
                                    logger.debug(f"Frame: camera={camera_index}, seq={sequence}")

                                # Costruisci header completo
                                header = {
                                    "camera": camera_index,
                                    "timestamp": timestamp,
                                    "sequence": sequence,
                                    "is_scan_frame": is_scan_frame,
                                    "format": "jpeg"
                                }
                            else:
                                # Fallback: parse formato legacy (se presente)
                                try:
                                    header_str = header_data.decode('utf-8', errors='ignore')
                                    header = json.loads(header_str)
                                    camera_index = header.get("camera")
                                    timestamp = header.get("timestamp")
                                    is_scan_frame = header.get("is_scan_frame", False)
                                    logger.info(f"Usando formato header legacy JSON: {header}")
                                except:
                                    logger.error(f"Impossibile decodificare header: {header_data[:20]}")
                                    continue
                        except Exception as e:
                            logger.error(f"Errore nella decodifica header: {e}, dati={header_data[:20]}")
                            continue

                        # Aggiorna statistiche camera
                        with QMutexLocker(self._mutex):
                            self._received_cameras.add(camera_index)
                            self._frame_counters[camera_index] = self._frame_counters.get(camera_index, 0) + 1
                            frame_count_by_camera[camera_index] = frame_count_by_camera.get(camera_index, 0) + 1

                        # Decodifica frame
                        try:
                            buffer = np.frombuffer(frame_data.buffer, dtype=np.uint8)
                            frame = cv2.imdecode(buffer, cv2.IMREAD_UNCHANGED)

                            if frame is None or frame.size == 0:
                                logger.warning(f"Decodifica frame fallita: frame vuoto o None")
                                continue

                            # Incrementa contatore
                            self._frames_processed += 1

                            # Log primo frame per camera
                            if not self._first_frame_received.get(camera_index, False):
                                self._first_frame_received[camera_index] = True
                                logger.info(f"PRIMO FRAME RICEVUTO da camera {camera_index}: dimensione={frame.shape}, "
                                            f"tipo={frame.dtype}")

                            # Routing diretto o segnale Qt
                            if self._direct_routing and self._frame_processor and is_scan_frame:
                                if hasattr(self._frame_processor, 'process_frame'):
                                    self._frame_processor.process_frame(camera_index, frame, header)
                                    logger.debug(f"Frame elaborato direttamente via process_frame")
                                else:
                                    self.scan_frame_received.emit(camera_index, frame, header)
                                    logger.debug(f"Frame inviato via scan_frame_received")
                            else:
                                self.frame_decoded.emit(camera_index, frame, timestamp)
                                logger.debug(f"Frame inviato via frame_decoded")

                        except Exception as e:
                            logger.error(f"Errore nella decodifica: {e}")
                            import traceback
                            logger.error(f"Traceback: {traceback.format_exc()}")
                            continue

                        # Statistiche periodiche
                        now = time.time()
                        if now - last_stats_time > 5.0:
                            elapsed = now - last_stats_time
                            total_frames = sum(frame_count_by_camera.values())
                            fps = total_frames / elapsed if elapsed > 0 else 0
                            logger.info(f"Statistiche ricezione: {total_frames} frame in {elapsed:.1f}s, "
                                        f"{fps:.1f} FPS, distribuzione={frame_count_by_camera}")
                            # Reset statistiche
                            last_stats_time = now
                            frame_count_by_camera = {0: 0, 1: 0}

                        # Misurazione tempo di elaborazione
                        process_end_time = time.time()
                        process_time = process_end_time - process_start_time
                        process_time_ms = process_time * 1000

                        # Aggiorna il lag con media mobile
                        alpha = 0.3  # Fattore di smorzamento
                        self._processing_lag = (1 - alpha) * self._processing_lag + alpha * process_time_ms

                    except zmq.ZMQError as e:
                        if e.errno == zmq.EAGAIN:
                            continue
                        logger.error(f"Errore ZMQ nel loop: {e}")
                        time.sleep(0.1)
                    except Exception as e:
                        logger.error(f"Errore nella ricezione: {e}")
                        import traceback
                        logger.error(f"Traceback: {traceback.format_exc()}")
                        time.sleep(0.01)

                # Uscita pulita dal loop
                logger.info("Uscita pulita dal loop di ricezione")

            except Exception as e:
                logger.error(f"Errore nella connessione: {e}")
                self._cleanup_socket()
                self._reconnect_attempts += 1
                reconnect_delay = min(reconnect_delay * 1.5, 10.0)  # Crescita più lenta
                time.sleep(reconnect_delay)

        # Pulizia finale
        self._cleanup_socket()
        with QMutexLocker(self._mutex):
            self._connected = False
        self.connection_state_changed.emit(False)
        logger.info("Thread di ricezione terminato")

    def _check_inactivity(self):
        """
        Verifica l'inattività della connessione senza disconnettere.
        Ora solo registra l'inattività senza cambiare lo stato.
        """
        current_time = time.time()
        with QMutexLocker(self._mutex):
            inactivity_time = current_time - self._last_activity

            # Log periodico invece di disconnessione
            if inactivity_time > self._inactivity_timeout:
                # Log solo ogni 30 secondi per evitare spam
                if not hasattr(self, '_last_inactivity_log') or \
                        current_time - getattr(self, '_last_inactivity_log', 0) > 30.0:
                    logger.info(f"Inattività di {inactivity_time:.1f}s rilevata, mantengo connessione")
                    self._last_inactivity_log = current_time

                # Opzionalmente, possiamo implementare una riconnessione soft senza disconnessione
                if inactivity_time > 60.0:  # Se inattivo per più di un minuto
                    if not hasattr(self, '_last_ping_attempt') or \
                            current_time - getattr(self, '_last_ping_attempt', 0) > 30.0:
                        logger.info("Lunga inattività: tentativo di ping ZMQ senza disconnessione")
                        self._last_ping_attempt = current_time

                        # Possiamo inviare un messaggio di ping ZMQ o tentare una riconnessione "morbida"
                        # Ma mai impostare self._connected = False!

    def _cleanup_socket(self):
        """Pulisce il socket e il contesto ZMQ in modo sicuro."""
        try:
            if self._socket:
                self._socket.close()
                self._socket = None
        except Exception as e:
            logger.debug(f"Errore nella chiusura del socket: {e}")

        # Non chiudiamo il contesto, ma solo in caso di shutdown finale
        if not self._running and self._context:
            try:
                self._context.term()
                self._context = None
            except Exception as e:
                logger.debug(f"Errore nella chiusura del contesto: {e}")

    # Aggiungi questi metodi alla classe StreamReceiverThread

    def set_direct_routing(self, enabled):
        """
        Abilita o disabilita il routing diretto dei frame.

        Args:
            enabled: True per abilitare, False per disabilitare
        """
        with QMutexLocker(self._mutex):
            self._direct_routing = enabled
            logger.info(f"Direct routing {'abilitato' if enabled else 'disabilitato'} in StreamReceiverThread")

    def set_frame_processor(self, processor):
        """
        Imposta un processore di frame per routing diretto.

        Args:
            processor: Istanza di ScanFrameProcessor
        """
        self._frame_processor = processor
        logger.info(f"Frame processor impostato in StreamReceiverThread: {processor is not None}")