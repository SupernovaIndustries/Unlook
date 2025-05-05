#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
UnLook Scanner Server - Applicazione server per il Raspberry Pi
Gestisce le camere e lo streaming video verso il client.
Versione ottimizzata con controllo di flusso e riduzione della latenza.
Integrazione con ScanManager per scansione 3D a luce strutturata.
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
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

# Fix PYTHONPATH per importazioni
PROJECT_DIR = Path(__file__).parent.absolute()
if PROJECT_DIR.name == 'server':
    # Siamo in server/main_standalone.py
    sys.path.insert(0, str(PROJECT_DIR.parent))
else:
    # Siamo in un altro percorso
    sys.path.insert(0, str(PROJECT_DIR))

# Configurazione percorsi
LOG_DIR = PROJECT_DIR / "logs"
CONFIG_DIR = PROJECT_DIR / "config"
CAPTURE_DIR = PROJECT_DIR / "captures"
SCAN_DIR = PROJECT_DIR / "scans"

# Assicura che le directory esistano
LOG_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
SCAN_DIR.mkdir(parents=True, exist_ok=True)

# Configurazione logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / 'server.log', mode='a')
    ]
)
logger = logging.getLogger("UnLookServer")

logger.info("UnLook Scanner Server v2.0.0 in avvio...")

# Pre-importazione di NumPy e OpenCV per evitare deadlock
try:
    import numpy as np
    import cv2

    logger.info(f"OpenCV ottimizzazioni hardware: {cv2.useOptimized()}")

    # Banner di avvio
    print("\n╔═══════════════════════════════════════════════╗")
    print("║             UnLook Scanner Server             ║")
    print("║             Versione 2.0.0                    ║")
    print("║        (c) 2025 SupernovaIndustries           ║")
    print("╚═══════════════════════════════════════════════╝\n")

    # Importazione di ZMQ e PiCamera2
    import zmq
    from picamera2 import Picamera2

    # Importa anche il modulo encoders
    import picamera2.encoders
    from picamera2.encoders import JpegEncoder, Quality

    # Importazione di ScanManager per scansione 3D
    try:
        from server.scan_manager import ScanManager
    except ImportError:
        try:
            from scan_manager import ScanManager

            logger.info("ScanManager importato correttamente")
        except ImportError as e:
            logger.error(f"Impossibile importare ScanManager: {e}")
            ScanManager = None
except ImportError as e:
    logger.error(f"Dipendenza mancante: {e}")
    logger.error("Installa le dipendenze necessarie con: pip install pyzmq numpy picamera2 opencv-python simplejpeg")
    sys.exit(1)

def set_realtime_priority():
    """Imposta priorità real-time per il processo."""
    try:
        import os
        import psutil

        # Ottieni PID corrente
        pid = os.getpid()
        p = psutil.Process(pid)

        # Imposta priorità massima
        p.nice(-20)  # Da -20 (massima) a 19 (minima)

        # Imposta affinità CPU (usa core specifici)
        # Lascia il core 0 per il sistema operativo
        p.cpu_affinity([1, 2, 3])  # Usa core 1, 2, 3 su Raspberry Pi 4

        logger.info(f"Process priority set to real-time, CPU affinity: {p.cpu_affinity()}")
        return True
    except Exception as e:
        logger.error(f"Failed to set real-time priority: {e}")
        return False

class UnLookServer:
    """
    Server principale che gestisce le camere e le connessioni con i client.
    Versione ottimizzata per ridurre la latenza e migliorare il controllo di flusso.
    Integra ScanManager per la funzionalità di scansione 3D.
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
            "scanning": False,
            "uptime": 0.0,
            "start_time": time.time()
        }

        # Inizializza i socket di comunicazione con configurazione a bassa latenza
        self.broadcast_socket = None
        self.context = zmq.Context()

        # Socket comandi
        self.command_socket = self.context.socket(zmq.REP)

        # Socket streaming con configurazione ultra-bassa latenza
        self.stream_socket = self.context.socket(zmq.PUB)
        self.stream_socket.setsockopt(zmq.SNDHWM, 1)  # Alta priorità a latenza vs throughput
        self.stream_socket.setsockopt(zmq.LINGER, 0)  # Non attendere alla chiusura
        try:
            self.stream_socket.setsockopt(zmq.IMMEDIATE, 1)  # Evita buffering
        except:
            pass  # Ignora se non supportato
        try:
            self.stream_socket.setsockopt(zmq.TCP_NODELAY, 1)  # Disabilita Nagle
        except:
            pass  # Ignora se non supportato

        # Configurazione aggiuntiva per migliorare la stabilità
        try:
            # Imposta timeout di riconnessione più breve per recupero più veloce
            self.stream_socket.setsockopt(zmq.RECONNECT_IVL, 100)  # 100ms invece del default 1s
            self.stream_socket.setsockopt(zmq.RECONNECT_IVL_MAX, 5000)  # Max 5s invece del default 30s

            # Timeout più breve per operazioni di rete
            self.stream_socket.setsockopt(zmq.SNDTIMEO, 1000)  # 1s timeout per invio

            # Aumenta il buffer TCP per ridurre problemi di congestione
            self.stream_socket.setsockopt(zmq.SNDBUF, 1024 * 1024)  # 1MB buffer di invio
        except:
            pass  # Ignora se non supportato

        # Inizializza i thread
        self.broadcast_thread = None
        self.command_thread = None
        self.stream_threads = []

        # Controllo di flusso
        self._frame_interval = 1.0 / 30.0  # 30fps target
        self._dynamic_interval = True  # Regolazione dinamica dell'intervallo
        self._last_frame_time = 0
        self._streaming_start_time = 0
        self._frame_count = 0

        # Parametri di qualità dell'immagine ottimizzati
        self._jpeg_quality = 75  # Qualità JPEG ridotta per bassa latenza

        # Informazioni sul client
        self.client_connected = False
        self.client_ip = None
        self._last_client_activity = 0

        # Inizializza il gestore di scansione 3D
        self.scan_manager = None
        if ScanManager is not None:
            try:
                self.scan_manager = ScanManager(self)
                logger.info("Gestore di scansione 3D inizializzato")
            except Exception as e:
                logger.error(f"Errore nell'inizializzazione del gestore di scansione 3D: {e}")

        logger.info(f"Server UnLook inizializzato con ID: {self.device_id}")
        logger.info(f"Configurazione: max_fps={self.config['stream'].get('max_fps', 30)}, quality={self._jpeg_quality}")


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
        Carica la configurazione dal file JSON.

        Args:
            config_path: Percorso del file di configurazione

        Returns:
            Dizionario di configurazione
        """
        # Configurazione predefinita
        default_config = {
            "server": {
                "discovery_port": 5678,
                "command_port": 5680,
                "stream_port": 5681,
                "broadcast_interval": 1.0,  # secondi
                "frame_interval": 0.033,  # 33ms tra frame (30fps nominali)
                "dynamic_fps": True  # Regolazione dinamica di FPS
            },
            "camera": {
                "left": {
                    "enabled": True,
                    "resolution": [1280, 720],
                    "framerate": 30,
                    "format": "RGB888",  # Utilizziamo sempre RGB888 come formato base
                    "mode": "color"  # La conversione verrà fatta via software
                },
                "right": {
                    "enabled": True,
                    "resolution": [1280, 720],
                    "framerate": 30,
                    "format": "RGB888",
                    "mode": "color"
                }
            },
            "stream": {
                "format": "jpeg",
                "quality": 75,  # Qualità JPEG (0-100)
                "max_fps": 30,  # FPS massimo
                "min_fps": 15  # FPS minimo per regolazione dinamica
            },
            "scan": {
                "pattern_type": "PROGRESSIVE",
                "num_patterns": 12,
                "exposure_time": 0.5,
                "quality": 3,
                "i2c_bus": 3,
                "i2c_address": "0x36"
            }
        }

        # Se non è stato specificato un percorso, usa la configurazione predefinita
        if not config_path:
            # Controlla se esiste un file di configurazione nella directory config
            default_config_path = CONFIG_DIR / 'config.json'
            if default_config_path.exists():
                config_path = str(default_config_path)
            else:
                logger.info("Utilizzo della configurazione predefinita")
                # Salva la configurazione predefinita per usi futuri
                with open(default_config_path, 'w') as f:
                    json.dump(default_config, f, indent=2)
                return default_config

        # Carica la configurazione dal file
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
                logger.info(f"Configurazione caricata da: {config_path}")

                # Assicura che le opzioni di controllo di flusso siano presenti
                if "server" in config:
                    if "frame_interval" not in config["server"]:
                        config["server"]["frame_interval"] = default_config["server"]["frame_interval"]
                    if "dynamic_fps" not in config["server"]:
                        config["server"]["dynamic_fps"] = default_config["server"]["dynamic_fps"]

                if "stream" in config:
                    if "quality" not in config["stream"]:
                        config["stream"]["quality"] = default_config["stream"]["quality"]
                    if "max_fps" not in config["stream"]:
                        config["stream"]["max_fps"] = default_config["stream"]["max_fps"]
                    if "min_fps" not in config["stream"]:
                        config["stream"]["min_fps"] = default_config["stream"]["min_fps"]

                # Assicura che tutti i parametri della camera siano presenti e corretti
                if "camera" in config:
                    for cam_name in ["left", "right"]:
                        if cam_name in config["camera"]:
                            # Assicura che format sia sempre un formato supportato
                            if "format" not in config["camera"][cam_name] or config["camera"][cam_name][
                                "format"] == "GREY":
                                config["camera"][cam_name]["format"] = "RGB888"
                            # Mantieni il campo mode per la conversione software
                            if "mode" not in config["camera"][cam_name]:
                                config["camera"][cam_name]["mode"] = "color"

                # Assicura che la sezione scan sia presente
                if "scan" not in config:
                    config["scan"] = default_config["scan"]
                else:
                    # Assicura che tutti i parametri di scan siano presenti
                    for key, value in default_config["scan"].items():
                        if key not in config["scan"]:
                            config["scan"][key] = value

                # Salva la configurazione aggiornata
                with open(config_path, 'w') as f:
                    json.dump(config, f, indent=2)

                return config
        except Exception as e:
            logger.error(f"Errore nel caricamento della configurazione: {e}")
            logger.info("Utilizzo della configurazione predefinita")
            return default_config

    def _init_cameras(self):
        """
        Inizializza le camere PiCamera2 con gestione robusta degli errori.
        """
        try:
            # Ottieni la lista delle camere disponibili
            cam_list = Picamera2.global_camera_info()
            logger.info(f"Camere disponibili: {len(cam_list)}")

            # Stampa informazioni sulle camere disponibili
            for i, cam in enumerate(cam_list):
                # Estrai informazioni basic dal dizionario
                name = cam.get("model", "Sconosciuto")
                logger.info(f"Camera {i}: {name}")

            # Se non ci sono camere, esci
            if not cam_list:
                logger.error("Nessuna camera trovata!")
                return

            # Assicurati che _jpeg_quality esista, altrimenti usa un valore predefinito
            if not hasattr(self, '_jpeg_quality'):
                self._jpeg_quality = 75  # Valore predefinito ragionevole
                logger.info(f"Attributo _jpeg_quality non trovato, impostato a {self._jpeg_quality}")

            # Inizializza la camera sinistra
            if self.config["camera"]["left"]["enabled"] and len(cam_list) > 0:
                left_camera = Picamera2(0)  # Camera 0

                # Configura la camera
                left_config = self.config["camera"]["left"]
                # Assicurati di usare un formato supportato, mai "GREY"
                format_str = left_config["format"]
                if format_str == "GREY":
                    format_str = "RGB888"  # Usa RGB e converti in scala di grigi in seguito

                # Stampa info sulla modalità
                if left_config.get("mode") == "grayscale":
                    logger.info("Camera left in modalità scala di grigi")
                else:
                    logger.info("Camera left in modalità colore")

                try:
                    # Configurazione semplice senza encoder JPEG diretto
                    # Questo approccio è più robusto e previene l'errore "unhashable type"
                    camera_config = left_camera.create_video_configuration(
                        main={"size": tuple(left_config["resolution"]),
                              "format": format_str},
                        controls={"FrameRate": left_config["framerate"]}
                    )
                    left_camera.configure(camera_config)
                    left_camera.start()

                    # Aggiunge la camera alla lista solo se l'inizializzazione ha successo
                    self.cameras.append({
                        "index": 0,
                        "camera": left_camera,
                        "name": "left",
                        "mode": left_config.get("mode", "color")
                    })
                    logger.info(
                        f"Camera left inizializzata: {left_config['resolution'][0]}x{left_config['resolution'][1]}@{left_config['framerate']}fps, formato={format_str}")
                except Exception as e:
                    logger.error(f"Errore nell'inizializzazione della camera left: {e}")
                    import traceback
                    logger.error(f"Traceback: {traceback.format_exc()}")

            # Inizializza la camera destra
            if self.config["camera"]["right"]["enabled"] and len(cam_list) > 1:
                right_camera = Picamera2(1)  # Camera 1

                # Configura la camera
                right_config = self.config["camera"]["right"]
                # Assicurati di usare un formato supportato, mai "GREY"
                format_str = right_config["format"]
                if format_str == "GREY":
                    format_str = "RGB888"  # Usa RGB e converti in scala di grigi in seguito

                # Stampa info sulla modalità
                if right_config.get("mode") == "grayscale":
                    logger.info("Camera right in modalità scala di grigi")
                else:
                    logger.info("Camera right in modalità colore")

                try:
                    # Configurazione semplice senza encoder JPEG diretto
                    camera_config = right_camera.create_video_configuration(
                        main={"size": tuple(right_config["resolution"]),
                              "format": format_str},
                        controls={"FrameRate": right_config["framerate"]}
                    )
                    right_camera.configure(camera_config)
                    right_camera.start()

                    # Aggiunge la camera alla lista solo se l'inizializzazione ha successo
                    self.cameras.append({
                        "index": 1,
                        "camera": right_camera,
                        "name": "right",
                        "mode": right_config.get("mode", "color")
                    })
                    logger.info(
                        f"Camera right inizializzata: {right_config['resolution'][0]}x{right_config['resolution'][1]}@{right_config['framerate']}fps, formato={format_str}")
                except Exception as e:
                    logger.error(f"Errore nell'inizializzazione della camera right: {e}")
                    import traceback
                    logger.error(f"Traceback: {traceback.format_exc()}")

            logger.info(f"Camere inizializzate: {len(self.cameras)}/{len(cam_list)}")

        except Exception as e:
            logger.error(f"Errore nell'inizializzazione delle camere: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")

    def start(self):
        """
        Avvia il server con monitoraggio dell'attività client.
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

            # Verifica che ci siano camere disponibili
            if not self.cameras:
                logger.error("Nessuna camera inizializzata, impossibile avviare il server")
                return

            # Verifica che le camere siano già avviate
            for cam_info in self.cameras:
                if not cam_info["camera"].started:
                    try:
                        cam_info["camera"].start()
                        logger.info(f"Camera {cam_info['name']} avviata")
                    except Exception as e:
                        logger.error(f"Errore nell'avvio della camera {cam_info['name']}: {e}")

            # Apri i socket
            command_port = self.config["server"]["command_port"]
            stream_port = self.config["server"]["stream_port"]

            try:
                self.command_socket.bind(f"tcp://*:{command_port}")
                logger.info(f"Socket di comando in ascolto su porta {command_port}")
            except zmq.ZMQError as e:
                logger.error(f"Errore nell'apertura del socket di comando: {e}")
                # Prova una porta alternativa
                command_port += 10
                try:
                    self.command_socket.bind(f"tcp://*:{command_port}")
                    logger.info(f"Socket di comando in ascolto su porta alternativa {command_port}")
                except zmq.ZMQError as e2:
                    logger.error(f"Impossibile aprire il socket di comando: {e2}")
                    return

            try:
                # Configurazione ottimizzata del socket di streaming
                # Imposta un valore di HWM basso ma sicuro per messaggi multipart
                self.stream_socket.setsockopt(zmq.SNDHWM, 1)
                self.stream_socket.bind(f"tcp://*:{stream_port}")
                logger.info(f"Socket di streaming in ascolto su porta {stream_port}")
            except zmq.ZMQError as e:
                logger.error(f"Errore nell'apertura del socket di streaming: {e}")
                # Prova una porta alternativa
                stream_port += 10
                try:
                    self.stream_socket.bind(f"tcp://*:{stream_port}")
                    logger.info(f"Socket di streaming in ascolto su porta alternativa {stream_port}")
                except zmq.ZMQError as e2:
                    logger.error(f"Impossibile aprire il socket di streaming: {e2}")
                    self.command_socket.close()
                    return

            # Aggiorna le porte nella configurazione
            self.config["server"]["command_port"] = command_port
            self.config["server"]["stream_port"] = stream_port

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

            # Carica parametri di controllo di flusso
            self._frame_interval = self.config["server"].get("frame_interval", 0.033)
            self._dynamic_interval = self.config["server"].get("dynamic_fps", True)
            self._jpeg_quality = self.config["stream"].get("quality", 90)

            # Assicurati che il quality sia limitato tra 70 e 95 per un buon rapporto latenza/qualità
            self._jpeg_quality = max(70, min(95, self._jpeg_quality))

            logger.info(
                f"Parametri di avvio: FPS={int(1.0 / self._frame_interval)}, qualità={self._jpeg_quality}, HWM=1")

        except Exception as e:
            logger.error(f"Errore nell'avvio del server: {e}")
            # Pulizia in caso di errore
            self._cleanup_resources()
            # Non imposta self.running a True

    def _cleanup_resources(self):
        """Pulisce le risorse in caso di errore durante l'avvio o lo spegnimento."""
        try:
            # Chiudi i socket
            try:
                if hasattr(self, 'command_socket') and self.command_socket:
                    self.command_socket.close()
            except Exception as e:
                logger.debug(f"Errore nella chiusura del socket di comando: {e}")

            try:
                if hasattr(self, 'stream_socket') and self.stream_socket:
                    self.stream_socket.close()
            except Exception as e:
                logger.debug(f"Errore nella chiusura del socket di streaming: {e}")

            # Ferma le camere
            for cam_info in self.cameras:
                try:
                    if cam_info["camera"].started:
                        cam_info["camera"].stop()
                except Exception as e:
                    logger.debug(f"Errore nell'arresto della camera {cam_info['name']}: {e}")
        except Exception as e:
            logger.error(f"Errore nella pulizia delle risorse: {e}")

    def stop(self):
        """
        Ferma il server.
        """
        if not self.running:
            return

        logger.info("Arresto del server UnLook")

        # Imposta lo stato di arresto
        self.running = False
        self.state["status"] = "stopping"

        # Ferma lo streaming
        if self.state["streaming"]:
            self.stop_streaming()

        # Pulisci il gestore di scansione 3D se presente
        if self.scan_manager:
            try:
                self.scan_manager.cleanup()
                logger.info("Gestore di scansione 3D arrestato")
            except Exception as e:
                logger.error(f"Errore nell'arresto del gestore di scansione 3D: {e}")

        # Ferma il servizio di broadcast
        if hasattr(self, 'broadcast_thread') and self.broadcast_thread and self.broadcast_thread.is_alive():
            logger.info("Arresto del servizio di broadcast...")
            if self.broadcast_socket:
                try:
                    self.broadcast_socket.close()
                except:
                    pass

        # Chiudi i socket ZeroMQ
        logger.info("Chiusura dei socket...")
        try:
            self.command_socket.close()
            self.stream_socket.close()
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

        logger.info("Server UnLook arrestato")

    def _start_broadcast_service(self):
        """
        Avvia il servizio di broadcast per permettere ai client di trovare il server.
        """
        logger.info("Avvio del servizio di broadcast...")

        # Crea un socket UDP per il broadcast
        self.broadcast_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.broadcast_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.broadcast_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

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

    def _get_local_ip(self):
        """Ottiene l'indirizzo IP locale principale."""
        try:
            # Crea un socket temporaneo per ottenere il proprio IP
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))  # Connettiti a un server esterno (Google DNS)
            local_ip = s.getsockname()[0]
            s.close()
            return local_ip
        except Exception as e:
            logger.error(f"Errore nell'ottenere l'IP locale: {e}")
            # Fallback a localhost
            return "127.0.0.1"

    def _broadcast_loop(self):
        """
        Loop principale per il servizio di broadcast.
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
        try:
            while self.running:
                try:
                    # Prepara il messaggio di annuncio
                    announce_msg = {
                        "type": "UNLOOK_ANNOUNCE",
                        "device_id": self.device_id,
                        "name": self.device_name,
                        "version": "1.0.0",
                        "cameras": len(self.cameras),
                        "ip_address": local_ip,
                        "port": self.config["server"]["command_port"],
                        "capabilities": {
                            "dual_camera": len(self.cameras) > 1,
                            "color_mode": True,
                            "tof": False,
                            "dlp": self.scan_manager is not None,
                            "structured_light": self.scan_manager is not None
                        }
                    }

                    # Converti il messaggio in JSON e poi in bytes
                    message = json.dumps(announce_msg).encode('utf-8')

                    # Invia il messaggio in broadcast
                    try:
                        self.broadcast_socket.sendto(message, (broadcast_address, discovery_port))
                    except Exception as e:
                        logger.debug(f"Errore nell'invio broadcast: {e}")

                    msg_count += 1
                    if msg_count % 10 == 0:  # Log ogni 10 messaggi
                        logger.info(f"Messaggio di broadcast #{msg_count} inviato")

                    # Attendi prima del prossimo invio
                    time.sleep(broadcast_interval)

                except Exception as e:
                    logger.error(f"Errore nel loop di broadcast: {e}")
                    if not self.running:
                        break
                    time.sleep(1.0)  # Pausa più lunga in caso di errore

        except Exception as e:
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

                        # Decodifica il messaggio
                        message = json.loads(message_data.decode('utf-8'))
                        command_type = message.get('type', '')
                        logger.info(f"Comando ricevuto: {command_type}")

                        # Processa il comando
                        response = self._process_command(message)

                        # Invia la risposta
                        try:
                            self.command_socket.send_json(response)
                            logger.debug(f"Risposta al comando {command_type} inviata")
                        except Exception as e:
                            logger.error(f"Errore nell'invio della risposta: {e}")

                except zmq.ZMQError as e:
                    if e.errno == zmq.ETERM:
                        # Il contesto è stato terminato
                        logger.info("Contesto ZMQ terminato, uscita dal command loop")
                        break
                    logger.error(f"Errore ZMQ nel command loop: {e}")
                except Exception as e:
                    logger.error(f"Errore nel command loop: {e}")

        except Exception as e:
            logger.error(f"Errore fatale nel command loop: {e}")
        finally:
            logger.info("Command loop terminato")

    def _process_command(self, command: Dict[str, Any]) -> Dict[str, Any]:
        """
        Processa un comando ricevuto da un client.
        Versione migliorata con supporto per comandi di scansione 3D.

        Args:
            command: Dizionario rappresentante il comando

        Returns:
            Dizionario di risposta
        """
        command_type = command.get('type', '')
        command_id = command.get('id', str(time.time()))  # Usa un ID per tracciare la richiesta
        logger.info(f"Comando ricevuto: {command_type} (ID: {command_id})")

        # Prepara una risposta base
        response = {
            "status": "ok",
            "type": f"{command_type}_response",
            "original_type": command_type,
            "id": command_id,
            "timestamp": time.time()
        }

        try:
            if command_type == 'PING':
                # Comando ping
                response['timestamp'] = time.time()
                # Aggiorna timestamp di attività client
                self._last_client_activity = time.time()
                # CORREZIONE: Aggiorna la connessione e salva l'IP del client
                self.client_connected = True

                # Usa l'IP del client se fornito nel messaggio
                if 'client_ip' in command:
                    self.client_ip = command.get('client_ip')
                    logger.debug(f"Ping ricevuto dal client {self.client_ip}, aggiornato timestamp attività")

            elif command_type == 'GET_STATUS':
                # Aggiorna lo stato
                self.state['uptime'] = time.time() - self.state['start_time']
                # Aggiorna timestamp di attività client
                self._last_client_activity = time.time()
                self.client_connected = True

                # Aggiungi lo stato alla risposta
                response['state'] = self.state

                # Includi informazioni sulle modalità attuali delle camere
                camera_modes = {}
                for cam_info in self.cameras:
                    camera_modes[cam_info["name"]] = cam_info.get("mode", "color")
                response['camera_modes'] = camera_modes

                # Aggiungi informazioni sulla scansione 3D se disponibile
                if self.scan_manager:
                    response['scan_status'] = self.scan_manager.get_scan_status()

            elif command_type == 'START_STREAM':

                # Aggiorna timestamp di attività client

                self._last_client_activity = time.time()

                self.client_connected = True

                # Avvia lo streaming con supporto parametri avanzati

                if not self.state["streaming"]:

                    # Opzioni opzionali per lo streaming

                    if 'quality' in command and isinstance(command['quality'], int):
                        # Limita qualità a un intervallo sicuro

                        self._jpeg_quality = max(70, min(95, command['quality']))

                        logger.info(f"Qualità JPEG impostata a {self._jpeg_quality}")

                    if 'target_fps' in command and isinstance(command['target_fps'], int):
                        # Calcola intervallo target FPS e limita a un intervallo sicuro

                        fps = max(5, min(60, command['target_fps']))

                        self._frame_interval = 1.0 / fps

                        logger.info(f"Target FPS impostato a {fps} (intervallo={self._frame_interval * 1000:.1f}ms)")

                    # Flag per uso di dual camera

                    dual_camera = command.get('dual_camera', True)

                    # NOVITÀ: Log esplicito per la modalità dual camera

                    logger.info(f"Streaming richiesto in modalità {'dual' if dual_camera else 'single'} camera")

                    # NOVITÀ: Verifica esplicitamente che entrambe le camere siano disponibili

                    available_cameras = len(self.cameras)

                    if dual_camera and available_cameras >= 2:

                        logger.info(
                            f"Entrambe le camere disponibili ({available_cameras}). Modalità dual camera confermata.")

                    elif dual_camera and available_cameras < 2:

                        logger.warning(
                            f"Modalità dual camera richiesta ma solo {available_cameras} camera disponibile.")

                    # Avvia lo streaming

                    self.start_streaming()

                    # Informazioni per il client

                    response['streaming'] = True

                    response['cameras'] = len(self.cameras)

                    response['quality'] = self._jpeg_quality

                    response['target_fps'] = int(1.0 / self._frame_interval)

                    response['dual_camera'] = dual_camera and len(self.cameras) > 1

            elif command_type == 'STOP_STREAM':
                # Aggiorna timestamp di attività client
                self._last_client_activity = time.time()

                # Ferma lo streaming
                if self.state["streaming"]:
                    self.stop_streaming()
                    response['streaming'] = False
                else:
                    response['streaming'] = False
                    response['message'] = "Streaming non attivo"

            elif command_type == 'SET_CONFIG':
                # Aggiorna timestamp di attività client
                self._last_client_activity = time.time()
                self.client_connected = True

                # Aggiorna la configurazione con gestione errori migliorata
                if 'config' in command:
                    # Controlla se lo streaming è attivo prima di applicare la configurazione
                    was_streaming = self.state["streaming"]

                    try:
                        # Se lo streaming è attivo, fermalo prima di applicare le modifiche
                        if was_streaming:
                            logger.info("Interruzione temporanea dello streaming per applicare la configurazione")
                            self.stop_streaming()
                            time.sleep(0.5)  # Piccola pausa per assicurarsi che lo streaming sia completamente fermato

                        # Ora applica la configurazione
                        self._update_config(command['config'])
                        response['config_updated'] = True

                        # Se lo streaming era attivo, riavvialo
                        if was_streaming:
                            time.sleep(0.5)  # Piccola pausa per assicurarsi che le camere siano pronte
                            logger.info("Riavvio dello streaming dopo aggiornamento configurazione")
                            self.start_streaming()

                    except Exception as e:
                        logger.error(f"Errore nell'applicazione della configurazione: {e}")
                        response['status'] = 'error'
                        response['error'] = f'Errore nell\'applicazione della configurazione: {str(e)}'

                        # Prova a riavviare lo streaming se era attivo
                        if was_streaming:
                            try:
                                self.start_streaming()
                            except Exception as e2:
                                logger.error(f"Errore nel riavvio dello streaming dopo errore di configurazione: {e2}")
                else:
                    response['status'] = 'error'
                    response['error'] = 'Configurazione mancante'

            elif command_type == 'GET_CONFIG':
                # Aggiorna timestamp di attività client
                self._last_client_activity = time.time()
                self.client_connected = True

                # Restituisci la configurazione
                response['config'] = self.config

                # Includi informazioni sulle modalità attuali delle camere
                camera_modes = {}
                for cam_info in self.cameras:
                    camera_modes[cam_info["name"]] = cam_info.get("mode", "color")
                response['camera_modes'] = camera_modes

            elif command_type == 'CAPTURE_FRAME':
                # Aggiorna timestamp di attività client
                self._last_client_activity = time.time()

                # Cattura un singolo frame
                frames = self._capture_frames()
                if frames:
                    response['captured'] = True
                    response['timestamp'] = time.time()
                else:
                    response['status'] = 'error'
                    response['error'] = 'Errore nella cattura dei frame'

            # --- COMANDI DI SCANSIONE 3D ---

            elif command_type == 'CHECK_SCAN_CAPABILITY':

                # Aggiorna timestamp di attività client

                self._last_client_activity = time.time()

                self.client_connected = True

                # Verifica le capacità di scansione 3D

                has_scan_capability = self.scan_manager is not None

                # Più dettagli sullo stato

                scan_capability_details = {}

                if has_scan_capability:

                    try:

                        # Ottieni informazioni dettagliate sulle capacità

                        capability_result = self.scan_manager.check_scan_capability()

                        response["scan_capability"] = capability_result["capability_available"]

                        response["scan_capability_details"] = capability_result["details"]

                    except Exception as e:

                        logger.error(f"Errore nella verifica delle capacità di scansione: {e}")

                        response["scan_capability"] = False

                        response["scan_capability_details"] = {"error": str(e)}

                else:

                    response["scan_capability"] = False

                    response["scan_capability_details"] = {

                        "error": "Gestore di scansione 3D non disponibile",

                        "i2c_bus": os.environ.get("UNLOOK_I2C_BUS", "non impostato"),

                        "i2c_address": os.environ.get("UNLOOK_I2C_ADDRESS", "non impostato")

                    }

            elif command_type == 'START_SCAN':

                # Aggiorna timestamp di attività client

                self._last_client_activity = time.time()

                self.client_connected = True

                # Avvia una scansione 3D

                if self.scan_manager:

                    try:

                        # Prima verifica se la scansione 3D è supportata

                        capability_check = self.scan_manager.check_scan_capability()

                        if not capability_check.get('capability_available', False):

                            # Scansione non supportata

                            error_details = capability_check.get('details', {})

                            error_msg = "Lo scanner non supporta la scansione 3D"

                            if 'error' in error_details:

                                error_msg += f": {error_details['error']}"

                            elif 'projector_error' in error_details:

                                error_msg += f": {error_details['projector_error']}"

                            response['status'] = 'error'

                            response['message'] = error_msg

                            logger.error(f"Tentativo di scansione fallito: {error_msg}")

                            return response

                        # Se siamo qui, la scansione è supportata

                        scan_config = command.get('scan_config', None)

                        scan_result = self.scan_manager.start_scan(scan_config)

                        # Aggiorna lo stato del server

                        self.state["scanning"] = scan_result['status'] == 'success'

                        # Restituisci il risultato

                        response.update(scan_result)

                        # Log di successo o fallimento

                        if scan_result['status'] == 'success':

                            logger.info(f"Scansione avviata con ID: {scan_result.get('scan_id')}")

                        else:

                            logger.error(f"Avvio scansione fallito: {scan_result.get('message')}")


                    except Exception as e:

                        # Log dettagliato dell'errore

                        logger.error(f"Errore nell'avvio della scansione: {str(e)}")

                        import traceback

                        logger.error(f"Traceback: {traceback.format_exc()}")

                        # Aggiorna la risposta con l'errore

                        response['status'] = 'error'

                        response['message'] = f"Errore nell'avvio della scansione: {str(e)}"

                else:

                    response['status'] = 'error'

                    response['message'] = 'Funzionalità di scansione 3D non disponibile'

                    logger.error("Tentativo di avvio scansione senza scan_manager disponibile")

            elif command_type == 'STOP_SCAN':
                # Aggiorna timestamp di attività client
                self._last_client_activity = time.time()
                self.client_connected = True

                # Interrompe una scansione 3D in corso
                if self.scan_manager:
                    scan_result = self.scan_manager.stop_scan()

                    # Aggiorna lo stato del server
                    self.state["scanning"] = False

                    # Restituisci il risultato
                    response.update(scan_result)
                else:
                    response['status'] = 'error'
                    response['message'] = 'Funzionalità di scansione 3D non disponibile'

            elif command_type == 'GET_SCAN_STATUS':

                # Aggiorna timestamp di attività client

                self._last_client_activity = time.time()

                self.client_connected = True

                # Ottiene lo stato della scansione 3D in corso

                if self.scan_manager:

                    try:

                        scan_status = self.scan_manager.get_scan_status()

                        response['scan_status'] = scan_status

                        # Aggiorna anche lo stato del server

                        self.state["scanning"] = scan_status.get('state', 'IDLE') == 'SCANNING'

                        # Log dettagliato per debug

                        status_state = scan_status.get('state', 'UNKNOWN')

                        status_progress = scan_status.get('progress', 0)

                        logger.info(f"Stato scansione: {status_state}, Progresso: {status_progress:.1f}%")

                        logger.debug(f"Dettagli stato scansione: {scan_status}")

                    except Exception as e:

                        logger.error(f"Errore nell'ottenere lo stato della scansione: {e}")

                        response['status'] = 'warning'

                        response['message'] = f'Errore nel recupero dello stato: {str(e)}'

                        response['scan_status'] = {'state': 'ERROR', 'error_message': str(e)}

                else:

                    response['status'] = 'warning'

                    response['message'] = 'Funzionalità di scansione 3D non disponibile'

                    response['scan_status'] = {'state': 'ERROR', 'error_message': 'Scan manager non disponibile'}

            elif command_type == 'GET_SCAN_CONFIG':
                # Aggiorna timestamp di attività client
                self._last_client_activity = time.time()
                self.client_connected = True

                # Ottiene la configurazione di scansione 3D
                if self.scan_manager:
                    scan_config = self.scan_manager.get_scan_config()
                    response['scan_config'] = scan_config
                else:
                    response['status'] = 'warning'
                    response['message'] = 'Funzionalità di scansione 3D non disponibile'
                    response['scan_config'] = None

            elif command_type == 'PING':
                # Comando ping
                response['timestamp'] = time.time()
                # Aggiorna timestamp di attività client
                self._last_client_activity = time.time()
                # CORREZIONE: Aggiorna la connessione e salva l'IP del client
                self.client_connected = True

                # Usa l'IP del client se fornito nel messaggio
                if 'client_ip' in command:
                    self.client_ip = command.get('client_ip')
                    logger.debug(f"Ping ricevuto dal client {self.client_ip}, aggiornato timestamp attività")

            elif command_type == 'SYNC_PATTERN':

                # Aggiorna timestamp di attività client
                self._last_client_activity = time.time()
                self.client_connected = True

                # Priorità alta per scansione
                is_capture_direct = command.get('capture_direct', False)

                # Ottieni timestamp precisi
                receive_timestamp = time.time()
                client_timestamp = command.get('timestamp', 0)

                # Priorità alta per pattern di scansione
                is_high_priority = command.get('priority') == 'high'

                # Verifica che il gestore di scansione sia disponibile
                if not self.scan_manager:
                    response['status'] = 'error'
                    response['message'] = 'Scan manager non disponibile'
                    return response

                # Estrai indice pattern
                pattern_index = command.get('pattern_index', -1)

                if pattern_index < 0:
                    response['status'] = 'error'
                    response['message'] = 'Indice pattern non valido'
                    return response

                # Sincronizza con proiezione prioritaria se richiesto
                if is_high_priority:
                    # Interrompi temporaneamente altre attività
                    # per garantire risposta rapida
                    try:
                        # Imposta priorità thread
                        import os
                        current_priority = os.nice(0)
                        os.nice(-10 - current_priority)  # Aumenta temporaneamente
                    except:
                        pass

                # Timestamp preciso pre-proiezione
                pre_projection_timestamp = time.time()

                # Sincronizza la proiezione
                sync_result = self.scan_manager.sync_pattern_projection(pattern_index)

                # Timestamp post-proiezione
                projection_timestamp = time.time()
                projection_time_ms = int((projection_timestamp - pre_projection_timestamp) * 1000)

                # Incorpora risultato e timestamp nella risposta
                response.update(sync_result)
                response["receive_timestamp"] = receive_timestamp
                response["pre_projection_timestamp"] = pre_projection_timestamp
                response["projection_timestamp"] = projection_timestamp
                response["projection_time_ms"] = projection_time_ms
                response["client_timestamp"] = client_timestamp

                # Ripristina priorità se modificata
                if is_high_priority:
                    try:
                        import os
                        os.nice(0)  # Ripristina priorità normale

                    except:
                        pass
            else:
                # Comando sconosciuto
                response['status'] = 'error'
                response['error'] = f'Comando sconosciuto: {command_type}'

            logger.debug(f"Risposta a {command_type} (ID: {command_id}): {json.dumps(response)[:200]}...")
            return response

        except Exception as e:
            logger.error(f"Errore nell'elaborazione del comando {command_type}: {e}")
            response['status'] = 'error'
            response['error'] = str(e)
            return response

    def _check_client_activity(self):
        """
        Verifica se il client è ancora attivo ma non disconnette automaticamente.
        """
        if not self.client_connected:
            return

        current_time = time.time()
        time_since_last_activity = current_time - self._last_client_activity

        # MIGLIORAMENTO: Disattivato il timeout di disconnessione automatica
        # Sostituito con un semplice log di avviso ogni 60 secondi

        if time_since_last_activity > 60.0 and (time_since_last_activity % 60.0) < 1.0:
            client_id = self.client_ip if self.client_ip else "sconosciuto"
            logger.info(
                f"Il client {client_id} risulta inattivo da {time_since_last_activity:.1f} secondi, "
                f"ma mantengo la connessione attiva."
            )

        # Non fermiamo più lo streaming né la scansione automaticamente

    def _check_client_activity_loop(self):
        """
        Loop di controllo per il monitoraggio dell'attività client.
        """
        while self.running:
            try:
                self._check_client_activity()
                time.sleep(5.0)  # Controlla ogni 5 secondi
            except Exception as e:
                logger.error(f"Errore nel controllo attività client: {e}")
                time.sleep(5.0)  # Continua comunque

    def _update_config(self, new_config: Dict[str, Any]):
        """
        Aggiorna la configurazione del server con gestione migliorata per le modalità camera.

        Args:
            new_config: Nuova configurazione
        """
        logger.info("Applicazione nuova configurazione...")

        # Interrompi lo streaming se attivo (dovrebbe già essere fermato nella funzione chiamante)
        was_streaming = self.state["streaming"]
        if was_streaming:
            self.stop_streaming()
            time.sleep(0.5)  # Assicura che lo streaming sia completamente fermato

        try:
            # Verifica se ci sono modifiche alle modalità delle camere
            # Se una camera cambia modalità, imposta entrambe le camere alla stessa modalità
            camera_mode_changed = False
            target_mode = None

            if "camera" in new_config:
                # Verifica se c'è una modifica alla modalità di una fotocamera
                if "left" in new_config["camera"] and "mode" in new_config["camera"]["left"]:
                    target_mode = new_config["camera"]["left"]["mode"]
                    camera_mode_changed = True
                elif "right" in new_config["camera"] and "mode" in new_config["camera"]["right"]:
                    target_mode = new_config["camera"]["right"]["mode"]
                    camera_mode_changed = True

                # Se c'è una modifica alla modalità, applica la stessa modalità a entrambe le camere
                if camera_mode_changed and target_mode:
                    logger.info(f"Cambio modalità camera rilevato. Impostazione di entrambe le camere a: {target_mode}")

                    # Imposta entrambe le camere alla stessa modalità
                    if "left" in new_config["camera"]:
                        new_config["camera"]["left"]["mode"] = target_mode
                    else:
                        # Se left non è presente nel nuovo config, crealo
                        if "left" not in new_config["camera"]:
                            new_config["camera"]["left"] = {}
                        new_config["camera"]["left"]["mode"] = target_mode

                    if "right" in new_config["camera"]:
                        new_config["camera"]["right"]["mode"] = target_mode
                    else:
                        # Se right non è presente nel nuovo config, crealo
                        if "right" not in new_config["camera"]:
                            new_config["camera"]["right"] = {}
                        new_config["camera"]["right"]["mode"] = target_mode

            # Verifica se ci sono modifiche alla configurazione di scansione
            if "scan" in new_config and self.scan_manager:
                logger.info("Aggiornamento configurazione di scansione")
                # Aggiorna la configurazione del gestore di scansione

            # Aggiorna ricorsivamente la configurazione
            self._update_dict_recursive(self.config, new_config)

            # Correggi i formati non supportati
            if "camera" in new_config:
                for cam_name in ["left", "right"]:
                    if cam_name in new_config["camera"]:
                        if "format" in new_config["camera"][cam_name] and new_config["camera"][cam_name][
                            "format"] == "GREY":
                            # Correggi il formato non supportato
                            self.config["camera"][cam_name]["format"] = "RGB888"
                            logger.info(f"Formato GREY non supportato, convertito a RGB888 per camera {cam_name}")

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

            logger.info("Configurazione aggiornata con successo")

        except Exception as e:
            logger.error(f"Errore nell'aggiornamento della configurazione: {e}")
            raise
        finally:
            # Se lo streaming era attivo, riavvialo
            if was_streaming:
                # Nella funzione chiamante verrà riavviato lo streaming
                pass

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
        Applica la configurazione alle camere con supporto per i controlli disponibili.
        """
        # Lista dei controlli supportati da PiCamera2
        supported_controls = ["ExposureTime", "FrameRate", "AnalogueGain",
                              "Brightness", "Contrast", "Saturation", "Sharpness"]

        # Se lo streaming è attivo, fermalo
        was_streaming = self.state["streaming"]
        if was_streaming:
            self.stop_streaming()

        # Riavvia le camere con la nuova configurazione
        for cam_info in self.cameras:
            try:
                camera = cam_info["camera"]

                # Ferma la camera se è attiva
                if camera.started:
                    camera.stop()
                    time.sleep(0.2)

                # Ottieni la configurazione
                if cam_info["name"] == "left":
                    cam_config = self.config["camera"]["left"]
                else:
                    cam_config = self.config["camera"]["right"]

                # Aggiorna la modalità della camera
                if "mode" in cam_config:
                    cam_info["mode"] = cam_config["mode"]
                    logger.info(f"Impostazione camera {cam_info['name']} in modalità {cam_config['mode']}")

                # Assicurati di usare RGB888 come formato di base
                format_str = "RGB888"

                # Prepara i controlli supportati
                controls = {"FrameRate": cam_config.get("framerate", 30)}

                # Esposizione - usa ExposureTime direttamente
                if "exposure" in cam_config:
                    exposure_val = int(cam_config["exposure"] * 10000 / 100)  # 0-100 a 0-10000
                    controls["ExposureTime"] = exposure_val
                    logger.info(f"Camera {cam_info['name']} esposizione: {exposure_val}")

                # Gain - usa AnalogueGain direttamente (senza AgcEnable)
                if "gain" in cam_config:
                    gain_val = cam_config["gain"] / 100.0 * 10.0  # 0-100 a 0-10
                    controls["AnalogueGain"] = gain_val
                    logger.info(f"Camera {cam_info['name']} gain: {gain_val}")

                # Altri controlli
                if "brightness" in cam_config:
                    brightness_val = (cam_config["brightness"] / 100.0) * 2.0 - 1.0  # -1.0 a 1.0
                    controls["Brightness"] = brightness_val

                if "contrast" in cam_config:
                    contrast_val = cam_config["contrast"] / 50.0  # 0-2.0
                    controls["Contrast"] = contrast_val

                if "saturation" in cam_config and format_str != "GREY":
                    saturation_val = cam_config["saturation"] / 50.0  # 0-2.0
                    controls["Saturation"] = saturation_val

                if "sharpness" in cam_config:
                    sharpness_val = cam_config["sharpness"] / 100.0
                    controls["Sharpness"] = sharpness_val

                # Applica la configurazione
                try:
                    logger.info(f"Applicazione nuova configurazione alla camera {cam_info['name']}")

                    # Configurazione semplificata
                    camera_config = camera.create_video_configuration(
                        main={"size": tuple(cam_config["resolution"]),
                              "format": format_str},
                        controls=controls
                    )

                    # Configura e avvia
                    camera.configure(camera_config)
                    camera.start()
                    logger.info(f"Configurazione applicata con successo alla camera {cam_info['name']}")

                except Exception as e:
                    logger.error(
                        f"Errore durante l'applicazione della configurazione alla camera {cam_info['name']}: {e}")

                    # Tenta comunque di avviare la camera
                    try:
                        camera.start()
                        logger.info(f"Camera {cam_info['name']} avviata con configurazione di base")
                    except Exception as e2:
                        logger.error(f"Errore nel riavvio della camera {cam_info['name']}: {e2}")

            except Exception as e:
                logger.error(f"Errore nell'applicazione della configurazione alla camera {cam_info['name']}: {e}")

        # Il riavvio dello streaming sarà gestito dalla funzione chiamante

    def start_streaming(self):
        """
        Avvia lo streaming video con miglior gestione delle modalità.
        """
        if self.state["streaming"]:
            logger.warning("Lo streaming è già attivo")
            return

        logger.info("Avvio dello streaming video...")

        # Avvia un thread di streaming per ogni camera
        self.stream_threads = []
        for cam_info in self.cameras:
            # Ottieni la modalità corrente
            mode = cam_info.get("mode", "color")
            logger.info(f"Avvio streaming camera {cam_info['index']} ({cam_info['name']}) in modalità {mode}")

            thread = threading.Thread(
                target=self._stream_camera,
                args=(cam_info["camera"], cam_info["index"], mode)
            )
            thread.daemon = True
            thread.start()
            self.stream_threads.append(thread)

        # Aggiorna lo stato
        self.state["streaming"] = True
        self._streaming_start_time = time.time()
        self._frame_count = 0  # Reset contatore frame
        logger.info("Streaming video avviato")

    def stop_streaming(self):
        """
        Ferma lo streaming video.
        """
        if not self.state["streaming"]:
            return

        logger.info("Arresto dello streaming video...")

        # Aggiorna lo stato
        self.state["streaming"] = False

        # Attendi che i thread di streaming terminino
        for thread in self.stream_threads:
            if thread.is_alive():
                thread.join(timeout=2.0)

        self.stream_threads = []

        # Calcola statistiche totali
        if self._streaming_start_time > 0 and self._frame_count > 0:
            total_time = time.time() - self._streaming_start_time
            if total_time > 0:
                avg_fps = self._frame_count / total_time
                logger.info(f"Statistiche streaming: {self._frame_count} frame in {total_time:.1f}s, "
                            f"media {avg_fps:.1f} FPS")

        logger.info("Streaming video arrestato")

    def _stream_camera(self, camera: "Picamera2", camera_index: int, mode: str = "color"):
        """
        Funzione di streaming ottimizzata che utilizza l'API di PiCamera2 con fallback a OpenCV.
        Gestisce entrambe le modalità di cattura e robusto fallback in caso di errori.

        Args:
            camera: Oggetto Picamera2
            camera_index: Indice della camera
            mode: Modalità di visualizzazione ("color" o "grayscale")
        """
        logger.info(f"Thread di streaming camera {camera_index} avviato, modalità={mode}")

        # Verifica che la camera sia avviata
        if not camera.started:
            try:
                camera.start()
                logger.info(f"Camera {camera_index} avviata")
            except Exception as e:
                logger.error(f"Impossibile avviare camera {camera_index}: {e}")
                return

        # Configurazioni base
        quality = max(70, min(92, self._jpeg_quality))  # Qualità bilanciata
        frame_interval = max(0.016, self._frame_interval)  # Limita a 60 FPS max

        # Importazioni per la codifica JPEG
        from io import BytesIO
        from PIL import Image
        import struct
        import simplejpeg  # Import migliorato per la compressione

        # Flag per utilizzo dell'encoder hardware (tenta all'inizio, fallback a software)
        use_hardware_encoder = True

        # Contatori errori per gestione fallback
        hardware_errors = 0

        # Encoder JPEG (inizializzato quando necessario)
        jpeg_encoder = None

        # Statistiche
        frame_count = 0
        last_stats_time = time.time()
        next_frame_time = time.time()

        # Loop principale di streaming
        while self.state["streaming"] and self.running:
            try:
                current_time = time.time()

                # Controllo di flusso semplice
                if current_time < next_frame_time:
                    sleep_time = next_frame_time - current_time
                    if sleep_time > 0.001:
                        time.sleep(sleep_time)

                # Aggiorna timestamp per prossimo frame
                next_frame_time = time.time() + frame_interval

                # 1. Cattura frame - con gestione robusta degli errori
                try:
                    timestamp = time.time()  # Timestamp preciso

                    # Metodo di cattura principale
                    frame = camera.capture_array("main")

                    # Verifica frame
                    if frame is None or frame.size == 0:
                        logger.warning(f"Frame vuoto ricevuto dalla camera {camera_index}, ritento con capture_array")
                        frame = camera.capture_array()
                        if frame is None or frame.size == 0:
                            time.sleep(0.01)
                            continue

                    # 2. Converti in grayscale se necessario
                    if mode == "grayscale" and len(frame.shape) == 3:
                        # Conversione efficiente usando pesi corretti per luminanza
                        gray_frame = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
                        frame = gray_frame

                    # 3. Compressione JPEG - tenta hardware, poi fallback a software
                    if use_hardware_encoder:
                        try:
                            # Tentativo hardware con gestione errori migliorata
                            buffer = BytesIO()

                            if len(frame.shape) == 2:  # Grayscale
                                # Usa compressione simplejpeg per grayscale
                                jpeg_data = simplejpeg.encode_jpeg(frame, quality=quality, colorspace='GRAY')
                                frame_data = jpeg_data
                            else:  # RGB
                                # Converte BGR se necessario (PiCamera2 può fornire RGB o BGR)
                                if hasattr(camera, 'camera_config') and camera.camera_config.main.format == "RGB888":
                                    # Converti RGB->BGR per OpenCV
                                    frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

                                # Usa Pillow che è più stabile di simplejpeg per immagini RGB
                                pil_img = Image.fromarray(frame, mode="RGB" if frame.shape[2] == 3 else "RGBA")
                                pil_img.save(buffer, format="JPEG", quality=quality, optimize=False)
                                frame_data = buffer.getvalue()

                        except Exception as e:
                            hardware_errors += 1
                            logger.warning(f"Errore encoder hardware (#{hardware_errors}): {e}, passaggio a software")

                            # Dopo 3 errori, passa definitivamente al software
                            if hardware_errors >= 3:
                                use_hardware_encoder = False

                            # Fallback immediato a codifica software
                            buffer = BytesIO()
                            if len(frame.shape) == 2:  # Grayscale
                                cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, quality])[1].tofile(buffer)
                            else:  # RGB/BGR
                                cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, quality])[1].tofile(buffer)
                            frame_data = buffer.getvalue()
                    else:
                        # Codifica software diretta
                        buffer = BytesIO()
                        if len(frame.shape) == 2:  # Grayscale
                            cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, quality])[1].tofile(buffer)
                        else:  # RGB/BGR
                            cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, quality])[1].tofile(buffer)
                        frame_data = buffer.getvalue()

                    # 4. Prepara header compatto in formato binario
                    is_scan_frame = 0  # Non è un frame di scansione
                    sequence = frame_count
                    header = struct.pack('!BBdI', camera_index, is_scan_frame, timestamp, sequence)

                    # 5. Invia header e frame
                    try:
                        self.stream_socket.send(header, zmq.SNDMORE)
                        self.stream_socket.send(frame_data, copy=False)  # Zero-copy
                    except zmq.ZMQError as e:
                        if e.errno == zmq.EAGAIN:
                            logger.warning(f"Socket bloccato nell'invio, salto frame camera {camera_index}")
                            continue
                        else:
                            raise

                    # Aggiorna contatori
                    frame_count += 1
                    self._frame_count += 1

                    # Log periodico
                    if current_time - last_stats_time > 10.0:
                        elapsed = current_time - last_stats_time
                        fps = frame_count / elapsed if elapsed > 0 else 0
                        logger.info(f"Camera {camera_index}: {frame_count} frames in {elapsed:.1f}s ({fps:.1f} FPS)")
                        frame_count = 0
                        last_stats_time = current_time

                except Exception as e:
                    logger.warning(f"Errore nella cattura o invio frame camera {camera_index}: {e}")
                    time.sleep(0.01)

            except Exception as e:
                logger.warning(f"Errore nel ciclo di streaming camera {camera_index}: {e}")
                time.sleep(0.01)

        logger.info(f"Thread di streaming camera {camera_index} terminato dopo {frame_count} frame")


    def _safe_capture_with_timeout(self, camera, timeout=0.5):
        """
        Cattura un frame con timeout usando un thread separato.
        Versione robusta con gestione errori migliorata.

        Args:
            camera: Oggetto Picamera2
            timeout: Timeout in secondi

        Returns:
            Frame acquisito o None in caso di timeout/errore
        """
        result = [None]
        error_info = [None]

        def capture_thread():
            try:
                result[0] = camera.capture_array()
            except Exception as e:
                error_info[0] = str(e)
                logger.error(f"Errore nella cattura: {e}")
                result[0] = None

        # Avvia thread di cattura
        t = threading.Thread(target=capture_thread)
        t.daemon = True
        t.start()

        # Attendi con timeout
        t.join(timeout)

        # Se il thread è ancora vivo, la cattura è in timeout
        if t.is_alive():
            logger.warning(f"Timeout ({timeout}s) nella cattura del frame")
            return None

        # Se c'è stato un errore, logga dettagli
        if error_info[0]:
            logger.warning(f"Errore cattura: {error_info[0]}")

        # Verifica che il frame sia valido
        if result[0] is not None:
            if result[0].size == 0 or not isinstance(result[0], np.ndarray):
                logger.warning("Frame non valido (vuoto o tipo errato)")
                return None

        return result[0]

    def _capture_frames(self) -> bool:
        """
        Cattura un singolo frame da tutte le camere attive.

        Returns:
            True se la cattura è riuscita, False altrimenti
        """
        try:
            # Timestamp per il nome del file
            timestamp = time.strftime("%Y%m%d_%H%M%S")

            # Crea la directory per i frame
            capture_dir = CAPTURE_DIR
            capture_dir.mkdir(parents=True, exist_ok=True)

            # Cattura i frame da tutte le camere
            for cam_info in self.cameras:
                camera = cam_info["camera"]
                name = cam_info["name"]

                try:
                    # Cattura il frame
                    frame = camera.capture_array()

                    # Conversione in base alla modalità
                    mode = cam_info.get("mode", "color")
                    if mode == "grayscale" and len(frame.shape) == 3:
                        # Converti in scala di grigi via software
                        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)

                    # Salva il frame come PNG
                    file_path = capture_dir / f"frame_{timestamp}_{name}.png"

                    # Conversione e salvataggio usando OpenCV (più affidabile)
                    cv2.imwrite(str(file_path), frame)

                    logger.info(f"Frame catturato dalla camera {name}: {file_path}")
                except Exception as e:
                    logger.error(f"Errore nella cattura del frame dalla camera {name}: {e}")

            return True

        except Exception as e:
            logger.error(f"Errore nella cattura dei frame: {e}")
            return False


def main():
    """
    Funzione principale.
    """
    # Parse degli argomenti
    parser = argparse.ArgumentParser(description='UnLook Scanner Server')
    parser.add_argument('-c', '--config', type=str, help='Percorso del file di configurazione')
    parser.add_argument('-p', '--port', type=int, help='Porta per i comandi (default dal config)')
    parser.add_argument('--quality', type=int, help='Qualità JPEG (5-95, default 90)', default=85)
    parser.add_argument('--fps', type=int, help='FPS target (5-60, default 30)', default=30)
    parser.add_argument('--debug', action='store_true', help='Abilita il livello di log DEBUG')
    parser.add_argument('--i2c-bus', type=int, help='Bus I2C per il proiettore DLP', default=3)
    parser.add_argument('--i2c-address', type=str, help='Indirizzo I2C per il proiettore DLP', default="0x36")
    args = parser.parse_args()

    # Imposta priorità real-time all'avvio
    set_realtime_priority()
    
    # Imposta il livello di log
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # Imposta variabili d'ambiente per ScanManager
    os.environ["UNLOOK_I2C_BUS"] = str(args.i2c_bus)
    os.environ["UNLOOK_I2C_ADDRESS"] = args.i2c_address

    # Inizializza il proiettore a nero
    try:
        from server.projector.dlp342x import DLPC342XController, OperatingMode, Color, BorderEnable
        logger.info(f"Tentativo di inizializzazione del proiettore con bus={args.i2c_bus}, address={args.i2c_address}")

        # Converti l'indirizzo nel formato corretto
        address = int(args.i2c_address, 16) if args.i2c_address.startswith("0x") else int(args.i2c_address)

        # Crea il controller e imposta una sequenza più robusta
        projector = DLPC342XController(bus=args.i2c_bus, address=address)

        # Prima ottieni lo stato attuale per verificare la connessione
        try:
            current_mode = projector.get_operating_mode()
            logger.info(f"Modalità attuale del proiettore: {current_mode}")
        except Exception as e:
            logger.warning(f"Impossibile leggere la modalità attuale: {e}")

        # Imposta la modalità pattern generator con un timeout più lungo
        projector.set_operating_mode(OperatingMode.TestPatternGenerator)
        logger.info("Impostata modalità TestPatternGenerator")
        time.sleep(1.0)  # Aumentiamo il tempo di attesa

        # Ripeti la generazione del pattern nero 3 volte per assicurarci
        for i in range(3):
            try:
                projector.generate_solid_field(Color.Black)
                logger.info(f"Pattern nero generato (tentativo {i + 1}/3)")
                time.sleep(0.3)  # Breve pausa tra i tentativi
            except Exception as e:
                logger.warning(f"Errore nella generazione del pattern nero (tentativo {i + 1}/3): {e}")

        # Disabilita il bordo
        try:
            projector.set_display_border(BorderEnable.Disable)
            logger.info("Bordo disabilitato")
        except Exception as e:
            logger.warning(f"Errore nella disabilitazione del bordo: {e}")

        # Verifica finale
        time.sleep(0.5)
        logger.info("Proiettore inizializzato a nero all'avvio del server")
    except Exception as e:
        logger.warning(f"Impossibile inizializzare il proiettore all'avvio: {e}")
        import traceback
        logger.warning(f"Traceback: {traceback.format_exc()}")

    # Crea e avvia il server
    server = UnLookServer(config_path=args.config)

    # Override delle impostazioni se specificate
    if args.port:
        server.config["server"]["command_port"] = args.port

    # Imposta qualità JPEG e FPS target
    server._jpeg_quality = max(70, min(95, args.quality))
    fps = max(5, min(60, args.fps))
    server._frame_interval = 1.0 / fps

    # Aggiorna configurazione di scansione
    if server.config["scan"]:
        server.config["scan"]["i2c_bus"] = args.i2c_bus
        server.config["scan"]["i2c_address"] = args.i2c_address

    logger.info(f"Parametri di avvio: FPS={fps}, qualità={server._jpeg_quality}, HWM=1")

    # Gestione dei segnali per un arresto pulito
    def signal_handler(sig, frame):
        logger.info("Segnale di interruzione ricevuto. Arresto in corso...")
        server.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Avvia il server
    server.start()

    # Loop principale
    try:
        logger.info("Server UnLook in esecuzione. Premi Ctrl+C per terminare.")
        logger.info(f"Identificatore UUID dispositivo: {server.device_id}")
        logger.info("Ricorda di etichettare il case con questo UUID!")

        # Capacità
        has_scanning = server.scan_manager is not None
        logger.info(f"Capacità di scansione 3D: {'Disponibile' if has_scanning else 'Non disponibile'}")
        logger.info(f"Numero di camere: {len(server.cameras)}")

        # Mantieni il thread principale attivo
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        logger.info("Interruzione da tastiera ricevuta. Arresto in corso...")
    finally:
        server.stop()


if __name__ == "__main__":
    main()