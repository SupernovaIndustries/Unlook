#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Connection Manager ottimizzato per comunicazioni a bassa latenza con scanner UnLook.
Gestisce connessioni ZMQ con supporto per comandi sincroni e asincroni.
Implementa meccanismi di keepalive e riconnessione automatica.
"""

import logging
import time
import threading
import json
import uuid
import zmq
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass
import socket
from contextlib import contextmanager

# Configurazione logging
logger = logging.getLogger(__name__)


@dataclass
class ConnectionInfo:
    """Informazioni sulla connessione a un dispositivo."""
    device_id: str
    ip_address: str
    port: int
    context: Optional[zmq.Context] = None
    socket: Optional[zmq.Socket] = None
    last_activity: float = 0.0
    is_connected: bool = False
    pending_responses: Dict[str, Dict] = None

    def __post_init__(self):
        """Inizializza le strutture dati dopo la creazione."""
        if self.pending_responses is None:
            self.pending_responses = {}


class ConnectionManager:
    """
    Gestisce le connessioni ai dispositivi scanner UnLook.
    Ottimizzato per bassa latenza e alta affidabilità con recovery automatico.
    """

    def __init__(self):
        """Inizializza il gestore di connessione."""
        self._connections: Dict[str, ConnectionInfo] = {}
        self._lock = threading.RLock()
        self._zmq_context = zmq.Context.instance()

        # Socket HWM ottimizzato per bassa latenza
        self._zmq_context.setsockopt(zmq.LINGER, 0)

        # Parametri di timeout ottimizzati
        self._connection_timeout = 3.0  # 3 secondi
        self._command_timeout = 2.0  # 2 secondi
        self._response_timeout = 2.0  # 2 secondi
        self._ping_interval = 2.0  # 2 secondi

        # Avvia thread di monitoraggio connessioni
        self._stopping = threading.Event()
        self._monitor_thread = threading.Thread(target=self._connection_monitor_loop, daemon=True)
        self._monitor_thread.start()

        logger.info("ConnectionManager inizializzato")

    def connect(self, device_id: str, ip_address: str, port: int = 5000) -> bool:
        """
        Stabilisce una connessione al dispositivo specificato.

        Args:
            device_id: ID univoco del dispositivo
            ip_address: Indirizzo IP del dispositivo
            port: Porta di comunicazione

        Returns:
            True se la connessione è stabilita con successo, False altrimenti
        """
        with self._lock:
            # Controlla se già connesso
            if device_id in self._connections and self._connections[device_id].is_connected:
                logger.info(f"Già connesso a {device_id}")
                return True

            try:
                # Se esiste già una connessione ma non è attiva, pulisci
                if device_id in self._connections:
                    self._cleanup_connection(device_id)

                # Crea socket ZMQ
                socket = self._zmq_context.socket(zmq.REQ)

                # Configura socket per bassa latenza
                socket.setsockopt(zmq.LINGER, 0)  # No lingering
                socket.setsockopt(zmq.RCVTIMEO, 5000)  # 5 secondi timeout ricezione
                socket.setsockopt(zmq.SNDTIMEO, 5000)  # 5 secondi timeout invio

                # Opzioni TCP aggressive per bassa latenza
                try:
                    socket.setsockopt(zmq.TCP_NODELAY, 1)
                    logger.debug("TCP_NODELAY abilitato")
                except:
                    # Non essenziale, ignora se non supportato
                    pass

                # Connetti al dispositivo
                endpoint = f"tcp://{ip_address}:{port}"
                logger.info(f"Connessione a {endpoint}...")
                socket.connect(endpoint)

                # Invia ping iniziale per verificare la connessione
                try:
                    # Timeout più lungo per la connessione iniziale
                    with self._set_socket_timeout(socket, 5000):
                        socket.send_json({
                            "command": "PING",
                            "timestamp": time.time(),
                            "request_id": str(uuid.uuid4())
                        })

                        response = socket.recv_json()
                        if response.get("status") != "ok":
                            raise Exception(f"Ping iniziale fallito: {response.get('message', 'Risposta non valida')}")
                except Exception as e:
                    logger.error(f"Errore nella connessione a {endpoint}: {e}")
                    socket.close()
                    return False

                # Crea e salva info connessione
                connection = ConnectionInfo(
                    device_id=device_id,
                    ip_address=ip_address,
                    port=port,
                    context=self._zmq_context,
                    socket=socket,
                    last_activity=time.time(),
                    is_connected=True
                )

                self._connections[device_id] = connection
                logger.info(f"Connessione stabilita con {device_id} a {ip_address}:{port}")
                return True

            except Exception as e:
                logger.error(f"Errore nella connessione a {device_id} ({ip_address}:{port}): {e}")
                return False

    def disconnect(self, device_id: str) -> bool:
        """
        Disconnette dal dispositivo specificato.

        Args:
            device_id: ID del dispositivo

        Returns:
            True se disconnesso con successo, False altrimenti
        """
        with self._lock:
            if device_id not in self._connections:
                logger.warning(f"Impossibile disconnettere: {device_id} non connesso")
                return False

            # Invia comando DISCONNECT se connesso
            connection = self._connections[device_id]
            if connection.is_connected:
                try:
                    # Invia disconnect con timeout breve
                    with self._set_socket_timeout(connection.socket, 1000):
                        connection.socket.send_json({
                            "command": "DISCONNECT",
                            "request_id": str(uuid.uuid4())
                        })

                        # Ricevi risposta ma non attendere troppo
                        try:
                            connection.socket.recv_json()
                        except zmq.Again:
                            pass  # Timeout accettabile durante disconnessione
                except Exception as e:
                    logger.debug(f"Errore nell'invio del comando DISCONNECT: {e}")

            # Pulisci la connessione indipendentemente dall'esito del comando
            self._cleanup_connection(device_id)
            return True

    def is_connected(self, device_id: str) -> bool:
        """
        Verifica se il dispositivo è attualmente connesso.

        Args:
            device_id: ID del dispositivo

        Returns:
            True se connesso, False altrimenti
        """
        with self._lock:
            return (device_id in self._connections and
                    self._connections[device_id].is_connected)

    def send_message(self, device_id: str, command: str,
                     data: Optional[Dict[str, Any]] = None,
                     timeout: float = None) -> bool:
        """
        Invia un messaggio a un dispositivo connesso.

        Args:
            device_id: ID del dispositivo
            command: Comando da inviare
            data: Dati aggiuntivi per il comando
            timeout: Timeout per l'invio in secondi (None = default timeout)

        Returns:
            True se il messaggio è stato inviato con successo, False altrimenti
        """
        # Verifica connessione
        with self._lock:
            if not self.is_connected(device_id):
                logger.error(f"Impossibile inviare messaggio: {device_id} non connesso")
                return False

            connection = self._connections[device_id]

        # Prepara il messaggio
        message = {
            "command": command,
            "request_id": str(uuid.uuid4())
        }

        # Aggiungi dati se forniti
        if data:
            message.update(data)

        # Timeout effettivo
        effective_timeout = timeout * 1000 if timeout else self._command_timeout * 1000

        try:
            # Acquisisci lock per questa operazione specifica
            with self._lock:
                if not connection.is_connected:
                    logger.error(f"Connessione persa durante preparazione invio a {device_id}")
                    return False

                # Memorizza ID richiesta per tracciare la risposta
                request_id = message["request_id"]
                connection.pending_responses[request_id] = {
                    "command": command,
                    "timestamp": time.time(),
                    "response": None
                }

                # Imposta timeout temporaneo e invia
                with self._set_socket_timeout(connection.socket, int(effective_timeout)):
                    connection.socket.send_json(message)

                # Aggiorna timestamp attività
                connection.last_activity = time.time()

            # Successo - messaggio inviato (risposta ricevuta separatamente)
            return True

        except zmq.Again:
            logger.error(f"Timeout inviando messaggio '{command}' a {device_id}")
            return False
        except Exception as e:
            logger.error(f"Errore inviando messaggio '{command}' a {device_id}: {e}")
            # Marca la connessione come problematica
            with self._lock:
                if device_id in self._connections:
                    self._connections[device_id].is_connected = False
            return False

    def receive_response(self, device_id: str, timeout: float = None) -> Optional[Dict]:
        """
        Riceve una risposta da un dispositivo connesso.

        Args:
            device_id: ID del dispositivo
            timeout: Timeout in secondi

        Returns:
            Dizionario con la risposta o None in caso di errore/timeout
        """
        with self._lock:
            if not self.is_connected(device_id):
                logger.error(f"Impossibile ricevere risposta: {device_id} non connesso")
                return None

            connection = self._connections[device_id]

        # Timeout effettivo
        effective_timeout = timeout * 1000 if timeout else self._response_timeout * 1000

        try:
            # Imposta timeout temporaneo e ricevi
            with self._set_socket_timeout(connection.socket, int(effective_timeout)):
                response = connection.socket.recv_json()

            # Aggiorna timestamp attività
            with self._lock:
                connection.last_activity = time.time()

                # Elabora risposta
                request_id = response.get("request_id")
                if request_id in connection.pending_responses:
                    # Memorizza risposta
                    connection.pending_responses[request_id]["response"] = response

                    # Pulizia vecchie risposte (opzionale)
                    self._cleanup_old_responses(connection)
                else:
                    logger.warning(f"Ricevuta risposta non richiesta: {response}")

            return response

        except zmq.Again:
            logger.error(f"Timeout ricevendo risposta da {device_id}")
            return None
        except Exception as e:
            logger.error(f"Errore ricevendo risposta da {device_id}: {e}")
            # Marca la connessione come problematica
            with self._lock:
                if device_id in self._connections:
                    self._connections[device_id].is_connected = False
            return None

    def wait_for_response(self, device_id: str, command: str,
                          timeout: float = None) -> Optional[Dict]:
        """
        Attende una risposta a un comando specifico.

        Args:
            device_id: ID del dispositivo
            command: Comando per cui attendere la risposta
            timeout: Timeout in secondi

        Returns:
            Dizionario con la risposta o None in caso di errore/timeout
        """
        effective_timeout = timeout or self._response_timeout
        start_time = time.time()

        # Loop fino al timeout
        while time.time() - start_time < effective_timeout:
            with self._lock:
                if not self.is_connected(device_id):
                    logger.error(f"Connessione persa mentre si attendeva risposta da {device_id}")
                    return None

                connection = self._connections[device_id]

                # Cerca nel dizionario delle risposte pendenti
                for request_id, request_info in list(connection.pending_responses.items()):
                    if request_info["command"] == command and request_info["response"]:
                        # Risposta trovata, torna la risposta e pulisci
                        response = request_info["response"]
                        del connection.pending_responses[request_id]
                        return response

            # Attendi un po' prima di riverificare
            time.sleep(0.01)

        logger.warning(f"Timeout attendendo risposta a '{command}' da {device_id}")
        return None

    def has_response(self, device_id: str, command: str) -> bool:
        """
        Verifica se è disponibile una risposta per un comando specifico.

        Args:
            device_id: ID del dispositivo
            command: Comando per cui verificare la risposta

        Returns:
            True se è disponibile una risposta, False altrimenti
        """
        with self._lock:
            if not self.is_connected(device_id):
                return False

            connection = self._connections[device_id]

            # Cerca nel dizionario delle risposte pendenti
            for request_info in connection.pending_responses.values():
                if request_info["command"] == command and request_info["response"]:
                    return True

        return False

    def get_response(self, device_id: str, command: str) -> Optional[Dict]:
        """
        Ottiene una risposta per un comando specifico senza attendere.

        Args:
            device_id: ID del dispositivo
            command: Comando per cui ottenere la risposta

        Returns:
            Dizionario con la risposta o None se non disponibile
        """
        with self._lock:
            if not self.is_connected(device_id):
                return None

            connection = self._connections[device_id]

            # Cerca nel dizionario delle risposte pendenti
            for request_id, request_info in list(connection.pending_responses.items()):
                if request_info["command"] == command and request_info["response"]:
                    # Risposta trovata, torna la risposta e pulisci
                    response = request_info["response"]
                    del connection.pending_responses[request_id]
                    return response

        return None

    def _connection_monitor_loop(self):
        """Thread di monitoraggio connessioni con keepalive e riconnessione."""
        logger.info("Avvio thread di monitoraggio connessioni")

        while not self._stopping.is_set():
            try:
                # Controlla tutte le connessioni
                with self._lock:
                    for device_id, connection in list(self._connections.items()):
                        # Salta se non connesso
                        if not connection.is_connected:
                            continue

                        # Controlla inattività
                        current_time = time.time()
                        inactivity_time = current_time - connection.last_activity

                        # Invia ping se inattivo da un po'
                        if inactivity_time > self._ping_interval:
                            self._send_keepalive_ping(device_id)

                # Attendi prima del prossimo ciclo
                time.sleep(1.0)

            except Exception as e:
                logger.error(f"Errore nel thread di monitoraggio: {e}")
                time.sleep(5.0)  # Attendi più a lungo in caso di errore

        logger.info("Thread di monitoraggio connessioni terminato")

    def _send_keepalive_ping(self, device_id: str) -> bool:
        """Invia un ping di keepalive al dispositivo."""
        try:
            # Non usare send_message per evitare ricorsione
            with self._lock:
                if not device_id in self._connections:
                    return False

                connection = self._connections[device_id]
                if not connection.is_connected:
                    return False

                # Prepara e invia ping
                ping_message = {
                    "command": "PING",
                    "request_id": str(uuid.uuid4()),
                    "timestamp": time.time(),
                    "keepalive": True
                }

                # Invia con timeout breve
                with self._set_socket_timeout(connection.socket, 500):  # 500ms
                    connection.socket.send_json(ping_message)

                    # Attendi risposta
                    try:
                        connection.socket.recv_json()
                        # Ping riuscito, aggiorna timestamp
                        connection.last_activity = time.time()
                        return True
                    except zmq.Again:
                        # Timeout - connessione problematica
                        logger.warning(f"Keepalive ping timeout per {device_id}")
                        connection.is_connected = False
                        return False

        except Exception as e:
            logger.error(f"Errore nel keepalive ping per {device_id}: {e}")
            with self._lock:
                if device_id in self._connections:
                    self._connections[device_id].is_connected = False
            return False

    def _cleanup_connection(self, device_id: str):
        """Pulisce le risorse associate a una connessione."""
        with self._lock:
            if device_id not in self._connections:
                return

            connection = self._connections[device_id]

            # Chiudi socket
            if connection.socket:
                try:
                    connection.socket.close()
                except Exception as e:
                    logger.debug(f"Errore chiudendo socket: {e}")

            # Rimuovi dalla lista connessioni
            del self._connections[device_id]
            logger.info(f"Connessione a {device_id} chiusa e pulita")

    def _cleanup_old_responses(self, connection: ConnectionInfo):
        """Pulisce le vecchie risposte pendenti."""
        # Rimuovi risposte più vecchie di 30 secondi
        current_time = time.time()
        old_threshold = 30.0  # 30 secondi

        to_remove = []
        for request_id, request_info in connection.pending_responses.items():
            if current_time - request_info["timestamp"] > old_threshold:
                to_remove.append(request_id)

        for request_id in to_remove:
            del connection.pending_responses[request_id]

        if to_remove:
            logger.debug(f"Rimosse {len(to_remove)} vecchie risposte pendenti")

    @contextmanager
    def _set_socket_timeout(self, socket, timeout_ms):
        """Context manager per impostare temporaneamente timeout socket."""
        # Salva timeout originali
        original_rcvtimeo = socket.getsockopt(zmq.RCVTIMEO)
        original_sndtimeo = socket.getsockopt(zmq.SNDTIMEO)

        try:
            # Imposta nuovi timeout
            socket.setsockopt(zmq.RCVTIMEO, timeout_ms)
            socket.setsockopt(zmq.SNDTIMEO, timeout_ms)
            yield
        finally:
            # Ripristina timeout originali
            socket.setsockopt(zmq.RCVTIMEO, original_rcvtimeo)
            socket.setsockopt(zmq.SNDTIMEO, original_sndtimeo)

    def close(self):
        """Chiude tutte le connessioni e termina il thread di monitoraggio."""
        logger.info("Chiusura ConnectionManager...")

        # Ferma thread di monitoraggio
        self._stopping.set()
        if self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=2.0)

        # Disconnetti da tutti i dispositivi
        with self._lock:
            for device_id in list(self._connections.keys()):
                self.disconnect(device_id)

        logger.info("ConnectionManager chiuso")