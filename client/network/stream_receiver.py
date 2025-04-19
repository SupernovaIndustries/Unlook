#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Versione ottimizzata di StreamReceiver che elimina il buffering e processa i frame direttamente.
Implementa un meccanismo di controllo di flusso "pull" per evitare l'accumulo di lag.
"""

import json
import logging
import time
import threading
import cv2
import numpy as np
from typing import Dict, Any, Optional, Callable, Tuple, List

import zmq
from PySide6.QtCore import QObject, Signal, Slot, QTimer, QMutex, QMutexLocker, QThread

# Configurazione logging
logger = logging.getLogger(__name__)


class StreamReceiverThread(QThread):
    """
    Thread dedicato per ricevere lo stream video senza buffering.
    Processa ed emette ogni frame direttamente senza code intermedie.
    """
    frame_decoded = Signal(int, np.ndarray, float)  # camera_index, frame, timestamp
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

    def run(self):
        """Loop principale del thread."""
        try:
            # Inizializza ZeroMQ
            self._context = zmq.Context()
            self._socket = self._context.socket(zmq.SUB)

            # Configurazione critica per minimizzare il buffering
            self._socket.setsockopt(zmq.LINGER, 0)  # Non attendere alla chiusura
            self._socket.setsockopt(zmq.RCVHWM, 1)  # Limitare buffer di ricezione a 1
            self._socket.setsockopt(zmq.RCVTIMEO, 100)  # 100ms timeout
            self._socket.setsockopt_string(zmq.SUBSCRIBE, "")  # Sottoscrivi a tutto

            # Connetti all'endpoint
            endpoint = f"tcp://{self.host}:{self.port}"
            logger.info(f"Connessione a {endpoint}...")
            self._socket.connect(endpoint)

            self._running = True
            self._last_activity = time.time()
            self._connected = True
            self.connection_state_changed.emit(True)

            # Loop principale
            while self._running:
                try:
                    # Attendi l'header con timeout
                    header_data = self._socket.recv()

                    # Aggiorna timestamp di attività
                    self._last_activity = time.time()

                    # Verifica se ci sono altri dati (dati del frame)
                    if not self._socket.get(zmq.RCVMORE):
                        logger.warning("Ricevuto header senza dati del frame")
                        continue

                    # Ricevi i dati del frame
                    frame_data = self._socket.recv()

                    # Decodifica header
                    header = json.loads(header_data.decode('utf-8'))
                    camera_index = header.get("camera")
                    timestamp = header.get("timestamp")
                    format_str = header.get("format")

                    # Verifica dati minimi necessari
                    if None in (camera_index, timestamp, format_str):
                        logger.warning(f"Header incompleto: {header}")
                        continue

                    # Decodifica frame immediatamente
                    if format_str.lower() == "jpeg":
                        frame_buffer = np.frombuffer(frame_data, dtype=np.uint8)
                        frame = cv2.imdecode(frame_buffer, cv2.IMREAD_COLOR)

                        if frame is None or frame.size == 0:
                            logger.warning(f"Decodifica fallita per frame della camera {camera_index}")
                            continue

                        # Emetti il frame decodificato direttamente
                        self.frame_decoded.emit(camera_index, frame, timestamp)

                except zmq.ZMQError as e:
                    if e.errno == zmq.EAGAIN:
                        # Timeout normale, verifica se la connessione è attiva
                        if time.time() - self._last_activity > 3.0:
                            logger.warning("Nessuna attività per 3 secondi, verifica connessione...")
                            if self._connected:
                                self._connected = False
                                self.connection_state_changed.emit(False)
                        continue

                    logger.error(f"Errore ZMQ: {e}")
                    if not self._running:
                        break

                    # Ritenta connessione
                    try:
                        if self._socket:
                            self._socket.close()
                        self._socket = self._context.socket(zmq.SUB)
                        self._socket.setsockopt(zmq.LINGER, 0)
                        self._socket.setsockopt(zmq.RCVHWM, 1)
                        self._socket.setsockopt(zmq.RCVTIMEO, 100)
                        self._socket.setsockopt_string(zmq.SUBSCRIBE, "")
                        self._socket.connect(endpoint)
                    except Exception as reconnect_error:
                        logger.error(f"Errore durante la riconnessione: {reconnect_error}")

                except Exception as e:
                    logger.error(f"Errore nella ricezione: {e}")
                    self.error_occurred.emit(str(e))
                    time.sleep(0.1)  # Breve pausa in caso di errore

        except Exception as e:
            logger.error(f"Errore fatale nel thread di ricezione: {e}")
            self.error_occurred.emit(str(e))

        finally:
            # Pulizia risorse
            if self._socket:
                self._socket.close()
            if self._context:
                self._context.term()

            if self._connected:
                self._connected = False
                self.connection_state_changed.emit(False)

            logger.info("Thread di ricezione terminato")

    def stop(self):
        """Ferma il thread di ricezione."""
        self._running = False
        self.wait(1000)  # Attendi fino a 1 secondo


class StreamReceiver(QObject):
    """
    Classe principale che gestisce la ricezione degli stream senza buffering.
    Questa versione elimina tutte le code e processa i frame direttamente.
    """

    # Segnali
    frame_received = Signal(int, np.ndarray, float)  # camera_index, frame, timestamp
    stream_started = Signal(int)  # camera_index
    stream_stopped = Signal(int)  # camera_index
    stream_error = Signal(int, str)  # camera_index, error_message

    def __init__(self, host: str, port: int):
        super().__init__()
        self.host = host
        self.port = port

        # Stato
        self._running = False
        self._cameras_active = set()

        # Thread di ricezione
        self._receiver_thread = None

        # Statistiche base
        self._stats = {}
        for camera_idx in range(2):  # Assumiamo massimo 2 camere
            self._stats[camera_idx] = {
                "frames_received": 0,
                "last_frame_time": 0,
                "fps": 0,
                "lag_ms": 0
            }

        logger.info(f"StreamReceiver senza buffering inizializzato: host={host}, port={port}")

    def start(self) -> bool:
        """Avvia la ricezione dello stream."""
        if self._running:
            logger.warning("StreamReceiver già in esecuzione")
            return True

        logger.info(f"Avvio StreamReceiver ottimizzato: {self.host}:{self.port}")

        try:
            self._running = True

            # Crea e avvia thread di ricezione
            self._receiver_thread = StreamReceiverThread(self.host, self.port)
            self._receiver_thread.frame_decoded.connect(self._on_frame_decoded)
            self._receiver_thread.connection_state_changed.connect(self._on_connection_state_changed)
            self._receiver_thread.error_occurred.connect(self._on_error)
            self._receiver_thread.start()

            return True

        except Exception as e:
            logger.error(f"Errore nell'avvio di StreamReceiver: {e}")
            self._running = False
            return False

    def stop(self):
        """Ferma la ricezione dello stream."""
        if not self._running:
            return

        logger.info("Arresto StreamReceiver...")

        self._running = False

        # Ferma thread di ricezione
        if self._receiver_thread:
            self._receiver_thread.stop()
            self._receiver_thread = None

        # Notifica arresto per tutte le camere attive
        for camera_idx in list(self._cameras_active):
            self.stream_stopped.emit(camera_idx)

        self._cameras_active.clear()

        logger.info("StreamReceiver arrestato")

    def is_running(self) -> bool:
        """Verifica se il ricevitore è in esecuzione."""
        return self._running

    def get_stats(self, camera_index: int) -> Dict[str, Any]:
        """Ottieni statistiche per una camera."""
        return self._stats.get(camera_index, {}).copy()

    @Slot(int, np.ndarray, float)
    def _on_frame_decoded(self, camera_index: int, frame: np.ndarray, timestamp: float):
        """Gestisce un frame decodificato dal thread di ricezione."""
        # Registra la camera come attiva se è la prima volta
        if camera_index not in self._cameras_active:
            self._cameras_active.add(camera_index)
            self.stream_started.emit(camera_index)
            logger.info(f"Stream avviato per camera {camera_index}")

        # Aggiorna statistiche
        if camera_index in self._stats:
            stats = self._stats[camera_index]
            stats["frames_received"] += 1

            # Calcola FPS
            current_time = time.time()
            if stats["last_frame_time"] > 0:
                frame_delta = current_time - stats["last_frame_time"]
                if frame_delta > 0:
                    instantaneous_fps = 1.0 / frame_delta
                    # Media mobile per stabilizzare FPS
                    alpha = 0.2
                    stats["fps"] = (1.0 - alpha) * stats["fps"] + alpha * instantaneous_fps

            stats["last_frame_time"] = current_time

            # Calcola lag
            lag_ms = int((current_time - timestamp) * 1000)
            stats["lag_ms"] = lag_ms

            # Log di statistiche occasionale
            if stats["frames_received"] % 100 == 0:
                logger.debug(f"Statistiche camera {camera_index}: "
                             f"frames={stats['frames_received']}, "
                             f"fps={stats['fps']:.1f}, "
                             f"lag={lag_ms}ms")

        # Emetti il frame
        self.frame_received.emit(camera_index, frame, timestamp)

    @Slot(bool)
    def _on_connection_state_changed(self, connected: bool):
        """Gestisce cambiamenti nello stato della connessione."""
        if connected:
            logger.info("Connessione stabilita")
        else:
            logger.warning("Connessione persa")
            # Notifica errore a tutte le camere attive
            for camera_idx in list(self._cameras_active):
                self.stream_error.emit(camera_idx, "Connessione persa")

    @Slot(str)
    def _on_error(self, error_msg: str):
        """Gestisce errori dal thread di ricezione."""
        logger.error(f"Errore nel ricevitore: {error_msg}")
        # Notifica errore a tutte le camere attive
        for camera_idx in list(self._cameras_active):
            self.stream_error.emit(camera_idx, error_msg)