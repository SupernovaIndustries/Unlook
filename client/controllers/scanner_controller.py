#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Controller per la gestione degli scanner UnLook.
Gestisce le connessioni, comandi e sincronizzazione tra GUI e dispositivi fisici.
"""

import logging
import time
import threading
import uuid
from typing import List, Optional, Dict, Any, Tuple
from PySide6.QtCore import QObject, Signal, Slot, Property, QSettings, QTimer, QCoreApplication
from PySide6.QtWidgets import QApplication, QMainWindow

# Importa i moduli del progetto con gestione robusta delle importazioni
try:
    from client.models.scanner_model import Scanner, ScannerManager, ScannerStatus
except ImportError:
    # Fallback per esecuzione diretta
    from client.models.scanner_model import Scanner, ScannerManager, ScannerStatus

# Configurazione logging
logger = logging.getLogger(__name__)


class ScannerController(QObject):
    """
    Controller che gestisce le interazioni tra l'interfaccia utente
    e il modello di gestione degli scanner.

    Implementa pattern di comunicazione robusti e meccanismi di
    recovery per garantire operatività continua anche in condizioni
    di rete non ideali.
    """
    # Segnali
    scanners_changed = Signal()
    scanner_connected = Signal(Scanner)
    scanner_disconnected = Signal(Scanner)
    connection_error = Signal(str, str)  # device_id, error_message
    scan_status_changed = Signal(str, dict)  # device_id, status_info

    def __init__(self, scanner_manager=None):
        """
        Inizializza il controller degli scanner.

        Args:
            scanner_manager: Manager degli scanner (opzionale)
        """
        super().__init__()
        self.scanner_manager = scanner_manager or ScannerManager()
        self._selected_scanner = None

        # Implementazione corretta per lazy initialization
        self._connection_mgr = None

        # Cache per migliorare performance delle interrogazioni frequenti
        self._connection_status_cache = {}
        self._last_status_check = {}

        # Collega segnali del ScannerManager
        self.scanner_manager.scanner_discovered.connect(self._on_scanner_discovered)
        self.scanner_manager.scanner_lost.connect(self._on_scanner_lost)

        # Timer per pulizia cache e sincronizzazione periodica
        self._cleanup_timer = QTimer(self)
        self._cleanup_timer.timeout.connect(self._cleanup_cache)
        self._cleanup_timer.start(30000)  # 30 secondi

        # Timer per il keepalive
        self._keepalive_timer = QTimer(self)
        self._keepalive_timer.timeout.connect(self._send_keepalive)
        self._keepalive_timer.start(2000)  # 2 secondi

        # Strutture per il monitoraggio
        self._last_heartbeat_responses = {}
        self._consecutive_missed_heartbeats = {}
        self._stream_receiver_instance = None

        # Carica le preferenze
        self._load_preferences()

        logger.info("ScannerController inizializzato")

    @property
    def connection_manager(self):
        """
        Restituisce l'istanza del connection manager, inizializzandola se necessario.
        Implementa il pattern Lazy Initialization corretto.

        Returns:
            ConnectionManager: Istanza del gestore connessioni
        """
        if self._connection_mgr is None:
            # Importiamo qui per evitare dipendenze circolari
            from client.network.connection_manager import ConnectionManager
            self._connection_mgr = ConnectionManager()
            logger.debug("ConnectionManager inizializzato on-demand")

        return self._connection_mgr

    def _send_keepalive(self):
        """
        Invia un ping keepalive allo scanner selezionato per mantenere
        attiva la connessione e monitorare lo stato.
        """
        if not self._selected_scanner or not self.is_connected(self._selected_scanner.device_id):
            return

        device_id = self._selected_scanner.device_id

        try:
            # Ottieni l'IP locale per bypass NAT
            local_ip = self._get_local_ip()

            # Invia comando ping
            ping_sent = self.send_command(
                device_id,
                "PING",
                {
                    "timestamp": time.time(),
                    "client_ip": local_ip,
                    "keepalive": True
                },
                timeout=0.5  # Timeout breve per evitare blocchi
            )

            if not ping_sent:
                logger.debug(f"Impossibile inviare ping keepalive a {self._selected_scanner.name}")
                return

            # Attendi esplicitamente la risposta per completare il ciclo REQ/REP
            response = self.receive_response(device_id, timeout=0.5)

            if response:
                # Reset contatore errori
                if device_id in self._consecutive_missed_heartbeats:
                    self._consecutive_missed_heartbeats[device_id] = 0
            else:
                # Incrementa contatore errori
                if device_id in self._consecutive_missed_heartbeats:
                    self._consecutive_missed_heartbeats[device_id] += 1
                    # Log solo per errori multipli consecutivi
                    if self._consecutive_missed_heartbeats[device_id] > 3:
                        logger.warning(
                            f"Mancata risposta al ping per {self._consecutive_missed_heartbeats[device_id]} volte consecutive")

                        # Se troppi errori consecutivi, tenta ripristino socket
                        if self._consecutive_missed_heartbeats[device_id] > 5:
                            logger.info(
                                f"Ripristino connessione dopo {self._consecutive_missed_heartbeats[device_id]} ping falliti")
                            self.connection_manager._reset_socket_state(device_id)
                            self._consecutive_missed_heartbeats[device_id] = 0

        except Exception as e:
            logger.error(f"Errore nell'invio del keepalive: {e}")

    def check_streaming_status(self, device_id: str) -> bool:
        """
        Verifica in modo esplicito se lo streaming è attivo per questo scanner.

        Args:
            device_id: ID dello scanner

        Returns:
            bool: True se lo streaming è attivo, False altrimenti
        """
        if not self.is_connected(device_id):
            return False

        try:
            # Richiedi lo stato con GET_STATUS
            status_sent = self.send_command(
                device_id,
                "GET_STATUS",
                timeout=2.0
            )

            if not status_sent:
                logger.warning(f"Impossibile inviare GET_STATUS a {device_id}")
                return False

            # Attendi la risposta
            response = self.receive_response(device_id, timeout=2.0)

            if not response:
                logger.warning(f"Nessuna risposta a GET_STATUS da {device_id}")
                return False

            # Controlla se lo streaming è attivo nella risposta
            state = response.get('state', {})
            streaming_active = state.get('streaming', False)

            if streaming_active:
                logger.info(f"Streaming attivo confermato per {device_id}")
            else:
                logger.warning(f"Lo streaming non risulta attivo per {device_id}")

            return streaming_active

        except Exception as e:
            logger.error(f"Errore nel controllo dello stato streaming: {e}")
            return False
    def _get_local_ip(self):
        """
        Rileva l'indirizzo IP locale della macchina per connessioni uscenti.
        Questo è importante per NAT traversal e configurazione firewall.

        Returns:
            str: Indirizzo IP locale o None se non rilevabile
        """
        try:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            return local_ip
        except Exception:
            return None

    def start_discovery(self):
        """
        Avvia la scoperta degli scanner nella rete locale usando
        protocolli broadcast/multicast.
        """
        self.scanner_manager.start_discovery()
        logger.info("Avviata scoperta scanner UnLook")

    def stop_discovery(self):
        """
        Ferma la scoperta degli scanner e libera risorse di rete.
        """
        self.scanner_manager.stop_discovery()
        logger.info("Fermata scoperta scanner UnLook")

    @Property(list, notify=scanners_changed)
    def scanners(self) -> List[Scanner]:
        """
        Restituisce la lista degli scanner disponibili.

        Returns:
            List[Scanner]: Lista degli scanner rilevati
        """
        return self.scanner_manager.scanners

    @Slot(str)
    def connect_to_scanner(self, device_id: str) -> bool:
        """
        Stabilisce una connessione con uno scanner specifico.

        Args:
            device_id: ID univoco dello scanner

        Returns:
            bool: True se la connessione è stata avviata, False altrimenti
        """
        # Verifica validità dell'ID
        if not device_id:
            logger.error("ID scanner non valido")
            return False

        # Recupera lo scanner dal manager
        scanner = self.scanner_manager.get_scanner(device_id)
        if not scanner:
            logger.error(f"Scanner con ID {device_id} non trovato")
            return False

        try:
            # Imposta lo stato a CONNECTING
            prev_status = scanner.status
            scanner.status = ScannerStatus.CONNECTING
            logger.info(f"Scanner {scanner.name} status: {prev_status.name} -> CONNECTING")

            # Stabilisce la connessione
            success = self.connection_manager.connect(
                scanner.device_id,
                scanner.ip_address,
                scanner.port
            )

            if success:
                # Aggiorna lo stato e notifica
                scanner.status = ScannerStatus.CONNECTED
                logger.info(f"Connessione stabilita con {scanner.name}")

                # Salva l'ultimo scanner connesso
                settings = QSettings()
                settings.setValue("scanner/last_device_id", device_id)

                # Emetti il segnale di connessione
                self.scanner_connected.emit(scanner)

                # Seleziona automaticamente questo scanner
                if not self._selected_scanner:
                    self.select_scanner(device_id)

                # Avvia il monitoraggio heartbeat
                self._consecutive_missed_heartbeats[device_id] = 0

                return True
            else:
                # Connessione fallita
                scanner.status = ScannerStatus.ERROR
                scanner.error_message = "Connessione fallita"
                logger.error(f"Impossibile connettersi a {scanner.name}")

                # Notifica errore
                self.connection_error.emit(device_id, "Connessione fallita")
                return False

        except Exception as e:
            # Gestione errori
            scanner.status = ScannerStatus.ERROR
            scanner.error_message = str(e)
            logger.error(f"Errore nella connessione a {scanner.name}: {e}")

            # Notifica errore
            self.connection_error.emit(device_id, str(e))
            return False

    @Slot(str)
    def disconnect_from_scanner(self, device_id: str, force_cleanup: bool = False) -> bool:
        """
        Chiude la connessione con uno scanner specifico.

        Args:
            device_id: ID univoco dello scanner
            force_cleanup: Se True, forza la pulizia delle risorse anche in caso di errore

        Returns:
            bool: True se la disconnessione è stata completata, False altrimenti
        """
        try:
            # Verifica esistenza scanner
            scanner = self.scanner_manager.get_scanner(device_id)
            if not scanner:
                logger.error(f"Scanner con ID {device_id} non trovato")
                return False

            # Imposta stato disconnesso immediatamente (anticipando la disconnessione fisica)
            old_status = scanner.status
            scanner.status = ScannerStatus.DISCONNECTED
            logger.info(f"Stato scanner {scanner.name} cambiato da {old_status.name} a DISCONNECTED")

            # Ferma eventuali streaming attivi
            if old_status == ScannerStatus.STREAMING:
                try:
                    self.send_command(device_id, "STOP_STREAM", timeout=1.0)
                    logger.info(f"Comando STOP_STREAM inviato a {scanner.name}")
                except Exception as e:
                    logger.warning(f"Errore nell'invio del comando STOP_STREAM: {e}")

            # Disconnette effettivamente
            success = self.connection_manager.disconnect(device_id)

            # Emette segnale di disconnessione
            if scanner:
                self.scanner_disconnected.emit(scanner)
                logger.info(f"Disconnessione da {scanner.name} completata")

                # Se era selezionato, deseleziona
                if self._selected_scanner and self._selected_scanner.device_id == device_id:
                    self._selected_scanner = None

            # Pulisci cache
            if device_id in self._connection_status_cache:
                del self._connection_status_cache[device_id]

            if device_id in self._last_status_check:
                del self._last_status_check[device_id]

            if device_id in self._consecutive_missed_heartbeats:
                del self._consecutive_missed_heartbeats[device_id]

            if device_id in self._last_heartbeat_responses:
                del self._last_heartbeat_responses[device_id]

            return success
        except Exception as e:
            logger.error(f"Errore durante la disconnessione da {device_id}: {e}")

            # Cleanup forzato se richiesto
            if force_cleanup:
                try:
                    self.connection_manager.disconnect(device_id)
                except:
                    pass

                # Emette comunque il segnale
                if scanner:
                    scanner.status = ScannerStatus.DISCONNECTED
                    self.scanner_disconnected.emit(scanner)

                return True

            return False

    @Slot(str)
    def select_scanner(self, device_id: str) -> bool:
        """
        Seleziona uno scanner come dispositivo corrente.

        Args:
            device_id: ID univoco dello scanner

        Returns:
            bool: True se la selezione è riuscita, False altrimenti
        """
        scanner = self.scanner_manager.get_scanner(device_id)
        if not scanner:
            logger.error(f"Scanner con ID {device_id} non trovato")
            return False

        self._selected_scanner = scanner
        logger.info(f"Scanner selezionato: {scanner.name}")
        return True

    @property
    def selected_scanner(self) -> Optional[Scanner]:
        """
        Restituisce lo scanner attualmente selezionato.

        Returns:
            Optional[Scanner]: Scanner selezionato o None
        """
        return self._selected_scanner

    def is_connected(self, device_id: str) -> bool:
        """
        Verifica se un determinato scanner è connesso con gestione
        ottimizzata della cache per ridurre overhead di rete.

        Args:
            device_id: ID univoco dello scanner

        Returns:
            bool: True se il dispositivo è connesso, False altrimenti
        """
        # Verifica esistenza scanner
        scanner = self.scanner_manager.get_scanner(device_id)
        if not scanner:
            return False

        # Ottimizzazione: se lo scanner è in streaming, è sicuramente connesso
        if scanner.status == ScannerStatus.STREAMING:
            return True

        # Ottimizzazione cache: limita verifiche frequenti
        current_time = time.time()
        last_check_time = self._last_status_check.get(device_id, 0)

        if current_time - last_check_time < 0.5:  # 500ms di cache
            return self._connection_status_cache.get(device_id, False)

        # Verifica effettiva dello stato
        try:
            # Controllo su due livelli
            scanner_state_connected = scanner.status in (ScannerStatus.CONNECTED, ScannerStatus.STREAMING)

            # Verifica diretta con connection manager
            connection_manager_connected = self.connection_manager.is_connected(device_id)

            # Sincronizza stato se c'è discrepanza
            if connection_manager_connected and scanner.status == ScannerStatus.DISCONNECTED:
                scanner.status = ScannerStatus.CONNECTED
                logger.info(f"Correzione automatica stato scanner {device_id}: impostato a CONNECTED")
            elif not connection_manager_connected and scanner.status == ScannerStatus.CONNECTED:
                if scanner.status != ScannerStatus.STREAMING:
                    scanner.status = ScannerStatus.DISCONNECTED
                    logger.info(f"Correzione automatica stato scanner {device_id}: impostato a DISCONNECTED")
                    self.scanner_disconnected.emit(scanner)

            # Aggiorna cache
            is_connected = scanner.status in (ScannerStatus.CONNECTED, ScannerStatus.STREAMING)
            self._connection_status_cache[device_id] = is_connected
            self._last_status_check[device_id] = current_time

            return is_connected

        except Exception as e:
            logger.error(f"Errore nel controllo della connessione per {device_id}: {e}")
            return scanner.status in (ScannerStatus.CONNECTED, ScannerStatus.STREAMING)

    def send_command(self, device_id: str, command_type: str,
                     data: Dict[str, Any] = None, timeout: float = None) -> bool:
        """
        Invia un comando allo scanner con supporto per timeout configurabile.
        Implementa meccanismo di retry intelligente per comandi critici.

        Args:
            device_id: ID del dispositivo
            command_type: Tipo di comando
            data: Dati del comando (opzionale)
            timeout: Timeout in secondi (opzionale)

        Returns:
            bool: True se il comando è stato inviato correttamente, False altrimenti
        """
        if not device_id:
            logger.error("Device ID non valido")
            return False

        # Verifica connessione (ottimizzato: bypass cache per comandi critici)
        bypass_commands = ["START_SCAN", "STOP_SCAN", "START_STREAM", "STOP_STREAM"]
        if command_type in bypass_commands:
            # Forza verifica diretta
            if not self.connection_manager.is_connected(device_id):
                logger.error(f"Impossibile inviare {command_type}: scanner non connesso")
                return False
        elif not self.is_connected(device_id):
            logger.error(f"Impossibile inviare {command_type}: scanner non connesso")
            return False

        try:
            # Prepara dati comando
            # I dati aggiuntivi non dovrebbero includere 'command' o 'type' per evitare conflitti
            safe_data = None
            if data:
                safe_data = data.copy()
                # Rimozione sicura per evitare conflitti
                if 'command' in safe_data or 'type' in safe_data:
                    logger.warning(f"I dati contengono 'command' o 'type' che potrebbero causare conflitti")
                    safe_data.pop('command', None)
                    safe_data.pop('type', None)

                # Aggiungiamo timestamp se non presente
                if 'timestamp' not in safe_data:
                    safe_data['timestamp'] = time.time()
            else:
                safe_data = {"timestamp": time.time()}

            # Log dei comandi principali
            if command_type not in ["PING", "GET_STATUS"]:
                logger.debug(f"Invio comando {command_type} a {device_id}")

            # Invia il comando - il connection_manager si occuperà di aggiungere command/type
            success = self.connection_manager.send_message(
                device_id,
                command_type,
                safe_data,
                timeout or 2.0  # Default 2s
            )

            # Gestione speciale per comandi che potrebbero richiedere retry
            if not success and command_type in ["START_SCAN", "STOP_SCAN", "START_STREAM"]:
                logger.warning(f"Primo tentativo {command_type} fallito, retry...")
                # Breve attesa
                time.sleep(0.2)
                # Ritenta con timeout più lungo
                success = self.connection_manager.send_message(
                    device_id,
                    command_type,
                    safe_data,
                    (timeout or 2.0) * 1.5  # 50% in più di timeout
                )

            return success

        except Exception as e:
            logger.error(f"Errore nell'invio del comando {command_type}: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False

    def wait_for_response(self, device_id: str, command_type: str,
                          timeout: float = None) -> Optional[Dict[str, Any]]:
        """
        Attende la risposta a un comando inviato con gestione ottimizzata dell'attesa
        che non blocca l'interfaccia utente.

        Args:
            device_id: ID univoco dello scanner
            command_type: Tipo di comando per cui si attende la risposta
            timeout: Timeout in secondi (default: 30 secondi)

        Returns:
            Optional[Dict[str, Any]]: Dizionario con la risposta o None se non ricevuta
        """
        if not self.is_connected(device_id):
            logger.error(f"Impossibile attendere risposta: scanner {device_id} non connesso")
            return None

        try:
            # Timeout effettivo basato sul tipo di comando
            if command_type.startswith("START_SCAN") or command_type.startswith("STOP_SCAN"):
                effective_timeout = min(timeout or 30.0, 20.0)  # Max 20s
            elif command_type.startswith("GET_SCAN") or command_type == "CHECK_SCAN_CAPABILITY":
                effective_timeout = min(timeout or 30.0, 15.0)  # Max 15s
            elif command_type == "SYNC_PATTERN":
                effective_timeout = min(timeout or 5.0, 0.5)  # Max 500ms per low latency
            else:
                effective_timeout = min(timeout or 10.0, 10.0)  # Default max 10s

            logger.debug(f"Attesa risposta a {command_type} con timeout {effective_timeout}s")

            # Attesa non bloccante con un solo controllo di response
            # Invece di polling attivo che potrebbe compromettere REQ/REP
            response = self.connection_manager.receive_response(device_id, effective_timeout)

            if response:
                # Verifica se la risposta è per il comando atteso
                resp_type = response.get('original_type') or response.get('type')
                if resp_type == command_type:
                    if command_type not in ["PING", "GET_STATUS", "SYNC_PATTERN"]:
                        logger.debug(f"Risposta ricevuta per {command_type}")
                    return response
                else:
                    logger.warning(f"Ricevuta risposta per {resp_type} mentre si attendeva {command_type}")
                    return None

            # Timeout
            logger.warning(f"Timeout nell'attesa della risposta a {command_type} dopo {effective_timeout}s")

            # Gestione speciale per timeout di comandi critici
            if command_type == "START_STREAM":
                # Forza reset del socket in caso di timeout su START_STREAM
                try:
                    self.connection_manager._reset_socket_state(device_id)
                except:
                    pass

            return None

        except Exception as e:
            logger.error(f"Errore nell'attesa della risposta a {command_type}: {e}")
            return None

    def try_autoconnect_last_scanner(self) -> bool:
        """
        Tenta di connettersi automaticamente all'ultimo scanner utilizzato.
        Implementa pattern di autoconnessione intelligente.

        Returns:
            bool: True se la connessione è stata avviata, False altrimenti
        """
        try:
            # Recupera ultimo ID dalle impostazioni
            settings = QSettings()
            last_device_id = settings.value("scanner/last_device_id")

            if not last_device_id:
                logger.info("Nessun ultimo scanner trovato nelle impostazioni")
                return False

            # Verifica disponibilità
            target_scanner = None
            for scanner in self.scanners:
                if scanner.device_id == last_device_id:
                    target_scanner = scanner
                    break

            if not target_scanner:
                logger.info(f"L'ultimo scanner utilizzato (ID: {last_device_id}) non è disponibile")
                return False

            # Tenta connessione automatica
            logger.info(f"Tentativo di connessione automatica a {target_scanner.name}")

            # Prima seleziona
            self.select_scanner(target_scanner.device_id)

            # Poi connetti
            success = self.connect_to_scanner(target_scanner.device_id)

            if success:
                logger.info(f"Connessione automatica a {target_scanner.name} riuscita")
            else:
                logger.warning(f"Connessione automatica a {target_scanner.name} fallita")

            return success

        except Exception as e:
            logger.error(f"Errore nella connessione automatica: {e}")
            return False

    @Slot(Scanner)
    def _on_scanner_discovered(self, scanner: Scanner):
        """
        Gestisce l'evento di scoperta di un nuovo scanner.

        Args:
            scanner: Oggetto Scanner scoperto
        """
        logger.info(f"Scanner scoperto: {scanner.name} ({scanner.device_id})")
        self.scanners_changed.emit()

    @Slot(Scanner)
    def _on_scanner_lost(self, scanner: Scanner):
        """
        Gestisce l'evento di perdita di un scanner dalla rete.

        Args:
            scanner: Oggetto Scanner perso
        """
        logger.info(f"Scanner perso: {scanner.name} ({scanner.device_id})")

        # Se lo scanner perso era quello selezionato, deselezionalo
        if self._selected_scanner and self._selected_scanner.device_id == scanner.device_id:
            self._selected_scanner = None

        # Pulisci cache
        device_id = scanner.device_id
        if device_id in self._connection_status_cache:
            del self._connection_status_cache[device_id]

        if device_id in self._last_status_check:
            del self._last_status_check[device_id]

        self.scanners_changed.emit()

    def _cleanup_cache(self):
        """
        Pulisce periodicamente le cache per evitare memory leak
        e obsolescenza dei dati.
        """
        # Pulisci cache connessione per scanner non più presenti
        current_scanners = set(s.device_id for s in self.scanners)

        # Rimuovi riferimenti a scanner non più disponibili
        for device_id in list(self._connection_status_cache.keys()):
            if device_id not in current_scanners:
                del self._connection_status_cache[device_id]

        for device_id in list(self._last_status_check.keys()):
            if device_id not in current_scanners:
                del self._last_status_check[device_id]

        for device_id in list(self._consecutive_missed_heartbeats.keys()):
            if device_id not in current_scanners:
                del self._consecutive_missed_heartbeats[device_id]

        for device_id in list(self._last_heartbeat_responses.keys()):
            if device_id not in current_scanners:
                del self._last_heartbeat_responses[device_id]

    def synchronize_scanner_states(self):
        """
        Sincronizza lo stato degli scanner tra i vari componenti
        dell'applicazione. Risolve inconsistenze di stato verificando
        la connettività effettiva.
        """
        # Ottieni tutti gli scanner
        scanners = self.scanner_manager.scanners

        for scanner in scanners:
            try:
                device_id = scanner.device_id

                # Limita verifiche troppo frequenti (max 1 ogni 2s per scanner)
                current_time = time.time()
                if device_id in self._last_status_check:
                    if current_time - self._last_status_check[device_id] < 2.0:
                        continue

                # Verifica effettiva (forza refresh della cache)
                self._last_status_check[device_id] = 0  # Reset timestamp per forzare check
                is_connected = self.is_connected(device_id)

                # Stato già aggiornato dal metodo is_connected
                logger.debug(f"Stato sincronizzato per {scanner.name}: {'connesso' if is_connected else 'disconnesso'}")

            except Exception as e:
                logger.error(f"Errore nella sincronizzazione dello stato di {scanner.name}: {e}")

    def receive_response(self, device_id: str, timeout: float = None) -> Optional[Dict[str, Any]]:
        """
        Riceve una risposta da un comando inviato in precedenza.

        Args:
            device_id: ID univoco dello scanner
            timeout: Timeout in secondi (default: usa il timeout predefinito)

        Returns:
            Dizionario con la risposta o None se non ricevuta
        """
        try:
            if not self.is_connected(device_id):
                logger.error(f"Impossibile ricevere risposta: scanner {device_id} non connesso")
                return None

            # Delega al connection manager
            response = self.connection_manager.receive_response(device_id, timeout)

            if response:
                # Aggiorna statistiche e timestamp
                if device_id in self._last_heartbeat_responses:
                    self._last_heartbeat_responses[device_id] = time.time()
                    self._consecutive_missed_heartbeats[device_id] = 0

                # Log essenziale solo per comandi significativi
                command_type = response.get("original_type", response.get("type", "unknown"))
                if command_type not in ["PING", "GET_STATUS"]:
                    logger.info(
                        f"Risposta ricevuta per comando {command_type}: status={response.get('status', 'unknown')}")

            return response

        except Exception as e:
            logger.error(f"Errore nella ricezione della risposta da {device_id}: {e}")
            return None

    def get_stream_receiver(self):
        """
        Restituisce il receiver di stream se disponibile.
        Questo metodo localizza il componente StreamReceiver nell'applicazione
        per consentire il routing diretto dei frame tra componenti.

        Returns:
            StreamReceiver: Istanza o None se non disponibile
        """
        # Se abbiamo già trovato l'istanza, usiamo quella
        if self._stream_receiver_instance is not None:
            return self._stream_receiver_instance

        # Cerca in MainWindow
        app = QApplication.instance()
        if app:
            for widget in app.topLevelWidgets():
                if isinstance(widget, QMainWindow):
                    # Cerca direttamente in MainWindow
                    if hasattr(widget, 'stream_receiver') and widget.stream_receiver:
                        self._stream_receiver_instance = widget.stream_receiver
                        return self._stream_receiver_instance

                    # Cerca in streaming_widget
                    if hasattr(widget, 'streaming_widget') and widget.streaming_widget:
                        if hasattr(widget.streaming_widget, 'stream_receiver'):
                            self._stream_receiver_instance = widget.streaming_widget.stream_receiver
                            return self._stream_receiver_instance

        return None

    def _try_reconnect(self, device_id: str):
        """
        Tenta di riconnettersi a uno scanner con backoff esponenziale.

        Args:
            device_id: ID del dispositivo
        """
        scanner = self.scanner_manager.get_scanner(device_id)
        if not scanner:
            logger.warning(f"Impossibile riconnettersi: scanner {device_id} non trovato")
            return

        # Verifica attuale stato
        is_already_connected = self.is_connected(device_id)
        if is_already_connected:
            logger.info(f"Riconnessione non necessaria per {scanner.name}, già connesso")
            return

        logger.info(f"Tentativo di riconnessione a {scanner.name}...")

        # Reset stato per connessione pulita
        scanner.status = ScannerStatus.DISCONNECTED

        # Assicurati che eventuali connessioni zombie siano chiuse
        try:
            self.connection_manager.disconnect(device_id)
        except:
            pass

        # Breve attesa
        time.sleep(0.5)

        # Tenta connessione
        success = self.connect_to_scanner(device_id)

        if success:
            logger.info(f"Riconnessione a {scanner.name} riuscita")
        else:
            logger.warning(f"Riconnessione a {scanner.name} fallita")

            # Programma un nuovo tentativo con attesa più lunga (backoff)
            retry_count = getattr(self, '_reconnect_attempts', {}).get(device_id, 0) + 1

            # Memorizza conteggio tentativi
            if not hasattr(self, '_reconnect_attempts'):
                self._reconnect_attempts = {}

            self._reconnect_attempts[device_id] = retry_count

            # Calcola tempo attesa con backoff esponenziale (max 30s)
            wait_time = min(5000 * (2 ** (retry_count - 1)), 30000)

            logger.info(f"Programmato tentativo {retry_count} fra {wait_time / 1000}s")
            QTimer.singleShot(wait_time, lambda: self._try_reconnect(device_id))

    def attempt_reconnection(self, device_id: str) -> bool:
        """
        Tenta di riconnettersi a uno scanner specifico con strategia
        di retry avanzata.

        Args:
            device_id: ID del dispositivo scanner da riconnettere

        Returns:
            bool: True se la riconnessione ha avuto successo, False altrimenti
        """
        # Trova lo scanner
        scanner = None
        for s in self.scanners:
            if s.device_id == device_id:
                scanner = s
                break

        if not scanner:
            logger.error(f"Scanner {device_id} non trovato, impossibile riconnettere")
            return False

        logger.info(f"Tentativo di riconnessione a {scanner.name} ({device_id})")

        # Prima disconnetti
        if self.is_connected(device_id):
            try:
                self.disconnect_from_scanner(device_id, force_cleanup=True)
                time.sleep(0.5)  # Attesa per pulizia
            except Exception as e:
                logger.warning(f"Errore nella disconnessione preparatoria: {e}")

        # Strategia con backoff
        max_attempts = 3
        base_delay = 0.5  # 500ms iniziali

        for attempt in range(max_attempts):
            try:
                # Calcola ritardo crescente
                delay = base_delay * (2 ** attempt)

                logger.info(f"Tentativo {attempt + 1}/{max_attempts} dopo {delay:.1f}s")

                # Attesa
                if attempt > 0:
                    time.sleep(delay)

                # Tenta connessione
                success = self.connect_to_scanner(device_id)

                if success:
                    logger.info(f"Riconnessione a {scanner.name} riuscita al tentativo {attempt + 1}")

                    # Verifica con ping
                    ping_success = self.send_command(
                        device_id,
                        "PING",
                        {"timestamp": time.time()},
                        timeout=1.0
                    )

                    if ping_success:
                        logger.info(f"Connessione a {scanner.name} verificata con ping")
                        # Reset contatore
                        self._consecutive_missed_heartbeats[device_id] = 0
                        return True
                    else:
                        logger.warning(f"Riconnessione a {scanner.name} riuscita ma ping fallito")
                else:
                    logger.warning(f"Tentativo {attempt + 1} fallito")

            except Exception as e:
                logger.error(f"Errore nel tentativo {attempt + 1}: {e}")

        # Tutti i tentativi falliti
        logger.error(f"Riconnessione a {scanner.name} fallita dopo {max_attempts} tentativi")

        # Aggiorna stato
        scanner.status = ScannerStatus.DISCONNECTED
        scanner.error_message = "Riconnessione fallita dopo multipli tentativi"

        return False

    def _load_preferences(self):
        """
        Carica le preferenze dell'utente, come l'ultimo scanner utilizzato.
        """
        try:
            settings = QSettings()

            # Carica l'ID dell'ultimo scanner
            last_scanner_id = settings.value("scanner/last_device_id", "")
            self._last_connected_scanner_id = last_scanner_id if last_scanner_id else None

            logger.debug(f"Preferenze caricate: ultimo scanner ID={self._last_connected_scanner_id}")
        except Exception as e:
            logger.warning(f"Impossibile caricare le preferenze: {e}")
            self._last_connected_scanner_id = None