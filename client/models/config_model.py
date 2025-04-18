#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Modello per la gestione delle configurazioni di UnLook.
"""

import json
import logging
import os
from pathlib import Path
from typing import Dict, Any, Optional, List
from enum import Enum, auto
from dataclasses import dataclass, field, asdict

from PySide6.QtCore import QObject, Signal, Slot

logger = logging.getLogger(__name__)


class StreamResolution(Enum):
    """Risoluzioni supportate per lo streaming."""
    LOW = (640, 480)
    MEDIUM = (1280, 720)
    HIGH = (1920, 1080)
    CUSTOM = auto()


class CameraMode(Enum):
    """Modalità di funzionamento della camera."""
    GRAYSCALE = "grayscale"
    COLOR = "color"


@dataclass
class CameraConfig:
    """Configurazione di una singola camera."""
    enabled: bool = True
    resolution: StreamResolution = StreamResolution.MEDIUM
    custom_resolution: tuple = (1280, 720)
    fps: int = 30
    exposure: int = 50  # 0-100
    gain: int = 50  # 0-100
    mode: CameraMode = CameraMode.GRAYSCALE

    # Parametri avanzati
    brightness: int = 50  # 0-100
    contrast: int = 50  # 0-100
    saturation: int = 50  # 0-100 (solo per modalità colore)
    sharpness: int = 50  # 0-100


@dataclass
class DLPConfig:
    """Configurazione del proiettore DLP."""
    enabled: bool = False
    brightness: int = 80  # 0-100
    pattern_type: str = "binary"  # binary, sinusoidal, ecc.
    num_patterns: int = 10


@dataclass
class ToFConfig:
    """Configurazione del sensore Time-of-Flight."""
    enabled: bool = False
    range: int = 2  # metri
    frame_rate: int = 15  # FPS


@dataclass
class ScanConfig:
    """Configurazione per una scansione."""
    name: str = "Nuova scansione"
    resolution: float = 1.0  # mm
    quality: int = 2  # 1-5
    color_capture: bool = False

    # Parametri di scansione 3D
    scan_mode: str = "structured_light"  # structured_light, tof
    scan_area: tuple = (200, 200, 200)  # mm


@dataclass
class NetworkConfig:
    """Configurazione di rete."""
    auto_discovery: bool = True
    discovery_interval: int = 5  # secondi
    connection_timeout: int = 10  # secondi
    stream_buffer_size: int = 5  # frame


@dataclass
class ApplicationConfig:
    """Configurazione dell'applicazione."""
    language: str = "it"
    theme: str = "dark"
    save_path: str = str(Path.home() / "UnLook" / "scans")
    auto_check_updates: bool = True
    show_advanced_options: bool = False


@dataclass
class UnLookConfig:
    """Configurazione complessiva dell'applicazione UnLook."""
    left_camera: CameraConfig = field(default_factory=CameraConfig)
    right_camera: CameraConfig = field(default_factory=CameraConfig)
    dlp: DLPConfig = field(default_factory=DLPConfig)
    tof: ToFConfig = field(default_factory=ToFConfig)
    scan: ScanConfig = field(default_factory=ScanConfig)
    network: NetworkConfig = field(default_factory=NetworkConfig)
    app: ApplicationConfig = field(default_factory=ApplicationConfig)

    # Configurazioni recenti
    recent_scanners: List[Dict[str, str]] = field(default_factory=list)
    recent_scans: List[str] = field(default_factory=list)


class ConfigManager(QObject):
    """
    Gestore delle configurazioni dell'applicazione UnLook.
    Fornisce metodi per caricare e salvare le configurazioni.
    """

    config_changed = Signal(str)  # section_name

    def __init__(self):
        super().__init__()

        # Configurazione predefinita
        self._config = UnLookConfig()

        # Percorso del file di configurazione
        self._config_dir = Path.home() / ".unlook"
        self._config_file = self._config_dir / "config.json"

        # Assicura che la directory di configurazione esista
        self._config_dir.mkdir(parents=True, exist_ok=True)

        # Carica la configurazione
        self.load_config()

    def load_config(self) -> bool:
        """
        Carica la configurazione dal file.

        Returns:
            True se il caricamento è riuscito, False altrimenti
        """
        try:
            if not self._config_file.exists():
                logger.info(f"File di configurazione non trovato, creazione di uno nuovo: {self._config_file}")
                self.save_config()
                return True

            with open(self._config_file, 'r', encoding='utf-8') as f:
                config_dict = json.load(f)

            # Aggiorna la configurazione con i valori caricati
            self._update_config_from_dict(config_dict)

            logger.info(f"Configurazione caricata da: {self._config_file}")
            return True
        except Exception as e:
            logger.error(f"Errore nel caricamento della configurazione: {str(e)}")
            return False

    def save_config(self) -> bool:
        """
        Salva la configurazione nel file.

        Returns:
            True se il salvataggio è riuscito, False altrimenti
        """
        try:
            # Converti la configurazione in un dizionario
            config_dict = self._config_to_dict()

            # Salva il dizionario in formato JSON
            with open(self._config_file, 'w', encoding='utf-8') as f:
                json.dump(config_dict, f, indent=2, ensure_ascii=False)

            logger.info(f"Configurazione salvata in: {self._config_file}")
            return True
        except Exception as e:
            logger.error(f"Errore nel salvataggio della configurazione: {str(e)}")
            return False

    def get_config(self) -> UnLookConfig:
        """
        Restituisce la configurazione corrente.

        Returns:
            Configurazione corrente
        """
        return self._config

    def update_camera_config(self, camera_index: int, config: CameraConfig) -> bool:
        """
        Aggiorna la configurazione di una camera.

        Args:
            camera_index: Indice della camera (0 per sinistra, 1 per destra)
            config: Nuova configurazione

        Returns:
            True se l'aggiornamento è riuscito, False altrimenti
        """
        try:
            if camera_index == 0:
                self._config.left_camera = config
                self.config_changed.emit("left_camera")
            elif camera_index == 1:
                self._config.right_camera = config
                self.config_changed.emit("right_camera")
            else:
                logger.error(f"Indice camera non valido: {camera_index}")
                return False

            return True
        except Exception as e:
            logger.error(f"Errore nell'aggiornamento della configurazione della camera: {str(e)}")
            return False

    def update_dlp_config(self, config: DLPConfig) -> bool:
        """
        Aggiorna la configurazione del proiettore DLP.

        Args:
            config: Nuova configurazione

        Returns:
            True se l'aggiornamento è riuscito, False altrimenti
        """
        try:
            self._config.dlp = config
            self.config_changed.emit("dlp")
            return True
        except Exception as e:
            logger.error(f"Errore nell'aggiornamento della configurazione DLP: {str(e)}")
            return False

    def update_tof_config(self, config: ToFConfig) -> bool:
        """
        Aggiorna la configurazione del sensore ToF.

        Args:
            config: Nuova configurazione

        Returns:
            True se l'aggiornamento è riuscito, False altrimenti
        """
        try:
            self._config.tof = config
            self.config_changed.emit("tof")
            return True
        except Exception as e:
            logger.error(f"Errore nell'aggiornamento della configurazione ToF: {str(e)}")
            return False

    def update_scan_config(self, config: ScanConfig) -> bool:
        """
        Aggiorna la configurazione di scansione.

        Args:
            config: Nuova configurazione

        Returns:
            True se l'aggiornamento è riuscito, False altrimenti
        """
        try:
            self._config.scan = config
            self.config_changed.emit("scan")
            return True
        except Exception as e:
            logger.error(f"Errore nell'aggiornamento della configurazione di scansione: {str(e)}")
            return False

    def update_network_config(self, config: NetworkConfig) -> bool:
        """
        Aggiorna la configurazione di rete.

        Args:
            config: Nuova configurazione

        Returns:
            True se l'aggiornamento è riuscito, False altrimenti
        """
        try:
            self._config.network = config
            self.config_changed.emit("network")
            return True
        except Exception as e:
            logger.error(f"Errore nell'aggiornamento della configurazione di rete: {str(e)}")
            return False

    def update_app_config(self, config: ApplicationConfig) -> bool:
        """
        Aggiorna la configurazione dell'applicazione.

        Args:
            config: Nuova configurazione

        Returns:
            True se l'aggiornamento è riuscito, False altrimenti
        """
        try:
            self._config.app = config
            self.config_changed.emit("app")
            return True
        except Exception as e:
            logger.error(f"Errore nell'aggiornamento della configurazione dell'applicazione: {str(e)}")
            return False

    def add_recent_scanner(self, device_id: str, name: str, ip_address: str) -> bool:
        """
        Aggiunge uno scanner alla lista degli scanner recenti.

        Args:
            device_id: ID del dispositivo
            name: Nome dello scanner
            ip_address: Indirizzo IP dello scanner

        Returns:
            True se l'aggiunta è riuscita, False altrimenti
        """
        try:
            # Verifica se lo scanner è già presente
            for scanner in self._config.recent_scanners:
                if scanner.get("device_id") == device_id:
                    # Aggiorna le informazioni
                    scanner["name"] = name
                    scanner["ip_address"] = ip_address
                    self.config_changed.emit("recent_scanners")
                    return True

            # Aggiungi il nuovo scanner
            self._config.recent_scanners.append({
                "device_id": device_id,
                "name": name,
                "ip_address": ip_address
            })

            # Limita la lista a 10 elementi
            if len(self._config.recent_scanners) > 10:
                self._config.recent_scanners = self._config.recent_scanners[-10:]

            self.config_changed.emit("recent_scanners")
            return True
        except Exception as e:
            logger.error(f"Errore nell'aggiunta dello scanner recente: {str(e)}")
            return False

    def add_recent_scan(self, scan_path: str) -> bool:
        """
        Aggiunge una scansione alla lista delle scansioni recenti.

        Args:
            scan_path: Percorso della scansione

        Returns:
            True se l'aggiunta è riuscita, False altrimenti
        """
        try:
            # Verifica se la scansione è già presente
            if scan_path in self._config.recent_scans:
                # Sposta la scansione in cima alla lista
                self._config.recent_scans.remove(scan_path)

            # Aggiungi la nuova scansione
            self._config.recent_scans.insert(0, scan_path)

            # Limita la lista a 10 elementi
            if len(self._config.recent_scans) > 10:
                self._config.recent_scans = self._config.recent_scans[:10]

            self.config_changed.emit("recent_scans")
            return True
        except Exception as e:
            logger.error(f"Errore nell'aggiunta della scansione recente: {str(e)}")
            return False

    def _config_to_dict(self) -> Dict[str, Any]:
        """
        Converte la configurazione in un dizionario.

        Returns:
            Dizionario rappresentante la configurazione
        """
        # Usa asdict di dataclasses per convertire in dizionario
        config_dict = asdict(self._config)

        # Gestisci le enumerazioni
        config_dict["left_camera"]["resolution"] = self._config.left_camera.resolution.name
        config_dict["right_camera"]["resolution"] = self._config.right_camera.resolution.name
        config_dict["left_camera"]["mode"] = self._config.left_camera.mode.value
        config_dict["right_camera"]["mode"] = self._config.right_camera.mode.value

        return config_dict

    def _update_config_from_dict(self, config_dict: Dict[str, Any]):
        """
        Aggiorna la configurazione da un dizionario.

        Args:
            config_dict: Dizionario contenente la configurazione
        """
        # Aggiorna i campi principali
        for section in ["left_camera", "right_camera", "dlp", "tof", "scan", "network", "app"]:
            if section in config_dict:
                section_dict = config_dict[section]

                # Gestisci le enumerazioni per le camere
                if section in ["left_camera", "right_camera"]:
                    # Converti la risoluzione da stringa a enum
                    if "resolution" in section_dict:
                        resolution_name = section_dict["resolution"]
                        try:
                            if resolution_name != "CUSTOM":
                                section_dict["resolution"] = StreamResolution[resolution_name]
                            else:
                                section_dict["resolution"] = StreamResolution.CUSTOM
                        except (KeyError, ValueError):
                            section_dict["resolution"] = StreamResolution.MEDIUM

                    # Converti la modalità da stringa a enum
                    if "mode" in section_dict:
                        mode_value = section_dict["mode"]
                        try:
                            section_dict["mode"] = CameraMode(mode_value)
                        except ValueError:
                            section_dict["mode"] = CameraMode.GRAYSCALE

                # Aggiorna la sezione
                if section == "left_camera":
                    self._config.left_camera = CameraConfig(**section_dict)
                elif section == "right_camera":
                    self._config.right_camera = CameraConfig(**section_dict)
                elif section == "dlp":
                    self._config.dlp = DLPConfig(**section_dict)
                elif section == "tof":
                    self._config.tof = ToFConfig(**section_dict)
                elif section == "scan":
                    self._config.scan = ScanConfig(**section_dict)
                elif section == "network":
                    self._config.network = NetworkConfig(**section_dict)
                elif section == "app":
                    self._config.app = ApplicationConfig(**section_dict)

        # Aggiorna le liste
        if "recent_scanners" in config_dict:
            self._config.recent_scanners = config_dict["recent_scanners"]

        if "recent_scans" in config_dict:
            self._config.recent_scans = config_dict["recent_scans"]