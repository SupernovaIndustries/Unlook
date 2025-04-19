#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
UnLook Scanner Server - Applicazione server per il Raspberry Pi
Gestisce le camere e lo streaming video verso il client.
Versione ottimizzata con controllo di flusso e riduzione della latenza.
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

# Configurazione percorsi
PROJECT_DIR = Path(__file__).parent.absolute()
LOG_DIR = PROJECT_DIR / "logs"
CONFIG_DIR = PROJECT_DIR / "config"
CAPTURE_DIR = PROJECT_DIR / "captures"

# Assicura che le directory esistano
LOG_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
CAPTURE_DIR.mkdir(parents=True, exist_ok=True)

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

# Importazioni necessarie
try:
    import zmq
    import numpy as np
    from picamera2 import Picamera2
    import cv2
except ImportError as e:
    logger.error(f"Dipendenza mancante: {e}")
    logger.error("Installa le dipendenze necessarie con: pip install pyzmq numpy picamera2 opencv-python")
    sys.exit(1)


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
            "start_time": time.time()
        }

        # Inizializza i socket di comunicazione
        self.broadcast_socket = None
        self.context = zmq.Context()
        self.command_socket = self.context.socket(zmq.REP)  # Socket per i comandi (REP)
        self.stream_socket = self.context.socket(zmq.PUB)  # Socket per lo streaming (PUB)

        # Inizializza i thread
        self.broadcast_thread = None
        self.command_thread = None
        self.stream_threads = []

        # Controllo di flusso
        self._frame_interval = 1.0 / 30.0  # Intervallo iniziale per 30 FPS
        self._dynamic_interval = True  # Regolazione dinamica dell'intervallo
        self._last_frame_time = 0
        self._streaming_start_time = 0
        self._frame_count = 0

        # Informazioni sul client
        self.client_connected = False
        self.client_ip = None
        self._last_client_activity = 0

        # Parametri di qualità dell'immagine
        self._jpeg_quality = 90  # Qualità JPEG ottimale per bassa latenza

        logger.info(f"Server UnLook inizializzato con ID: {self.device_id}")

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
                    "format": "RGB888"
                },
                "right": {
                    "enabled": True,
                    "resolution": [1280, 720],
                    "framerate": 30,
                    "format": "RGB888"
                }
            },
            "stream": {
                "format": "jpeg",
                "quality": 90,  # Qualità JPEG (0-100)
                "max_fps": 30,  # FPS massimo
                "min_fps": 15  # FPS minimo per regolazione dinamica
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
        Inizializza le camere PiCamera2.
        """
        try:
            # Ottieni la lista delle camere disponibili
            cam_list = Picamera2.global_camera_info()
            logger.info(f"Camere disponibili: {len(cam_list)}")

            # Se non ci sono camere, esci
            if not cam_list:
                logger.error("Nessuna camera trovata!")
                return

            # Inizializza la camera sinistra
            if self.config["camera"]["left"]["enabled"] and len(cam_list) > 0:
                left_camera = Picamera2(0)  # Camera 0

                # Configura la camera
                left_config = self.config["camera"]["left"]
                camera_config = left_camera.create_video_configuration(
                    main={"size": tuple(left_config["resolution"]),
                          "format": left_config["format"]},
                    controls={"FrameRate": left_config["framerate"]}
                )
                left_camera.configure(camera_config)

                self.cameras.append({"index": 0, "camera": left_camera, "name": "left"})
                logger.info("Camera sinistra inizializzata")

            # Inizializza la camera destra
            if self.config["camera"]["right"]["enabled"] and len(cam_list) > 1:
                right_camera = Picamera2(1)  # Camera 1

                # Configura la camera
                right_config = self.config["camera"]["right"]
                camera_config = right_camera.create_video_configuration(
                    main={"size": tuple(right_config["resolution"]),
                          "format": right_config["format"]},
                    controls={"FrameRate": right_config["framerate"]}
                )
                right_camera.configure(camera_config)

                self.cameras.append({"index": 1, "camera": right_camera, "name": "right"})
                logger.info("Camera destra inizializzata")

            logger.info(f"Camere inizializzate: {len(self.cameras)}")

        except Exception as e:
            logger.error(f"Errore nell'inizializzazione delle camere: {e}")

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

            # Avvia le camere
            for cam_info in self.cameras:
                cam_info["camera"].start()
                logger.info(f"Camera {cam_info['name']} avviata")

            # Apri i socket
            command_port = self.config["server"]["command_port"]
            stream_port = self.config["server"]["stream_port"]

            self.command_socket.bind(f"tcp://*:{command_port}")

            # Configurazione ottimizzata del socket di streaming
            # Imposta un valore di HWM basso ma sicuro per messaggi multipart
            self.stream_socket.setsockopt(zmq.SNDHWM, 3)
            # Non impostare CONFLATE per evitare problemi con messaggi multipart
            self.stream_socket.bind(f"tcp://*:{stream_port}")

            logger.info(f"Socket di comando in ascolto su porta {command_port}")
            logger.info(f"Socket di streaming in ascolto su porta {stream_port}")

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

            logger.info("Server UnLook avviato con successo")
            logger.info(
                f"Controllo di flusso: intervallo={self._frame_interval * 1000:.1f}ms, dinamico={self._dynamic_interval}")
            logger.info(f"Qualità JPEG: {self._jpeg_quality}")

        except Exception as e:
            logger.error(f"Errore nell'avvio del server: {e}")
            self.stop()

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

        # Ferma il servizio di broadcast
        if self.broadcast_thread and self.broadcast_thread.is_alive():
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
                            "dlp": False
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
        Versione migliorata con gestione della disconnessione e tracciamento dell'attività.
        """
        command_type = command.get('type', '')
        logger.info(f"Elaborazione comando: {command_type}")

        # Aggiorna il timestamp dell'ultima attività del client
        self._last_client_activity = time.time()

        # Ottieni l'indirizzo IP del client se disponibile
        client_ip = command.get('client_ip', None)
        if client_ip and client_ip != self.client_ip:
            self.client_ip = client_ip
            logger.info(f"Aggiornato indirizzo IP client: {client_ip}")

        # Prepara una risposta base
        response = {
            "status": "ok",
            "type": f"{command_type}_response"
        }

        try:
            if command_type == 'PING':
                # Comando ping/heartbeat
                response['timestamp'] = time.time()
                # Considera il client connesso
                self.client_connected = True
                self.state["clients_connected"] = 1

            elif command_type == 'GET_STATUS':
                # Aggiorna lo stato
                self.state['uptime'] = time.time() - self.state['start_time']
                # Aggiungi lo stato alla risposta
                response['state'] = self.state

            elif command_type == 'START_STREAM':
                # Avvia lo streaming
                if not self.state["streaming"]:
                    logger.info(f"Avvio streaming richiesto da client {self.client_ip}")

                    # Reset delle statistiche di streaming
                    self._frame_count = 0
                    self._streaming_start_time = time.time()
                    self._last_frame_time = 0

                    # Imposta il nuovo valore di qualità JPEG se richiesto
                    if 'quality' in command and isinstance(command['quality'], int):
                        self._jpeg_quality = max(70, min(95, command['quality']))
                        logger.info(f"Qualità JPEG impostata a {self._jpeg_quality}")

                    # Imposta il nuovo target FPS se richiesto
                    if 'target_fps' in command and isinstance(command['target_fps'], int):
                        target_fps = max(5, min(60, command['target_fps']))
                        self._frame_interval = 1.0 / target_fps
                        logger.info(
                            f"Target FPS impostato a {target_fps} (intervallo={self._frame_interval * 1000:.1f}ms)")

                    self.start_streaming()
                    response['streaming'] = True
                    response['message'] = "Streaming avviato"
                else:
                    logger.info("Lo streaming è già attivo, ignorata richiesta di avvio")
                    response['streaming'] = True
                    response['message'] = "Streaming già attivo"

            elif command_type == 'STOP_STREAM':
                # Ferma lo streaming
                if self.state["streaming"]:
                    logger.info(f"Arresto streaming richiesto da client {self.client_ip}")
                    self.stop_streaming()
                    response['streaming'] = False
                    response['message'] = "Streaming arrestato"
                else:
                    logger.info("Lo streaming non è attivo, ignorata richiesta di arresto")
                    response['streaming'] = False
                    response['message'] = "Streaming non attivo"

            elif command_type == 'DISCONNECT':
                # Il client si disconnette esplicitamente
                logger.info(f"Il client {self.client_ip} ha richiesto la disconnessione esplicita")

                # Ferma lo streaming se attivo
                if self.state["streaming"]:
                    logger.info("Arresto dello streaming per disconnessione client")
                    self.stop_streaming()

                # Aggiorna lo stato
                self.client_connected = False
                self.client_ip = None
                self.state["clients_connected"] = 0

                response['disconnected'] = True
                response['message'] = "Disconnessione completata"

            elif command_type == 'SET_CONFIG':
                # Aggiorna la configurazione
                if 'config' in command:
                    self._update_config(command['config'])
                    response['config_updated'] = True

                    # Se la configurazione include parametri di streaming, aggiornali
                    if 'stream' in command['config']:
                        stream_config = command['config']['stream']
                        if 'quality' in stream_config:
                            self._jpeg_quality = max(70, min(95, stream_config["quality"]))
                            logger.info(f"Qualità streaming aggiornata: {self._jpeg_quality}")

                    # Se la configurazione include parametri del server, aggiornali
                    if 'server' in command['config']:
                        server_config = command['config']['server']
                        if 'frame_interval' in server_config:
                            self._frame_interval = server_config["frame_interval"]
                            logger.info(f"Intervallo frame aggiornato: {self._frame_interval}")
                        if 'dynamic_fps' in server_config:
                            self._dynamic_interval = server_config["dynamic_fps"]
                            logger.info(f"FPS dinamico: {self._dynamic_interval}")
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
                else:
                    response['status'] = 'error'
                    response['error'] = 'Errore nella cattura dei frame'

            else:
                # Comando sconosciuto
                response['status'] = 'error'
                response['error'] = f'Comando sconosciuto: {command_type}'

        except Exception as e:
            logger.error(f"Errore nell'elaborazione del comando {command_type}: {e}")
            response['status'] = 'error'
            response['error'] = str(e)

        return response

    def _check_client_activity(self):
        """
        Verifica se il client è ancora attivo e, in caso contrario, rilascia le risorse.
        Da chiamare periodicamente nel loop principale.
        """
        if not self.client_connected:
            return

        current_time = time.time()
        time_since_last_activity = current_time - self._last_client_activity

        # Se non si hanno notizie dal client per più di 10 secondi, considerarlo disconnesso
        if time_since_last_activity > 10.0:
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
        while self.running:
            try:
                self._check_client_activity()
                time.sleep(5.0)  # Controlla ogni 5 secondi
            except Exception as e:
                logger.error(f"Errore nel controllo attività client: {e}")
                time.sleep(5.0)  # Continua comunque

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
        Versione migliorata con supporto per modalità colore/scala di grigi.
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
                if "mode" in cam_config:
                    if cam_config["mode"] == "grayscale":
                        format_str = "GREY"
                        logger.info(f"Camera {cam_info['name']} impostata in modalità scala di grigi")
                    else:  # color
                        format_str = "RGB888"
                        logger.info(f"Camera {cam_info['name']} impostata in modalità colore")

                # Applica i controlli avanzati se presenti
                controls = {"FrameRate": cam_config.get("framerate", 30)}

                # Controlla se ci sono altre impostazioni da applicare
                if "exposure" in cam_config:
                    # Converti da 0-100 a valori appropriati per la camera
                    # AEC e AGC potrebbero dover essere disabilitati per controllo manuale
                    controls["AeEnable"] = 0  # Disabilita auto-esposizione
                    # Mappa da 0-100 a un valore di esposizione appropriato (dipende dall'hardware)
                    exposure_val = int(cam_config["exposure"] * 10000 / 100)  # esempio mappatura
                    controls["ExposureTime"] = exposure_val
                    logger.info(f"Camera {cam_info['name']} esposizione: {exposure_val}")

                if "gain" in cam_config:
                    controls["AgcEnable"] = 0  # Disabilita auto-gain
                    gain_val = cam_config["gain"] / 100.0 * 10.0  # Mappa 0-100 a 0-10
                    controls["AnalogueGain"] = gain_val
                    logger.info(f"Camera {cam_info['name']} gain: {gain_val}")

                if "brightness" in cam_config:
                    # Mappa 0-100 a valore appropriato per la camera
                    brightness_val = (cam_config["brightness"] / 100.0) * 2.0 - 1.0  # -1.0 a 1.0
                    controls["Brightness"] = brightness_val

                if "contrast" in cam_config:
                    # Mappa 0-100 a valore appropriato per la camera
                    contrast_val = cam_config["contrast"] / 50.0  # 0-2.0, 1.0 è neutro
                    controls["Contrast"] = contrast_val

                if "saturation" in cam_config and format_str != "GREY":
                    # Mappa 0-100 a valore appropriato per la camera
                    saturation_val = cam_config["saturation"] / 50.0  # 0-2.0, 1.0 è neutro
                    controls["Saturation"] = saturation_val

                if "sharpness" in cam_config:
                    # Mappa 0-100 a valore appropriato per la camera
                    sharpness_val = cam_config["sharpness"] / 100.0
                    controls["Sharpness"] = sharpness_val

                # Applica la configurazione
                camera_config = camera.create_video_configuration(
                    main={"size": tuple(cam_config["resolution"]),
                          "format": format_str},
                    controls=controls
                )
                camera.configure(camera_config)

                # Riavvia la camera
                camera.start()
                logger.info(f"Configurazione applicata alla camera {cam_info['name']}")

            except Exception as e:
                logger.error(f"Errore nell'applicazione della configurazione alla camera {cam_info['name']}: {e}")

        # Riavvia lo streaming se era attivo
        if was_streaming:
            self.start_streaming()

    def start_streaming(self):
        """
        Avvia lo streaming video.
        """
        if self.state["streaming"]:
            logger.warning("Lo streaming è già attivo")
            return

        logger.info("Avvio dello streaming video...")

        # Avvia un thread di streaming per ogni camera
        self.stream_threads = []
        for cam_info in self.cameras:
            thread = threading.Thread(
                target=self._stream_camera,
                args=(cam_info["camera"], cam_info["index"])
            )
            thread.daemon = True
            thread.start()
            self.stream_threads.append(thread)

        # Aggiorna lo stato
        self.state["streaming"] = True
        self._streaming_start_time = time.time()
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

    def _stream_camera(self, camera: "Picamera2", camera_index: int):
        """
        Funzione ottimizzata che gestisce lo streaming di una camera.
        Versione con latenza ridotta e controllo di flusso adattivo.
        """
        logger.info(f"Thread di streaming camera {camera_index} avviato")

        try:
            # Ottieni parametri di configurazione
            quality = self._jpeg_quality

            # Configura intervallo iniziale
            current_interval = self._frame_interval
            min_interval = 1.0 / 60  # massimo 60 FPS

            # Loop principale per lo streaming
            local_frame_count = 0
            start_time = time.time()
            last_stats_time = start_time
            last_frame_time = 0
            next_frame_time = 0

            # Imposta priorità del thread di streaming
            try:
                import os
                # Cerca di impostare priorità alta su sistemi Linux
                os.nice(-10)
            except:
                pass

            while self.state["streaming"] and self.running:
                try:
                    # Controllo di flusso basato su tempo per mantenere FPS stabile
                    current_time = time.time()

                    # Attendi fino al prossimo frame programmato per rispettare l'intervallo
                    if current_time < next_frame_time:
                        wait_time = next_frame_time - current_time
                        if wait_time > 0.001:  # Attendi solo se il tempo è significativo
                            time.sleep(wait_time)
                        continue

                    # Programma il prossimo frame
                    next_frame_time = current_time + current_interval

                    # Cattura il frame
                    frame = camera.capture_array()

                    if frame is None or frame.size == 0:
                        logger.error(f"Frame vuoto dalla camera {camera_index}")
                        time.sleep(0.01)
                        continue

                    # Converti in BGR se necessario (per OpenCV)
                    if len(frame.shape) == 3 and frame.shape[2] == 4:  # RGBA
                        frame = cv2.cvtColor(frame, cv2.COLOR_RGBA2BGR)
                    elif len(frame.shape) == 2:  # Grayscale
                        frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)

                    # Comprimi in JPEG con qualità ottimizzata
                    encode_params = [cv2.IMWRITE_JPEG_QUALITY, quality]
                    success, encoded_data = cv2.imencode('.jpg', frame, encode_params)

                    if not success or encoded_data is None or encoded_data.size == 0:
                        logger.error(f"Errore nella codifica JPEG, camera {camera_index}")
                        time.sleep(0.01)
                        continue

                    # Crea l'header del messaggio
                    current_time = time.time()  # Aggiorna per timestamp preciso
                    header = {
                        "camera": camera_index,
                        "frame": local_frame_count,
                        "timestamp": current_time,
                        "format": "jpeg",
                        "resolution": [frame.shape[1], frame.shape[0]]
                    }

                    # Invia l'header e poi i dati
                    try:
                        self.stream_socket.send_json(header, zmq.SNDMORE)
                        self.stream_socket.send(encoded_data.tobytes(), copy=False)

                        # Aggiorna contatori
                        local_frame_count += 1
                        self._frame_count += 1  # Contatore globale
                        last_frame_time = current_time  # Per controllo di intervallo

                    except Exception as e:
                        logger.error(f"Errore nell'invio del frame: {e}")
                        time.sleep(0.01)
                        continue

                    # Calcola FPS ogni 30 frame
                    if local_frame_count % 30 == 0:
                        current_time = time.time()
                        elapsed = current_time - last_stats_time
                        if elapsed > 0:
                            current_fps = 30 / elapsed
                            effective_interval = elapsed / 30
                            logger.info(f"Camera {camera_index}: {current_fps:.1f} FPS "
                                        f"(intervallo={effective_interval * 1000:.1f}ms, "
                                        f"frames: {local_frame_count})")
                        last_stats_time = current_time

                except Exception as e:
                    logger.error(f"Errore nello streaming camera {camera_index}: {e}")
                    time.sleep(0.1)  # Pausa più lunga in caso di errore

        except Exception as e:
            logger.error(f"Errore fatale nello streaming camera {camera_index}: {e}")

        logger.info(f"Thread di streaming camera {camera_index} terminato")

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

                # Cattura il frame
                frame = camera.capture_array()

                # Salva il frame come PNG
                file_path = capture_dir / f"frame_{timestamp}_{name}.png"

                # Conversione e salvataggio usando PIL
                from PIL import Image
                Image.fromarray(frame).save(str(file_path))

                logger.info(f"Frame catturato dalla camera {name}: {file_path}")

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
    parser.add_argument('--quality', type=int, help='Qualità JPEG (5-95, default 90)', default=90)
    parser.add_argument('--fps', type=int, help='FPS target (5-60, default 30)', default=30)
    parser.add_argument('--debug', action='store_true', help='Abilita il livello di log DEBUG')
    args = parser.parse_args()

    # Imposta il livello di log
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # Crea e avvia il server
    server = UnLookServer(config_path=args.config)

    # Override delle impostazioni se specificate
    if args.port:
        server.config["server"]["command_port"] = args.port

    # Imposta qualità JPEG e FPS target
    server._jpeg_quality = max(70, min(95, args.quality))
    fps = max(5, min(60, args.fps))
    server._frame_interval = 1.0 / fps

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

        # Mantieni il thread principale attivo
        while server.running:
            time.sleep(1)

    except KeyboardInterrupt:
        logger.info("Interruzione da tastiera ricevuta. Arresto in corso...")
    finally:
        server.stop()


if __name__ == "__main__":
    main()