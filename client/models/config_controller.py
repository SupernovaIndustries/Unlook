#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Controller per la gestione della configurazione del sistema UnLook.
"""

import logging
from typing import Dict, Any, Optional, List, Tuple

from PySide6.QtCore import QObject, Signal, Slot

from client.models.config_model import (
    ConfigManager, CameraConfig, NetworkConfig, ToFConfig,
    DLPConfig, ScanConfig, ApplicationConfig,
    StreamResolution, CameraMode
)
from client.models.scanner_model import Scanner

logger = logging.getLogger(__name__)


class ConfigController(QObject):
    """
    Controller che gestisce le interazioni tra l'interfaccia utente
    e il modello di gestione delle configurazioni.
    """

    # Segnali
    config_updated = Signal(str)  # section_name
    config_applied = Signal(str, str)  # section_name, device_id
    config_error = Signal(str, str)  # section_name, error_message

    def __init__(self, config_manager: ConfigManager):
        super().__init__()
        self._config_manager = config_manager

        # Collega i segnali del ConfigManager
        self._config_manager.config_changed.connect(self._on_config_changed)

    def get_config(self) -> UnLookConfig:
        """
        Restituisce la configurazione corrente.

        Returns:
            Configurazione corrente
        """
        return self._config_manager.get_config()

    def get_camera_config(self, camera_index: int) -> CameraConfig:
        """
        Restituisce la configurazione di una camera.

        Args:
            camera_index: Indice della camera (0 per sinistra, 1 per destra)

        Returns:
            Configurazione della camera
        """
        config = self._config_manager.get_config()
        return config.left_camera if camera_index == 0 else config.right_camera

    def get_dlp_config(self) -> DLPConfig:
        """
        Restituisce la configurazione del proiettore DLP.

        Returns:
            Configurazione del proiettore DLP
        """
        return self._config_manager.get_config().dlp

    def get_tof_config(self) -> ToFConfig:
        """
        Restituisce la configurazione del sensore ToF.

        Returns:
            Configurazione del sensore ToF
        """
        return self._config_manager.get_config().tof

    def get_scan_config(self) -> ScanConfig:
        """
        Restituisce la configurazione di scansione.

        Returns:
            Configurazione di scansione
        """
        return self._config_manager.get_config().scan

    def get_network_config(self) -> NetworkConfig:
        """
        Restituisce la configurazione di rete.

        Returns:
            Configurazione di rete
        """
        return self._config_manager.get_config().network

    def get_app_config(self) -> ApplicationConfig:
        """
        Restituisce la configurazione dell'applicazione.

        Returns:
            Configurazione dell'applicazione
        """
        return self._config_manager.get_config().app

    @Slot(int, CameraConfig)
    def update_camera_config(self, camera_index: int, config: CameraConfig) -> bool:
        """
        Aggiorna la configurazione di una camera.

        Args:
            camera_index: Indice della camera (0 per sinistra, 1 per destra)
            config: Nuova configurazione

        Returns:
            True se l'aggiornamento è riuscito, False altrimenti
        """
        return self._config_manager.update_camera_config(camera_index, config)

    @Slot(DLPConfig)
    def update_dlp_config(self, config: DLPConfig) -> bool:
        """
        Aggiorna la configurazione del proiettore DLP.

        Args:
            config: Nuova configurazione

        Returns:
            True se l'aggiornamento è riuscito, False altrimenti
        """
        return self._config_manager.update_dlp_config(config)

    @Slot(ToFConfig)
    def update_tof_config(self, config: ToFConfig) -> bool:
        """
        Aggiorna la configurazione del sensore ToF.

        Args:
            config: Nuova configurazione

        Returns:
            True se l'aggiornamento è riuscito, False altrimenti
        """
        return self._config_manager.update_tof_config(config)

    @Slot(ScanConfig)
    def update_scan_config(self, config: ScanConfig) -> bool:
        """
        Aggiorna la configurazione di scansione.

        Args:
            config: Nuova configurazione

        Returns:
            True se l'aggiornamento è riuscito, False altrimenti
        """
        return self._config_manager.update_scan_config(config)

    @Slot(NetworkConfig)
    def update_network_config(self, config: NetworkConfig) -> bool:
        """
        Aggiorna la configurazione di rete.

        Args:
            config: Nuova configurazione

        Returns:
            True se l'aggiornamento è riuscito, False altrimenti
        """
        return self._config_manager.update_network_config(config)

    @Slot(ApplicationConfig)
    def update_app_config(self, config: ApplicationConfig) -> bool:
        """
        Aggiorna la configurazione dell'applicazione.

        Args:
            config: Nuova configurazione

        Returns:
            True se l'aggiornamento è riuscito, False altrimenti
        """
        return self._config_manager.update_app_config(config)

    @Slot()
    def save_config(self) -> bool:
        """
        Salva la configurazione.

        Returns:
            True se il salvataggio è riuscito, False altrimenti
        """
        return self._config_manager.save_config()  # Correzione: prima era .save()

    @Slot()
    def load_config(self) -> bool:
        """
        Carica la configurazione.

        Returns:
            True se il caricamento è riuscito, False altrimenti
        """
        return self._config_manager.load_config()

    @Slot(Scanner)
    def add_recent_scanner(self, scanner: Scanner) -> bool:
        """
        Aggiunge uno scanner alla lista degli scanner recenti.

        Args:
            scanner: Scanner da aggiungere

        Returns:
            True se l'aggiunta è riuscita, False altrimenti
        """
        return self._config_manager.add_recent_scanner(
            scanner.device_id,
            scanner.name,
            scanner.ip_address
        )

    @Slot(str)
    def add_recent_scan(self, scan_path: str) -> bool:
        """
        Aggiunge una scansione alla lista delle scansioni recenti.

        Args:
            scan_path: Percorso della scansione

        Returns:
            True se l'aggiunta è riuscita, False altrimenti
        """
        return self._config_manager.add_recent_scan(scan_path)

    @Slot(str, str)
    def apply_config_to_scanner(self, section_name: str, device_id: str) -> bool:
        """
        Applica una configurazione a uno scanner specifico.

        Args:
            section_name: Nome della sezione da applicare (camera, dlp, tof, scan)
            device_id: ID del dispositivo a cui applicare la configurazione

        Returns:
            True se l'applicazione è riuscita, False altrimenti
        """
        # Implementazione dell'invio della configurazione allo scanner
        # (il codice effettivo dipende dal protocollo di comunicazione con lo scanner)
        try:
            logger.info(f"Applicazione della configurazione '{section_name}' allo scanner {device_id}")

            # TODO: Implementare l'invio effettivo della configurazione allo scanner
            # Questo è un segnaposto che simula il successo dell'operazione

            # Emetti il segnale di successo
            self.config_applied.emit(section_name, device_id)
            return True
        except Exception as e:
            logger.error(f"Errore nell'applicazione della configurazione: {str(e)}")
            self.config_error.emit(section_name, str(e))
            return False

    @Slot(str)
    def _on_config_changed(self, section_name: str):
        """
        Gestisce l'evento di modifica della configurazione.

        Args:
            section_name: Nome della sezione modificata
        """
        logger.debug(f"Configurazione modificata: {section_name}")
        self.config_updated.emit(section_name)

    def get_available_resolutions(self) -> List[Tuple[str, Tuple[int, int]]]:
        """
        Restituisce la lista delle risoluzioni disponibili.

        Returns:
            Lista di tuple (nome, dimensioni)
        """
        return [
            ("Bassa (640x480)", StreamResolution.LOW.value),
            ("Media (1280x720)", StreamResolution.MEDIUM.value),
            ("Alta (1920x1080)", StreamResolution.HIGH.value),
            ("Personalizzata", (0, 0))  # Il valore effettivo sarà preso da custom_resolution
        ]

    def get_available_camera_modes(self) -> List[Tuple[str, str]]:
        """
        Restituisce la lista delle modalità camera disponibili.

        Returns:
            Lista di tuple (nome, valore)
        """
        return [
            ("Scala di grigi", CameraMode.GRAYSCALE.value),
            ("Colore", CameraMode.COLOR.value)
        ]