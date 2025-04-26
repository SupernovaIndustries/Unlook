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


class StreamReceiverThread(QThread):
    """
    Thread dedicato per ricevere lo stream video senza buffering.
    Processa ed emette ogni frame direttamente senza code intermedie.
    Versione ottimizzata con riconnessione automatica e gestione robusta degli errori.
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
        self._received_cameras = set()
        self._frame_counters = {0: 0, 1: 0}  # Contatori per entrambe le camere
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 5
        self._mutex = QMutex()  # Mutex per proteggere lo stato

    def run(self):
        """Loop principale del thread con meccanismo di riconnessione automatica."""
        reconnect_delay = 1.0  # Delay iniziale in secondi

        while self._reconnect_attempts <= self._max_reconnect_attempts:
            try:
                # Inizializza ZeroMQ
                self._context = zmq.Context()
                self._socket = self._context.socket(zmq.SUB)

                # Configurazione migliorata per ZeroMQ
                self._socket.setsockopt(zmq.LINGER, 0)  # Non attendere alla chiusura
                self._socket.setsockopt(zmq.RCVHWM, 2)  # Limita buffer ma mantieni compatibilità multipart
                self._socket.setsockopt_string(zmq.SUBSCRIBE, "")  # Sottoscrivi a tutto

                # Impostiamo un timeout più breve per rilevare disconnessioni più rapidamente
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
                    self._reconnect_attempts = 0  # Reset counter on successful connection

                self.connection_state_changed.emit(True)

                # Log dei parametri di prestazione
                logger.info(f"StreamReceiverThread inizializzato: buffer limitato a 2 messaggi, timeout 500ms")

                # Loop principale
                while self._is_running():
                    try:
                        # Attendi l'header
                        try:
                            header_data = self._socket.recv()
                        except zmq.Again:
                            # Controlliamo se l'inattività è troppo lunga
                            current_time = time.time()

                            with QMutexLocker(self._mutex):
                                inactivity_time = current_time - self._last_activity
                                is_connected = self._connected

                            # Se non c'è attività per 5 secondi, controlliamo se il server è ancora vivo
                            if inactivity_time > 5.0 and is_connected:
                                # Non cambiamo immediatamente lo stato, attendiamo ulteriormente
                                if inactivity_time > 10.0:
                                    # Dopo 10 secondi senza attività, considera la connessione persa
                                    logger.warning(
                                        f"Nessuna attività per {inactivity_time:.1f} secondi, potenziale disconnessione")

                                    # Facciamo un ultimo tentativo di controllo dell'aliveness del socket
                                    if inactivity_time > 15.0:
                                        logger.error(
                                            f"Nessuna attività per {inactivity_time:.1f} secondi, connessione persa")
                                        with QMutexLocker(self._mutex):
                                            self._connected = False
                                        self.connection_state_changed.emit(False)
                                        # Usciamo dal loop principale per attivare la riconnessione
                                        break
                            continue

                        # Aggiorna timestamp di attività
                        with QMutexLocker(self._mutex):
                            self._last_activity = time.time()
                            was_connected = self._connected

                            # Se non eravamo connessi, ora lo siamo
                            if not was_connected:
                                self._connected = True
                                emit_connection_change = True
                            else:
                                emit_connection_change = False

                        # Se c'è stata una disconnessione, notifichiamo che la connessione è di nuovo attiva
                        if emit_connection_change:
                            self.connection_state_changed.emit(True)
                            logger.info("Connessione ripristinata, ricezione dati")

                        # Verifica se ci sono altri dati (dati del frame)
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
                        except json.JSONDecodeError:
                            logger.warning("Header JSON non valido")
                            continue

                        # Verifica dati minimi necessari
                        if None in (camera_index, timestamp, format_str):
                            logger.warning(f"Header incompleto: {header}")
                            continue

                        # Aggiungi camera all'insieme delle camere rilevate
                        with QMutexLocker(self._mutex):
                            if camera_index not in self._received_cameras:
                                self._received_cameras.add(camera_index)
                                new_camera = True
                            else:
                                new_camera = False

                            # Registra la ricezione del frame
                            self._frame_counters[camera_index] = self._frame_counters.get(camera_index, 0) + 1
                            frame_count = self._frame_counters[camera_index]

                        if new_camera:
                            logger.info(f"Nuova camera rilevata: {camera_index}")

                        if frame_count % 100 == 0:
                            logger.debug(f"Ricevuti {frame_count} frame dalla camera {camera_index}")

                        # Decodifica frame immediatamente con ottimizzazioni
                        if format_str.lower() == "jpeg":
                            try:
                                # Decodifica con IMDECODE_UNCHANGED per mantenere il formato originale
                                frame_buffer = np.frombuffer(frame_data, dtype=np.uint8)

                                # Usa IMREAD_UNCHANGED per preservare alpha channel se presente
                                frame = cv2.imdecode(frame_buffer, cv2.IMREAD_UNCHANGED)

                                if frame is None or frame.size == 0:
                                    logger.warning(f"Decodifica fallita per frame della camera {camera_index}")
                                    continue

                                # Emetti il frame decodificato direttamente
                                self.frame_decoded.emit(camera_index, frame, timestamp)

                            except Exception as decode_error:
                                logger.warning(f"Errore nella decodifica: {decode_error}")
                                continue

                    except zmq.ZMQError as e:
                        if e.errno == zmq.EAGAIN:
                            # Timeout normale, continua
                            continue

                        logger.error(f"Errore ZMQ: {e}")

                        # Verifica se il thread è stato fermato
                        if not self._is_running():
                            break

                        # Usciamo dal loop principale per attivare il meccanismo di riconnessione
                        break

                    except Exception as e:
                        logger.error(f"Errore nella ricezione: {e}")
                        self.error_occurred.emit(str(e))
                        time.sleep(0.1)  # Breve pausa in caso di errore

                # Se siamo usciti dal loop principale in seguito a uno stop esplicito,
                # usciamo anche dal loop di riconnessione
                if not self._is_running():
                    break

                # Se siamo qui, c'è stato un errore e dobbiamo riconnetterci
                self._cleanup_socket()

                with QMutexLocker(self._mutex):
                    self._reconnect_attempts += 1
                    reconnect_attempt = self._reconnect_attempts

                # Backoff esponenziale
                current_delay = min(reconnect_delay * (2 ** (reconnect_attempt - 1)), 30.0)
                logger.info(f"Attesa di {current_delay:.1f} secondi prima del tentativo di riconnessione...")
                time.sleep(current_delay)

            except Exception as e:
                logger.error(f"Errore fatale nel thread di ricezione: {e}")
                self.error_occurred.emit(str(e))

                # Verifica se il thread è stato fermato
                if not self._is_running():
                    break

                # Pulisci il socket corrente
                self._cleanup_socket()

                # Incrementa il contatore di tentativi
                with QMutexLocker(self._mutex):
                    self._reconnect_attempts += 1
                    reconnect_attempt = self._reconnect_attempts
                    max_attempts = self._max_reconnect_attempts

                # Se abbiamo superato il numero massimo di tentativi, usciamo
                if reconnect_attempt > max_attempts:
                    logger.error(f"Superato il numero massimo di tentativi di riconnessione ({max_attempts})")
                    break

                # Backoff esponenziale
                current_delay = min(reconnect_delay * (2 ** (reconnect_attempt - 1)), 30.0)
                logger.info(
                    f"Attesa di {current_delay:.1f} secondi prima del tentativo di riconnessione dopo errore fatale...")
                time.sleep(current_delay)

        # Se siamo qui, abbiamo esaurito i tentativi o abbiamo terminato normalmente
        self._cleanup_socket()

        with QMutexLocker(self._mutex):
            was_connected = self._connected
            self._connected = False

        if was_connected:
            self.connection_state_changed.emit(False)

        logger.info("Thread di ricezione terminato")

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
        if not self.wait(2000):  # 2 secondi di timeout
            logger.warning("Timeout nell'attesa della terminazione del thread di ricezione")

        # Assicurati che le risorse siano rilasciate
        self._cleanup_socket()
        logger.info("Thread di ricezione arrestato")

    @property
    def cameras_active(self) -> set:
        """Restituisce l'insieme delle camere attivamente rilevate."""
        with QMutexLocker(self._mutex):
            return self._received_cameras.copy()  # Restituisci una copia per evitare race condition


class StreamReceiverThread(QThread):
    """
    Thread dedicato per ricevere lo stream video senza buffering.
    Processa ed emette ogni frame direttamente senza code intermedie.
    Versione ottimizzata con riconnessione automatica e gestione robusta degli errori.
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
        self._received_cameras = set()
        self._frame_counters = {0: 0, 1: 0}  # Contatori per entrambe le camere
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 5
        self._mutex = QMutex()  # Mutex per proteggere lo stato

    def run(self):
        """Loop principale del thread con meccanismo di riconnessione automatica."""
        reconnect_delay = 1.0  # Delay iniziale in secondi

        while self._reconnect_attempts <= self._max_reconnect_attempts:
            try:
                # Inizializza ZeroMQ
                self._context = zmq.Context()
                self._socket = self._context.socket(zmq.SUB)

                # Configurazione migliorata per ZeroMQ
                self._socket.setsockopt(zmq.LINGER, 0)  # Non attendere alla chiusura
                self._socket.setsockopt(zmq.RCVHWM, 2)  # Limita buffer ma mantieni compatibilità multipart
                self._socket.setsockopt_string(zmq.SUBSCRIBE, "")  # Sottoscrivi a tutto

                # Impostiamo un timeout più breve per rilevare disconnessioni più rapidamente
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
                    self._reconnect_attempts = 0  # Reset counter on successful connection

                self.connection_state_changed.emit(True)

                # Log dei parametri di prestazione
                logger.info(f"StreamReceiverThread inizializzato: buffer limitato a 2 messaggi, timeout 500ms")

                # Loop principale
                while self._is_running():
                    try:
                        # Attendi l'header
                        try:
                            header_data = self._socket.recv()
                        except zmq.Again:
                            # Controlliamo se l'inattività è troppo lunga
                            current_time = time.time()

                            with QMutexLocker(self._mutex):
                                inactivity_time = current_time - self._last_activity
                                is_connected = self._connected

                            # Se non c'è attività per 5 secondi, controlliamo se il server è ancora vivo
                            if inactivity_time > 5.0 and is_connected:
                                # Non cambiamo immediatamente lo stato, attendiamo ulteriormente
                                if inactivity_time > 10.0:
                                    # Dopo 10 secondi senza attività, considera la connessione persa
                                    logger.warning(
                                        f"Nessuna attività per {inactivity_time:.1f} secondi, potenziale disconnessione")

                                    # Facciamo un ultimo tentativo di controllo dell'aliveness del socket
                                    if inactivity_time > 15.0:
                                        logger.error(
                                            f"Nessuna attività per {inactivity_time:.1f} secondi, connessione persa")
                                        with QMutexLocker(self._mutex):
                                            self._connected = False
                                        self.connection_state_changed.emit(False)
                                        # Usciamo dal loop principale per attivare la riconnessione
                                        break
                            continue

                        # Aggiorna timestamp di attività
                        with QMutexLocker(self._mutex):
                            self._last_activity = time.time()
                            was_connected = self._connected

                            # Se non eravamo connessi, ora lo siamo
                            if not was_connected:
                                self._connected = True
                                emit_connection_change = True
                            else:
                                emit_connection_change = False

                        # Se c'è stata una disconnessione, notifichiamo che la connessione è di nuovo attiva
                        if emit_connection_change:
                            self.connection_state_changed.emit(True)
                            logger.info("Connessione ripristinata, ricezione dati")

                        # Verifica se ci sono altri dati (dati del frame)
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
                        except json.JSONDecodeError:
                            logger.warning("Header JSON non valido")
                            continue

                        # Verifica dati minimi necessari
                        if None in (camera_index, timestamp, format_str):
                            logger.warning(f"Header incompleto: {header}")
                            continue

                        # Aggiungi camera all'insieme delle camere rilevate
                        with QMutexLocker(self._mutex):
                            if camera_index not in self._received_cameras:
                                self._received_cameras.add(camera_index)
                                new_camera = True
                            else:
                                new_camera = False

                            # Registra la ricezione del frame
                            self._frame_counters[camera_index] = self._frame_counters.get(camera_index, 0) + 1
                            frame_count = self._frame_counters[camera_index]

                        if new_camera:
                            logger.info(f"Nuova camera rilevata: {camera_index}")

                        if frame_count % 100 == 0:
                            logger.debug(f"Ricevuti {frame_count} frame dalla camera {camera_index}")

                        # Decodifica frame immediatamente con ottimizzazioni
                        if format_str.lower() == "jpeg":
                            try:
                                # Decodifica con IMDECODE_UNCHANGED per mantenere il formato originale
                                frame_buffer = np.frombuffer(frame_data, dtype=np.uint8)

                                # Usa IMREAD_UNCHANGED per preservare alpha channel se presente
                                frame = cv2.imdecode(frame_buffer, cv2.IMREAD_UNCHANGED)

                                if frame is None or frame.size == 0:
                                    logger.warning(f"Decodifica fallita per frame della camera {camera_index}")
                                    continue

                                # Emetti il frame decodificato direttamente
                                self.frame_decoded.emit(camera_index, frame, timestamp)

                            except Exception as decode_error:
                                logger.warning(f"Errore nella decodifica: {decode_error}")
                                continue

                    except zmq.ZMQError as e:
                        if e.errno == zmq.EAGAIN:
                            # Timeout normale, continua
                            continue

                        logger.error(f"Errore ZMQ: {e}")

                        # Verifica se il thread è stato fermato
                        if not self._is_running():
                            break

                        # Usciamo dal loop principale per attivare il meccanismo di riconnessione
                        break

                    except Exception as e:
                        logger.error(f"Errore nella ricezione: {e}")
                        self.error_occurred.emit(str(e))
                        time.sleep(0.1)  # Breve pausa in caso di errore

                # Se siamo usciti dal loop principale in seguito a uno stop esplicito,
                # usciamo anche dal loop di riconnessione
                if not self._is_running():
                    break

                # Se siamo qui, c'è stato un errore e dobbiamo riconnetterci
                self._cleanup_socket()

                with QMutexLocker(self._mutex):
                    self._reconnect_attempts += 1
                    reconnect_attempt = self._reconnect_attempts

                # Backoff esponenziale
                current_delay = min(reconnect_delay * (2 ** (reconnect_attempt - 1)), 30.0)
                logger.info(f"Attesa di {current_delay:.1f} secondi prima del tentativo di riconnessione...")
                time.sleep(current_delay)

            except Exception as e:
                logger.error(f"Errore fatale nel thread di ricezione: {e}")
                self.error_occurred.emit(str(e))

                # Verifica se il thread è stato fermato
                if not self._is_running():
                    break

                # Pulisci il socket corrente
                self._cleanup_socket()

                # Incrementa il contatore di tentativi
                with QMutexLocker(self._mutex):
                    self._reconnect_attempts += 1
                    reconnect_attempt = self._reconnect_attempts
                    max_attempts = self._max_reconnect_attempts

                # Se abbiamo superato il numero massimo di tentativi, usciamo
                if reconnect_attempt > max_attempts:
                    logger.error(f"Superato il numero massimo di tentativi di riconnessione ({max_attempts})")
                    break

                # Backoff esponenziale
                current_delay = min(reconnect_delay * (2 ** (reconnect_attempt - 1)), 30.0)
                logger.info(
                    f"Attesa di {current_delay:.1f} secondi prima del tentativo di riconnessione dopo errore fatale...")
                time.sleep(current_delay)

        # Se siamo qui, abbiamo esaurito i tentativi o abbiamo terminato normalmente
        self._cleanup_socket()

        with QMutexLocker(self._mutex):
            was_connected = self._connected
            self._connected = False

        if was_connected:
            self.connection_state_changed.emit(False)

        logger.info("Thread di ricezione terminato")

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
        if not self.wait(2000):  # 2 secondi di timeout
            logger.warning("Timeout nell'attesa della terminazione del thread di ricezione")

        # Assicurati che le risorse siano rilasciate
        self._cleanup_socket()
        logger.info("Thread di ricezione arrestato")

    @property
    def cameras_active(self) -> set:
        """Restituisce l'insieme delle camere attivamente rilevate."""
        with QMutexLocker(self._mutex):
            return self._received_cameras.copy()  # Restituisci una copia per evitare race condition