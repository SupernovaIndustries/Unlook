#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
UnLook Scanner Server - Applicazione server per il Raspberry Pi
Versione ultra-ottimizzata con latenza ridotta e stabilità migliorata.
v2.0.0 (Aprile 2025)
"""

import os
import sys
import time
import json
import logging
import socket
import uuid
import signal
import threading
import argparse
import gc  # Per garbage collection manuale
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Set, Union
from datetime import datetime

# Configurazione percorsi
PROJECT_DIR = Path(__file__).parent.absolute()
LOG_DIR = PROJECT_DIR / "logs"
CONFIG_DIR = PROJECT_DIR / "config"
CAPTURE_DIR = PROJECT_DIR / "captures"

# Assicura che le directory esistano
LOG_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
CAPTURE_DIR.mkdir(parents=True, exist_ok=True)

# Configurazione logging ottimizzata
log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
log_file = LOG_DIR / f'server_{datetime.now().strftime("%Y%m%d")}.log'

file_handler = logging.FileHandler(log_file, mode='a')
file_handler.setFormatter(log_formatter)
file_handler.setLevel(logging.INFO)

console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
console_handler.setLevel(logging.INFO)

logger = logging.getLogger("UnLookServer")
logger.setLevel(logging.INFO)
logger.addHandler(file_handler)
logger.addHandler(console_handler)

# Riduzione log di terze parti
logging.getLogger("picamera2").setLevel(logging.WARNING)
logging.getLogger("zmq").setLevel(logging.WARNING)

# Versione server
SERVER_VERSION = "2.0.0"
logger.info(f"UnLook Scanner Server v{SERVER_VERSION} in avvio...")

# Verifica importazioni in parallelo per velocizzare l'avvio
import_errors = []
import_threads = []
import_lock = threading.Lock()


def import_module(module_name, package=None):
    try:
        if package:
            __import__(f"{package}.{module_name}")
        else:
            __import__(module_name)
        return True
    except ImportError as e:
        with import_lock:
            import_errors.append((module_name, str(e)))
        return False


# Lista moduli da importare
modules_to_import = [
    ("zmq", None),
    ("numpy", None),
    ("picamera2", None),
    ("cv2", None),
]

# Avvia thread di importazione
for module, package in modules_to_import:
    thread = threading.Thread(target=import_module, args=(module, package))
    thread.daemon = True
    thread.start()
    import_threads.append(thread)

# Attendi il completamento di tutti i thread di importazione
for thread in import_threads:
    thread.join()

# Verifica se ci sono stati errori di importazione
if import_errors:
    for module, error in import_errors:
        logger.error(f"Dipendenza mancante: {module} - {error}")
    logger.error("Installa le dipendenze mancanti con: pip install pyzmq numpy picamera2 opencv-python")
    sys.exit(1)

# Ora possiamo importare i moduli garantendo che siano stati caricati
import zmq
import numpy as np
from picamera2 import Picamera2
import cv2

# Ottimizzazioni OpenCV per prestazioni
if hasattr(cv2, 'setUseOptimized'):
    cv2.setUseOptimized(True)
    logger.info(f"OpenCV ottimizzazioni hardware: {cv2.useOptimized()}")

# Opzioni ZMQ
if hasattr(zmq, 'IMMEDIATE'):
    zmq.IMMEDIATE = 1  # Assicura che i messaggi vengano inviati immediatamente

# Imposta LINGER a 0 globalmente se possibile
if hasattr(zmq, 'LINGER'):
    zmq.LINGER = 0  # Non attende flush alla chiusura


# Classe di utilità per le statistiche
class PerformanceStats:
    """Classe per il monitoraggio delle prestazioni."""

    def __init__(self, window_size=50):
        self.window_size = window_size
        self.reset()

    def reset(self):
        self.times = []
        self.values = {}
        self.start_time = time.time()
        self.frame_count = 0

    def add_frame(self, **kwargs):
        """Aggiunge statistiche per un frame."""
        self.frame_count += 1
        current_time = time.time()
        self.times.append(current_time)

        # Mantieni solo ultimi N timestamp
        if len(self.times) > self.window_size:
            self.times.pop(0)

        # Aggiorna valori
        for key, value in kwargs.items():
            if key not in self.values:
                self.values[key] = []

            self.values[key].append(value)

            # Mantieni solo ultimi N valori
            if len(self.values[key]) > self.window_size:
                self.values[key].pop(0)

    def get_fps(self):
        """Calcola FPS dagli ultimi N frame."""
        if len(self.times) < 2:
            return 0

        elapsed = self.times[-1] - self.times[0]
        if elapsed <= 0:
            return 0

        return (len(self.times) - 1) / elapsed

    def get_average(self, key):
        """Calcola media per una metrica."""
        if key not in self.values or not self.values[key]:
            return 0

        return sum(self.values[key]) / len(self.values[key])

    def get_max(self, key):
        """Calcola valore massimo per una metrica."""
        if key not in self.values or not self.values[key]:
            return 0

        return max(self.values[key])

    def get_summary(self):
        """Restituisce un sommario delle statistiche."""
        result = {
            "fps": self.get_fps(),
            "frame_count": self.frame_count,
            "elapsed": time.time() - self.start_time
        }

        # Aggiungi statistiche per ogni metrica
        for key in self.values:
            result[f"avg_{key}"] = self.get_average(key)
            result[f"max_{key}"] = self.get_max(key)

        return result


class UnLookServer:
    """
    Server principale che gestisce le camere e le connessioni con i client.
    Versione ottimizzata per ridurre la latenza e migliorare il controllo di flusso.
    """

    def __init__(self, config_path: str = None):
        """
        Inizializza il server UnLook.

        Args:
            config_path: Percorso del file di configurazione JSON
        """
        self.running = False
        self.device_id = self._generate_device_id()
        self.device_name = f"UnLook-{self.device_id[-6:]}"

        # Carica la configurazione
        self.config = self._load_config(config_path)

        # Inizializza le camere
        self.cameras = []
        self._init_cameras()

        # Inizializza lo stato
        self.state = {
            "status": "idle",
            "cameras_connected": len(self.cameras),
            "clients_connected": 0,
            "streaming": False,
            "uptime": 0.0,
            "start_time": time.time(),
            "version": SERVER_VERSION
        }

        # Inizializza i socket di comunicazione
        self.broadcast_socket = None
        self.context = zmq.Context()
        self.command_socket = self.context.socket(zmq.REP)  # Socket per i comandi (REP)
        self.stream_socket = None  # Inizializzato in start() per ottimizzazione

        # Inizializza i thread
        self.broadcast_thread = None
        self.command_thread = None
        self.stream_threads = []

        # Controllo di flusso
        self._frame_interval = 1.0 / self.config["stream"].get("max_fps", 30)
        self._dynamic_interval = self.config["server"].get("dynamic_fps", True)
        self._last_frame_time = {0: 0, 1: 0}  # Per entrambe le camere
        self._streaming_start_time = 0
        self._frame_count = {0: 0, 1: 0}  # Per entrambe le camere

        # Informazioni sul client
        self.client_connected = False
        self.client_ip = None
        self._last_client_activity = 0
        self._client_lag_reports = {}  # Camera_idx -> lista di lag reports

        # Parametri di qualità dell'immagine ottimizzati per bassa latenza
        self._jpeg_quality = self.config["stream"].get("quality", 90)

        # Configurazione avanzata ZMQ
        self._zmq_hwm = self.config["server"].get("zmq_hwm", 1)  # Default a 1 per bassa latenza

        # Statistiche per ogni camera
        self._stats = {}

        # Bandwidth monitoring
        self._bytes_sent = 0
        self._last_bytes_check = time.time()
        self._bandwidth_estimates = []  # in bytes/sec

        logger.info(f"Server UnLook inizializzato con ID: {self.device_id}")
        logger.info(f"Configurazione: max_fps={1.0 / self._frame_interval:.1f}, quality={self._jpeg_quality}")

    def _generate_device_id(self) -> str:
        """
        Genera un ID univoco per il dispositivo o lo recupera se già esistente.

        Returns:
            ID univoco del dispositivo
        """
        # Percorso del file ID
        id_file = CONFIG_DIR / 'device_id'

        # Se il file esiste, leggi l'ID
        if id_file.exists():
            with open(id_file, 'r') as f:
                device_id = f.read().strip()
                logger.info(f"ID dispositivo caricato: {device_id}")
                return device_id

        # Altrimenti, genera un nuovo ID
        device_id = str(uuid.uuid4())

        # Salva l'ID nel file
        with open(id_file, 'w') as f:
            f.write(device_id)

        logger.info(f"Nuovo ID dispositivo generato: {device_id}")
        return device_id

    def _load_config(self, config_path: Optional[str]) -> Dict[str, Any]:
        """
        Carica la configurazione dal file JSON con valori predefiniti ottimizzati.

        Args:
            config_path: Percorso del file di configurazione

        Returns:
            Dizionario di configurazione
        """
        # Configurazione predefinita ottimizzata
        default_config = {
            "server": {
                "discovery_port": 5678,
                "command_port": 5680,
                "stream_port": 5681,
                "broadcast_interval": 1.0,
                "frame_interval": 0.025,  # 40fps nominali (25ms)
                "dynamic_fps": True,
                "zmq_hwm": 1,  # Buffer ridotto per bassa latenza
                "connection_timeout": 10.0  # Secondi di inattività per considerare un client disconnesso
            },
            "camera": {
                "left": {
                    "enabled": True,
                    "resolution": [1280, 720],
                    "framerate": 40,
                    "format": "RGB888",
                    "mode": "color",  # Default a colori
                    "exposure": 50,  # 0-100
                    "gain": 50,  # 0-100
                    "brightness": 50,  # 0-100
                    "contrast": 50,  # 0-100
                    "saturation": 50,  # 0-100
                    "sharpness": 50  # 0-100
                },
                "right": {
                    "enabled": True,
                    "resolution": [1280, 720],
                    "framerate": 40,
                    "format": "RGB888",
                    "mode": "color",  # Default a colori
                    "exposure": 50,  # 0-100
                    "gain": 50,  # 0-100
                    "brightness": 50,  # 0-100
                    "contrast": 50,  # 0-100
                    "saturation": 50,  # 0-100
                    "sharpness": 50  # 0-100
                }
            },
            "stream": {
                "format": "jpeg",
                "quality": 85,  # JPEG 85 è un buon compromesso qualità/prestazioni
                "max_fps": 40,
                "min_fps": 20,
                "dynamic_quality": True,  # Regolazione dinamica della qualità
                "min_quality": 70,
                "max_quality": 95
            },
            "advanced": {
                "log_level": "INFO",
                "zmq_immediate": True,  # Evita buffering per messaggi rapidi
                "parallel_encode": True,  # Encoding parallelo se disponibile
                "memory_profile": "minimal",  # minimal, balanced, performance
                "frame_skip": True  # Abilita il salto frame in caso di lag
            }
        }

        # Se non è stato specificato un percorso, usa la configurazione predefinita
        if not config_path:
            # Controlla se esiste un file di configurazione nella directory config
            default_config_path = CONFIG_DIR / 'config.json'
            if default_config_path.exists():
                config_path = str(default_config_path)
            else:
                logger.info("Utilizzo della configurazione predefinita ottimizzata")
                # Salva la configurazione predefinita per usi futuri
                with open(default_config_path, 'w') as f:
                    json.dump(default_config, f, indent=2)
                return default_config

        # Carica la configurazione dal file
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
                logger.info(f"Configurazione caricata da: {config_path}")

                # Aggiorna ricorsivamente per assicurare che tutti i valori siano presenti
                self._update_config_recursive(default_config, config)

                # Salva la configurazione aggiornata
                with open(config_path, 'w') as f:
                    json.dump(default_config, f, indent=2)

                return default_config
        except Exception as e:
            logger.error(f"Errore nel caricamento della configurazione: {e}")
            logger.info("Utilizzo della configurazione predefinita")
            return default_config

    def _update_config_recursive(self, target: Dict[str, Any], source: Dict[str, Any]) -> None:
        """
        Aggiorna ricorsivamente la configurazione target con i valori dalla sorgente.
        A differenza di _update_dict_recursive, questa mantiene la struttura target
        e aggiunge solo i valori presenti in source.

        Args:
            target: Dizionario target da aggiornare
            source: Dizionario sorgente con i nuovi valori
        """
        for key, value in source.items():
            if key in target and isinstance(target[key], dict) and isinstance(value, dict):
                self._update_config_recursive(target[key], value)
            elif key in target:
                target[key] = value

    def _init_cameras(self):
        """
        Inizializza le camere PiCamera2.
        Versione ottimizzata con rilevamento capabilities e gestione errori.
        """
        try:
            # Log dell'avvio inizializzazione
            logger.info("Inizializzazione camere in corso...")

            # Ottieni la lista delle camere disponibili
            cam_list = Picamera2.global_camera_info()
            logger.info(f"Camere disponibili: {len(cam_list)}")

            # Log delle caratteristiche delle camere
            for i, cam_info in enumerate(cam_list):
                logger.info(f"Camera {i}: {cam_info.get('model', 'Sconosciuto')}")

                # Mostra capabilities se disponibili
                if 'capabilities' in cam_info:
                    caps = cam_info['capabilities']
                    for cap, val in caps.items():
                        if isinstance(val, (list, tuple)) and len(val) < 10:
                            logger.info(f"    {cap}: {val}")
                        elif isinstance(val, (list, tuple)):
                            logger.info(f"    {cap}: [{len(val)} elementi]")
                        else:
                            logger.info(f"    {cap}: {val}")

            # Se non ci sono camere, esci con un messaggio chiaro
            if not cam_list:
                logger.error("Nessuna camera trovata! Verifica connessioni hardware e permessi.")
                return

            # Inizializza tutte le camere dichiarate in config
            camera_configs = [
                {"index": 0, "name": "left", "config": self.config["camera"]["left"]},
                {"index": 1, "name": "right", "config": self.config["camera"]["right"]}
            ]

            for cam_def in camera_configs:
                # Verifica se questa camera è abilitata
                if not cam_def["config"]["enabled"]:
                    logger.info(f"Camera {cam_def['name']} disabilitata da configurazione, saltata.")
                    continue

                # Verifica se l'indice è valido
                if cam_def["index"] >= len(cam_list):
                    logger.warning(f"Camera {cam_def['name']} (index={cam_def['index']}) "
                                   f"non disponibile: solo {len(cam_list)} camere trovate.")
                    continue

                # Inizializza la camera con try-except specifico
                try:
                    logger.info(f"Inizializzazione camera {cam_def['name']}...")

                    # Ottieni camera
                    camera = Picamera2(cam_def["index"])

                    # Configura la camera
                    cam_config = cam_def["config"]

                    # Determina formato in base a modalità
                    format_str = cam_config.get("format", "RGB888")
                    if "mode" in cam_config:
                        if cam_config["mode"] == "grayscale":
                            format_str = "GREY"
                            logger.info(f"Camera {cam_def['name']} in modalità scala di grigi")
                        else:
                            format_str = "RGB888"
                            logger.info(f"Camera {cam_def['name']} in modalità colore")

                    # Configura la camera
                    resolution = tuple(cam_config["resolution"])
                    framerate = cam_config.get("framerate", 40)

                    # Crea configurazione base
                    cam_config_obj = camera.create_video_configuration(
                        main={"size": resolution, "format": format_str},
                        controls={"FrameRate": framerate}
                    )

                    # Configura e avvia
                    camera.configure(cam_config_obj)
                    camera.start()

                    # Aggiungi alle camere attive
                    self.cameras.append({
                        "index": cam_def["index"],
                        "camera": camera,
                        "name": cam_def["name"],
                        "format": format_str,
                        "resolution": resolution,
                        "framerate": framerate
                    })

                    logger.info(f"Camera {cam_def['name']} inizializzata: "
                                f"{resolution[0]}x{resolution[1]}@{framerate}fps, formato={format_str}")

                except Exception as e:
                    logger.error(f"Errore nell'inizializzazione della camera {cam_def['name']}: {e}")

                    # Fornisci ulteriori info di debug
                    if "Permission denied" in str(e):
                        logger.error("Permesso negato: verifica che l'utente abbia accesso alle camere.")
                    elif "Device or resource busy" in str(e):
                        logger.error("Dispositivo occupato: la camera potrebbe essere in uso da un altro processo.")
                    elif "No such file or directory" in str(e):
                        logger.error("File o directory non trovata: verifica che il dispositivo camera esista.")

            logger.info(f"Camere inizializzate: {len(self.cameras)}/{len(camera_configs)}")

            # Se nessuna camera è stata inizializzata, avvisa ma continua
            if not self.cameras:
                logger.warning("Nessuna camera inizializzata! Il server funzionerà con funzionalità limitate.")

        except Exception as e:
            logger.error(f"Errore generale nell'inizializzazione delle camere: {e}")

    def start(self):
        """
        Avvia il server con configurazione ottimizzata per bassa latenza.
        """
        if self.running:
            logger.warning("Il server è già in esecuzione")
            return

        logger.info("Avvio del server UnLook")

        try:
            # Inizializza il timestamp dell'ultima attività client
            self._last_client_activity = 0
            self.client_connected = False
            self.client_ip = None

            # Avvia le camere se non già avviate
            for cam_info in self.cameras:
                if not cam_info["camera"].started:
                    cam_info["camera"].start()
                    logger.info(f"Camera {cam_info['name']} avviata")

            # Apri i socket ottimizzati per bassa latenza
            command_port = self.config["server"]["command_port"]
            stream_port = self.config["server"]["stream_port"]

            # Configura socket comandi
            self.command_socket.setsockopt(zmq.LINGER, 0)  # Non attendere flush alla chiusura
            self.command_socket.setsockopt(zmq.RCVTIMEO, 1000)  # Timeout di 1 secondo
            self.command_socket.bind(f"tcp://*:{command_port}")

            # Crea e configura socket di streaming (PUB)
            self.stream_socket = self.context.socket(zmq.PUB)
            self.stream_socket.setsockopt(zmq.LINGER, 0)
            self.stream_socket.setsockopt(zmq.SNDHWM, self._zmq_hwm)  # Ottimizzato per bassa latenza

            # Configura IMMEDIATE per risposta rapida
            if hasattr(zmq, 'IMMEDIATE'):
                self.stream_socket.setsockopt(zmq.IMMEDIATE, 1)

            # Configura TCP_NODELAY per ridurre latenza
            self.stream_socket.setsockopt(zmq.TCP_NODELAY, 1)

            # Configura routing/backlog
            self.stream_socket.setsockopt(zmq.BACKLOG, 4)  # Backlog piccolo per connessioni rapide

            # Bind socket
            self.stream_socket.bind(f"tcp://*:{stream_port}")

            logger.info(f"Socket di comando in ascolto su porta {command_port}")
            logger.info(f"Socket di streaming in ascolto su porta {stream_port}")
            logger.info(f"Configurazione ZMQ: HWM={self._zmq_hwm}, LINGER=0, TCP_NODELAY=1")

            # Avvia il servizio di broadcast
            self._start_broadcast_service()

            # Avvia il loop di ricezione comandi
            self._start_command_handler()

            # Avvia il timer di controllo attività client
            self._activity_check_timer = threading.Timer(5.0, self._check_client_activity_loop)
            self._activity_check_timer.daemon = True
            self._activity_check_timer.start()

            # Imposta lo stato in esecuzione
            self.running = True
            self.state["status"] = "running"

            # Carica parametri di controllo di flusso e streaming
            self._frame_interval = max(0.01, self.config["server"].get("frame_interval", 0.025))
            self._dynamic_interval = self.config["server"].get("dynamic_fps", True)
            self._jpeg_quality = self.config["stream"].get("quality", 85)

            # Assicurati che il quality sia limitato tra 70 e 95 per un buon rapporto latenza/qualità
            min_quality = self.config["stream"].get("min_quality", 70)
            max_quality = self.config["stream"].get("max_quality", 95)
            self._jpeg_quality = max(min_quality, min(max_quality, self._jpeg_quality))

            # Inizializza statistiche per ogni camera
            for cam_info in self.cameras:
                self._stats[cam_info["index"]] = PerformanceStats(window_size=100)

            logger.info("Server UnLook avviato con successo")
            logger.info(
                f"Controllo di flusso: intervallo={self._frame_interval * 1000:.1f}ms ({1.0 / self._frame_interval:.1f}FPS)")
            logger.info(f"Qualità JPEG: {self._jpeg_quality} (range {min_quality}-{max_quality})")

            # Eseguire garbage collection manuale per ottimizzare la memoria all'inizio
            gc.collect()

        except Exception as e:
            logger.error(f"Errore nell'avvio del server: {e}")
            self.stop()

    def stop(self):
        """
        Ferma il server in modo sicuro e pulito.
        """
        if not self.running:
            return

        logger.info("Arresto del server UnLook...")

        # Imposta lo stato di arresto
        self.running = False
        self.state["status"] = "stopping"

        # Ferma lo streaming
        if self.state["streaming"]:
            self.stop_streaming()

        # Ferma il servizio di broadcast
        if self.broadcast_thread and self.broadcast_thread.is_alive():
            logger.info("Arresto del servizio di broadcast...")
            if self.broadcast_socket:
                try:
                    self.broadcast_socket.close()
                except:
                    pass

        # Ferma il timer di controllo attività
        if hasattr(self, '_activity_check_timer'):
            logger.info("Arresto del timer di controllo attività...")
            self._activity_check_timer.cancel()

        # Chiudi i socket ZeroMQ in modo sicuro
        logger.info("Chiusura dei socket...")
        try:
            if hasattr(self, 'command_socket') and self.command_socket:
                self.command_socket.close()

            if hasattr(self, 'stream_socket') and self.stream_socket:
                self.stream_socket.close()

            if hasattr(self, 'context') and self.context:
                self.context.term()
        except Exception as e:
            logger.error(f"Errore nella chiusura dei socket: {e}")

        # Ferma le camere
        for cam_info in self.cameras:
            logger.info(f"Arresto della camera {cam_info['name']}...")
            try:
                cam_info["camera"].stop()
            except Exception as e:
                logger.error(f"Errore nell'arresto della camera {cam_info['name']}: {e}")

        # Stampa statistiche finali
        logger.info("Statistiche finali:")
        uptime = time.time() - self.state["start_time"]
        logger.info(f"Uptime: {uptime:.1f} secondi")

        for cam_idx, stats in self._stats.items():
            summary = stats.get_summary()
            logger.info(f"Camera {cam_idx}: {summary['frame_count']} frames, "
                        f"media: {summary['fps']:.1f} FPS")

        logger.info("Server UnLook arrestato con successo")

        # Eseguire garbage collection per liberare le risorse
        gc.collect()

    def _start_broadcast_service(self):
        """
        Avvia il servizio di broadcast ottimizzato per permettere ai client di trovare il server.
        """
        logger.info("Avvio del servizio di broadcast...")

        # Crea un socket UDP per il broadcast
        self.broadcast_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.broadcast_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.broadcast_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        # Imposta timeout basso
        self.broadcast_socket.settimeout(0.5)

        # Associa a tutte le interfacce
        try:
            # Usa una porta casuale per l'invio
            self.broadcast_socket.bind(('', 0))
            _, port = self.broadcast_socket.getsockname()
            logger.info(f"Socket di broadcast associato alla porta {port}")
        except Exception as e:
            logger.error(f"Errore nell'associazione del socket di broadcast: {e}")

        # Avvia il thread di broadcast
        self.broadcast_thread = threading.Thread(target=self._broadcast_loop)
        self.broadcast_thread.daemon = True
        self.broadcast_thread.start()

        logger.info("Servizio di broadcast avviato")

    def _get_local_ip(self) -> str:
        """
        Ottiene l'indirizzo IP locale principale.
        Versione migliorata con cache e fallback.
        """
        # Verifica se l'IP è già in cache
        if hasattr(self, '_cached_local_ip'):
            return self._cached_local_ip

        local_ip = None

        # Prova prima con il metodo socket (più affidabile)
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.1)  # Timeout breve
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
        except:
            pass

        # Fallback con hostname se il primo metodo fallisce
        if not local_ip:
            try:
                local_ip = socket.gethostbyname(socket.gethostname())
                # Verifica che non sia localhost
                if local_ip.startswith("127."):
                    local_ip = None
            except:
                pass

        # Ulteriore fallback con tutti gli IP
        if not local_ip:
            try:
                for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
                    if not ip.startswith("127."):
                        local_ip = ip
                        break
            except:
                pass

        # Ultimo fallback a localhost
        if not local_ip:
            local_ip = "127.0.0.1"
            logger.warning("Impossibile ottenere IP locale, utilizzo localhost")

        # Cache l'IP per future chiamate
        self._cached_local_ip = local_ip
        logger.info(f"IP locale determinato: {local_ip}")

        return local_ip

    def _broadcast_loop(self):
        """
        Loop principale per il servizio di broadcast.
        Versione ottimizzata per ridurre il carico di rete.
        """
        discovery_port = self.config["server"]["discovery_port"]
        broadcast_interval = self.config["server"]["broadcast_interval"]
        broadcast_address = "255.255.255.255"  # Indirizzo di broadcast

        # Ottieni l'indirizzo IP locale
        local_ip = self._get_local_ip()

        logger.info(f"Loop di broadcast avviato (indirizzo: {broadcast_address})")
        logger.info(f"Inviando sulla porta discovery: {discovery_port}")
        logger.info(f"Indirizzo IP locale: {local_ip}")
        logger.info(f"Intervallo di broadcast: {broadcast_interval} secondi")

        msg_count = 0

        # Crea un messaggio di base che viene riutilizzato
        base_announce = {
            "type": "UNLOOK_ANNOUNCE",
            "device_id": self.device_id,
            "name": self.device_name,
            "version": SERVER_VERSION,
            "cameras": len(self.cameras),
            "ip_address": local_ip,
            "port": self.config["server"]["command_port"],
        }

        try:
            while self.running:
                try:
                    # Aggiorna le capabilities dinamicamente
                    capabilities = {
                        "dual_camera": len(self.cameras) > 1,
                        "color_mode": True,
                        "tof": False,
                        "dlp": False
                    }

                    # Aggiorna il messaggio base
                    announce_msg = base_announce.copy()
                    announce_msg["capabilities"] = capabilities
                    announce_msg["timestamp"] = time.time()

                    # Converti il messaggio in JSON e poi in bytes
                    message = json.dumps(announce_msg).encode('utf-8')

                    # Invia il messaggio in broadcast
                    try:
                        self.broadcast_socket.sendto(message, (broadcast_address, discovery_port))
                    except Exception as e:
                        if self.running:  # Solo log se ancora in esecuzione
                            logger.debug(f"Errore nell'invio broadcast: {e}")

                    msg_count += 1
                    if msg_count % 10 == 0:  # Log ogni 10 messaggi
                        logger.debug(f"Messaggio di broadcast #{msg_count} inviato")

                    # Attendi prima del prossimo invio
                    for _ in range(int(broadcast_interval * 10)):  # Dividi in piccoli sleep per reattività
                        if not self.running:
                            break
                        time.sleep(0.1)

                except Exception as e:
                    if self.running:  # Solo log se ancora in esecuzione
                        logger.error(f"Errore nel loop di broadcast: {e}")

                    # Pausa più lunga in caso di errore
                    time.sleep(1.0)

        except Exception as e:
            if self.running:  # Solo log se ancora in esecuzione
                logger.error(f"Errore fatale nel loop di broadcast: {e}")
        finally:
            logger.info("Loop di broadcast terminato")

    def _start_command_handler(self):
        """
        Avvia il gestore dei comandi in un thread separato.
        """
        # Assicurati che running sia True prima di avviare il thread
        self.running = True

        # Crea e avvia il thread
        self.command_thread = threading.Thread(target=self._command_loop)
        self.command_thread.daemon = True
        self.command_thread.start()

        # Verifica che il thread sia stato avviato correttamente
        if self.command_thread.is_alive():
            logger.info("Handler dei comandi avviato")
        else:
            logger.error("Impossibile avviare l'handler dei comandi!")

    def _command_loop(self):
        """
        Loop principale per la gestione dei comandi dai client.
        Versione ottimizzata con poller e gestione errori migliorata.
        """
        logger.info("Command loop avviato")

        try:
            while self.running:
                try:
                    # Attendi un comando - questo blocca finché non arriva un messaggio o il server si ferma
                    poller = zmq.Poller()
                    poller.register(self.command_socket, zmq.POLLIN)

                    socks = dict(poller.poll(1000))  # 1 secondo di timeout

                    if self.command_socket in socks and socks[self.command_socket] == zmq.POLLIN:
                        # Ricezione del messaggio
                        message_data = self.command_socket.recv()

                        # Aggiorna timestamp attività client
                        self._last_client_activity = time.time()

                        # Registra indirizzo client se disponibile
                        try:
                            client_ip = self.command_socket.get(zmq.LAST_ENDPOINT)
                            if client_ip and not self.client_connected:
                                self.client_ip = client_ip
                                self.client_connected = True
                                logger.info(f"Client connesso: {client_ip}")
                                self.state["clients_connected"] = 1
                        except:
                            pass

                        # Decodifica il messaggio
                        try:
                            message = json.loads(message_data.decode('utf-8'))
                            command_type = message.get('type', '')
                        except json.JSONDecodeError:
                            # Messaggio non valido
                            command_type = "INVALID"
                            message = {}

                        # Log del comando (solo se non è PING per ridurre spam)
                        if command_type != "PING":
                            logger.info(f"Comando ricevuto: {command_type}")

                        # Processa il comando
                        response = self._process_command(message)

                        # Invia la risposta
                        try:
                            self.command_socket.send_json(response)
                            if command_type != "PING":
                                logger.debug(f"Risposta al comando {command_type} inviata")
                        except Exception as e:
                            logger.error(f"Errore nell'invio della risposta: {e}")

                except zmq.ZMQError as e:
                    if e.errno == zmq.ETERM:
                        # Il contesto è stato terminato
                        logger.info("Contesto ZMQ terminato, uscita dal command loop")
                        break

                    if self.running:  # Solo log se ancora in esecuzione
                        logger.error(f"Errore ZMQ nel command loop: {e}")
                except Exception as e:
                    if self.running:  # Solo log se ancora in esecuzione
                        logger.error(f"Errore nel command loop: {e}")

        except Exception as e:
            if self.running:  # Solo log se ancora in esecuzione
                logger.error(f"Errore fatale nel command loop: {e}")
        finally:
            logger.info("Command loop terminato")

    def _process_command(self, command: Dict[str, Any]) -> Dict[str, Any]:
        """
        Processa un comando ricevuto da un client.
        Versione migliorata con supporto parametri di streaming avanzati.

        Args:
            command: Dizionario rappresentante il comando

        Returns:
            Dizionario di risposta
        """
        command_type = command.get('type', '')

        # Non loggare PING per ridurre spam
        if command_type != "PING":
            logger.debug(f"Elaborazione comando: {command_type}")

        # Prepara una risposta base
        response = {
            "status": "ok",
            "type": f"{command_type}_response",
            "timestamp": time.time()
        }

        try:
            if command_type == 'PING':
                # Comando ping
                if 'lag_report' in command and isinstance(command['lag_report'], dict):
                    # Client riporta lag per camera
                    for cam_idx_str, lag_ms in command['lag_report'].items():
                        try:
                            cam_idx = int(cam_idx_str)

                            # Aggiungi lag report
                            if cam_idx not in self._client_lag_reports:
                                self._client_lag_reports[cam_idx] = []

                            lag_reports = self._client_lag_reports[cam_idx]
                            lag_reports.append(lag_ms)

                            # Mantieni solo ultimi 10 report
                            if len(lag_reports) > 10:
                                lag_reports.pop(0)
                        except:
                            pass

                # Aggiungi timestamp preciso
                response['timestamp'] = time.time()

                # Aggiungi statistiche FPS per ogni camera
                response['fps'] = {}
                for cam_idx, stats in self._stats.items():
                    response['fps'][str(cam_idx)] = stats.get_fps()

            elif command_type == 'GET_STATUS':
                # Aggiorna lo stato
                self.state['uptime'] = time.time() - self.state['start_time']

                # Aggiungi statistiche avanzate
                self.state['stats'] = {}
                for cam_idx, stats in self._stats.items():
                    self.state['stats'][str(cam_idx)] = stats.get_summary()

                # Aggiungi stato hardware CPU/memoria
                try:
                    import psutil
                    self.state['hardware'] = {
                        'cpu_percent': psutil.cpu_percent(),
                        'memory_percent': psutil.virtual_memory().percent,
                        'cpu_temp': self._get_cpu_temperature()
                    }
                except:
                    pass

                # Aggiungi lo stato alla risposta
                response['state'] = self.state

            elif command_type == 'START_STREAM':
                # Avvia lo streaming con supporto parametri avanzati
                if not self.state["streaming"]:
                    # Opzioni opzionali per lo streaming
                    if 'quality' in command and isinstance(command['quality'], int):
                        # Limita qualità a un intervallo sicuro
                        min_quality = self.config["stream"].get("min_quality", 70)
                        max_quality = self.config["stream"].get("max_quality", 95)
                        self._jpeg_quality = max(min_quality, min(max_quality, command['quality']))
                        logger.info(f"Qualità JPEG impostata a {self._jpeg_quality}")

                    if 'target_fps' in command and isinstance(command['target_fps'], int):
                        # Calcola intervallo target FPS e limita a un intervallo sicuro
                        min_fps = self.config["stream"].get("min_fps", 20)
                        max_fps = self.config["stream"].get("max_fps", 60)
                        fps = max(min_fps, min(max_fps, command['target_fps']))
                        self._frame_interval = 1.0 / fps
                        logger.info(f"Target FPS impostato a {fps} (intervallo={self._frame_interval * 1000:.1f}ms)")

                    # Flag per uso di dual camera
                    dual_camera = command.get('dual_camera', True)

                    # Reset statistiche
                    for cam_idx in self._stats:
                        self._stats[cam_idx].reset()

                    # Avvia lo streaming
                    self.start_streaming()

                    # Informazioni per il client
                    response['streaming'] = True
                    response['cameras'] = len(self.cameras)
                    response['quality'] = self._jpeg_quality
                    response['target_fps'] = int(1.0 / self._frame_interval)
                    response['dual_camera'] = dual_camera and len(self.cameras) > 1

                    # Info avanzate
                    response['server_version'] = SERVER_VERSION

                    # Formati camera
                    response['camera_details'] = []
                    for cam_info in self.cameras:
                        response['camera_details'].append({
                            'index': cam_info['index'],
                            'name': cam_info['name'],
                            'format': cam_info['format'],
                            'resolution': cam_info['resolution'],
                            'framerate': cam_info['framerate']
                        })
                else:
                    response['streaming'] = True
                    response['message'] = "Streaming già attivo"

            elif command_type == 'STOP_STREAM':
                # Ferma lo streaming
                if self.state["streaming"]:
                    self.stop_streaming()
                    response['streaming'] = False

                    # Aggiungi statistiche finali
                    response['stats'] = {}
                    for cam_idx, stats in self._stats.items():
                        response['stats'][str(cam_idx)] = stats.get_summary()
                else:
                    response['streaming'] = False
                    response['message'] = "Streaming non attivo"

            elif command_type == 'SET_CONFIG':
                # Aggiorna la configurazione
                if 'config' in command:
                    self._update_config(command['config'])
                    response['config_updated'] = True
                else:
                    response['status'] = 'error'
                    response['error'] = 'Configurazione mancante'

            elif command_type == 'GET_CONFIG':
                # Restituisci la configurazione
                response['config'] = self.config

            elif command_type == 'CAPTURE_FRAME':
                # Cattura un singolo frame
                frames = self._capture_frames()
                if frames:
                    response['captured'] = True
                    response['timestamp'] = time.time()
                    response['frames'] = frames
                else:
                    response['status'] = 'error'
                    response['error'] = 'Errore nella cattura dei frame'

            elif command_type == 'GET_CAPABILITIES':
                # Restituisci capabilities avanzate
                response['capabilities'] = {
                    'dual_camera': len(self.cameras) > 1,
                    'color_mode': True,
                    'grayscale_mode': True,
                    'max_resolution': self._get_max_resolution(),
                    'min_resolution': [320, 240],
                    'max_fps': self.config["stream"].get("max_fps", 60),
                    'min_fps': self.config["stream"].get("min_fps", 20),
                    'server_version': SERVER_VERSION,
                    'cameras': [
                        {
                            'index': cam_info['index'],
                            'name': cam_info['name'],
                            'format': cam_info['format'],
                            'resolution': cam_info['resolution'],
                            'framerate': cam_info['framerate']
                        } for cam_info in self.cameras
                    ]
                }

            else:
                # Comando sconosciuto
                response['status'] = 'error'
                response['error'] = f'Comando sconosciuto: {command_type}'

        except Exception as e:
            logger.error(f"Errore nell'elaborazione del comando {command_type}: {e}")
            response['status'] = 'error'
            response['error'] = str(e)

        return response

    def _get_max_resolution(self) -> List[int]:
        """Determina la risoluzione massima supportata dalle camere."""
        if not self.cameras:
            return [1920, 1080]  # Default

        # Trova la risoluzione massima tra tutte le camere
        max_width = 0
        max_height = 0

        for cam_info in self.cameras:
            width, height = cam_info['resolution']
            max_width = max(max_width, width)
            max_height = max(max_height, height)

        return [max_width, max_height]

    def _get_cpu_temperature(self) -> float:
        """Ottiene la temperatura CPU su Raspberry Pi."""
        try:
            with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
                temp = float(f.read()) / 1000.0
                return temp
        except:
            return 0.0

    def _check_client_activity(self):
        """
        Verifica se il client è ancora attivo e, in caso contrario, rilascia le risorse.
        Da chiamare periodicamente nel loop principale.
        """
        if not self.client_connected:
            return

        current_time = time.time()
        time_since_last_activity = current_time - self._last_client_activity
        timeout = self.config["server"].get("connection_timeout", 10.0)

        # Se non si hanno notizie dal client per più di N secondi, considerarlo disconnesso
        if time_since_last_activity > timeout:
            logger.info(
                f"Il client {self.client_ip} risulta inattivo da {time_since_last_activity:.1f} secondi, considerato disconnesso.")

            # Ferma lo streaming se attivo
            if self.state["streaming"]:
                logger.info("Arresto automatico dello streaming per client inattivo")
                self.stop_streaming()

            # Aggiorna lo stato
            self.client_connected = False
            self.client_ip = None
            self.state["clients_connected"] = 0

            # Log per facilitare il debug
            logger.info("Risorse rilasciate per client inattivo")

    def _check_client_activity_loop(self):
        """
        Loop di controllo per il monitoraggio dell'attività client.
        """
        check_interval = 5.0  # Verifica ogni 5 secondi

        while self.running:
            try:
                self._check_client_activity()
                time.sleep(check_interval)
            except Exception as e:
                if self.running:  # Solo log se ancora in esecuzione
                    logger.error(f"Errore nel controllo attività client: {e}")
                time.sleep(check_interval)

    def _update_config(self, new_config: Dict[str, Any]):
        """
        Aggiorna la configurazione del server.

        Args:
            new_config: Nuova configurazione
        """
        # Aggiorna ricorsivamente la configurazione
        self._update_dict_recursive(self.config, new_config)

        # Applica le modifiche alle camere
        self._apply_camera_config()

        # Salva la configurazione aggiornata
        config_path = CONFIG_DIR / 'config.json'
        try:
            with open(config_path, 'w') as f:
                json.dump(self.config, f, indent=2)
            logger.info(f"Configurazione salvata in {config_path}")
        except Exception as e:
            logger.error(f"Errore nel salvataggio della configurazione: {e}")

        logger.info("Configurazione aggiornata")

    def _update_dict_recursive(self, original: Dict[str, Any], update: Dict[str, Any]):
        """
        Aggiorna ricorsivamente un dizionario con i valori di un altro.

        Args:
            original: Dizionario originale da aggiornare
            update: Dizionario con i nuovi valori
        """
        for key, value in update.items():
            if key in original and isinstance(original[key], dict) and isinstance(value, dict):
                self._update_dict_recursive(original[key], value)
            else:
                original[key] = value

    def _apply_camera_config(self):
        """
        Applica la configurazione alle camere.
        Versione migliorata per gestire il cambio di modalità.
        """
        # Se lo streaming è attivo, fermalo
        was_streaming = self.state["streaming"]
        if was_streaming:
            self.stop_streaming()

        # Riavvia le camere con la nuova configurazione
        for cam_info in self.cameras:
            try:
                camera = cam_info["camera"]
                camera.stop()

                # Ottieni la configurazione
                if cam_info["name"] == "left":
                    cam_config = self.config["camera"]["left"]
                else:
                    cam_config = self.config["camera"]["right"]

                # Determina il formato in base alla modalità se specificata
                format_str = cam_config.get("format", "RGB888")

                # Applica configurazione specifiche per la modalità
                if "mode" in cam_config:
                    if cam_config["mode"] == "grayscale":
                        format_str = "GREY"  # Formato corretto per grayscale
                        logger.info(f"Camera {cam_info['name']} impostata in modalità scala di grigi (GREY)")
                    else:  # color
                        format_str = "RGB888"  # Formato per colore
                        logger.info(f"Camera {cam_info['name']} impostata in modalità colore (RGB888)")

                # Controlli avanzati della camera
                controls = {"FrameRate": cam_config.get("framerate", 30)}

                # Parametri di esposizione e guadagno
                if "exposure" in cam_config:
                    # Converti da 0-100 a valore appropriato
                    controls["AeEnable"] = 0  # Disabilita auto-esposizione
                    # Mappatura migliorata
                    exposure_val = int((cam_config["exposure"] / 100.0) * 66666)
                    controls["ExposureTime"] = exposure_val
                    logger.info(f"Camera {cam_info['name']} esposizione: {exposure_val}")

                if "gain" in cam_config:
                    controls["AgcEnable"] = 0  # Disabilita auto-gain
                    # Mappatura migliorata con gamma non lineare per migliore controllo
                    gain_factor = (cam_config["gain"] / 100.0) ** 2.0  # Mappatura gamma-corretta
                    gain_val = gain_factor * 8.0  # Massimo gain 8.0
                    controls["AnalogueGain"] = gain_val
                    logger.info(f"Camera {cam_info['name']} gain: {gain_val:.2f}")

                # Altri parametri avanzati
                if "brightness" in cam_config:
                    # Mappatura migliorata -1.0 a 1.0
                    brightness_val = ((cam_config["brightness"] / 100.0) * 2.0) - 1.0
                    controls["Brightness"] = brightness_val

                if "contrast" in cam_config:
                    # Mappatura migliorata 0.0 a 2.0 con controllo non lineare
                    contrast_val = (cam_config["contrast"] / 50.0) ** 1.2
                    controls["Contrast"] = contrast_val

                if "saturation" in cam_config and format_str != "GREY":
                    # Applicare saturazione solo in modalità colore
                    saturation_val = cam_config["saturation"] / 50.0
                    controls["Saturation"] = saturation_val

                if "sharpness" in cam_config:
                    sharpness_val = cam_config["sharpness"] / 100.0
                    controls["Sharpness"] = sharpness_val

                # Debug log per formato e controlli
                logger.info(f"Camera {cam_info['name']} configurazione: formato={format_str}, controlli={controls}")

                # Applica la configurazione con protezione errori
                try:
                    # Crea configurazione con controlli espliciti
                    camera_config = camera.create_video_configuration(
                        main={"size": tuple(cam_config["resolution"]),
                              "format": format_str},
                        controls=controls
                    )

                    # Configura con gestione errori
                    camera.configure(camera_config)

                    # Aggiorna info della camera
                    cam_info["format"] = format_str
                    cam_info["resolution"] = tuple(cam_config["resolution"])
                    cam_info["framerate"] = cam_config.get("framerate", 30)

                    # Attendi brevemente dopo la configurazione
                    time.sleep(0.1)

                    # Riavvia la camera
                    camera.start()
                    logger.info(f"Configurazione applicata alla camera {cam_info['name']}")

                except Exception as e:
                    logger.error(f"Errore nella configurazione camera {cam_info['name']}: {e}")

                    # Tentativo di fallback con configurazione minima
                    try:
                        logger.info(f"Tentativo di fallback per camera {cam_info['name']}")
                        basic_config = camera.create_video_configuration(
                            main={"size": tuple(cam_config["resolution"]),
                                  "format": format_str}
                        )
                        camera.configure(basic_config)
                        camera.start()

                        # Aggiorna info camera anche in fallback
                        cam_info["format"] = format_str
                        cam_info["resolution"] = tuple(cam_config["resolution"])

                        logger.info(f"Configurazione base applicata alla camera {cam_info['name']}")
                    except Exception as fallback_error:
                        logger.error(f"Fallimento anche del fallback: {fallback_error}")
                        # In caso di errore anche del fallback, cerchiamo di non fermare tutta l'applicazione
                        try:
                            camera.start()
                        except:
                            pass

            except Exception as e:
                logger.error(f"Errore nell'applicazione della configurazione alla camera {cam_info['name']}: {e}")

        # Pausa per stabilizzazione camere dopo riconfigurazione
        time.sleep(0.5)

        # Riavvia lo streaming se era attivo
        if was_streaming:
            try:
                self.start_streaming()
                logger.info("Streaming riavviato dopo cambio configurazione")
            except Exception as e:
                logger.error(f"Errore nel riavvio dello streaming: {e}")

    def start_streaming(self):
        """
        Avvia lo streaming video ottimizzato.
        """
        if self.state["streaming"]:
            logger.warning("Lo streaming è già attivo")
            return

        logger.info("Avvio dello streaming video...")

        # Reset contatori
        self._frame_count = {cam_info["index"]: 0 for cam_info in self.cameras}
        self._streaming_start_time = time.time()
        self._bytes_sent = 0
        self._last_bytes_check = time.time()
        self._bandwidth_estimates = []

        # Reset statistiche
        for cam_idx in self._stats:
            self._stats[cam_idx].reset()

        # Avvia un thread di streaming per ogni camera
        self.stream_threads = []
        for cam_info in self.cameras:
            thread = threading.Thread(
                target=self._stream_camera,
                args=(cam_info["camera"], cam_info["index"]),
                name=f"StreamThread-{cam_info['name']}"
            )
            thread.daemon = True

            # Prova a impostare la priorità
            try:
                import os
                os.nice(-10)  # Priorità più alta (-20 è max, 19 è min)
            except:
                pass

            # Avvia il thread
            thread.start()
            self.stream_threads.append(thread)

        # Aggiorna lo stato
        self.state["streaming"] = True
        logger.info(f"Streaming video avviato con {len(self.stream_threads)} camere")

    def stop_streaming(self):
        """
        Ferma lo streaming video in modo pulito.
        """
        if not self.state["streaming"]:
            return

        logger.info("Arresto dello streaming video...")

        # Aggiorna lo stato
        self.state["streaming"] = False

        # Attendi che i thread di streaming terminino
        for thread in self.stream_threads:
            if thread.is_alive():
                try:
                    thread.join(timeout=2.0)
                except:
                    pass

        self.stream_threads = []

        # Calcola statistiche totali
        streaming_duration = time.time() - self._streaming_start_time

        if streaming_duration > 0:
            total_frames = sum(self._frame_count.values())
            avg_fps = total_frames / streaming_duration

            # Statistiche per camera
            for cam_idx, frames in self._frame_count.items():
                if frames > 0 and streaming_duration > 0:
                    camera_fps = frames / streaming_duration
                    logger.info(f"Camera {cam_idx}: {frames} frames, media {camera_fps:.1f} FPS")

            # Statistiche complessive
            logger.info(f"Streaming arrestato: {total_frames} frames totali in {streaming_duration:.1f}s")
            logger.info(f"FPS medio totale: {avg_fps:.1f}")

            # Statistiche di banda
            if self._bandwidth_estimates:
                avg_bandwidth = sum(self._bandwidth_estimates) / len(self._bandwidth_estimates)
                max_bandwidth = max(self._bandwidth_estimates)
                logger.info(f"Banda utilizzata: media {avg_bandwidth / 1024 / 1024:.2f} MB/s, " +
                            f"max {max_bandwidth / 1024 / 1024:.2f} MB/s")

        # Gc collection dopo streaming
        gc.collect()

        logger.info("Streaming video arrestato con successo")

    def _stream_camera(self, camera: "Picamera2", camera_index: int):
        """
        Funzione ultra-ottimizzata che gestisce lo streaming di una camera.
        Versione con latenza ridotta e gestione avanzata dell'encoding.

        Args:
            camera: Oggetto camera
            camera_index: Indice della camera (0=sinistra, 1=destra)
        """
        logger.info(f"Thread di streaming camera {camera_index} avviato")

        try:
            # Imposta priorità del thread al massimo possibile
            try:
                # Aumenta la priorità del thread - funziona su Linux/Unix
                import os
                os.nice(-20)  # Priorità massima su Linux
                logger.info(f"Priorità massima impostata per thread di streaming camera {camera_index}")
            except Exception as e:
                # Se non è possibile impostare la priorità, continua comunque
                logger.debug(f"Impossibile impostare priorità thread: {e}")

            # Ottieni qualità JPEG ottimale
            quality = max(70, min(95, self._jpeg_quality))  # Limita tra 70-95
            logger.info(f"Camera {camera_index} - qualità JPEG: {quality}")

            # Configura intervallo iniziale per il target FPS
            current_interval = max(0.01, self._frame_interval)  # Garantisci almeno 10ms
            min_interval = 1.0 / max(30, self.config["stream"].get("max_fps", 60))
            logger.info(f"Camera {camera_index} - intervallo iniziale: {current_interval * 1000:.1f}ms")

            # Ottimizzazioni per buffer di encoding
            encode_params = [cv2.IMWRITE_JPEG_QUALITY, quality,
                             cv2.IMWRITE_JPEG_OPTIMIZE, 1,  # Attiva ottimizzazioni extra
                             cv2.IMWRITE_JPEG_PROGRESSIVE, 0]  # Disattiva formato progressivo

            # Monitoraggio prestazioni
            stats = self._stats[camera_index]
            frame_count = 0

            # Pre-allocazione buffer
            encoded_data_buffer = None

            # Tracking per la qualità dinamica
            lag_reports = []  # Lista per tracking del lag

            # Flag per evitare operazioni inutili su grayscale
            is_grayscale_mode = False

            # Verifica formato dalla configurazione o dall'info camera
            if camera_index < len(self.cameras):
                cam_info = self.cameras[camera_index]
                if cam_info["format"] == "GREY":
                    is_grayscale_mode = True
                    logger.info(f"Camera {camera_index} in modalità grayscale - ottimizzazione attiva")
            else:
                # Fallback alla configurazione
                cam_config = self.config["camera"]["left" if camera_index == 0 else "right"]
                if "mode" in cam_config and cam_config["mode"] == "grayscale":
                    is_grayscale_mode = True
                    logger.info(f"Camera {camera_index} in modalità grayscale - ottimizzazione attiva")

            # Imposta tempo del prossimo frame
            next_frame_time = time.time()

            # Loop principale per lo streaming ultra-ottimizzato
            while self.state["streaming"] and self.running:
                try:
                    # Controllo di flusso preciso
                    current_time = time.time()

                    # Attendi fino al prossimo frame programmato
                    if current_time < next_frame_time:
                        # Micropausa per CPU efficiency
                        wait_time = next_frame_time - current_time
                        if wait_time > 0.001:  # Solo se il tempo è significativo
                            time.sleep(min(wait_time, 0.005))  # Micropausa max 5ms
                        continue

                    # Calcola il prossimo tempo di acquisizione
                    next_frame_time = current_time + current_interval

                    # Cattura il frame con timing preciso
                    start_time = time.time()
                    frame = camera.capture_array()
                    capture_time = (time.time() - start_time) * 1000  # ms

                    if frame is None or frame.size == 0:
                        logger.warning(f"Frame vuoto dalla camera {camera_index}")
                        time.sleep(0.001)  # Micropausa
                        continue

                    # Ottimizzazione frame in base alla modalità
                    start_process = time.time()
                    frame_to_encode = frame

                    # Verifica if grayscale conversion needed (solo se in modalità colore)
                    if not is_grayscale_mode and len(frame.shape) == 3:
                        if frame.shape[2] == 4:  # RGBA
                            frame_to_encode = cv2.cvtColor(frame, cv2.COLOR_RGBA2BGR)
                        # Altrimenti presumiamo già BGR
                    elif is_grayscale_mode and len(frame.shape) == 3:
                        # Se la camera è in modalità grayscale ma il frame è a colori, convertiamo
                        frame_to_encode = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

                    process_time = (time.time() - start_process) * 1000  # ms

                    # Comprimi in JPEG con parametri ottimizzati
                    start_encode = time.time()
                    success, encoded_data = cv2.imencode('.jpg', frame_to_encode, encode_params)
                    encode_time = (time.time() - start_encode) * 1000  # ms

                    if not success or encoded_data is None or encoded_data.size == 0:
                        logger.error(f"Errore nella codifica JPEG, camera {camera_index}")
                        time.sleep(0.001)  # Micropausa
                        continue

                    # Crea l'header con timing preciso
                    timestamp = time.time()  # Timestamp di fine elaborazione
                    header = {
                        "camera": camera_index,
                        "frame": frame_count,
                        "timestamp": timestamp,
                        "format": "jpeg",
                        "resolution": [frame.shape[1], frame.shape[0]],
                        "mode": "grayscale" if is_grayscale_mode else "color"
                    }

                    # Invia l'header e poi i dati ottimizzando
                    try:
                        # Versione high-efficiency ZMQ senza copie memoria
                        header_json = json.dumps(header).encode('utf-8')
                        self.stream_socket.send(header_json, zmq.SNDMORE | zmq.DONTWAIT)
                        self.stream_socket.send(encoded_data.tobytes(), copy=False, flags=zmq.DONTWAIT)

                        # Aggiorna contatori
                        frame_count += 1
                        self._frame_count[camera_index] = frame_count

                        # Tracking bandwidth
                        self._bytes_sent += len(header_json) + len(encoded_data.tobytes())
                    except zmq.ZMQError as e:
                        if e.errno == zmq.EAGAIN:
                            # Socket non disponibile, client in ritardo - salta questo frame
                            continue
                        logger.error(f"Errore ZMQ nell'invio: {e}")
                        time.sleep(0.001)  # Micropausa
                        continue
                    except Exception as e:
                        logger.error(f"Errore generico nell'invio: {e}")
                        continue

                    # Aggiungi statistiche a tracker
                    stats.add_frame(
                        capture_time=capture_time,
                        process_time=process_time,
                        encode_time=encode_time,
                        size_kb=len(encoded_data.tobytes()) / 1024
                    )

                    # Bandwidth tracking ogni ~100 frame
                    if frame_count % 100 == 0:
                        current_time = time.time()
                        elapsed = current_time - self._last_bytes_check
                        if elapsed > 0:
                            bandwidth = self._bytes_sent / elapsed  # bytes/sec
                            self._bandwidth_estimates.append(bandwidth)
                            # Keep only last 10
                            if len(self._bandwidth_estimates) > 10:
                                self._bandwidth_estimates.pop(0)

                            # Reset counters
                            self._bytes_sent = 0
                            self._last_bytes_check = current_time

                    # Calcola statistiche dettagliate ogni 50 frame
                    if frame_count % 50 == 0:
                        summary = stats.get_summary()
                        fps = summary['fps']
                        avg_size = stats.get_average('size_kb')
                        avg_encode = stats.get_average('encode_time')
                        avg_capture = stats.get_average('capture_time')

                        # Log delle statistiche (livello INFO per essere più visibile)
                        logger.info(f"Camera {camera_index}: {fps:.1f} FPS, " +
                                    f"{avg_size:.1f} KB/frame, encode: {avg_encode:.1f}ms, " +
                                    f"capture: {avg_capture:.1f}ms")

                        # Verifica lag report dal client
                        if camera_index in self._client_lag_reports and self._client_lag_reports[camera_index]:
                            # Calcola lag medio riportato
                            lag_reports = self._client_lag_reports[camera_index]
                            if lag_reports:
                                avg_lag = sum(lag_reports) / len(lag_reports)
                                self._client_lag_reports[camera_index] = []  # Reset

                                # Log del lag
                                logger.info(f"Camera {camera_index}: lag medio client: {avg_lag:.1f}ms")

                                # Regola qualità se necessario e abilitato
                                if self.config["stream"].get("dynamic_quality", True):
                                    min_quality = self.config["stream"].get("min_quality", 70)
                                    max_quality = self.config["stream"].get("max_quality", 95)

                                    if avg_lag > 250 and quality > min_quality + 5:
                                        # Lag alto - riduci qualità
                                        quality = max(min_quality, quality - 5)
                                        encode_params[1] = quality
                                        logger.info(f"Camera {camera_index}: Lag elevato ({avg_lag:.0f}ms), " +
                                                    f"qualità ridotta a {quality}")
                                    elif avg_lag < 120 and quality < max_quality - 2:
                                        # Lag basso - aumenta qualità
                                        quality = min(max_quality, quality + 2)
                                        encode_params[1] = quality
                                        logger.info(f"Camera {camera_index}: Lag basso ({avg_lag:.0f}ms), " +
                                                    f"qualità aumentata a {quality}")

                except Exception as e:
                if self.running and self.state["streaming"]:  # Solo log se ancora in esecuzione
                    logger.error(f"Errore nello streaming camera {camera_index}: {e}")
                time.sleep(0.01)  # Pausa più lunga in caso di errore

                # Reset del timing
                next_frame_time = time.time() + current_interval

        except Exception as e:
            if self.running:  # Solo log se ancora in esecuzione
                logger.error(f"Errore fatale nello streaming camera {camera_index}: {e}")

        finally:
            # Statistiche finali per questa camera
            total_frames = self._frame_count.get(camera_index, 0)
            streaming_duration = time.time() - self._streaming_start_time

            if streaming_duration > 0 and total_frames > 0:
                camera_fps = total_frames / streaming_duration
                logger.info(f"Thread streaming camera {camera_index} terminato: {total_frames} frame, " +
                            f"{camera_fps:.1f} FPS medi")
            else:
                logger.info(f"Thread di streaming camera {camera_index} terminato")


def _capture_frames(self) -> List[Dict[str, Any]]:
    """
    Cattura un singolo frame da tutte le camere attive.

    Returns:
        Lista di informazioni sui frame catturati
    """
    try:
        # Timestamp per il nome del file
        timestamp = time.strftime("%Y%m%d_%H%M%S")

        # Timestamp per il nome file con alta precisione millisecondi
        precise_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]

        # Crea la directory per i frame se non esiste
        capture_dir = CAPTURE_DIR
        capture_dir.mkdir(parents=True, exist_ok=True)

        # Lista per info sui frame catturati
        captured_frames = []

        # Cattura i frame da tutte le camere
        for cam_info in self.cameras:
            camera = cam_info["camera"]
            name = cam_info["name"]
            camera_index = cam_info["index"]

            try:
                # Cattura il frame con timestamp preciso
                start_time = time.time()
                frame = camera.capture_array()
                capture_time = (time.time() - start_time) * 1000  # ms

                if frame is None or frame.size == 0:
                    logger.error(f"Frame vuoto dalla camera {name}")
                    continue

                # Genera nome file
                file_name = f"frame_{precise_timestamp}_{name}.jpg"
                file_path = capture_dir / file_name

                # Salva il frame come JPEG con alta qualità
                try:
                    success = cv2.imwrite(str(file_path), frame,
                                          [cv2.IMWRITE_JPEG_QUALITY, 95,
                                           cv2.IMWRITE_JPEG_OPTIMIZE, 1])

                    if not success:
                        # Fallback a PIL se OpenCV fallisce
                        from PIL import Image
                        Image.fromarray(frame).save(str(file_path), quality=95)

                except Exception as e:
                    logger.error(f"Errore nel salvataggio con OpenCV, fallback a PIL: {e}")
                    # Fallback a PIL
                    try:
                        from PIL import Image
                        Image.fromarray(frame).save(str(file_path), quality=95)
                    except Exception as pil_error:
                        logger.error(f"Anche PIL ha fallito: {pil_error}")
                        continue

                # Log info frame
                logger.info(f"Frame catturato dalla camera {name}: {file_path}")

                # Info sul frame
                frame_info = {
                    "camera": camera_index,
                    "name": name,
                    "file": str(file_path),
                    "timestamp": time.time(),
                    "resolution": [frame.shape[1], frame.shape[0]],
                    "size_bytes": os.path.getsize(file_path),
                    "capture_time_ms": capture_time
                }

                captured_frames.append(frame_info)

            except Exception as e:
                logger.error(f"Errore nella cattura frame da camera {name}: {e}")

        return captured_frames

    except Exception as e:
        logger.error(f"Errore generale nella cattura dei frame: {e}")
        return []


def main():
    """
    Funzione principale con gestione argomenti migliorata.
    """
    # Parse degli argomenti
    parser = argparse.ArgumentParser(description=f'UnLook Scanner Server v{SERVER_VERSION}')
    parser.add_argument('-c', '--config', type=str, help='Percorso del file di configurazione')
    parser.add_argument('-p', '--port', type=int, help='Porta per i comandi (default dal config)')
    parser.add_argument('-s', '--stream-port', type=int, help='Porta per lo streaming (default: porta comandi + 1)')
    parser.add_argument('--quality', type=int, help='Qualità JPEG (70-95, default 85)', default=85)
    parser.add_argument('--fps', type=int, help='FPS target (20-60, default 40)', default=40)
    parser.add_argument('--hwm', type=int, help='High Water Mark per ZMQ (default 1)', default=1)
    parser.add_argument('--debug', action='store_true', help='Abilita il livello di log DEBUG')
    parser.add_argument('--version', action='store_true', help='Mostra versione ed esci')
    args = parser.parse_args()

    # Mostra versione se richiesto
    if args.version:
        print(f"UnLook Scanner Server v{SERVER_VERSION}")
        return

    # Imposta il livello di log
    if args.debug:
        logger.setLevel(logging.DEBUG)
        console_handler.setLevel(logging.DEBUG)
        logger.debug("Modalità debug attivata")

    # Mostra banner di avvio
    print(f"""
╔═══════════════════════════════════════════════╗
║             UnLook Scanner Server              ║
║             Versione {SERVER_VERSION.ljust(10)}                 ║
║        (c) 2025 SupernovaIndustries           ║
╚═══════════════════════════════════════════════╝
    """)

    # Crea e avvia il server
    server = UnLookServer(config_path=args.config)

    # Override delle impostazioni se specificate
    if args.port:
        server.config["server"]["command_port"] = args.port
        logger.info(f"Porta comandi impostata a {args.port} da linea di comando")

    if args.stream_port:
        server.config["server"]["stream_port"] = args.stream_port
        logger.info(f"Porta streaming impostata a {args.stream_port} da linea di comando")
    elif args.port:
        # Se è specificata solo la porta comandi, imposta stream_port = command_port + 1
        server.config["server"]["stream_port"] = args.port + 1
        logger.info(f"Porta streaming impostata a {args.port + 1} (command_port + 1)")

    # Imposta qualità JPEG e FPS target
    min_quality = server.config["stream"].get("min_quality", 70)
    max_quality = server.config["stream"].get("max_quality", 95)
    server._jpeg_quality = max(min_quality, min(max_quality, args.quality))

    min_fps = server.config["stream"].get("min_fps", 20)
    max_fps = server.config["stream"].get("max_fps", 60)
    fps = max(min_fps, min(max_fps, args.fps))
    server._frame_interval = 1.0 / fps

    # Imposta HWM
    server._zmq_hwm = max(1, args.hwm)

    logger.info(f"Parametri di avvio: FPS={fps}, qualità={server._jpeg_quality}, HWM={server._zmq_hwm}")

    # Gestione dei segnali per un arresto pulito
    def signal_handler(sig, frame):
        print("\nSegnale di interruzione ricevuto. Arresto in corso...")
        server.stop()
        time.sleep(0.5)  # Piccola pausa per permettere ai log di essere scritti
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Avvia il server
    server.start()

    # Loop principale con controllo errori
    try:
        logger.info("Server UnLook in esecuzione. Premi Ctrl+C per terminare.")
        logger.info(f"Identificatore UUID dispositivo: {server.device_id}")
        logger.info("Ricorda di etichettare il case con questo UUID!")

        # Mantieni il thread principale attivo con monitoraggio stato
        last_status_time = time.time()

        while server.running:
            time.sleep(1)

            # Stampa info stato ogni 60 secondi
            current_time = time.time()
            if current_time - last_status_time >= 60:
                uptime = current_time - server.state["start_time"]
                streaming_status = "attivo" if server.state["streaming"] else "inattivo"
                client_status = "connesso" if server.client_connected else "non connesso"

                logger.info(
                    f"Stato server: uptime={int(uptime)}s, streaming={streaming_status}, client={client_status}")

                # Aggiorna timestamp
                last_status_time = current_time

    except KeyboardInterrupt:
        print("\nInterruzione da tastiera ricevuta. Arresto in corso...")
    except Exception as e:
        logger.error(f"Errore nel loop principale: {e}")
    finally:
        server.stop()


if __name__ == "__main__":
    main()