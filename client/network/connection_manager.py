#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Gestisce le connessioni con gli scanner UnLook.
Versione migliorata con gestione più robusta delle connessioni.
"""

import json
import logging
import socket
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
        self._last_ping_time = 0
        self._last_response_time = 0
        self._ping_interval = 3.0  # secondi
        self._response_timeout = 10.0  # secondi
        self._connected = False

    def run(self):
        """Esegue il loop principale di connessione."""
        try:
            # Crea e configura il socket ZMQ
            self._context = zmq.Context()
            self._socket = self._context.socket(zmq.REQ)  # Usiamo REQ che corrisponde a REP del server

            # Configurazione del socket per una connessione più robusta
            self._socket.setsockopt(zmq.LINGER, 100)  # Attesa minima alla chiusura (ms)
            self._socket.setsockopt(zmq.RCVTIMEO, 2000)  # Timeout di ricezione (ms)
            self._socket.setsockopt(zmq.SNDTIMEO, 2000)  # Timeout di invio (ms)
            self._socket.setsockopt(zmq.RECONNECT_IVL, 100)  # Intervallo tra i tentativi di riconnessione (ms)
            self._socket.setsockopt(zmq.RECONNECT_IVL_MAX, 5000)  # Intervallo massimo tra i tentativi (ms)

            # Connessione
            endpoint = f"tcp://{self.host}:{self.port}"
            logger.info(f"Tentativo di connessione a {endpoint}")
            self._socket.connect(endpoint)

            # Connessione riuscita
            logger.info(f"Connessione stabilita con {self.host}:{self.port}")
            self._running = True
            self._connected = True
            self.connection_ready.emit(self.device_id)

            # Invia immediatamente un PING per confermare la connessione
            self._send_ping()
            self._last_ping_time = time.time()

            # Loop principale
            while self._running:
                # Verifica se è necessario inviare un ping
                current_time = time.time()
                if current_time - self._last_ping_time >= self._ping_interval:
                    self._send_ping()
                    self._last_ping_time = current_time

                # Verifica timeout di risposta
                if self._last_response_time > 0 and current_time - self._last_response_time > self._response_timeout:
                    logger.warning(f"Timeout di risposta dal server {self.host}")
                    self._connected = False
                    # Riprova a connettersi (ZMQ gestirà i tentativi di riconnessione)

                # Invia i messaggi in coda se connesso
                if self._connected:
                    self._process_send_queue()

                # Pausa breve per evitare di sovraccaricare la CPU
                time.sleep(0.05)

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
            "timestamp": time.time(),
            "ip_address": self._get_local_ip()
        }
        message_data = json.dumps(ping_message).encode('utf-8')
        if not self.send_data(message_data):
            logger.warning(f"Impossibile inviare ping al server {self.host}")

    def _get_local_ip(self):
        """Ottiene l'indirizzo IP locale."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))  # Connessione a un server esterno
            local_ip = s.getsockname()[0]
            s.close()
            return local_ip
        except:
            return "127.0.0.1"  # Fallback a localhost

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

            # Preleva un messaggio dalla coda (solo uno per volta con REQ/REP)
            if self._send_queue:
                data = self._send_queue.pop(0)
            else:
                return

        # Invia il messaggio
        try:
            # Invia il messaggio
            self._socket.send(data)

            # Attendi la risposta (pattern REQ/REP: req->rep->req->rep...)
            reply = self._socket.recv()

            # Aggiorna il timestamp dell'ultima risposta
            self._last_response_time = time.time()
            self._connected = True

            try:
                # Decodifica e processa la risposta
                reply_json = reply.decode('utf-8')
                reply_data = json.loads(reply_json)
                self.data_received.emit(self.device_id, reply_data)
            except Exception as e:
                logger.error(f"Errore nella decodifica della risposta: {e}")
        except zmq.ZMQError as e:
            logger.error(f"Errore ZMQ durante l'invio: {e}")
            # Imposta lo stato di non connesso
            self._connected = False
        except Exception as e:
            logger.error(f"Errore durante l'invio: {str(e)}")
            self._connected = False

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

    _instance = None

    def __new__(cls):
        """Implementa il pattern Singleton."""
        if cls._instance is None:
            cls._instance = super(ConnectionManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """Inizializza il connection manager (solo la prima volta)."""
        if self._initialized:
            return

        super().__init__()
        self._connections: Dict[str, ConnectionWorker] = {}
        self._message_handlers: Dict[str, Callable] = {}
        self._initialized = True

        # Timer per verificare le connessioni
        self._check_timer = QTimer(self)
        self._check_timer.timeout.connect(self._check_connections)
        self._check_timer.start(5000)  # Controlla ogni 5 secondi

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
                logger.info(f"Connessione già attiva per {device_id}")
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

        # Invia un messaggio di disconnessione esplicito (se possibile)
        try:
            self.send_message(device_id, "DISCONNECT")
        except:
            pass

        # Ferma il worker
        worker = self._connections[device_id]
        worker.stop()

        # Attendiamo la terminazione con un timeout
        if worker.isRunning():
            worker.wait(2000)  # 2 secondi di timeout

        # Rimuovi la connessione
        self._cleanup_connection(device_id)

        logger.info(f"Disconnessione completata per {device_id}")
        return True

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
            "timestamp": time.time(),
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

    def _check_connections(self):
        """Verifica lo stato di tutte le connessioni attive."""
        for device_id, worker in list(self._connections.items()):
            if not worker.isRunning():
                logger.warning(f"Worker per {device_id} non più in esecuzione, pulizia...")
                self._cleanup_connection(device_id)
                self.connection_closed.emit(device_id)

    def _on_connection_ready(self, device_id: str):
        """Gestisce l'evento di connessione pronta."""
        logger.info(f"Connessione stabilita con {device_id}")
        self.connection_established.emit(device_id)

    def _on_connection_error(self, device_id: str, error: str):
        """Gestisce l'evento di errore di connessione."""
        logger.error(f"Errore di connessione per {device_id}: {error}")
        self.connection_failed.emit(device_id, error)

    def _on_connection_closed(self, device_id: str):
        """Gestisce l'evento di chiusura della connessione."""
        logger.info(f"Connessione chiusa per {device_id}")
        self.connection_closed.emit(device_id)

    def _on_data_received(self, device_id: str, message: dict):
        """Gestisce l'evento di ricezione dati."""
        try:
            # Estrai il tipo di messaggio
            message_type = message.get('type', '')
            if message_type.endswith('_response'):
                # Rimuovi il suffisso "_response" per gestire più facilmente i tipi di risposta
                message_type = message_type[:-9]

            logger.debug(f"Messaggio ricevuto da {device_id}: {message_type}")

            # Emetti il segnale generico di dati ricevuti
            self.data_received.emit(device_id, message)

            # Gestisci il messaggio con l'handler specifico
            if message_type in self._message_handlers:
                handler = self._message_handlers[message_type]
                handler(device_id, message)
        except Exception as e:
            logger.error(f"Errore nella gestione dei dati ricevuti: {str(e)}")