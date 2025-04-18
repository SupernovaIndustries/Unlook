#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Modelli per la gestione degli scanner 3D UnLook.
"""

import logging
import time
from enum import Enum
from dataclasses import dataclass
from typing import Dict, List, Optional, Callable
from PySide6.QtCore import QObject, Signal, Slot, QTimer

from client.network.discovery_service import DiscoveryService

logger = logging.getLogger(__name__)


class ScannerStatus(Enum):
    """Stati possibili per uno scanner."""
    DISCONNECTED = 0
    CONNECTING = 1
    CONNECTED = 2
    STREAMING = 3
    ERROR = 4


@dataclass
class ScannerCapabilities:
    """Capacità supportate da uno scanner."""
    dual_camera: bool = False
    color_mode: bool = False
    max_resolution: tuple = (1280, 720)
    supports_tof: bool = False
    supports_dlp: bool = False

    # Parametri regolabili
    exposure_range: tuple = (0, 100)
    fps_range: tuple = (10, 30)


class Scanner(QObject):
    """
    Modello che rappresenta un singolo scanner UnLook.
    """
    status_changed = Signal(ScannerStatus)

    def __init__(self, device_id: str, ip_address: str, port: int = 5000):
        super().__init__()
        self.device_id = device_id
        self.name = f"UnLook-{device_id[-6:]}"
        self.ip_address = ip_address
        self.port = port
        self._status = ScannerStatus.DISCONNECTED
        self.last_seen = time.time()
        self.capabilities = ScannerCapabilities()

        # Statistiche di connessione
        self.ping_time = 0.0
        self.connection_quality = 0.0
        self.error_message = ""

    @property
    def status(self) -> ScannerStatus:
        return self._status

    @status.setter
    def status(self, value: ScannerStatus):
        if value != self._status:
            self._status = value
            self.status_changed.emit(value)
            logger.info(f"Scanner {self.name} status: {value.name}")

    def update_last_seen(self):
        """Aggiorna il timestamp dell'ultimo avvistamento dello scanner."""
        self.last_seen = time.time()

    def __eq__(self, other):
        if not isinstance(other, Scanner):
            return False
        return self.device_id == other.device_id

    def __hash__(self):
        return hash(self.device_id)


class ScannerManager(QObject):
    """
    Gestisce la scoperta e le connessioni agli scanner UnLook.
    """
    scanner_discovered = Signal(Scanner)
    scanner_lost = Signal(Scanner)
    discovery_started = Signal()
    discovery_stopped = Signal()

    def __init__(self):
        super().__init__()
        self._scanners: Dict[str, Scanner] = {}
        self._discovery_service = DiscoveryService()
        self._discovery_service.device_discovered.connect(self._on_device_discovered)

        # Timer per verificare scanner inattivi
        self._cleanup_timer = QTimer()
        self._cleanup_timer.timeout.connect(self._check_inactive_scanners)
        self._cleanup_timer.setInterval(5000)  # Controlla ogni 5 secondi

        # Stato della scoperta
        self._is_discovering = False

    def start_discovery(self):
        """Avvia la scoperta degli scanner UnLook sulla rete."""
        if not self._is_discovering:
            logger.info("Avvio della scoperta degli scanner UnLook")
            self._discovery_service.start()
            self._cleanup_timer.start()
            self._is_discovering = True
            self.discovery_started.emit()

    def stop_discovery(self):
        """Interrompe la scoperta degli scanner."""
        if self._is_discovering:
            logger.info("Interruzione della scoperta degli scanner")
            self._discovery_service.stop()
            self._cleanup_timer.stop()
            self._is_discovering = False
            self.discovery_stopped.emit()

    @property
    def scanners(self) -> List[Scanner]:
        """Restituisce la lista di tutti gli scanner scoperti."""
        return list(self._scanners.values())

    def get_scanner(self, device_id: str) -> Optional[Scanner]:
        """Ottiene uno scanner tramite il suo ID dispositivo."""
        return self._scanners.get(device_id)

    @Slot(str, str, int)
    def _on_device_discovered(self, device_id: str, ip_address: str, port: int):
        """Gestisce l'evento di scoperta di un nuovo dispositivo."""
        if device_id in self._scanners:
            # Aggiorna lo scanner esistente
            scanner = self._scanners[device_id]
            scanner.ip_address = ip_address
            scanner.port = port
            scanner.update_last_seen()
            logger.debug(f"Scanner aggiornato: {scanner.name} a {ip_address}:{port}")
        else:
            # Crea un nuovo scanner
            scanner = Scanner(device_id, ip_address, port)
            self._scanners[device_id] = scanner
            logger.info(f"Nuovo scanner scoperto: {scanner.name} a {ip_address}:{port}")
            self.scanner_discovered.emit(scanner)

    def _check_inactive_scanners(self):
        """Rimuove gli scanner che non sono stati visti per un certo periodo."""
        current_time = time.time()
        inactive_threshold = 15.0  # 15 secondi

        to_remove = []
        for device_id, scanner in self._scanners.items():
            if current_time - scanner.last_seen > inactive_threshold:
                logger.info(f"Scanner {scanner.name} non più disponibile")
                to_remove.append(device_id)

        # Rimuove gli scanner inattivi
        for device_id in to_remove:
            scanner = self._scanners.pop(device_id)
            self.scanner_lost.emit(scanner)