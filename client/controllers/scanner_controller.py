#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Controller per la gestione degli scanner UnLook.
"""

import logging
import time
from typing import List, Optional, Callable, Dict, Any

from PySide6.QtCore import QObject, Signal, Slot, Property, QSettings, QTimer

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

    def __init__(self, scanner_manager: ScannerManager):
        super().__init__()
        self._scanner_manager = scanner_manager
        self._connection_manager = ConnectionManager()
        self._selected_scanner: Optional[Scanner] = None

        # Collega i segnali del ScannerManager
        self._scanner_manager.scanner_discovered.connect(self._on_scanner_discovered)
        self._scanner_manager.scanner_lost.connect(self._on_scanner_lost)

        # Collega i segnali del ConnectionManager
        self._connection_manager.connection_established.connect(self._on_connection_established)
        self._connection_manager.connection_failed.connect(self._on_connection_failed)
        self._connection_manager.connection_closed.connect(self._on_connection_closed)

        # Aggiungi un timer per il keep-alive
        self._keepalive_timer = QTimer(self)
        self._keepalive_timer.timeout.connect(self._send_keepalive)
        self._keepalive_timer.start(5000)  # Invia un ping ogni 5 secondi

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
        self._scanner_manager.start_discovery()

    def stop_discovery(self):
        """Ferma la scoperta degli scanner."""
        self._scanner_manager.stop_discovery()

    @Property(list, notify=scanners_changed)
    def scanners(self) -> List[Scanner]:
        """Restituisce la lista degli scanner disponibili."""
        return self._scanner_manager.scanners

    @Slot(str)
    def connect_to_scanner(self, device_id: str) -> bool:
        """
        Stabilisce una connessione con uno scanner specifico.

        Args:
            device_id: ID univoco dello scanner

        Returns:
            True se la connessione è stata avviata, False altrimenti
        """
        scanner = self._scanner_manager.get_scanner(device_id)
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
        scanner = self._scanner_manager.get_scanner(device_id)
        if not scanner:
            logger.error(f"Scanner con ID {device_id} non trovato")
            return False

        # Chiude la connessione
        return self._connection_manager.disconnect(device_id)

    @Slot(str)
    def select_scanner(self, device_id: str) -> bool:
        """
        Seleziona uno scanner come dispositivo corrente.

        Args:
            device_id: ID univoco dello scanner

        Returns:
            True se la selezione è riuscita, False altrimenti
        """
        scanner = self._scanner_manager.get_scanner(device_id)
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
        Versione migliorata per dare priorità allo stato di streaming.
        """
        scanner = self._scanner_manager.get_scanner(device_id)
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
            # Evita creazione non necessaria dell'istanza se esistente
            if hasattr(self, '_connection_manager'):
                connection_manager = self._connection_manager
            else:
                from client.network.connection_manager import ConnectionManager
                connection_manager = ConnectionManager()

            connection_manager_connected = connection_manager.is_connected(device_id)

            # Se c'è una discrepanza tra lo stato memorizzato e quello reale, non aggiorniamo
            # immediatamente lo stato a DISCONNECTED, specialmente se è in streaming
            if scanner_state_connected and not connection_manager_connected:
                logger.warning(
                    f"Rilevata discrepanza: scanner {scanner.device_id} considerato connesso ma connessione non attiva")
                # Non aggiorniamo lo stato immediatamente a DISCONNECTED
        except Exception as e:
            logger.error(f"Errore nel controllo della connessione: {e}")

        # La connessione è valida se uno dei due controlli è positivo
        return scanner_state_connected or connection_manager_connected

    def send_command(self, device_id: str, command_type: str, payload: Dict[str, Any] = None) -> bool:
        """
        Invia un comando allo scanner specificato.

        Args:
            device_id: ID univoco dello scanner
            command_type: Tipo di comando da inviare
            payload: Dati aggiuntivi per il comando (opzionale)

        Returns:
            True se il comando è stato inviato, False altrimenti
        """
        if not self.is_connected(device_id):
            logger.error(f"Impossibile inviare comando: scanner {device_id} non connesso")
            return False

        try:
            return self._connection_manager.send_message(device_id, command_type, payload)
        except Exception as e:
            logger.error(f"Errore nell'invio del comando {command_type}: {e}")
            return False

    def wait_for_response(self, device_id: str, command_type: str, timeout: float = 30.0) -> Optional[Dict[str, Any]]:
        """
        Attende la risposta a un comando inviato.

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
            # Attendi che la risposta sia disponibile
            start_time = time.time()
            check_interval = 0.2  # Controlla ogni 200ms
            while (time.time() - start_time) < timeout:
                if self._connection_manager.has_response(device_id, command_type):
                    response = self._connection_manager.get_response(device_id, command_type)
                    logger.info(f"Risposta ricevuta per comando {command_type}: {response}")
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

            logger.warning(f"Timeout nell'attesa della risposta a {command_type}")

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
                        time.sleep(1.0)
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
        scanner = self._scanner_manager.get_scanner(device_id)
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

    @Slot(str, str)
    def _on_connection_failed(self, device_id: str, error: str):
        """Gestisce l'evento di fallimento della connessione."""
        scanner = self._scanner_manager.get_scanner(device_id)
        if scanner:
            scanner.status = ScannerStatus.ERROR
            scanner.error_message = error
            logger.error(f"Connessione fallita con {scanner.name}: {error}")
            self.connection_error.emit(device_id, error)

    @Slot(str)
    def _on_connection_closed(self, device_id: str):
        """Gestisce l'evento di chiusura della connessione."""
        scanner = self._scanner_manager.get_scanner(device_id)
        if scanner:
            scanner.status = ScannerStatus.DISCONNECTED
            logger.info(f"Connessione chiusa con {scanner.name}")
            self.scanner_disconnected.emit(scanner)