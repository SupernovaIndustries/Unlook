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

from PySide6.QtCore import QObject, Signal, QThread, QMutex, QMutexLocker

logger = logging.getLogger(__name__)


class ConnectionWorker(QThread):
    """
    Worker thread che gestisce una connessione TCP con uno scanner.
    """
    connection_ready = Signal(str)  # device_id
    connection_error = Signal(str, str)  # device_id, error_message
    connection_closed = Signal(str)  # device_id
    data_received = Signal(str, bytes)  # device_id, data

    def __init__(self, device_id: str, host: str, port: int):
        super().__init__()
        self.device_id = device_id
        self.host = host
        self.port = port
        self._socket = None
        self._running = False
        self._mutex = QMutex()
        self._send_queue = []

    def run(self):
        """Esegue il loop principale di connessione."""
        try:
            # Crea e configura il socket
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            self._socket.settimeout(5.0)  # Timeout di 5 secondi per la connessione

            # Tenta la connessione
            logger.info(f"Tentativo di connessione a {self.host}:{self.port}")
            self._socket.connect((self.host, self.port))

            # Connessione riuscita
            logger.info(f"Connessione stabilita con {self.host}:{self.port}")
            self._socket.settimeout(0.5)  # Riduce il timeout per le operazioni normali
            self._running = True
            self.connection_ready.emit(self.device_id)

            # Loop principale
            message_buffer = b""
            header_size = 4  # Dimensione dell'header del messaggio (lunghezza)

            while self._running:
                # Invia i messaggi in coda
                self._process_send_queue()

                # Ricevi dati
                try:
                    chunk = self._socket.recv(4096)
                    if not chunk:  # Connessione chiusa dall'altro lato
                        logger.info(f"Connessione chiusa dal server: {self.device_id}")
                        break

                    # Aggiungi il chunk al buffer
                    message_buffer += chunk

                    # Processa i messaggi completi
                    while len(message_buffer) >= header_size:
                        # Leggi la lunghezza del messaggio
                        msg_len = struct.unpack("!I", message_buffer[:header_size])[0]

                        # Controlla se abbiamo ricevuto il messaggio completo
                        if len(message_buffer) >= header_size + msg_len:
                            # Estrai il messaggio
                            message = message_buffer[header_size:header_size + msg_len]
                            # Rimuovi il messaggio dal buffer
                            message_buffer = message_buffer[header_size + msg_len:]
                            # Emetti il segnale
                            self.data_received.emit(self.device_id, message)
                        else:
                            # Messaggio incompleto, attendi altri dati
                            break
                except socket.timeout:
                    # Timeout normale, continua
                    continue
                except ConnectionError as e:
                    logger.error(f"Errore di connessione: {str(e)}")
                    break
                except Exception as e:
                    logger.error(f"Errore durante la ricezione: {str(e)}")
                    break
        except ConnectionRefusedError:
            logger.error(f"Connessione rifiutata da {self.host}:{self.port}")
            self.connection_error.emit(self.device_id, "Connessione rifiutata")
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

    def send_data(self, data: bytes) -> bool:
        """
        Accoda i dati da inviare al server.

        Args:
            data: Dati binari da inviare

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
                # Aggiungi l'header con la lunghezza
                header = struct.pack("!I", len(data))
                # Invia l'header e i dati
                self._socket.sendall(header + data)
            except Exception as e:
                logger.error(f"Errore durante l'invio: {str(e)}")
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


class ConnectionManager(QObject):
    # Definisci i segnali come attributi di classe, non come decoratori
    connection_established = Signal(str)  # signal con un parametro str
    connection_failed = Signal(str, str)  # signal con due parametri str
    connection_closed = Signal(str)       # signal con un parametro str
    data_received = Signal(str, dict)  # device_id, parsed_data

    def __init__(self):
        super().__init__()
        self._connections: Dict[str, ConnectionWorker] = {}
        self._message_handlers: Dict[str, Callable] = {}

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

        # Ferma il worker
        worker = self._connections[device_id]
        worker.stop()

        # Attendi la terminazione
        if worker.isRunning():
            worker.wait(1000)  # Attendi al massimo 1 secondo

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
            "timestamp": int(time.time() * 1000),
            "payload": payload or {}
        }

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

    def _on_data_received(self, device_id: str, data: bytes):
        """Gestisce l'evento di ricezione dati."""
        try:
            # Decodifica i dati JSON
            message_str = data.decode('utf-8')
            message = json.loads(message_str)

            # Estrai il tipo di messaggio
            message_type = message.get('type')

            # Emetti il segnale generico di dati ricevuti
            self.data_received.emit(device_id, message)

            # Gestisci il messaggio con l'handler specifico
            if message_type in self._message_handlers:
                handler = self._message_handlers[message_type]
                handler(device_id, message)
        except json.JSONDecodeError:
            logger.error(f"Errore di decodifica JSON per {device_id}")
        except Exception as e:
            logger.error(f"Errore nella gestione dei dati ricevuti: {str(e)}")