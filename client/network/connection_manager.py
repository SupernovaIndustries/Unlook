#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Gestisce le connessioni con gli scanner UnLook.
"""

import json
import logging
import socket
import struct
import time
from typing import Dict, Optional, Tuple, Any, Callable

from PySide6.QtCore import QObject, Signal, QThread, QMutex, QMutexLocker, QTimer

logger = logging.getLogger(__name__)

try:
    import zmq
except ImportError:
    logger.error("ZMQ non trovato, installalo con: pip install pyzmq")
    raise


class ConnectionWorker(QThread):
    """
    Worker thread che gestisce una connessione ZMQ con uno scanner.
    """
    connection_ready = Signal(str)  # device_id
    connection_error = Signal(str, str)  # device_id, error_message
    connection_closed = Signal(str)  # device_id
    data_received = Signal(str, dict)  # device_id, parsed_data

    def __init__(self, device_id: str, host: str, port: int):
        super().__init__()
        self.device_id = device_id
        self.host = host
        self.port = port
        self._socket = None
        self._context = None
        self._running = False
        self._mutex = QMutex()
        self._send_queue = []
        self._error_count = 0
        self._max_errors = 3  # Numero massimo di errori prima di chiudere la connessione

    def run(self):
        """Esegue il loop principale di connessione."""
        try:
            # Crea e configura il socket ZMQ
            self._context = zmq.Context()
            self._socket = self._context.socket(zmq.DEALER)  # Usiamo DEALER invece di REQ

            # Configura socket
            self._socket.setsockopt(zmq.LINGER, 0)  # Non aspettare alla chiusura

            # Genera un'identità casuale o usa lo user_id come identità
            identity = f"client-{self.device_id[:8]}".encode('utf-8')
            self._socket.setsockopt(zmq.IDENTITY, identity)

            # Connessione
            endpoint = f"tcp://{self.host}:{self.port}"
            logger.info(f"Tentativo di connessione a {endpoint}")
            self._socket.connect(endpoint)

            # Connessione riuscita
            logger.info(f"Connessione stabilita con {self.host}:{self.port}")
            self._running = True
            self.connection_ready.emit(self.device_id)

            # Invia immediatamente un PING per confermare la connessione
            self._send_ping()

            # Setup poller
            poller = zmq.Poller()
            poller.register(self._socket, zmq.POLLIN)

            # Loop principale
            last_ping_time = time.time()
            ping_interval = 5.0  # Invia un ping ogni 5 secondi

            while self._running:
                # Invia i messaggi in coda
                self._process_send_queue()

                # Invia periodicamente un ping per mantenere la connessione attiva
                current_time = time.time()
                if current_time - last_ping_time > ping_interval:
                    self._send_ping()
                    last_ping_time = current_time

                # Ricevi dati con timeout usando il poller
                try:
                    socks = dict(poller.poll(500))  # 500ms di timeout

                    if self._socket in socks and socks[self._socket] == zmq.POLLIN:
                        # In DEALER/ROUTER, il primo frame è vuoto (delimiter)
                        empty = self._socket.recv()

                        # Verifica che sia un frame vuoto (delimiter)
                        if empty:
                            logger.debug(f"Ricevuto frame non vuoto come delimiter: {empty}")

                        # Il secondo frame contiene i dati
                        message_data = self._socket.recv()

                        # Decodifica il messaggio
                        message_json = message_data.decode('utf-8')
                        message = json.loads(message_json)

                        # Emetti il segnale con i dati decodificati
                        self.data_received.emit(self.device_id, message)

                        # Resetta il contatore degli errori
                        self._error_count = 0
                except zmq.ZMQError as e:
                    if e.errno == zmq.EAGAIN:
                        # Timeout normale, continua
                        continue
                    else:
                        logger.error(f"Errore ZMQ: {e}")
                        self._error_count += 1
                except Exception as e:
                    logger.error(f"Errore durante la ricezione: {str(e)}")
                    self._error_count += 1

                # Se ci sono troppi errori, chiudi la connessione
                if self._error_count >= self._max_errors:
                    logger.error(f"Troppi errori di connessione. Chiusura della connessione.")
                    break

                # Breve pausa per non sovraccaricare la CPU
                self.msleep(10)

        except zmq.ZMQError as e:
            logger.error(f"Errore ZMQ nella connessione: {e}")
            self.connection_error.emit(self.device_id, f"Errore ZMQ: {str(e)}")
        except socket.timeout:
            logger.error(f"Timeout durante la connessione a {self.host}:{self.port}")
            self.connection_error.emit(self.device_id, "Timeout di connessione")
        except Exception as e:
            logger.error(f"Errore durante la connessione: {str(e)}")
            self.connection_error.emit(self.device_id, f"Errore: {str(e)}")
        finally:
            # Chiudi il socket
            self._cleanup()
            # Notifica la chiusura
            self.connection_closed.emit(self.device_id)

    def _send_ping(self):
        """Invia un ping al server per mantenere la connessione attiva."""
        ping_message = {
            "type": "PING",
            "timestamp": int(time.time() * 1000)  # Millisecondi
        }
        message_data = json.dumps(ping_message).encode('utf-8')
        self.send_data(message_data)
        logger.debug(f"Ping inviato al server {self.host}")

    def send_data(self, data: bytes) -> bool:
        """
        Accoda i dati da inviare al server.

        Args:
            data: Dati binari da inviare (già serializzati JSON)

        Returns:
            True se i dati sono stati accodati, False altrimenti
        """
        with QMutexLocker(self._mutex):
            if not self._running:
                return False
            self._send_queue.append(data)
            return True

    def _process_send_queue(self):
        """Processa la coda dei messaggi da inviare."""
        with QMutexLocker(self._mutex):
            if not self._send_queue:
                return

            # Preleva tutti i messaggi dalla coda
            messages = self._send_queue
            self._send_queue = []

        # Invia i messaggi
        for data in messages:
            try:
                # In DEALER/ROUTER, si invia prima un frame vuoto come delimiter
                self._socket.send(b"", zmq.SNDMORE)
                # Poi si inviano i dati
                self._socket.send(data)
            except zmq.ZMQError as e:
                logger.error(f"Errore ZMQ durante l'invio: {e}")
                self._error_count += 1
                if self._error_count >= self._max_errors:
                    logger.error(f"Troppi errori di invio. Chiusura della connessione.")
                    self._running = False
                break
            except Exception as e:
                logger.error(f"Errore durante l'invio: {str(e)}")
                self._error_count += 1
                if self._error_count >= self._max_errors:
                    logger.error(f"Troppi errori di invio. Chiusura della connessione.")
                    self._running = False
                break

    def stop(self):
        """Ferma il worker e chiude la connessione."""
        self._running = False
        self._cleanup()

    def _cleanup(self):
        """Pulisce le risorse del worker."""
        if self._socket:
            try:
                self._socket.close()
            except:
                pass
            self._socket = None

        if self._context:
            try:
                self._context.term()
            except:
                pass
            self._context = None


class ConnectionManager(QObject):
    """
    Gestisce le connessioni con gli scanner UnLook.
    """
    connection_established = Signal(str)  # device_id
    connection_failed = Signal(str, str)  # device_id, error_message
    connection_closed = Signal(str)  # device_id
    data_received = Signal(str, dict)  # device_id, parsed_data

    def __init__(self):
        super().__init__()
        self._connections: Dict[str, ConnectionWorker] = {}
        self._message_handlers: Dict[str, Callable] = {}

        # Timer per il heartbeat
        self._heartbeat_timer = QTimer(self)
        self._heartbeat_timer.timeout.connect(self._send_heartbeat)
        self._heartbeat_timer.start(5000)  # Invia un ping ogni 5 secondi

    def connect(self, device_id: str, host: str, port: int) -> bool:
        """
        Stabilisce una connessione con uno scanner.

        Args:
            device_id: ID univoco dello scanner
            host: Indirizzo IP o hostname dello scanner
            port: Porta di connessione

        Returns:
            True se la connessione è stata avviata, False altrimenti
        """
        # Controlla se c'è già una connessione attiva
        if device_id in self._connections:
            worker = self._connections[device_id]
            if worker.isRunning():
                logger.warning(f"Connessione già attiva per {device_id}")
                return True

            # Rimuovi la vecchia connessione
            self._cleanup_connection(device_id)

        # Crea un nuovo worker
        worker = ConnectionWorker(device_id, host, port)

        # Collega i segnali
        worker.connection_ready.connect(self._on_connection_ready)
        worker.connection_error.connect(self._on_connection_error)
        worker.connection_closed.connect(self._on_connection_closed)
        worker.data_received.connect(self._on_data_received)

        # Salva e avvia il worker
        self._connections[device_id] = worker
        worker.start()

        logger.info(f"Connessione avviata per {device_id} a {host}:{port}")
        return True

    def disconnect(self, device_id: str) -> bool:
        """
        Chiude la connessione con uno scanner.

        Args:
            device_id: ID univoco dello scanner

        Returns:
            True se la disconnessione è stata avviata, False altrimenti
        """
        if device_id not in self._connections:
            logger.warning(f"Nessuna connessione attiva per {device_id}")
            return False

        # Invia un messaggio di disconnessione esplicito
        self.send_message(device_id, "DISCONNECT")

        # Attendi un momento per permettere l'invio del messaggio
        QTimer.singleShot(200, lambda: self._complete_disconnect(device_id))

        return True

    def _complete_disconnect(self, device_id: str):
        """Completa la disconnessione dopo aver inviato il messaggio."""
        # Ferma il worker
        if device_id in self._connections:
            worker = self._connections[device_id]
            worker.stop()

            # Attendi la terminazione
            if worker.isRunning():
                worker.wait(1000)  # Attendi al massimo 1 secondo

            # Rimuovi la connessione
            self._cleanup_connection(device_id)

            logger.info(f"Disconnessione completata per {device_id}")

    def send_message(self, device_id: str, message_type: str, payload: Dict = None) -> bool:
        """
        Invia un messaggio a uno scanner.

        Args:
            device_id: ID univoco dello scanner
            message_type: Tipo di messaggio
            payload: Dati da inviare

        Returns:
            True se il messaggio è stato inviato, False altrimenti
        """
        if device_id not in self._connections:
            logger.error(f"Nessuna connessione attiva per {device_id}")
            return False

        worker = self._connections[device_id]
        if not worker.isRunning():
            logger.error(f"Connessione non attiva per {device_id}")
            return False

        # Prepara il messaggio
        message = {
            "type": message_type,
            "timestamp": int(time.time() * 1000),
        }

        # Aggiungi il payload se presente
        if payload:
            message.update(payload)

        # Serializza e invia
        data = json.dumps(message).encode('utf-8')
        return worker.send_data(data)

    def register_message_handler(self, message_type: str, handler: Callable):
        """
        Registra un gestore per un tipo specifico di messaggio.

        Args:
            message_type: Tipo di messaggio da gestire
            handler: Funzione di callback che gestirà il messaggio
        """
        self._message_handlers[message_type] = handler

    def is_connected(self, device_id: str) -> bool:
        """
        Verifica se un dispositivo è connesso.

        Args:
            device_id: ID univoco dello scanner

        Returns:
            True se il dispositivo è connesso, False altrimenti
        """
        if device_id not in self._connections:
            return False

        worker = self._connections[device_id]
        return worker.isRunning()

    def _cleanup_connection(self, device_id: str):
        """Rimuove una connessione dalla gestione."""
        if device_id in self._connections:
            worker = self._connections.pop(device_id)
            # Disconnetti i segnali
            try:
                worker.connection_ready.disconnect()
                worker.connection_error.disconnect()
                worker.connection_closed.disconnect()
                worker.data_received.disconnect()
            except:
                pass

    def _on_connection_ready(self, device_id: str):
        """Gestisce l'evento di connessione pronta."""
        logger.info(f"Connessione stabilita con {device_id}")
        self.connection_established.emit(device_id)

    def _on_connection_error(self, device_id: str, error: str):
        """Gestisce l'evento di errore di connessione."""
        logger.error(f"Errore di connessione per {device_id}: {error}")
        self._cleanup_connection(device_id)
        self.connection_failed.emit(device_id, error)

    def _on_connection_closed(self, device_id: str):
        """Gestisce l'evento di chiusura della connessione."""
        logger.info(f"Connessione chiusa per {device_id}")
        self._cleanup_connection(device_id)
        self.connection_closed.emit(device_id)

    def _on_data_received(self, device_id: str, message: dict):
        """Gestisce l'evento di ricezione dati."""
        try:
            # Estrai il tipo di messaggio
            message_type = message.get('type')
            logger.debug(f"Messaggio ricevuto da {device_id}: {message_type}")

            # Emetti il segnale generico di dati ricevuti
            self.data_received.emit(device_id, message)

            # Gestisci il messaggio con l'handler specifico
            if message_type in self._message_handlers:
                handler = self._message_handlers[message_type]
                handler(device_id, message)
        except Exception as e:
            logger.error(f"Errore nella gestione dei dati ricevuti: {str(e)}")

    def _send_heartbeat(self):
        """Invia un heartbeat a tutti i dispositivi connessi."""
        for device_id in list(self._connections.keys()):
            if self.is_connected(device_id):
                self.send_message(device_id, "PING")