#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Controller per la gestione degli scanner UnLook.
"""

import logging
from typing import List, Optional, Callable

from PySide6.QtCore import QObject, Signal, Slot, Property

# Importa i moduli del progetto in modo che funzionino sia con esecuzione diretta che tramite launcher
try:
    from client.models.scanner_model import Scanner, ScannerManager, ScannerStatus
    from client.network.connection_manager import ConnectionManager
except ImportError:
    # Fallback per esecuzione diretta
    from models.scanner_model import Scanner, ScannerManager, ScannerStatus
    from network.connection_manager import ConnectionManager

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
        """Verifica se un determinato scanner è connesso."""
        scanner = self._scanner_manager.get_scanner(device_id)
        if not scanner:
            return False
        return scanner.status in (ScannerStatus.CONNECTED, ScannerStatus.STREAMING)

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