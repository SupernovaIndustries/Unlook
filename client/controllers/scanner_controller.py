#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Controller per la gestione degli scanner UnLook.
"""

import logging
import time
from typing import List, Optional, Callable, Dict, Any
import uuid
import threading
from PySide6.QtCore import QObject, Signal, Slot, Property, QSettings, QTimer, QCoreApplication
from PySide6.QtWidgets import QApplication, QMainWindow

# Importa i moduli del progetto in modo che funzionino sia con esecuzione diretta che tramite launcher
try:
    from client.models.scanner_model import Scanner, ScannerManager, ScannerStatus
    from client.network.connection_manager import ConnectionManager
except ImportError:
    # Fallback per esecuzione diretta
    from client.models.scanner_model import Scanner, ScannerManager, ScannerStatus
    from client.network.connection_manager import ConnectionManager

logger = logging.getLogger(__name__)


class ScannerController(QObject):
    """
    Controller che gestisce le interazioni tra l'interfaccia utente
    e il modello di gestione degli scanner.
    """
    # Segnali
    scanners_changed = Signal()
    scanner_connected = Signal(Scanner)
    scanner_disconnected = Signal(Scanner)
    connection_error = Signal(str, str)  # device_id, error_message

    def __init__(self, scanner_manager=None):
        """
        Inizializza il controller degli scanner.

        Args:
            scanner_manager: Manager degli scanner (opzionale)
        """
        super().__init__()
        self.scanner_manager = scanner_manager or ScannerManager()
        self._selected_scanner = None

        # Importa ConnectionManager come classe, non come istanza
        from client.network.connection_manager import ConnectionManager

        # Memorizza la classe (non creare ancora l'istanza)
        self._connection_manager_class = ConnectionManager

        # Collega segnali del ScannerManager
        self.scanner_manager.scanner_discovered.connect(self._on_scanner_discovered)
        self.scanner_manager.scanner_lost.connect(self._on_scanner_lost)

        # Dizionario per memorizzare le preferenze utente
        self._last_connected_scanner = None

        # Carica le preferenze
        self._load_preferences()

        logger.info("ScannerController inizializzato")

        # Metodo getter per ottenere l'istanza di ConnectionManager
    def _connection_manager(self):
        """
        Restituisce l'istanza del connection manager, inizializzandola se necessario.
        Implementa il pattern Lazy Initialization.
        """
        if not hasattr(self, '_connection_manager'):
            # Crea una nuova istanza usando la classe memorizzata in _connection_manager_class
            from client.network.connection_manager import ConnectionManager
            self._connection_manager = ConnectionManager()

        return self._connection_manager

    def _send_keepalive(self):
        """Invia un ping per mantenere attiva la connessione."""
        if self._selected_scanner and self.is_connected(self._selected_scanner.device_id):
            try:
                self.send_command(self._selected_scanner.device_id, "PING", {"timestamp": time.time()})
                logger.debug(f"Inviato ping a {self._selected_scanner.name}")
            except Exception as e:
                logger.error(f"Errore nell'invio del ping: {e}")

    def start_discovery(self):
        """Avvia la scoperta degli scanner nella rete locale."""
        self.scanner_manager.start_discovery()

    def stop_discovery(self):
        """Ferma la scoperta degli scanner."""
        self.scanner_manager.stop_discovery()

    @Property(list, notify=scanners_changed)
    def scanners(self) -> List[Scanner]:
        """Restituisce la lista degli scanner disponibili."""
        return self.scanner_manager.scanners

    @Slot(str)
    def connect_to_scanner(self, device_id: str) -> bool:
        """
        Stabilisce una connessione con uno scanner specifico.

        Args:
            device_id: ID univoco dello scanner

        Returns:
            True se la connessione è stata avviata, False altrimenti
        """
        scanner = self.scanner_manager.get_scanner(device_id)
        if not scanner:
            logger.error(f"Scanner con ID {device_id} non trovato")
            return False

        # Imposta lo stato dello scanner
        scanner.status = ScannerStatus.CONNECTING

        # Avvia la connessione
        return self._connection_manager.connect(
            scanner.device_id,
            scanner.ip_address,
            scanner.port
        )

    @Slot(str)
    def disconnect_from_scanner(self, device_id: str) -> bool:
        """
        Chiude la connessione con uno scanner specifico.

        Args:
            device_id: ID univoco dello scanner

        Returns:
            True se la disconnessione è stata avviata, False altrimenti
        """
        try:
            scanner = self.scanner_manager.get_scanner(device_id)
            if not scanner:
                logger.error(f"Scanner con ID {device_id} non trovato")
                return False

            # Imposta lo stato a DISCONNECTING per evitare operazioni durante disconnessione
            if scanner:
                try:
                    old_status = scanner.status
                    scanner.status = ScannerStatus.DISCONNECTED  # Impostiamo subito a disconnesso
                    logger.info(f"Stato scanner {device_id} cambiato da {old_status} a DISCONNECTED")
                except Exception as e:
                    logger.error(f"Errore nel cambio stato scanner: {e}")

            # Chiude la connessione
            success = self._connection_manager.disconnect(device_id)

            # Emetti il segnale di disconnessione se necessario
            if success and scanner:
                try:
                    self.scanner_disconnected.emit(scanner)
                except Exception as e:
                    logger.error(f"Errore nell'emissione del segnale di disconnessione: {e}")

            return success
        except Exception as e:
            logger.error(f"Errore durante la disconnessione da {device_id}: {e}")
            return False

    @Slot(str)
    def select_scanner(self, device_id: str) -> bool:
        """
        Seleziona uno scanner come dispositivo corrente.

        Args:
            device_id: ID univoco dello scanner

        Returns:
            True se la selezione è riuscita, False altrimenti
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
        """Restituisce lo scanner attualmente selezionato."""
        return self._selected_scanner

    def is_connected(self, device_id: str) -> bool:
        """
        Verifica se un determinato scanner è connesso.
        Versione migliorata per dare priorità allo stato di streaming e
        garantire consistenza tra diversi componenti dell'applicazione.

        Args:
            device_id: ID univoco dello scanner

        Returns:
            True se il dispositivo è connesso, False altrimenti
        """
        scanner = self.scanner_manager.get_scanner(device_id)
        if not scanner:
            return False

        # Se lo scanner è in streaming, consideriamolo sempre connesso
        if scanner.status == ScannerStatus.STREAMING:
            return True

        # Controllo su due livelli:
        # 1. Verifica lo stato memorizzato nello scanner
        scanner_state_connected = scanner.status in (ScannerStatus.CONNECTED, ScannerStatus.STREAMING)

        # 2. Verifica anche con il connection manager per conferma diretta
        connection_manager_connected = False
        try:
            # Usa l'istanza esistente del connection manager
            connection_manager_connected = self._connection_manager.is_connected(device_id)

            # Sincronizza lo stato se c'è una discrepanza
            if connection_manager_connected and scanner.status == ScannerStatus.DISCONNECTED:
                # Aggiorna lo stato dello scanner a connesso
                scanner.status = ScannerStatus.CONNECTED
                logger.info(f"Correzione automatica stato scanner {device_id}: impostato a CONNECTED")
            elif not connection_manager_connected and scanner.status == ScannerStatus.CONNECTED:
                # Se lo scanner non è in streaming, aggiorna lo stato a disconnesso
                if scanner.status != ScannerStatus.STREAMING:
                    scanner.status = ScannerStatus.DISCONNECTED
                    logger.info(f"Correzione automatica stato scanner {device_id}: impostato a DISCONNECTED")
                    # Emetti il segnale di disconnessione
                    self.scanner_disconnected.emit(scanner)
        except Exception as e:
            logger.error(f"Errore nel controllo della connessione: {e}")

        # La connessione è valida se uno dei due controlli è positivo,
        # ma diamo priorità allo stato dello scanner se è in streaming
        return scanner.status in (ScannerStatus.CONNECTED, ScannerStatus.STREAMING)

    def send_command(self, device_id, command_type, data=None, timeout=None):
        """
        Invia un comando allo scanner con supporto per timeout configurabile.

        Args:
            device_id: ID del dispositivo
            command_type: Tipo di comando
            data: Dati del comando (opzionale)
            timeout: Timeout in secondi (opzionale)

        Returns:
            True se il comando è stato inviato correttamente, False altrimenti
        """
        try:
            # Ottieni ConnectionManager tramite il getter
            connection_manager = self._connection_manager()

            # Verifica che il device_id sia valido
            if not device_id:
                logger.error("Device ID non valido")
                return False

            # Prepara i dati comando
            command_data = {
                "type": command_type,
                "id": str(uuid.uuid4()),
                "timestamp": time.time()
            }

            # Aggiungi i dati se presenti
            if data:
                command_data.update(data)

            # Invia il comando con timeout specifico se fornito
            if timeout is not None:
                # Se il metodo non esiste, implementiamo qui un fallback
                if hasattr(connection_manager, 'send_message_with_timeout'):
                    return connection_manager.send_message_with_timeout(device_id, command_data, timeout)
                else:
                    # Implementazione fallback
                    logger.warning("Metodo send_message_with_timeout non disponibile, uso send_message standard")
                    return connection_manager.send_message(device_id, command_data)
            else:
                return connection_manager.send_message(device_id, command_data)

        except Exception as e:
            logger.error(f"Errore nell'invio del comando {command_type}: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False

    def start_heartbeat(self, interval=5.0):
        """
        Avvia un timer per l'invio periodico di heartbeat a tutti gli scanner connessi.
        Importante per mantenere le connessioni attive e rilevare disconnessioni.

        Args:
            interval: Intervallo in secondi tra heartbeat consecutivi (default: 5.0)
        """
        # Ferma eventuali timer esistenti
        if hasattr(self, '_heartbeat_timer') and self._heartbeat_timer:
            self._heartbeat_timer.cancel()

        # Crea un nuovo timer
        self._heartbeat_interval = interval
        self._heartbeat_timer = threading.Timer(interval, self._heartbeat_loop)
        self._heartbeat_timer.daemon = True
        self._heartbeat_timer.start()

        # Inizializza strutture dati per il monitoraggio
        if not hasattr(self, '_last_heartbeat_responses'):
            self._last_heartbeat_responses = {}
        if not hasattr(self, '_consecutive_missed_heartbeats'):
            self._consecutive_missed_heartbeats = {}

        logger.info(f"Heartbeat avviato con intervallo di {interval} secondi")

    def _heartbeat_loop(self):
        """Loop interno per l'invio ciclico di heartbeat."""
        try:
            # Invia heartbeat a tutti gli scanner connessi
            self.send_heartbeat()

            # Verifica se ci sono scanner che non rispondono
            self._check_unresponsive_scanners()

            # Pianifica il prossimo heartbeat
            if hasattr(self, '_heartbeat_interval'):
                self._heartbeat_timer = threading.Timer(self._heartbeat_interval, self._heartbeat_loop)
                self._heartbeat_timer.daemon = True
                self._heartbeat_timer.start()
        except Exception as e:
            logger.error(f"Errore nel loop di heartbeat: {e}")
            # Riprova comunque
            if hasattr(self, '_heartbeat_interval'):
                self._heartbeat_timer = threading.Timer(self._heartbeat_interval, self._heartbeat_loop)
                self._heartbeat_timer.daemon = True
                self._heartbeat_timer.start()

    def send_heartbeat(self):
        """
        Invia un heartbeat a tutti gli scanner connessi.
        Importante per verificare che la connessione sia ancora attiva.
        """
        if not hasattr(self, '_scanner_connections'):
            logger.warning("Nessuna connessione scanner disponibile per l'invio del heartbeat")
            return

        # Ottieni l'IP locale per eventuale configurazione NAT/firewall
        import socket
        local_ip = None
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
        except:
            pass

        # Timestamp preciso per misurazione latenza
        timestamp = time.time()

        # Invia heartbeat a tutti gli scanner connessi
        for device_id, connection in self._scanner_connections.items():
            try:
                # Verifica se la connessione è attiva
                if not self.is_connected(device_id):
                    logger.debug(f"Scanner {device_id} non connesso, salto heartbeat")
                    continue

                # Prepara il payload
                payload = {
                    "timestamp": timestamp,
                    "client_ip": local_ip
                }

                # Invia il comando PING con timeout ridotto
                success = self.send_command(
                    device_id,
                    "PING",
                    payload,
                    timeout=1.0  # Timeout ridotto per heartbeat
                )

                # Aggiorna lo stato basato sulla risposta
                if success:
                    self._last_heartbeat_responses[device_id] = timestamp
                    self._consecutive_missed_heartbeats[device_id] = 0
                    logger.debug(f"Heartbeat inviato con successo a {device_id}")
                else:
                    missed = self._consecutive_missed_heartbeats.get(device_id, 0) + 1
                    self._consecutive_missed_heartbeats[device_id] = missed
                    logger.warning(f"Heartbeat fallito per {device_id} (consecutivi: {missed})")

            except Exception as e:
                logger.error(f"Errore nell'invio del heartbeat a {device_id}: {e}")
                # Incrementa contatore fallimenti
                missed = self._consecutive_missed_heartbeats.get(device_id, 0) + 1
                self._consecutive_missed_heartbeats[device_id] = missed

    def _check_unresponsive_scanners(self):
        """
        Verifica gli scanner che non rispondono e tenta il recupero.
        Strategia: dopo 3 heartbeat mancati consecutivi, tenta la riconnessione.
        """
        current_time = time.time()
        reconnection_threshold = 3  # Tentativi mancati prima di riconnessione

        for device_id, missed in list(self._consecutive_missed_heartbeats.items()):
            # Verifica se abbiamo superato la soglia
            if missed >= reconnection_threshold:
                logger.warning(
                    f"Scanner {device_id} non risponde da {missed} heartbeat consecutivi, tentativo di riconnessione")

                # Tenta la riconnessione
                self.attempt_reconnection(device_id)

                # Reset contatore per dare il tempo di riconnettersi
                self._consecutive_missed_heartbeats[device_id] = 0

    def attempt_reconnection(self, device_id):
        """
        Tenta di riconnettersi a uno scanner specifico.
        Implementa una strategia di riconnessione robusta con backoff esponenziale.

        Args:
            device_id: ID del dispositivo scanner da riconnettere

        Returns:
            bool: True se la riconnessione ha avuto successo, False altrimenti
        """
        # Verifica se lo scanner è registrato
        scanner = None
        for s in self.scanners:
            if s.device_id == device_id:
                scanner = s
                break

        if not scanner:
            logger.error(f"Scanner {device_id} non trovato nel registro, impossibile riconnettere")
            return False

        logger.info(f"Tentativo di riconnessione a {scanner.name} ({device_id})")

        # Prima disconnetti per pulire eventuali connessioni zombie
        if self.is_connected(device_id):
            try:
                # Disconnessione soft per evitare di bloccare risorse
                self.disconnect_from_scanner(device_id, force_cleanup=True)
                time.sleep(0.5)  # Pausa breve per permettere la pulizia completa
            except Exception as e:
                logger.warning(f"Errore nella disconnessione preparatoria: {e}")
                # Continua comunque con la riconnessione

        # Strategia con backoff esponenziale
        max_attempts = 3
        base_delay = 0.5  # 500ms iniziali

        for attempt in range(max_attempts):
            try:
                # Calcola ritardo crescente
                delay = base_delay * (2 ** attempt)

                # Log del tentativo
                logger.info(
                    f"Tentativo {attempt + 1}/{max_attempts} di riconnessione a {scanner.name} dopo {delay:.1f}s")

                # Attendi prima del tentativo
                if attempt > 0:
                    time.sleep(delay)

                # Tenta la connessione
                success = self.connect_to_scanner(device_id)

                if success:
                    logger.info(f"Riconnessione a {scanner.name} riuscita al tentativo {attempt + 1}")

                    # Verifica la connessione con un ping
                    ping_success = self.send_command(
                        device_id,
                        "PING",
                        {"timestamp": time.time()},
                        timeout=1.0
                    )

                    if ping_success:
                        logger.info(f"Connessione a {scanner.name} verificata con ping")
                        # Reset contatore heartbeat
                        self._consecutive_missed_heartbeats[device_id] = 0
                        return True
                    else:
                        logger.warning(f"Riconnessione a {scanner.name} riuscita ma ping fallito")
                        # Continua con il prossimo tentativo
                else:
                    logger.warning(f"Tentativo {attempt + 1} di riconnessione a {scanner.name} fallito")

            except Exception as e:
                logger.error(f"Errore nel tentativo {attempt + 1} di riconnessione a {scanner.name}: {e}")

        # Se arriviamo qui, tutti i tentativi sono falliti
        logger.error(f"Riconnessione a {scanner.name} fallita dopo {max_attempts} tentativi")

        # Aggiorna lo stato dello scanner
        scanner.status = ScannerStatus.DISCONNECTED
        scanner.error_message = "Riconnessione fallita dopo multipli tentativi"

        return False

    def synchronize_scanner_states(self):
        """
        Sincronizza lo stato degli scanner tra i vari componenti dell'applicazione.
        Risolve inconsistenze di stato verificando la connettività effettiva.
        """
        # Ottieni tutti gli scanner attualmente gestiti
        scanners = self.scanner_manager.scanners

        for scanner in scanners:
            try:
                # Verifica la connettività effettiva con il server
                connection_active = self._connection_manager.is_connected(scanner.device_id)

                # Lo stato memorizzato nello scanner
                current_state = scanner.status

                # Risolvi le inconsistenze
                if connection_active and current_state == ScannerStatus.DISCONNECTED:
                    # La connessione è attiva ma lo scanner risulta disconnesso
                    logger.info(f"Correzione stato scanner {scanner.name}: da DISCONNECTED a CONNECTED")
                    scanner.status = ScannerStatus.CONNECTED
                    self.scanner_connected.emit(scanner)

                elif not connection_active and current_state in (ScannerStatus.CONNECTED, ScannerStatus.CONNECTING):
                    # La connessione non è attiva ma lo scanner risulta connesso
                    logger.info(f"Correzione stato scanner {scanner.name}: da {current_state.name} a DISCONNECTED")
                    scanner.status = ScannerStatus.DISCONNECTED
                    self.scanner_disconnected.emit(scanner)

                # Non modifichiamo lo stato STREAMING a meno che non ci sia una disconnessione evidente
                elif not connection_active and current_state == ScannerStatus.STREAMING:
                    # Verifica ulteriore con un ping esplicito
                    ping_result = self.send_command(scanner.device_id, "PING", {"timestamp": time.time()})
                    if not ping_result:
                        logger.info(f"Correzione stato scanner {scanner.name}: da STREAMING a DISCONNECTED")
                        scanner.status = ScannerStatus.DISCONNECTED
                        self.scanner_disconnected.emit(scanner)

            except Exception as e:
                logger.error(f"Errore nella sincronizzazione dello stato di {scanner.name}: {e}")

    def wait_for_response(self, device_id: str, command_type: str, timeout: float = 30.0) -> Optional[Dict[str, Any]]:
        """
        Attende la risposta a un comando inviato.
        Versione migliorata che non blocca l'interfaccia utente e gestisce
        correttamente gli errori e i timeout.

        Args:
            device_id: ID univoco dello scanner
            command_type: Tipo di comando per cui si attende la risposta
            timeout: Timeout in secondi (default: 30 secondi)

        Returns:
            Dizionario con la risposta o None se non ricevuta entro il timeout
        """
        if not self.is_connected(device_id):
            logger.error(f"Impossibile attendere risposta: scanner {device_id} non connesso")
            return None

        try:
            # Per i comandi di scansione, usiamo un timeout più corto
            # MODIFICA: Ridotti i timeout per evitare blocchi UI
            if command_type.startswith("START_SCAN") or command_type.startswith("STOP_SCAN"):
                effective_timeout = 20.0  # Ridotto da 60s a 20s
            elif command_type.startswith("GET_SCAN") or command_type == "CHECK_SCAN_CAPABILITY":
                effective_timeout = 15.0  # Ridotto da 60s a 15s
            else:
                effective_timeout = min(timeout, 10.0)  # Limitato a massimo 10s

            logger.info(f"Usando timeout di {effective_timeout}s per comando {command_type}")

            # Attendi che la risposta sia disponibile
            start_time = time.time()
            check_interval = 0.1  # Controlla più frequentemente (ogni 100ms)
            while (time.time() - start_time) < effective_timeout:
                # IMPORTANTE: Permetti all'interfaccia grafica di processare eventi durante l'attesa
                QApplication.processEvents()

                if self._connection_manager.has_response(device_id, command_type):
                    response = self._connection_manager.get_response(device_id, command_type)
                    logger.info(f"Risposta ricevuta per comando {command_type}")
                    return response

                # Aggiungiamo un tentativo di ping esplicito ogni 3 secondi
                elapsed = time.time() - start_time
                if elapsed > 3 and elapsed % 3 < check_interval:
                    try:
                        self.send_command(device_id, "PING", {"timestamp": time.time(), "waiting_for": command_type})
                        logger.debug(f"Inviato ping durante attesa risposta a {command_type}")
                    except Exception as ping_err:
                        logger.debug(f"Errore ping durante attesa: {ping_err}")

                time.sleep(check_interval)

            logger.warning(f"Timeout nell'attesa della risposta a {command_type} dopo {effective_timeout}s")

            # Verifica se lo scanner è ancora connesso
            is_still_connected = self.is_connected(device_id)
            logger.info(f"Controllo connessione dopo timeout: connesso={is_still_connected}")

            # Prova un'ultima richiesta diretta
            if is_still_connected:
                try:
                    if command_type == "START_SCAN":
                        # Per START_SCAN, verifica lo stato della scansione
                        status_result = self.send_command(device_id, "GET_SCAN_STATUS")
                        if status_result:
                            logger.info("Richiesto stato scansione dopo timeout di START_SCAN")
                    elif command_type == "GET_SCAN_STATUS":
                        # Per GET_SCAN_STATUS, aspetta un po' e riprova
                        time.sleep(0.5)  # Attesa più breve
                        status_result = self.send_command(device_id, "GET_SCAN_STATUS")
                        if status_result:
                            logger.info("Ritentata richiesta stato scansione dopo timeout")
                except Exception as retry_err:
                    logger.debug(f"Errore nel tentativo aggiuntivo: {retry_err}")

            return None
        except Exception as e:
            logger.error(f"Errore nell'attesa della risposta a {command_type}: {e}")
            return None

    def try_autoconnect_last_scanner(self) -> bool:
        """
        Tenta di connettersi automaticamente all'ultimo scanner utilizzato.

        Returns:
            True se la connessione è stata avviata, False altrimenti
        """
        try:
            # Cerca nell'elenco degli scanner recenti
            settings = QSettings()
            last_device_id = settings.value("scanner/last_device_id")

            if not last_device_id:
                logger.info("Nessun ultimo scanner trovato nelle impostazioni")
                return False

            # Verifica se lo scanner è disponibile
            for scanner in self.scanners:
                if scanner.device_id == last_device_id:
                    logger.info(f"Tentativo di connessione automatica a {scanner.name}")
                    return self.connect_to_scanner(scanner.device_id)

            logger.info(f"L'ultimo scanner utilizzato (ID: {last_device_id}) non è disponibile")
            return False
        except Exception as e:
            logger.error(f"Errore nella connessione automatica: {e}")
            return False

    @Slot(Scanner)
    def _on_scanner_discovered(self, scanner: Scanner):
        """Gestisce l'evento di scoperta di un nuovo scanner."""
        logger.info(f"Scanner scoperto: {scanner.name} ({scanner.device_id})")
        self.scanners_changed.emit()

    @Slot(Scanner)
    def _on_scanner_lost(self, scanner: Scanner):
        """Gestisce l'evento di perdita di un scanner."""
        logger.info(f"Scanner perso: {scanner.name} ({scanner.device_id})")

        # Se lo scanner perso era quello selezionato, deselezionalo
        if self._selected_scanner and self._selected_scanner.device_id == scanner.device_id:
            self._selected_scanner = None

        self.scanners_changed.emit()

    @Slot(str)
    def _on_connection_established(self, device_id: str):
        """Gestisce l'evento di connessione stabilita."""
        scanner = self.scanner_manager.get_scanner(device_id)
        if scanner:
            scanner.status = ScannerStatus.CONNECTED
            logger.info(f"Connessione stabilita con {scanner.name}")
            self.scanner_connected.emit(scanner)

            # Salva l'ultimo scanner connesso
            try:
                from PySide6.QtCore import QSettings
                settings = QSettings()
                settings.setValue("scanner/last_device_id", device_id)
            except Exception as e:
                logger.error(f"Errore nel salvataggio dell'ultimo scanner: {e}")
    def get_stream_receiver(self):
        """
        Restituisce il receiver di stream se disponibile.
        Questo metodo può essere usato da componenti che hanno bisogno di accedere
        direttamente al receiver di stream.

        Returns:
            StreamReceiver o None se non disponibile
        """
        # Cerca in MainWindow
        app = QApplication.instance()
        if app:
            for widget in app.topLevelWidgets():
                if isinstance(widget, QMainWindow):
                    if hasattr(widget, 'stream_receiver'):
                        return widget.stream_receiver

        return None
    @Slot(str, str)
    def _on_connection_failed(self, device_id: str, error: str):
        """Gestisce l'evento di fallimento della connessione."""
        scanner = self.scanner_manager.get_scanner(device_id)
        if scanner:
            scanner.status = ScannerStatus.ERROR
            scanner.error_message = error
            logger.error(f"Connessione fallita con {scanner.name}: {error}")
            self.connection_error.emit(device_id, error)

    @Slot(str)
    def _on_connection_closed(self, device_id: str):
        """Gestisce l'evento di chiusura della connessione con riconnessione automatica."""
        scanner = self.scanner_manager.get_scanner(device_id)
        if scanner:
            old_status = scanner.status
            scanner.status = ScannerStatus.DISCONNECTED
            logger.info(f"Connessione chiusa con {scanner.name}")

            # Notifica la disconnessione
            self.scanner_disconnected.emit(scanner)

            # Se lo scanner era connesso o in streaming, prova a riconnettersi automaticamente
            if old_status in (ScannerStatus.CONNECTED, ScannerStatus.STREAMING):
                # Verifica se lo scanner è ancora presente nella lista
                if device_id in [s.device_id for s in self.scanner_manager.scanners]:
                    logger.info(f"Tentativo di riconnessione automatica a {scanner.name}")

                    # Attendi un momento prima di riconnetterti
                    QTimer.singleShot(2000, lambda: self._try_reconnect(device_id))

    def _try_reconnect(self, device_id: str):
        """Tenta di riconnettersi a uno scanner."""
        scanner = self.scanner_manager.get_scanner(device_id)
        if not scanner:
            logger.warning(f"Impossibile riconnettersi: scanner {device_id} non trovato")
            return

        logger.info(f"Riconnessione a {scanner.name}...")

        # Tenta la connessione
        success = self.connect_to_scanner(device_id)

        if success:
            logger.info(f"Riconnessione a {scanner.name} riuscita")
        else:
            logger.warning(f"Riconnessione a {scanner.name} fallita")

            # Riprova dopo un intervallo più lungo
            QTimer.singleShot(5000, lambda: self._try_reconnect(device_id))

    def _load_preferences(self):
        """
        Carica le preferenze dell'utente, come l'ultimo scanner utilizzato.
        """
        try:
            from PySide6.QtCore import QSettings
            settings = QSettings()

            # Carica l'ID dell'ultimo scanner utilizzato
            last_scanner_id = settings.value("scanner/last_device_id", "")
            self._last_connected_scanner_id = last_scanner_id if last_scanner_id else None

            logger.debug(f"Preferenze caricate: ultimo scanner ID={self._last_connected_scanner_id}")
        except Exception as e:
            logger.warning(f"Impossibile caricare le preferenze: {e}")
            self._last_connected_scanner_id = None