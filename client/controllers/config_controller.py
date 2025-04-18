#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Controller per la gestione della configurazione del sistema UnLook.
"""

import logging
from typing import Dict, Any, Optional

from client.models.config_model import (
    ConfigManager, CameraConfig, NetworkConfig, ToFConfig,
    DLPConfig, ScanConfig, ApplicationConfig
)

logger = logging.getLogger(__name__)


class ConfigController:
    """Controller per la gestione della configurazione."""

    def __init__(self, config_manager: ConfigManager):
        """Inizializza il controller."""
        self._config_manager = config_manager

    def get_camera_config(self, camera_index: int) -> CameraConfig:
        """Restituisce la configurazione della camera specificata."""
        return self._config_manager.get_camera_config(camera_index)

    def update_camera_config(self, camera_index: int, config: CameraConfig) -> None:
        """Aggiorna la configurazione della camera specificata."""
        self._config_manager.update_camera_config(camera_index, config)

    def get_scan_config(self) -> ScanConfig:
        """Restituisce la configurazione di scansione."""
        return self._config_manager.get_scan_config()

    def update_scan_config(self, config: ScanConfig) -> None:
        """Aggiorna la configurazione di scansione."""
        self._config_manager.update_scan_config(config)

    def get_app_config(self) -> ApplicationConfig:
        """Restituisce la configurazione dell'applicazione."""
        return self._config_manager.get_app_config()

    def update_app_config(self, config: ApplicationConfig) -> None:
        """Aggiorna la configurazione dell'applicazione."""
        self._config_manager.update_app_config(config)

    def get_available_resolutions(self) -> list[tuple[str, tuple[int, int]]]:
        """Restituisce le risoluzioni disponibili."""
        return [
            ("Bassa (640x480)", (640, 480)),
            ("Media (1280x720)", (1280, 720)),
            ("Alta (1920x1080)", (1920, 1080)),
            ("Personalizzata", (-1, -1))
        ]

    def get_available_camera_modes(self) -> list[tuple[str, str]]:
        """Restituisce le modalità camera disponibili."""
        return [
            ("Scala di grigi", "grayscale"),
            ("Colore", "color")
        ]

    def save_config(self) -> None:
        """Salva la configurazione su disco."""
        self._config_manager.save()

    def load_config(self) -> None:
        """Carica la configurazione da disco."""
        self._config_manager.load()