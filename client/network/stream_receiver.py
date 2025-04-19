#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Gestore per la ricezione degli stream video dal server UnLook.
Versione migliorata con gestione degli errori e robustezza aumentata.
"""

import json
import logging
import time
import threading
import cv2
import numpy as np
from typing import Dict, Any, Optional, Callable, Tuple, List

import zmq
from PySide6.QtCore import QObject, Signal, Slot, QTimer, QMutex, QMutexLocker

try:
    from client.utils.thread_safe_queue import ThreadSafeQueue
except ImportError:
    # Fallback per esecuzione diretta
    from utils.thread_safe_queue import ThreadSafeQueue

logger = logging.getLogger(__name__)


class StreamReceiver(QObject):
    """
    Riceve e gestisce gli stream video dal server UnLook.
    Supporta streaming JPEG con riconnessione automatica.
    """

    # Segnali
    frame_received = Signal(int, np.ndarray)  # camera_index, frame
    stream_started = Signal(int)  # camera_index
    stream_stopped = Signal(int)  # camera_index
    stream_error = Signal(int, str)  # camera_index, error_message

    def __init__(self, host: str, port: int, queue_size: int = 5):
        super().__init__()
        self.host = host
        self.port = port
        self.queue_size = queue_size

        # Stato
        self._running = False
        self._paused = False
        self._cameras_receiving = set()
        self._connected = False
        self._reconnect_timer = QTimer(self)
        self._reconnect_timer.timeout.connect(self._attempt_reconnect)
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 5
        self._last_frame_time = 0
        self._frame_timeout = 5.0  # secondi

        # Socket ZeroMQ
        self._context = None
        self._socket = None
        self._socket_mutex = QMutex()

        # Thread di ricezione
        self._receiver_thread = None
        self._processor_threads = {}

        # Code di frame
        self._frame_queues = {
            0: ThreadSafeQueue(maxsize=queue_size),  # Camera sinistra
            1: ThreadSafeQueue(maxsize=queue_size)  # Camera destra
        }

        # Statistiche
        self._stats = {
            0: {  # Camera sinistra
                "frames_received": 0,
                "frames_processed": 0,
                "last_frame_time": 0,
                "fps": 0
            },
            1: {  # Camera destra
                "frames_received": 0,
                "frames_processed": 0,
                "last_frame_time": 0,
                "fps": 0
            }
        }

        logger.info(f"StreamReceiver inizializzato con host={host}, port={port}")

    def start(self):
        """Avvia la ricezione dello stream."""
        if self._running:
            logger.warning("StreamReceiver già in esecuzione")
            return True

        logger.info(f"Avvio dello StreamReceiver {self.host}:{self.port}")

        try:
            # Imposta lo stato
            self._running = True
            self._paused = False
            self._reconnect_attempts = 0

            # Crea il contesto ZeroMQ (se non esiste già)
            if not self._context:
                self._context = zmq.Context()

            # Inizializza la connessione
            self._initialize_connection()

            # Avvia il thread di ricezione
            self._receiver_thread = threading.Thread(target=self._receive_loop)
            self._receiver_thread.daemon = True
            self._receiver_thread.start()

            return True

        except Exception as e:
            logger.error(f"Errore nell'avvio dello StreamReceiver: {e}")
            self._cleanup()
            return False

    def _process_frame_message(self, header: Dict[str, Any], data: bytes):
        """
        Processa un messaggio di frame ricevuto.

        Args:
            header: Header del messaggio
            data: Dati binari del frame
        """
        try:
            # Estrai le informazioni dall'header
            camera_index = header["camera"]
            frame_number = header["frame"]
            timestamp = header["timestamp"]
            format_str = header["format"]
            resolution = header["resolution"]

            # Debug per vedere cosa stiamo ricevendo
            logger.debug(
                f"Header frame: camera={camera_index}, n={frame_number}, formato={format_str}, risoluzione={resolution}")
            logger.debug(f"Dimensione dati frame: {len(data)} bytes")

            # Aggiorna le statistiche
            stats = self._stats[camera_index]
            stats["frames_received"] += 1

            # Se è il primo frame per questa camera, avvia il processore
            if camera_index not in self._cameras_receiving:
                self._cameras_receiving.add(camera_index)
                self._start_processor(camera_index, format_str, resolution)
                self.stream_started.emit(camera_index)

            # Aggiungi il frame alla coda (non bloccare se la coda è piena)
            # Nota: qui passiamo una tupla con (frame_number, timestamp, format_str, resolution, data)
            frame_data = (frame_number, timestamp, format_str, resolution, data)

            # Verifico che stiamo inserendo dati validi
            if data is None or len(data) == 0:
                logger.warning(f"Dati frame vuoti/None per camera {camera_index}, frame {frame_number}")
                return

            self._frame_queues[camera_index].put(frame_data, block=False)
            logger.debug(f"Frame accodato: camera={camera_index}, n={frame_number}, formato={format_str}")

        except Exception as e:
            logger.error(f"Errore nell'elaborazione del messaggio di frame: {e}")

    def _initialize_connection(self):
        """Inizializza la connessione ZeroMQ."""
        with QMutexLocker(self._socket_mutex):
            try:
                # Chiudi il socket esistente se presente
                if self._socket:
                    try:
                        self._socket.close()
                    except:
                        pass
                    self._socket = None

                # Crea un nuovo socket
                self._socket = self._context.socket(zmq.SUB)

                # Configura il socket
                self._socket.setsockopt(zmq.LINGER, 100)  # Non aspettare troppo alla chiusura
                self._socket.setsockopt(zmq.RCVHWM, 10)  # Limita la coda di ricezione hardware
                self._socket.setsockopt(zmq.RCVTIMEO, 1000)  # Timeout di ricezione di 1 secondo
                self._socket.setsockopt(zmq.RECONNECT_IVL, 100)  # 100ms tra tentativi di riconnessione
                self._socket.setsockopt(zmq.RECONNECT_IVL_MAX, 5000)  # Max 5 secondi tra tentativi

                # Sottoscrivi a tutti i messaggi
                self._socket.setsockopt(zmq.SUBSCRIBE, b"")

                # Connetti al server
                endpoint = f"tcp://{self.host}:{self.port}"
                self._socket.connect(endpoint)

                logger.info(f"Connessione ZeroMQ stabilita con {endpoint}")
                self._connected = True

            except Exception as e:
                logger.error(f"Errore nell'inizializzazione della connessione: {e}")
                self._connected = False
                raise

    def _attempt_reconnect(self):
        """Tenta di riconnettersi al server."""
        if not self._running or self._connected:
            self._reconnect_timer.stop()
            return

        self._reconnect_attempts += 1
        logger.info(f"Tentativo di riconnessione {self._reconnect_attempts}/{self._max_reconnect_attempts}")

        if self._reconnect_attempts > self._max_reconnect_attempts:
            logger.error("Numero massimo di tentativi di riconnessione raggiunto")
            self._reconnect_timer.stop()

            # Emetti errori per tutte le camere attive
            for camera_index in self._cameras_receiving:
                self.stream_error.emit(camera_index, "Connessione persa, impossibile riconnettersi")

            # Ferma lo streaming
            self.stop()
            return

        try:
            self._initialize_connection()
            logger.info("Riconnessione riuscita")
            self._reconnect_timer.stop()
            self._connected = True
        except Exception as e:
            logger.error(f"Errore nella riconnessione: {e}")
            # Aumenta progressivamente il tempo tra i tentativi
            self._reconnect_timer.setInterval(1000 * self._reconnect_attempts)

    def stop(self):
        """Ferma la ricezione dello stream."""
        if not self._running:
            return

        logger.info("Arresto dello StreamReceiver...")

        # Imposta lo stato
        self._running = False

        # Ferma il timer di riconnessione
        if self._reconnect_timer.isActive():
            self._reconnect_timer.stop()

        # Attendi la terminazione del thread di ricezione
        if self._receiver_thread and self._receiver_thread.is_alive():
            self._receiver_thread.join(timeout=2.0)

        # Ferma i thread di processamento
        for camera_index in list(self._processor_threads.keys()):
            self._stop_processor(camera_index)

        # Pulizia delle risorse
        self._cleanup()

        logger.info("StreamReceiver arrestato")

    def pause(self):
        """Mette in pausa la ricezione dello stream."""
        if not self._running or self._paused:
            return

        logger.info("Pausa dello StreamReceiver")
        self._paused = True

    def resume(self):
        """Riprende la ricezione dello stream."""
        if not self._running or not self._paused:
            return

        logger.info("Ripresa dello StreamReceiver")
        self._paused = False

    def is_running(self) -> bool:
        """Verifica se il receiver è in esecuzione."""
        return self._running

    def is_paused(self) -> bool:
        """Verifica se il receiver è in pausa."""
        return self._paused

    def get_stats(self, camera_index: int) -> Dict[str, Any]:
        """Restituisce le statistiche per una camera."""
        if camera_index not in self._stats:
            return {}

        return self._stats[camera_index].copy()

    def clear_queue(self, camera_index: int):
        """Svuota la coda dei frame per una camera."""
        if camera_index in self._frame_queues:
            self._frame_queues[camera_index].clear()

    def _receive_loop(self):
        """Loop principale per la ricezione dei frame."""
        logger.info("Thread di ricezione avviato")

        try:
            while self._running:
                try:
                    if not self._connected:
                        # Se non siamo connessi, attendi un po' e riprova
                        if not self._reconnect_timer.isActive():
                            # Avvia il timer di riconnessione solo se non è già attivo
                            self._reconnect_timer.start(1000)  # 1 secondo
                        time.sleep(0.1)
                        continue

                    # Verifica timeout dei frame
                    if self._last_frame_time > 0 and time.time() - self._last_frame_time > self._frame_timeout:
                        logger.warning(f"Nessun frame ricevuto negli ultimi {self._frame_timeout} secondi")
                        self._connected = False
                        if not self._reconnect_timer.isActive():
                            self._reconnect_timer.start(1000)
                        continue

                    # Ricevi il messaggio (header JSON e dati binari)
                    with QMutexLocker(self._socket_mutex):
                        try:
                            # Ricevi l'header
                            header_data = self._socket.recv()

                            # Aggiorna il timestamp dell'ultimo frame
                            self._last_frame_time = time.time()

                            # Assicurati che ci siano altri dati da ricevere
                            if not self._socket.get(zmq.RCVMORE):
                                logger.warning("Ricevuto header senza dati del frame")
                                continue

                            # Ricevi i dati del frame
                            frame_data = self._socket.recv()

                            # Decodifica l'header
                            header = json.loads(header_data.decode('utf-8'))

                            # Reset del contatore di tentativi di riconnessione
                            self._reconnect_attempts = 0

                        except zmq.ZMQError as e:
                            if e.errno == zmq.EAGAIN:
                                # Timeout di ricezione, continua
                                continue
                            logger.error(f"Errore ZMQ nella ricezione: {e}")
                            if e.errno in (zmq.ETERM, zmq.ENOTSOCK, zmq.ENOTSUP):
                                # Errori fatali
                                self._connected = False
                                if not self._reconnect_timer.isActive():
                                    self._reconnect_timer.start(1000)
                            continue
                        except Exception as e:
                            logger.error(f"Errore nella decodifica dell'header: {e}")
                            continue

                    # Salta i frame se in pausa
                    if self._paused:
                        continue

                    # Processa il frame
                    self._process_frame_message(header, frame_data)

                except Exception as e:
                    logger.error(f"Errore nella ricezione del frame: {e}")
                    if not self._running:
                        break
                    time.sleep(0.1)  # Breve pausa in caso di errore

        except Exception as e:
            logger.error(f"Errore fatale nel thread di ricezione: {e}")

        logger.info("Thread di ricezione terminato")

    def _process_frame_message(self, header: Dict[str, Any], data: bytes):
        """
        Processa un messaggio di frame ricevuto.

        Args:
            header: Header del messaggio
            data: Dati binari del frame
        """
        try:
            # Estrai le informazioni dall'header
            camera_index = header["camera"]
            frame_number = header["frame"]
            timestamp = header["timestamp"]
            format_str = header["format"]
            resolution = header["resolution"]

            # Aggiorna le statistiche
            stats = self._stats[camera_index]
            stats["frames_received"] += 1

            # Se è il primo frame per questa camera, avvia il processore
            if camera_index not in self._cameras_receiving:
                self._cameras_receiving.add(camera_index)
                self._start_processor(camera_index, format_str, resolution)
                self.stream_started.emit(camera_index)

            # Aggiungi il frame alla coda (non bloccare se la coda è piena)
            self._frame_queues[camera_index].put((
                frame_number, timestamp, format_str, resolution, data
            ), block=False)

            logger.debug(f"Frame ricevuto: camera={camera_index}, n={frame_number}, formato={format_str}")

        except Exception as e:
            logger.error(f"Errore nell'elaborazione del messaggio di frame: {e}")

    def _start_processor(self, camera_index: int, format_str: str, resolution: List[int]):
        """
        Avvia un thread di processamento per una camera.

        Args:
            camera_index: Indice della camera
            format_str: Formato dello stream
            resolution: Risoluzione dello stream
        """
        # Verifica se c'è già un thread attivo
        if camera_index in self._processor_threads:
            thread = self._processor_threads[camera_index]
            if thread.is_alive():
                return

        # Avvia il thread di processamento
        thread = threading.Thread(
            target=self._process_frames,
            args=(camera_index, format_str, tuple(resolution))
        )
        thread.daemon = True
        thread.start()

        self._processor_threads[camera_index] = thread
        logger.info(f"Processore avviato per camera {camera_index}, formato={format_str}, risoluzione={resolution}")

    def _stop_processor(self, camera_index: int):
        """
        Ferma il thread di processamento per una camera.

        Args:
            camera_index: Indice della camera
        """
        # Rimuovi la camera dalle attive
        if camera_index in self._cameras_receiving:
            self._cameras_receiving.remove(camera_index)

        # Attendi che il thread termini
        if camera_index in self._processor_threads:
            thread = self._processor_threads[camera_index]
            if thread.is_alive():
                thread.join(timeout=2.0)
            del self._processor_threads[camera_index]

        # Svuota la coda
        if camera_index in self._frame_queues:
            self._frame_queues[camera_index].clear()

        # Emetti il segnale di stream fermato
        self.stream_stopped.emit(camera_index)
        logger.info(f"Processore fermato per camera {camera_index}")

    def _process_frames(self, camera_index: int, format_str: str, resolution: Tuple[int, int]):
        """
        Loop di processamento dei frame per una camera.

        Args:
            camera_index: Indice della camera
            format_str: Formato dello stream
            resolution: Risoluzione dello stream
        """
        logger.info(f"Thread di processamento camera {camera_index} avviato")

        try:
            queue = self._frame_queues[camera_index]
            stats = self._stats[camera_index]

            # Imposta la larghezza e altezza
            width, height = resolution

            while camera_index in self._cameras_receiving and self._running:
                try:
                    # Preleva un frame dalla coda
                    frame_data = queue.get(block=True, timeout=1.0)

                    # Verifica che frame_data non sia None (timeout della coda)
                    if frame_data is None:
                        logger.debug(f"Timeout o dati None dalla coda per camera {camera_index}")
                        continue

                    # Stampa debug per verificare cosa stiamo ricevendo
                    logger.debug(f"Dati frame estratti dalla coda: camera={camera_index}, tipo={type(frame_data)}")

                    try:
                        # Ora spacchetta la tupla in modo sicuro
                        frame_number, timestamp, format_str, resolution, data = frame_data

                        logger.debug(
                            f"Frame decodificato: n={frame_number}, formato={format_str}, dim_dati={len(data) if data is not None else 'None'}")

                        # Decodifica il frame in base al formato
                        if format_str.lower() == "jpeg":
                            # Decodifica JPEG
                            try:
                                # Converti i dati in un buffer numpy
                                frame_buffer = np.frombuffer(data, dtype=np.uint8)

                                # Decodifica l'immagine JPEG
                                frame = cv2.imdecode(frame_buffer, cv2.IMREAD_COLOR)

                                if frame is not None and frame.size > 0:
                                    logger.debug(f"Frame decodificato con successo: shape={frame.shape}")
                                    # Emetti il frame decodificato
                                    self.frame_received.emit(camera_index, frame)
                                    stats["frames_processed"] += 1
                                else:
                                    logger.warning(f"Frame non valido ricevuto dalla camera {camera_index}")
                            except Exception as e:
                                logger.error(f"Errore nella decodifica JPEG: {e}")
                                continue
                        elif format_str.lower() == "h264":
                            # Per ora, saltiamo i frame H.264 (richiederebbe un decoder specifico)
                            logger.warning("Formato H264 ricevuto ma non supportato dal StreamReceiver")
                            continue
                        else:
                            # Formato non supportato
                            logger.warning(f"Formato frame non supportato: {format_str}")
                            continue
                    except ValueError as e:
                        logger.error(f"Errore nello spacchettamento dei dati del frame: {e}, dati={frame_data}")
                        continue

                    # Calcola FPS
                    current_time = time.time()
                    if stats["last_frame_time"] > 0:
                        time_diff = current_time - stats["last_frame_time"]
                        if time_diff > 0:
                            # Calcola FPS istantaneo
                            instant_fps = 1.0 / time_diff
                            # Media mobile per stabilizzare il valore
                            alpha = 0.2
                            stats["fps"] = (1.0 - alpha) * stats["fps"] + alpha * instant_fps

                    stats["last_frame_time"] = current_time

                except Exception as e:
                    if camera_index in self._cameras_receiving and self._running:
                        logger.error(f"Errore nel processamento del frame per camera {camera_index}: {e}")
                        # Emetti il segnale di errore
                        self.stream_error.emit(camera_index, str(e))
                        time.sleep(0.1)  # Breve pausa in caso di errore

        except Exception as e:
            logger.error(f"Errore fatale nel thread di processamento camera {camera_index}: {e}")
            # Emetti il segnale di errore
            self.stream_error.emit(camera_index, str(e))

        logger.info(f"Thread di processamento camera {camera_index} terminato")

    def _cleanup(self):
        """Pulisce le risorse."""
        # Chiudi il socket
        with QMutexLocker(self._socket_mutex):
            if self._socket:
                try:
                    self._socket.close()
                except:
                    pass
                self._socket = None

        # Termina il context ZMQ
        if self._context:
            try:
                self._context.term()
            except:
                pass
            self._context = None

        # Svuota le code
        for queue in self._frame_queues.values():
            queue.clear()

        # Reimposta lo stato
        self._cameras_receiving = set()
        self._processor_threads = {}
        self._connected = False