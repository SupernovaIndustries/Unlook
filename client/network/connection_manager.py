#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Gestisce le connessioni con gli scanner UnLook.
Versione migliorata con gestione degli stati di socket ZMQ e meccanismi avanzati di riconnessione.
"""

import json
import logging
import socket
import time
import threading
from typing import Dict, Optional, Tuple, Any, Callable
from collections import defaultdict

from PySide6.QtCore import QObject, Signal, QThread, QMutex, QMutexLocker, QTimer, QCoreApplication

logger = logging.getLogger(__name__)

try:
    import zmq
except ImportError:
    logger.error("ZMQ non trovato, installalo con: pip install pyzmq")
    raise


class ConnectionWorker(QThread):
    """
    Worker thread che gestisce una connessione ZMQ con uno scanner.
    Versione migliorata con gestione avanzata degli stati dei socket e riconnessione automatica.
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
        self._consecutive_errors = 0
        # Flag per tracciare lo stato REQ/REP
        self._waiting_for_reply = False
        self._last_activity = time.time()
        # Creazione di un evento di chiusura
        self._shutdown_event = threading.Event()

    def run(self):
        """Esegue il loop principale di connessione con migliore gestione degli errori e riconnessione automatica."""
        reconnect_attempts = 0
        max_reconnect_attempts = 5
        reconnect_delay = 1.0  # Delay iniziale (1 secondo)

        while reconnect_attempts <= max_reconnect_attempts and not self._shutdown_event.is_set():
            try:
                # Crea e configura il socket ZMQ
                if self._context is None:
                    self._context = zmq.Context()

                self._socket = self._context.socket(zmq.REQ)  # Usiamo REQ che corrisponde a REP del server

                # Connessione con timeout e opzioni migliorate
                endpoint = f"tcp://{self.host}:{self.port}"

                # Configurazione socket con migliori opzioni per robustezza
                self._socket.setsockopt(zmq.RCVTIMEO, 5000)  # 5 secondi timeout ricezione
                self._socket.setsockopt(zmq.SNDTIMEO, 5000)  # 5 secondi timeout invio
                self._socket.setsockopt(zmq.LINGER, 1000)  # Attendi fino a 1 secondo alla chiusura
                self._socket.setsockopt(zmq.RECONNECT_IVL, 500)  # Riconnetti ogni 500ms
                self._socket.setsockopt(zmq.RECONNECT_IVL_MAX, 5000)  # Max intervallo riconnessione 5s
                self._socket.setsockopt(zmq.TCP_KEEPALIVE, 1)  # Abilita TCP keepalive
                self._socket.setsockopt(zmq.TCP_KEEPALIVE_IDLE, 60)  # Inizia keepalive dopo 60s di inattività
                self._socket.setsockopt(zmq.TCP_KEEPALIVE_INTVL, 5)  # Intervallo keepalive 5s

                # Se questo è un tentativo di riconnessione, lo segnaliamo
                if reconnect_attempts > 0:
                    logger.info(
                        f"Tentativo di riconnessione {reconnect_attempts}/{max_reconnect_attempts} a {endpoint}")
                else:
                    logger.info(f"Tentativo di connessione a {endpoint}")

                # Connessione
                self._socket.connect(endpoint)

                # Reset del flag di attesa risposta
                with QMutexLocker(self._mutex):
                    self._waiting_for_reply = False

                # Connessione riuscita
                logger.info(f"Connessione stabilita con {self.host}:{self.port}")
                with QMutexLocker(self._mutex):
                    self._running = True
                    self._last_activity = time.time()

                # Reset contatore tentativi di riconnessione
                reconnect_attempts = 0

                # Notifica connessione riuscita
                self.connection_ready.emit(self.device_id)

                # Loop principale
                while self._running and not self._shutdown_event.is_set():
                    # Invia i messaggi in coda
                    self._process_send_queue()

                    # Aggiorna periodicamente lo stato di attività
                    current_time = time.time()
                    with QMutexLocker(self._mutex):
                        inactivity_time = current_time - self._last_activity

                    # Se non c'è attività per più di 30 secondi, considera il socket inattivo
                    if inactivity_time > 30.0:
                        logger.warning(f"Socket inattivo per {inactivity_time:.1f} secondi, inviando ping")
                        # Tenta l'invio di un ping
                        success = self._send_ping()
                        if not success:
                            logger.error("Impossibile inviare ping, connessione persa")
                            break  # Esce dal loop principale per riconnettersi

                    # Pausa breve per evitare di sovraccaricare la CPU
                    time.sleep(0.05)

                    # Permettiamo alla QApplication di processare eventi
                    QCoreApplication.processEvents()

                # Se siamo usciti dal loop in modo pulito (self._running = False), usciamo dal loop esterno
                if not self._running or self._shutdown_event.is_set():
                    break

            except zmq.ZMQError as e:
                logger.error(f"Errore ZMQ nella connessione: {e}")

                # Se il thread è stato fermato esplicitamente, usciamo
                if self._shutdown_event.is_set():
                    break

                # Incrementa il contatore di tentativi e calcola il ritardo
                reconnect_attempts += 1
                current_delay = min(reconnect_delay * (2 ** (reconnect_attempts - 1)),
                                    30.0)  # Backoff esponenziale, max 30 secondi

                # Se abbiamo superato il numero massimo di tentativi, notifica l'errore e esci
                if reconnect_attempts > max_reconnect_attempts:
                    self.connection_error.emit(self.device_id,
                                               f"Impossibile connettersi dopo {max_reconnect_attempts} tentativi")
                    break

                # Pulisci il socket corrente
                self._cleanup_socket()

                # Attendi prima di riprovare
                logger.info(f"Attesa di {current_delay:.1f} secondi prima del prossimo tentativo...")
                time.sleep(current_delay)

            except socket.timeout:
                logger.error(f"Timeout durante la connessione a {self.host}:{self.port}")

                # Comportamento simile all'errore ZMQ
                if self._shutdown_event.is_set():
                    break

                reconnect_attempts += 1
                current_delay = min(reconnect_delay * (2 ** (reconnect_attempts - 1)), 30.0)

                if reconnect_attempts > max_reconnect_attempts:
                    self.connection_error.emit(self.device_id, "Timeout di connessione ripetuti")
                    break

                self._cleanup_socket()
                time.sleep(current_delay)

            except Exception as e:
                logger.error(f"Errore durante la connessione: {str(e)}")

                if self._shutdown_event.is_set():
                    break

                reconnect_attempts += 1
                current_delay = min(reconnect_delay * (2 ** (reconnect_attempts - 1)), 30.0)

                if reconnect_attempts > max_reconnect_attempts:
                    self.connection_error.emit(self.device_id, f"Errore: {str(e)}")
                    break

                self._cleanup_socket()
                time.sleep(current_delay)

            finally:
                if reconnect_attempts > max_reconnect_attempts or self._shutdown_event.is_set():
                    # Chiudi il socket in modo sicuro solo se usciamo definitivamente
                    self._cleanup_socket()

                    # Notifica la chiusura solo se non è stato un ordine esplicito di stop
                    if not self._shutdown_event.is_set():
                        self.connection_closed.emit(self.device_id)

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
        """Processa la coda dei messaggi da inviare con miglior gestione degli errori e stato del socket."""
        with QMutexLocker(self._mutex):
            if not self._send_queue or self._waiting_for_reply:
                return

            # Preleva un messaggio dalla coda (solo uno per volta con REQ/REP)
            data = self._send_queue.pop(0)
            # Segnala che stiamo per inviare e attendere una risposta
            self._waiting_for_reply = True
            # Aggiorna timestamp attività
            self._last_activity = time.time()

        # Invia il messaggio fuori dal mutex lock
        try:
            # Invia il messaggio con timeout
            self._socket.send(data, flags=zmq.NOBLOCK)

            # Attendi la risposta (pattern REQ/REP: req->rep->req->rep...)
            try:
                # Impostiamo un timeout per rilevare disconnessioni più rapidamente
                poller = zmq.Poller()
                poller.register(self._socket, zmq.POLLIN)

                if poller.poll(5000):  # 5 secondi di timeout
                    reply = self._socket.recv()

                    # Reset del flag di attesa risposta
                    with QMutexLocker(self._mutex):
                        self._waiting_for_reply = False
                        self._last_activity = time.time()
                        self._consecutive_errors = 0

                    try:
                        # Decodifica e processa la risposta
                        reply_json = reply.decode('utf-8')
                        reply_data = json.loads(reply_json)
                        self.data_received.emit(self.device_id, reply_data)
                    except Exception as e:
                        logger.error(f"Errore nella decodifica della risposta: {e}")
                else:
                    # Timeout nella ricezione della risposta
                    logger.error("Timeout nella ricezione della risposta")

                    # Incrementa il contatore di errori consecutivi
                    with QMutexLocker(self._mutex):
                        self._consecutive_errors += 1
                        if self._consecutive_errors >= 3:
                            logger.error("Troppe risposte mancate, connessione persa")
                            self._running = False
                            # Reset del flag di attesa risposta per evitare deadlock
                            self._waiting_for_reply = False
                            # Emetti il segnale fuori dal mutex

                    if self._consecutive_errors >= 3:
                        self.connection_closed.emit(self.device_id)
                        return

                    # Riavvia il socket per resettare lo stato REQ/REP
                    self._restart_socket()

                    # Riaccodiamo il messaggio
                    with QMutexLocker(self._mutex):
                        # Reset del flag di attesa risposta
                        self._waiting_for_reply = False
                        # Rimetti il messaggio in cima alla coda
                        self._send_queue.insert(0, data)

            except zmq.ZMQError as e:
                logger.error(f"Errore ZMQ durante l'attesa di risposta: {e}")

                # Incrementa il contatore di errori consecutivi
                with QMutexLocker(self._mutex):
                    self._consecutive_errors += 1
                    if self._consecutive_errors >= 3:
                        logger.error("Troppe risposte mancate, connessione persa")
                        self._running = False
                        # Reset del flag di attesa risposta per evitare deadlock
                        self._waiting_for_reply = False
                        # Emetti il segnale fuori dal mutex

                if self._consecutive_errors >= 3:
                    self.connection_closed.emit(self.device_id)
                    return

                # Riavvia il socket per resettare lo stato REQ/REP
                self._restart_socket()

                # Riaccodiamo il messaggio
                with QMutexLocker(self._mutex):
                    # Reset del flag di attesa risposta
                    self._waiting_for_reply = False
                    # Rimetti il messaggio in cima alla coda
                    self._send_queue.insert(0, data)

        except zmq.ZMQError as e:
            logger.error(f"Errore ZMQ durante l'invio: {e}")

            # Reset del flag di attesa risposta
            with QMutexLocker(self._mutex):
                self._waiting_for_reply = False
                self._consecutive_errors += 1

                # Riaccodiamo il messaggio
                self._send_queue.insert(0, data)

            # Se è un errore critico, segnala la disconnessione
            if e.errno in [zmq.ETERM, zmq.ENOTSOCK, zmq.ENOTSUP]:
                logger.error("Errore fatale nella connessione ZMQ")
                with QMutexLocker(self._mutex):
                    self._running = False
                self.connection_closed.emit(self.device_id)

            # Riavvia il socket per resettare lo stato REQ/REP
            self._restart_socket()

        except Exception as e:
            logger.error(f"Errore durante l'invio: {str(e)}")

            # Reset del flag di attesa risposta
            with QMutexLocker(self._mutex):
                self._waiting_for_reply = False
                # Riaccodiamo il messaggio
                self._send_queue.insert(0, data)

            # Riavvia il socket per resettare lo stato REQ/REP
            self._restart_socket()

    def _send_ping(self) -> bool:
        """
        Invia un ping al server per verificare lo stato della connessione.
        Usato solo quando il socket è in stato inattivo.

        Returns:
            True se il ping è stato inviato con successo, False altrimenti
        """
        try:
            # Crea un messaggio di ping
            ping_msg = {
                "type": "PING",
                "timestamp": time.time(),
                "is_keepalive": True
            }

            # Serializza
            data = json.dumps(ping_msg).encode('utf-8')

            # Metti in coda
            return self.send_data(data)
        except Exception as e:
            logger.error(f"Errore nell'invio del ping: {e}")
            return False

    def _restart_socket(self):
        """Riavvia il socket per resettare lo stato REQ/REP."""
        logger.info("Riavvio del socket per resettare lo stato REQ/REP")

        try:
            # Chiudi il socket esistente
            if self._socket:
                try:
                    self._socket.setsockopt(zmq.LINGER, 0)
                    self._socket.close()
                except Exception as e:
                    logger.debug(f"Errore nella chiusura del socket: {e}")
                self._socket = None

            # Crea un nuovo socket
            if self._context:
                try:
                    self._socket = self._context.socket(zmq.REQ)

                    # Configura il nuovo socket
                    self._socket.setsockopt(zmq.RCVTIMEO, 5000)
                    self._socket.setsockopt(zmq.SNDTIMEO, 5000)
                    self._socket.setsockopt(zmq.LINGER, 1000)
                    self._socket.setsockopt(zmq.RECONNECT_IVL, 500)
                    self._socket.setsockopt(zmq.RECONNECT_IVL_MAX, 5000)
                    self._socket.setsockopt(zmq.TCP_KEEPALIVE, 1)
                    self._socket.setsockopt(zmq.TCP_KEEPALIVE_IDLE, 60)
                    self._socket.setsockopt(zmq.TCP_KEEPALIVE_INTVL, 5)

                    # Riconnetti all'endpoint
                    endpoint = f"tcp://{self.host}:{self.port}"
                    self._socket.connect(endpoint)

                    logger.info(f"Socket riavviato e riconnesso a {endpoint}")
                    return True
                except Exception as e:
                    logger.error(f"Errore nella creazione del nuovo socket: {e}")
                    return False
        except Exception as e:
            logger.error(f"Errore nel riavvio del socket: {e}")
            return False

    def stop(self):
        """Ferma il worker e chiude la connessione in modo sicuro."""
        logger.info(f"Arresto del worker di connessione per {self.device_id}...")

        try:
            # Segnala l'evento di arresto
            self._shutdown_event.set()

            with QMutexLocker(self._mutex):
                self._running = False

            # Pulisci subito le risorse socket per evitare blocchi
            self._cleanup_socket()

            # Attendiamo un breve momento per permettere al thread di completare
            # eventuali operazioni in corso
            if self.isRunning():
                # Se il thread è ancora in esecuzione, attendiamo con timeout
                if not self.wait(2000):  # Attendi fino a 2 secondi
                    logger.warning(f"Thread di connessione per {self.device_id} non si ferma entro il timeout")
                    # Non forziamo con terminate() che è pericoloso

            logger.info(f"Worker di connessione per {self.device_id} arrestato")
        except Exception as e:
            logger.error(f"Errore nell'arresto del worker di connessione: {e}")
            # Assicurati che le risorse vengano comunque rilasciate
            try:
                self._cleanup_socket()
            except Exception as cleanup_err:
                logger.error(f"Errore anche nella pulizia del socket: {cleanup_err}")

    def _cleanup_socket(self):
        """Pulisce le risorse del worker in modo sicuro."""
        try:
            if self._socket:
                try:
                    # Chiusura sicura: prima impostiamo LINGER a 0
                    self._socket.setsockopt(zmq.LINGER, 0)
                    self._socket.close()
                except:
                    pass
                self._socket = None

            if self._context:
                try:
                    # Termina il contesto in modo sicuro
                    self._context.term()
                except:
                    pass
                self._context = None

            logger.debug(f"Risorse ZMQ rilasciate per worker {self.device_id}")
        except Exception as e:
            logger.error(f"Errore nel rilascio delle risorse ZMQ: {e}")


class ConnectionManager(QObject):
    """
    Gestisce le connessioni con gli scanner UnLook.
    Versione migliorata con gestione più robusta delle connessioni e riconnessioni automatiche.
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
        self._responses: Dict[str, Dict[str, Any]] = defaultdict(dict)
        self._responses_mutex = QMutex()
        self._connections_mutex = QMutex()  # Mutex per proteggere la lista delle connessioni
        self._initialized = True

        # Aggiungi un timer per il monitoraggio periodico delle connessioni
        self._monitor_timer = QTimer(self)
        self._monitor_timer.timeout.connect(self._monitor_connections)
        self._monitor_timer.start(10000)  # Controlla ogni 10 secondi

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
        with QMutexLocker(self._connections_mutex):
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
        Chiude la connessione con uno scanner in modo sicuro e robusto.

        Args:
            device_id: ID univoco dello scanner

        Returns:
            True se la disconnessione è stata avviata, False altrimenti
        """
        logger.info(f"Richiesta disconnessione per device {device_id}")

        try:
            with QMutexLocker(self._connections_mutex):
                if device_id not in self._connections:
                    logger.warning(f"Nessuna connessione attiva per {device_id}")
                    return False

                # Ottieni il riferimento al worker prima di rimuoverlo dal dizionario
                worker = self._connections[device_id]

                # Rimuovi immediatamente dal dizionario per evitare accessi multipli
                self._connections.pop(device_id)

                # Pulisci le risposte in sospeso
                with QMutexLocker(self._responses_mutex):
                    if device_id in self._responses:
                        del self._responses[device_id]

            # Fuori dal mutex, gestiamo la disconnessione effettiva
            try:
                # Tentativo di invio diretto del comando DISCONNECT, senza passare per la coda
                # Ma solo se il worker è ancora in esecuzione
                if worker.isRunning():
                    try:
                        message = {"type": "DISCONNECT", "timestamp": time.time()}
                        data = json.dumps(message).encode('utf-8')
                        worker.send_data(data)
                        logger.debug(f"Comando DISCONNECT inviato a {device_id}")
                    except Exception as msg_err:
                        logger.debug(f"Impossibile inviare DISCONNECT: {msg_err}")
            except Exception as e:
                logger.debug(f"Errore nell'invio del messaggio di disconnessione: {e}")

            # Ferma il worker in modo sicuro
            try:
                # Usa stop() che dovrebbe gestire internamente la terminazione
                worker.stop()

                # Attendi la terminazione con un timeout ragionevole
                if worker.isRunning():
                    logger.debug(f"In attesa della terminazione del worker per {device_id}...")
                    worker.wait(2000)  # 2 secondi di timeout

                    if worker.isRunning():
                        logger.warning(f"Il worker per {device_id} non si è fermato nel timeout previsto")
            except Exception as stop_err:
                logger.error(f"Errore nell'arresto del worker: {stop_err}")

            # Disconnetti i segnali in modo sicuro
            self._disconnect_worker_signals_safely(worker)

            logger.info(f"Disconnessione completata per {device_id}")
            return True

        except Exception as e:
            logger.error(f"Errore critico durante la disconnessione di {device_id}: {e}")
            # Rilascia comunque le risorse per evitare memory leak
            try:
                with QMutexLocker(self._connections_mutex):
                    if device_id in self._connections:
                        self._connections.pop(device_id)

                with QMutexLocker(self._responses_mutex):
                    if device_id in self._responses:
                        del self._responses[device_id]
            except:
                pass
            return False

    def _disconnect_worker_signals_safely(self, worker):
        """Disconnette in modo sicuro i segnali del worker."""
        try:
            # Disconnetti ogni segnale individualmente per gestire meglio gli errori
            signals_to_disconnect = [
                'connection_ready',
                'connection_error',
                'connection_closed',
                'data_received'
            ]

            for signal_name in signals_to_disconnect:
                try:
                    if hasattr(worker, signal_name):
                        signal = getattr(worker, signal_name)
                        # In PySide6/PyQt, non abbiamo accesso diretto al numero di ricevitori
                        # quindi catturiamo semplicemente le eccezioni
                        try:
                            signal.disconnect()
                        except TypeError:  # Tipo di errore quando non ci sono connessioni
                            pass
                        except Exception as e:
                            logger.debug(f"Errore nella disconnessione del segnale {signal_name}: {e}")
                except Exception as e:
                    logger.debug(f"Errore nell'accesso al segnale {signal_name}: {e}")
        except Exception as e:
            logger.error(f"Errore generale nella disconnessione dei segnali: {e}")

    def send_message(self, device_id: str, message: Dict[str, Any], timeout: float = 5.0) -> bool:
        """
        Invia un messaggio a un dispositivo con supporto timeout.

        Args:
            device_id: ID del dispositivo
            message: Messaggio da inviare
            timeout: Timeout in secondi per l'invio del messaggio

        Returns:
            True se il messaggio è stato inviato con successo, False altrimenti
        """
        if device_id not in self._connections:
            logger.error(f"Nessuna connessione attiva per {device_id}")
            return False

        try:
            # Imposta timeout sul socket
            connection = self._connections[device_id]
            socket = connection.get("socket")
            if socket:
                # Salva il timeout originale
                original_timeout = socket.getsockopt(zmq.RCVTIMEO)
                # Imposta il nuovo timeout (in millisecondi)
                socket.setsockopt(zmq.RCVTIMEO, int(timeout * 1000))

                # Invia il messaggio
                json_message = json.dumps(message).encode('utf-8')
                socket.send(json_message)

                # Ripristina il timeout originale
                socket.setsockopt(zmq.RCVTIMEO, original_timeout)

                # Memorizza la risposta attesa
                self._expected_responses[device_id] = message.get("type")
                return True
        except zmq.ZMQError as e:
            logger.error(f"Errore ZMQ nell'invio del messaggio: {e}")
        except Exception as e:
            logger.error(f"Errore nell'invio del messaggio: {e}")

        return False

    def send_message_with_timeout(self, device_id, message, timeout=5.0):
        """
        Invia un messaggio con timeout configurabile.

        Args:
            device_id: ID del dispositivo
            message: Messaggio da inviare
            timeout: Timeout in secondi (default: 5.0)

        Returns:
            True se il messaggio è stato inviato correttamente, False altrimenti
        """
        try:
            connection = self._get_connection(device_id)
            if not connection:
                logger.error(f"Nessuna connessione trovata per {device_id}")
                return False

            # Salva il timeout originale
            original_timeout = connection.socket.getsockopt(zmq.SNDTIMEO)

            try:
                # Imposta il nuovo timeout (in millisecondi)
                connection.socket.setsockopt(zmq.SNDTIMEO, int(timeout * 1000))

                # Invia il messaggio
                connection.socket.send_json(message)

                # Messaggio inviato con successo
                logger.debug(f"Messaggio {message.get('type')} inviato a {device_id} (timeout: {timeout}s)")
                return True

            finally:
                # Ripristina il timeout originale
                connection.socket.setsockopt(zmq.SNDTIMEO, original_timeout)

        except zmq.ZMQError as e:
            if e.errno == zmq.EAGAIN:
                logger.warning(f"Timeout ({timeout}s) raggiunto durante l'invio a {device_id}")
            else:
                logger.error(f"Errore ZMQ nell'invio a {device_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Errore imprevisto nell'invio a {device_id}: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False

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
        Versione migliorata che controlla effettivamente lo stato attuale.

        Args:
            device_id: ID univoco dello scanner

        Returns:
            True se il dispositivo è connesso, False altrimenti
        """
        with QMutexLocker(self._connections_mutex):
            if device_id not in self._connections:
                return False

            worker = self._connections[device_id]
            return worker.isRunning()

    def has_response(self, device_id: str, command_type: str) -> bool:
        """
        Verifica se è disponibile una risposta per un comando specifico.
        Versione migliorata per cercare anche risposte con suffissi o con original_type.

        Args:
            device_id: ID univoco dello scanner
            command_type: Tipo di comando

        Returns:
            True se è disponibile una risposta, False altrimenti
        """
        with QMutexLocker(self._responses_mutex):
            if device_id not in self._responses:
                return False

            # Verifica diretta
            if command_type in self._responses[device_id]:
                return True

            # Verifica con suffisso "_response"
            response_type = f"{command_type}_response"
            if response_type in self._responses[device_id]:
                return True

            # Verifica basata sul campo original_type
            for resp_data in self._responses[device_id].values():
                if isinstance(resp_data, dict) and resp_data.get("original_type") == command_type:
                    return True

            return False

    def get_response(self, device_id: str, command_type: str) -> Optional[Dict[str, Any]]:
        """
        Restituisce la risposta per un comando specifico e la rimuove dalla coda.
        Versione migliorata per una ricerca più flessibile.

        Args:
            device_id: ID univoco dello scanner
            command_type: Tipo di comando

        Returns:
            Dizionario con la risposta o None se non disponibile
        """
        with QMutexLocker(self._responses_mutex):
            if device_id in self._responses:
                # Prima verifica per il tipo esatto
                if command_type in self._responses[device_id]:
                    response = self._responses[device_id].pop(command_type)
                    return response

                # Poi controlla se c'è una risposta con il suffisso "_response"
                response_type = f"{command_type}_response"
                if response_type in self._responses[device_id]:
                    response = self._responses[device_id].pop(response_type)
                    return response

                # Infine verifica se c'è una risposta con original_type che corrisponde
                for resp_type, resp_data in list(self._responses[device_id].items()):
                    if isinstance(resp_data, dict) and resp_data.get("original_type") == command_type:
                        response = self._responses[device_id].pop(resp_type)
                        return response

            return None

    def wait_for_response(self, device_id: str, command_type: str, timeout: float = 30.0) -> Optional[Dict[str, Any]]:
        """
        Attende la risposta a un comando specifico con un timeout.
        Versione migliorata che evita di bloccare completamente il thread UI.

        Args:
            device_id: ID univoco dello scanner
            command_type: Tipo di comando
            timeout: Timeout in secondi

        Returns:
            Risposta o None se scaduto il timeout
        """
        start_time = time.time()

        # Check immediato
        response = self.get_response(device_id, command_type)
        if response:
            return response

        # Loop di attesa con processing degli eventi Qt
        while (time.time() - start_time) < timeout:
            # Piccola pausa per non saturare la CPU
            time.sleep(0.01)

            # Verifica se è arrivata una risposta
            response = self.get_response(device_id, command_type)
            if response:
                return response

            # Permetti all'applicazione di processare eventi
            QCoreApplication.processEvents()

            # Verifica se il dispositivo è ancora connesso
            if not self.is_connected(device_id):
                logger.warning(f"Dispositivo {device_id} disconnesso durante l'attesa della risposta")
                return None

        # Timeout scaduto
        logger.warning(f"Timeout durante l'attesa della risposta a {command_type} per {device_id}")
        return None

    def _cleanup_connection(self, device_id: str):
        """Rimuove una connessione dalla gestione."""
        with QMutexLocker(self._connections_mutex):
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

            # Rimuovi anche le risposte in sospeso
            with QMutexLocker(self._responses_mutex):
                if device_id in self._responses:
                    del self._responses[device_id]

    def _monitor_connections(self):
        """
        Monitora periodicamente lo stato delle connessioni.
        Utile per rilevare connessioni che potrebbero essere in uno stato inconsistente.
        """
        with QMutexLocker(self._connections_mutex):
            for device_id, worker in list(self._connections.items()):
                # Verifica se il worker è ancora in esecuzione
                if not worker.isRunning():
                    logger.warning(f"Worker per {device_id} non più in esecuzione, pulizia risorse")
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

        # Rilascia le risorse della connessione
        self._cleanup_connection(device_id)

        # Emetti il segnale
        self.connection_closed.emit(device_id)

    def _on_data_received(self, device_id: str, message: dict):
        """Gestisce l'evento di ricezione dati."""
        try:
            # Estrai il tipo di messaggio
            message_type = message.get('type', '')
            original_type = None

            if message_type.endswith('_response'):
                # Estrai il tipo originale del comando (rimuovendo "_response")
                original_type = message_type[:-9]

            logger.debug(f"Messaggio ricevuto da {device_id}: {message_type}")

            # Archivia la risposta per il comando originale
            if original_type:
                with QMutexLocker(self._responses_mutex):
                    self._responses[device_id][original_type] = message
                logger.debug(f"Risposta archiviata per comando {original_type}")

            # Emetti il segnale generico di dati ricevuti
            self.data_received.emit(device_id, message)

            # Gestisci il messaggio con l'handler specifico
            if message_type in self._message_handlers:
                handler = self._message_handlers[message_type]
                handler(device_id, message)

            # Gestisci anche con l'handler del tipo originale se esiste
            if original_type and original_type in self._message_handlers:
                handler = self._message_handlers[original_type]
                handler(device_id, message)

        except Exception as e:
            logger.error(f"Errore nella gestione dei dati ricevuti: {str(e)}")