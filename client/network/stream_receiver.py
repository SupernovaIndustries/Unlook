#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Gestore per la ricezione degli stream video dal server UnLook.
"""

import logging
import time
import threading
import cv2
import numpy as np
from typing import Dict, Any, Optional, Callable, Tuple, List

import zmq
from PySide6.QtCore import QObject, Signal, Slot

try:
    from client.utils.thread_safe_queue import ThreadSafeQueue
except ImportError:
    # Fallback per esecuzione diretta
    from utils.thread_safe_queue import ThreadSafeQueue

logger = logging.getLogger(__name__)


class StreamReceiver(QObject):
    """
    Riceve e gestisce gli stream video dal server UnLook.
    Supporta streaming JPEG.
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

        # Socket ZeroMQ
        self._context = zmq.Context()
        self._socket = None

        # Thread di ricezione
        self._receiver_thread = None

        # Code di frame
        self._frame_queues = {
            0: ThreadSafeQueue(maxsize=queue_size),  # Camera sinistra
            1: ThreadSafeQueue(maxsize=queue_size)  # Camera destra
        }

        # Thread di processamento
        self._processor_threads = {}

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
            # Crea il socket ZeroMQ
            self._socket = self._context.socket(zmq.SUB)

            # Configura il socket
            self._socket.setsockopt(zmq.LINGER, 0)  # Non aspettare alla chiusura
            self._socket.connect(f"tcp://{self.host}:{self.port}")
            self._socket.setsockopt(zmq.SUBSCRIBE, b"")  # Sottoscrivi a tutti i messaggi

            # Imposta lo stato
            self._running = True
            self._paused = False

            # Avvia il thread di ricezione
            self._receiver_thread = threading.Thread(target=self._receive_loop)
            self._receiver_thread.daemon = True
            self._receiver_thread.start()

            logger.info(f"StreamReceiver avviato su {self.host}:{self.port}")
            return True

        except Exception as e:
            logger.error(f"Errore nell'avvio dello StreamReceiver: {e}")
            self._cleanup()
            return False

    def stop(self):
        """Ferma la ricezione dello stream."""
        if not self._running:
            return

        logger.info("Arresto dello StreamReceiver...")

        # Imposta lo stato
        self._running = False

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
            # Setup poller per timeout più preciso
            poller = zmq.Poller()
            poller.register(self._socket, zmq.POLLIN)

            while self._running:
                try:
                    # Usa il poller con timeout
                    socks = dict(poller.poll(500))  # 500ms di timeout

                    # Se non ci sono messaggi, continua
                    if self._socket not in socks:
                        continue

                    # Ricevi il messaggio (header JSON e dati binari)
                    try:
                        # Ricevi l'header
                        header_data = self._socket.recv()

                        # Assicurati che ci siano altri dati da ricevere
                        if not self._socket.get(zmq.RCVMORE):
                            logger.warning("Ricevuto header senza dati del frame")
                            continue

                        # Ricevi i dati del frame
                        frame_data = self._socket.recv()

                        # Decodifica l'header
                        header = json.loads(header_data.decode('utf-8'))
                    except zmq.ZMQError as e:
                        logger.error(f"Errore ZMQ nella ricezione: {e}")
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

            # Aggiungi il frame alla coda
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
                    if not frame_data:
                        continue

                    frame_number, timestamp, format_str, resolution, data = frame_data

                    # Decodifica il frame in base al formato
                    if format_str.lower() == "jpeg":
                        # Decodifica JPEG
                        try:
                            # Converti i dati in un buffer numpy
                            frame_buffer = np.frombuffer(data, dtype=np.uint8)

                            # Decodifica l'immagine JPEG
                            frame = cv2.imdecode(frame_buffer, cv2.IMREAD_COLOR)

                            if frame is not None and frame.size > 0:
                                # Emetti il frame decodificato
                                self.frame_received.emit(camera_index, frame)
                                stats["frames_processed"] += 1
                            else:
                                logger.warning(f"Frame non valido ricevuto dalla camera {camera_index}")
                        except Exception as e:
                            logger.error(f"Errore nella decodifica JPEG: {e}")
                            continue
                    else:
                        # Formato non supportato
                        logger.warning(f"Formato frame non supportato: {format_str}")
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


# Import json qui per evitare errori di circularità
import json