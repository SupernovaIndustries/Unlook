#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Versione ottimizzata di StreamReceiver che elimina il buffering e processa i frame direttamente.
Implementa un meccanismo di controllo di flusso "pull" per evitare l'accumulo di lag.
Migliorato per il supporto dual camera e prestazioni ottimizzate.
"""

import json
import logging
import time
import threading
import cv2
import numpy as np
from typing import Dict, Any, Optional, Callable, Tuple, List, Set

import zmq
from PySide6.QtCore import QObject, Signal, Slot, QTimer, QMutex, QMutexLocker, QThread

# Configurazione logging
logger = logging.getLogger(__name__)


class StreamReceiver(QObject):
    """
    Gestore principale per la ricezione di stream video.
    Versione migliorata con gestione di dual camera, riconnessione automatica,
    e supporto per frame di scansione 3D.
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
        self.error.emit(error_message)


class StreamReceiverThread(QThread):
    """
    Thread dedicato per ricevere lo stream video senza buffering.
    Processa ed emette ogni frame direttamente senza code intermedie.
    Versione ottimizzata con riconnessione automatica, gestione robusta degli errori,
    e supporto per frame di scansione 3D.
    """
    frame_decoded = Signal(int, np.ndarray, float)  # camera_index, frame, timestamp
    scan_frame_received = Signal(int, np.ndarray, dict)  # camera_index, frame, frame_info
    connection_state_changed = Signal(bool)  # connected
    error_occurred = Signal(str)  # error_message

    def __init__(self, host: str, port: int):
        super().__init__()
        self.host = host
        self.port = port
        self._running = False
        self._context = None
        self._socket = None
        self._last_activity = 0
        self._connected = False
        self._received_cameras = set()
        self._frame_counters = {0: 0, 1: 0}  # Contatori per entrambe le camere
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 5
        self._mutex = QMutex()  # Mutex per proteggere lo stato

    def run(self):
        """Loop principale del thread con meccanismo di riconnessione automatica e controllo di flusso adattivo."""
        reconnect_delay = 1.0  # Delay iniziale in secondi

        # Aggiungiamo variabili per il controllo di flusso adattivo
        self._processing_lag = 0  # Misura del ritardo di elaborazione
        self._frame_drop_threshold = 100  # ms, soglia per il drop dei frame
        self._max_queue_size = 2  # Limitiamo la coda a un massimo di 2 messaggi
        self._frame_interval = 0  # Tempo medio tra frame consecutivi
        self._last_frame_time = 0  # Timestamp dell'ultimo frame ricevuto
        self._adaptive_mode = True  # Abilita/disabilita modalità adattiva

        while self._reconnect_attempts <= self._max_reconnect_attempts:
            try:
                # Inizializza ZeroMQ
                self._context = zmq.Context()
                self._socket = self._context.socket(zmq.SUB)

                # Configurazione migliorata per ZeroMQ con controllo di flusso
                self._socket.setsockopt(zmq.LINGER, 0)  # Non attendere alla chiusura

                # IMPORTANTE: Limita il buffer di ricezione per evitare accumulo di frame
                self._socket.setsockopt(zmq.RCVHWM,
                                        self._max_queue_size)  # Limita la dimensione della coda di ricezione

                self._socket.setsockopt_string(zmq.SUBSCRIBE, "")  # Sottoscrivi a tutto
                self._socket.setsockopt(zmq.RCVTIMEO, 500)  # 500ms timeout

                # Connetti all'endpoint
                endpoint = f"tcp://{self.host}:{self.port}"
                if self._reconnect_attempts > 0:
                    logger.info(
                        f"Tentativo di riconnessione {self._reconnect_attempts}/{self._max_reconnect_attempts} a {endpoint}")
                else:
                    logger.info(f"Connessione a {endpoint}...")

                self._socket.connect(endpoint)

                # Inizializza stato
                with QMutexLocker(self._mutex):
                    self._running = True
                    self._last_activity = time.time()
                    self._connected = True
                    self._reconnect_attempts = 0

                self.connection_state_changed.emit(True)

                # Configurazione controllo di flusso
                logger.info(
                    f"StreamReceiverThread inizializzato con controllo di flusso adattivo (max_queue={self._max_queue_size})")

                # Loop principale con controllo di flusso adattivo
                while self._is_running():
                    try:
                        # Misuriamo il tempo di inizio elaborazione
                        process_start_time = time.time()

                        # Verifica se siamo in modalità di scarto frame a causa di sovraccarico
                        dropping_frames = self._adaptive_mode and self._processing_lag > self._frame_drop_threshold

                        # Se siamo in ritardo e adaptive_mode è attivo, possiamo scartare frame
                        # eccetto per il primo frame di ogni camera dopo un periodo di inattività
                        if dropping_frames and self._last_frame_time > 0 and time.time() - self._last_frame_time < 0.5:
                            # Ricevi ma scarta il frame per svuotare la coda (modalità di recupero da lag)
                            try:
                                self._socket.recv()  # Ricevi header
                                if self._socket.get(zmq.RCVMORE):
                                    self._socket.recv()  # Ricevi dati
                                logger.debug(f"Frame scartato (lag={self._processing_lag:.1f}ms)")
                                continue
                            except zmq.Again:
                                # Timeout normale, continua
                                continue

                        # Attendi l'header
                        try:
                            header_data = self._socket.recv()
                        except zmq.Again:
                            # Timeout normale, controlla inattività
                            current_time = time.time()
                            with QMutexLocker(self._mutex):
                                inactivity_time = current_time - self._last_activity
                                is_connected = self._connected

                            # Gestione inattività
                            if inactivity_time > 5.0 and is_connected:
                                if inactivity_time > 10.0:
                                    logger.warning(
                                        f"Nessuna attività per {inactivity_time:.1f} secondi, potenziale disconnessione")
                                    if inactivity_time > 15.0:
                                        logger.error(
                                            f"Nessuna attività per {inactivity_time:.1f} secondi, connessione persa")
                                        with QMutexLocker(self._mutex):
                                            self._connected = False
                                        self.connection_state_changed.emit(False)
                                        break
                            continue

                        # Aggiorna timestamp di attività
                        with QMutexLocker(self._mutex):
                            self._last_activity = time.time()
                            was_connected = self._connected
                            if not was_connected:
                                self._connected = True
                                emit_connection_change = True
                            else:
                                emit_connection_change = False

                        if emit_connection_change:
                            self.connection_state_changed.emit(True)
                            logger.info("Connessione ripristinata, ricezione dati")

                        # Verifica ulteriori dati
                        if not self._socket.get(zmq.RCVMORE):
                            logger.warning("Ricevuto header senza dati del frame")
                            continue

                        # Ricevi i dati del frame
                        frame_data = self._socket.recv()

                        # Decodifica header
                        try:
                            header = json.loads(header_data.decode('utf-8'))
                            camera_index = header.get("camera")
                            timestamp = header.get("timestamp")
                            format_str = header.get("format")
                            is_scan_frame = header.get("is_scan_frame", False)
                        except json.JSONDecodeError:
                            logger.warning("Header JSON non valido")
                            continue

                        # Verifica dati minimi necessari
                        if None in (camera_index, timestamp, format_str):
                            logger.warning(f"Header incompleto: {header}")
                            continue

                        # Aggiorna le statistiche per il controllo di flusso
                        current_time = time.time()
                        if self._last_frame_time > 0:
                            frame_interval = current_time - self._last_frame_time
                            # Aggiorna media mobile dell'intervallo
                            alpha = 0.2  # Fattore di smorzamento
                            self._frame_interval = (1 - alpha) * self._frame_interval + alpha * frame_interval

                        self._last_frame_time = current_time

                        # Aggiorna camera attiva
                        with QMutexLocker(self._mutex):
                            if camera_index not in self._received_cameras:
                                self._received_cameras.add(camera_index)
                                new_camera = True
                            else:
                                new_camera = False
                            self._frame_counters[camera_index] = self._frame_counters.get(camera_index, 0) + 1
                            frame_count = self._frame_counters[camera_index]

                        # Log occasionale
                        if new_camera:
                            logger.info(f"Nuova camera rilevata: {camera_index}")
                        if frame_count % 100 == 0:
                            logger.debug(f"Ricevuti {frame_count} frame dalla camera {camera_index}")

                        # Decodifica il frame con verifica del tipo
                        if format_str.lower() == "jpeg":
                            try:
                                # Decodifica con gestione errori ottimizzata
                                frame_buffer = np.frombuffer(frame_data, dtype=np.uint8)
                                frame = cv2.imdecode(frame_buffer, cv2.IMREAD_UNCHANGED)

                                if frame is None or frame.size == 0:
                                    logger.warning(f"Decodifica fallita per frame della camera {camera_index}")
                                    continue

                                # Emetti il segnale appropriato in base al tipo di frame
                                if is_scan_frame:
                                    # Estraiamo informazioni aggiuntive per i frame di scansione
                                    frame_info = {
                                        "scan_id": header.get("scan_id"),
                                        "pattern_index": header.get("pattern_index"),
                                        "pattern_name": header.get("pattern_name"),
                                        "timestamp": timestamp,
                                        "is_scan_frame": True
                                    }
                                    self.scan_frame_received.emit(camera_index, frame, frame_info)
                                else:
                                    # Frame normale di streaming
                                    self.frame_decoded.emit(camera_index, frame, timestamp)

                            except Exception as decode_error:
                                logger.warning(f"Errore nella decodifica: {decode_error}")
                                continue

                        # Misurazione del tempo di elaborazione per il controllo di flusso
                        process_end_time = time.time()
                        process_time_ms = (process_end_time - process_start_time) * 1000

                        # Aggiorna il lag di elaborazione con media mobile
                        alpha = 0.3  # Fattore di smorzamento
                        self._processing_lag = (1 - alpha) * self._processing_lag + alpha * process_time_ms

                        # Adatta il controllo di flusso in base al lag
                        if self._adaptive_mode:
                            # Se il lag è molto alto, incrementiamo la soglia di scarto
                            if self._processing_lag > self._frame_drop_threshold * 2:
                                self._frame_drop_threshold = min(200, self._frame_drop_threshold * 1.2)
                                if frame_count % 30 == 0:
                                    logger.info(
                                        f"Controllo flusso: aumento soglia di scarto a {self._frame_drop_threshold:.1f}ms (lag={self._processing_lag:.1f}ms)")
                            # Se il lag è basso, riduciamo gradualmente la soglia di scarto
                            elif self._processing_lag < self._frame_drop_threshold / 2:
                                self._frame_drop_threshold = max(50, self._frame_drop_threshold * 0.9)

                    except zmq.ZMQError as e:
                        if e.errno == zmq.EAGAIN:
                            # Timeout normale
                            continue
                        logger.error(f"Errore ZMQ: {e}")
                        if not self._is_running():
                            break
                        break  # Usciamo per riconnessione

                    except Exception as e:
                        logger.error(f"Errore nella ricezione: {e}")
                        self.error_occurred.emit(str(e))
                        time.sleep(0.1)  # Breve pausa

                # Se usciti dal loop in modo pulito
                if not self._running or self._shutdown_event.is_set():
                    break

            except Exception as e:
                logger.error(f"Errore fatale nel thread di ricezione: {e}")
                self.error_occurred.emit(str(e))
                if not self._is_running():
                    break
                self._cleanup_socket()
                self._reconnect_attempts += 1
                current_delay = min(reconnect_delay * (2 ** (self._reconnect_attempts - 1)), 30.0)
                logger.info(f"Attesa di {current_delay:.1f} secondi prima del prossimo tentativo...")
                time.sleep(current_delay)

        # Pulizia finale
        self._cleanup_socket()
        with QMutexLocker(self._mutex):
            was_connected = self._connected
            self._connected = False
        if was_connected:
            self.connection_state_changed.emit(False)
        logger.info("Thread di ricezione terminato")

    # Aggiungiamo nuovi metodi per controllare il flusso
    def set_high_performance(self, enabled: bool):
        """
        Abilita/disabilita la modalità ad alte prestazioni con riduzione della qualità
        per migliorare la reattività.

        Args:
            enabled: True per abilitare, False per disabilitare
        """
        with QMutexLocker(self._mutex):
            if enabled:
                self._max_queue_size = 1  # Riduce al minimo la coda
                self._frame_drop_threshold = 50  # Imposta una soglia bassa per il drop
                self._adaptive_mode = True  # Abilita il controllo adattivo
                logger.info("Modalità alte prestazioni abilitata")
            else:
                self._max_queue_size = 2  # Coda standard
                self._frame_drop_threshold = 100  # Soglia standard
                self._adaptive_mode = False  # Disabilita adattamento
                logger.info("Modalità alte prestazioni disabilitata")

    def get_performance_stats(self) -> dict:
        """
        Restituisce le statistiche di prestazione del ricevitore.

        Returns:
            Dizionario con informazioni di prestazione
        """
        with QMutexLocker(self._mutex):
            return {
                "processing_lag": self._processing_lag,
                "frame_interval": self._frame_interval * 1000 if self._frame_interval > 0 else 0,
                "estimated_fps": 1.0 / self._frame_interval if self._frame_interval > 0 else 0,
                "drop_threshold": self._frame_drop_threshold,
                "adaptive_mode": self._adaptive_mode,
                "cameras_active": list(self._received_cameras),
                "max_queue_size": self._max_queue_size
            }

    def _is_running(self) -> bool:
        """Verifica se il thread è in esecuzione in modo thread-safe."""
        with QMutexLocker(self._mutex):
            return self._running

    def _cleanup_socket(self):
        """Pulisce il socket e il contesto ZMQ in modo sicuro."""
        try:
            if self._socket:
                try:
                    self._socket.setsockopt(zmq.LINGER, 0)  # Assicura che la chiusura sia immediata
                    self._socket.close()
                except Exception as e:
                    logger.debug(f"Errore nella chiusura del socket: {e}")
                self._socket = None
        except Exception as e:
            logger.error(f"Errore nella pulizia del socket: {e}")

        try:
            if self._context:
                try:
                    self._context.term()
                except Exception as e:
                    logger.debug(f"Errore nella terminazione del contesto: {e}")
                self._context = None
        except Exception as e:
            logger.error(f"Errore nella pulizia del contesto: {e}")

    def stop(self):
        """Ferma il thread di ricezione in modo sicuro."""
        logger.info("Arresto del thread di ricezione...")

        with QMutexLocker(self._mutex):
            self._running = False

        # Attendi che il thread termini con un timeout
        if self.isRunning() and not self.wait(2000):  # 2 secondi di timeout
            logger.warning("Timeout nell'attesa della terminazione del thread di ricezione")

        # Assicurati che le risorse siano rilasciate
        self._cleanup_socket()
        logger.info("Thread di ricezione arrestato")

    @property
    def cameras_active(self) -> set:
        """Restituisce l'insieme delle camere attivamente rilevate."""
        with QMutexLocker(self._mutex):
            return self._received_cameras.copy()  # Restituisci una copia per evitare race condition