#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
UnLook Scanner Server - Applicazione server per il Raspberry Pi
Gestisce le camere e lo streaming video verso il client.
Implementa un sistema di broadcast automatico per la scoperta senza multicast.
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

# Assicura che le directory esistano
LOG_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

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
import zmq
import numpy as np
from picamera2 import Picamera2
import cv2


class UnLookServer:
    """
    Server principale che gestisce le camere e le connessioni con i client.
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

        # Assicura che le nuove chiavi di configurazione siano presenti
        self._ensure_config_keys()

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

        # Flag per tenere traccia del client connesso
        self.client_connected = False
        self.client_ip = None
        self.client_connection_time = 0

        # Mutex per proteggere l'accesso al flag client_connected
        self.client_mutex = threading.Lock()

        logger.info(f"Server UnLook inizializzato con ID: {self.device_id}")
        logger.info(f"È consigliabile etichettare il case con l'UUID: {self.device_id}")

    def _ensure_config_keys(self):
        """Assicura che tutte le chiavi di configurazione necessarie siano presenti."""
        # Verifica che la sezione server esista
        if "server" not in self.config:
            self.config["server"] = {}

        # Aggiungi le chiavi mancanti con valori predefiniti
        server_config = self.config["server"]

        if "discovery_port" not in server_config:
            server_config["discovery_port"] = 5678

        if "command_port" not in server_config:
            server_config["command_port"] = 5680

        if "stream_port" not in server_config:
            server_config["stream_port"] = 5681

        if "broadcast_port" not in server_config:
            server_config["broadcast_port"] = 5679

        if "broadcast_interval" not in server_config:
            server_config["broadcast_interval"] = 1.0

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
                "broadcast_port": 5679  # porta per il broadcast diretto
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
                "format": "h264",  # h264, mjpeg, raw
                "quality": 23,  # 0-51 per h264 (più basso è meglio)
                "bitrate": 2000000  # 2 Mbps
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
                # Salva la configurazione predefinita per futuri utilizzi
                with open(default_config_path, 'w') as f:
                    json.dump(default_config, f, indent=2)
                return default_config

        # Carica la configurazione dal file
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
                logger.info(f"Configurazione caricata da: {config_path}")
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
        Avvia il server.
        """
        if self.running:
            logger.warning("Il server è già in esecuzione")
            return

        logger.info("Avvio del server UnLook")

        try:
            # Imposta lo stato in esecuzione
            self.running = True

            # Avvia le camere
            for cam_info in self.cameras:
                cam_info["camera"].start()
                logger.info(f"Camera {cam_info['name']} avviata")

            # Apri i socket
            command_port = self.config["server"]["command_port"]
            stream_port = self.config["server"]["stream_port"]

            self.command_socket.bind(f"tcp://*:{command_port}")
            self.stream_socket.bind(f"tcp://*:{stream_port}")

            logger.info(f"Socket di comando in ascolto su porta {command_port}")
            logger.info(f"Socket di streaming in ascolto su porta {stream_port}")

            # Avvia il servizio di broadcast
            self._start_broadcast_service()

            # Avvia il loop di ricezione comandi
            self._start_command_handler()

            self.state["status"] = "running"

            logger.info("Server UnLook avviato con successo")

        except Exception as e:
            logger.error(f"Errore nell'avvio del server: {e}")
            self.stop()

    def stop(self):
        """
        Ferma il server.
        """
        logger.info("Arresto del server UnLook")

        # Imposta lo stato di arresto
        self.running = False
        self.state["status"] = "stopping"

        # Ferma lo streaming
        self.stop_streaming()

        # Ferma il servizio di broadcast
        if self.broadcast_thread and self.broadcast_thread.is_alive():
            logger.info("Arresto del servizio di broadcast...")
            if self.broadcast_socket:
                try:
                    self.broadcast_socket.close()
                except:
                    pass

        # Attendi che i thread terminino
        if self.broadcast_thread and self.broadcast_thread.is_alive():
            try:
                self.broadcast_thread.join(timeout=2.0)
            except:
                pass

        if self.command_thread and self.command_thread.is_alive():
            try:
                self.command_thread.join(timeout=2.0)
            except:
                pass

        # Chiudi i socket ZeroMQ
        logger.info("Chiusura dei socket...")
        try:
            self.command_socket.close()
            self.stream_socket.close()
            self.context.term()
        except:
            pass

        # Ferma le camere
        for cam_info in self.cameras:
            logger.info(f"Arresto della camera {cam_info['name']}...")
            try:
                cam_info["camera"].stop()
            except:
                pass

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

        # Bind socket per ricevere risposte (opzionale)
        try:
            # Usa una porta casuale per l'invio per evitare conflitti
            self.broadcast_socket.bind(('', 0))
            _, port = self.broadcast_socket.getsockname()
            logger.info(f"Socket di broadcast associato alla porta {port}")
        except Exception as e:
            logger.error(f"Errore nell'associazione del socket di broadcast: {e}")
            # Non richiedere bind, può funzionare comunque per l'invio

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
        broadcast_port = self.config["server"]["broadcast_port"]
        broadcast_interval = self.config["server"]["broadcast_interval"]
        broadcast_address = "255.255.255.255"  # Indirizzo di broadcast

        # Ottieni l'indirizzo IP locale
        local_ip = self._get_local_ip()

        logger.info(f"Broadcast loop avviato (indirizzo: {broadcast_address})")
        logger.info(f"Inviando sulla porta discovery: {discovery_port} e porta broadcast: {broadcast_port}")
        logger.info(f"Indirizzo IP locale: {local_ip}")

        msg_count = 0
        try:
            while self.running:
                try:
                    # Controlla se c'è un client connesso
                    with self.client_mutex:
                        has_client = self.client_connected

                    # Se c'è un client connesso, non inviare il broadcast
                    if has_client:
                        time.sleep(1.0)  # Controlla meno frequentemente quando connesso
                        continue

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
                    # Tenta l'invio sul socket di discovery (5678) e su quello di broadcast (5679)
                    try:
                        self.broadcast_socket.sendto(message, (broadcast_address, discovery_port))
                    except Exception as e:
                        logger.debug(f"Errore nell'invio al socket discovery: {e}")

                    try:
                        self.broadcast_socket.sendto(message, (broadcast_address, broadcast_port))
                    except Exception as e:
                        logger.debug(f"Errore nell'invio al socket broadcast: {e}")

                    msg_count += 1
                    if msg_count % 10 == 0:  # Log ogni 10 messaggi per ridurre il rumore
                        logger.info(f"Messaggio di broadcast #{msg_count} inviato")

                    # Attendi prima del prossimo invio
                    time.sleep(broadcast_interval)

                except Exception as e:
                    logger.error(f"Errore nel broadcast loop: {e}")
                    if not self.running:
                        break
                    time.sleep(1.0)  # Pausa più lunga in caso di errore

        except Exception as e:
            logger.error(f"Errore fatale nel broadcast loop: {e}")
        finally:
            logger.info("Broadcast loop terminato")

    def _start_command_handler(self):
        """
        Avvia il gestore dei comandi in un thread separato.
        """
        self.command_thread = threading.Thread(target=self._command_loop)
        self.command_thread.daemon = True
        self.command_thread.start()
        logger.info("Handler dei comandi avviato")

    def _command_loop(self):
        """
        Loop principale per la gestione dei comandi dai client.
        """
        logger.info("Command loop avviato")

        try:
            while self.running:
                try:
                    # Imposta un timeout per poter controllare regolarmente self.running
                    self.command_socket.setsockopt(zmq.RCVTIMEO, 1000)  # 1 secondo

                    # Attendi un comando
                    message = self.command_socket.recv_json()

                    # Estrai l'indirizzo del client
                    client_routing_id = self.command_socket.get_routing_id()
                    client_ip = None

                    try:
                        # Prova a ottenere l'indirizzo IP del client
                        peer_endpoint = self.command_socket.get(zmq.LAST_ENDPOINT)
                        if peer_endpoint:
                            client_ip = peer_endpoint.split("//")[1].split(":")[0]
                            logger.info(f"Comando ricevuto dal client {client_ip}")
                    except Exception as e:
                        logger.debug(f"Impossibile ottenere l'IP del client: {e}")

                    # Quando si riceve un comando, considera il client come connesso
                    if client_ip:
                        with self.client_mutex:
                            if not self.client_connected:
                                self.client_connected = True
                                self.client_ip = client_ip
                                self.client_connection_time = time.time()
                                logger.info(f"Client {client_ip} connesso")

                    # Processa il comando
                    response = self._process_command(message, client_ip)

                    # Invia la risposta
                    self.command_socket.send_json(response)

                except zmq.Again:
                    # Timeout normale, continua
                    continue
                except Exception as e:
                    logger.error(f"Errore nel command loop: {e}")
                    # Invia una risposta di errore
                    try:
                        self.command_socket.send_json({
                            "status": "error",
                            "error": str(e)
                        })
                    except:
                        pass

                    # Controlla disconnessione client
                    with self.client_mutex:
                        if self.client_connected:
                            # Se è passato troppo tempo dall'ultimo comando, considera il client disconnesso
                            if time.time() - self.client_connection_time > 120.0:  # 2 minuti di timeout
                                self.client_connected = False
                                logger.info(f"Client {self.client_ip} disconnesso (timeout)")
                                self.client_ip = None

                    time.sleep(0.1)  # Piccola pausa per evitare loop troppo rapidi

        except Exception as e:
            logger.error(f"Errore fatale nel command loop: {e}")

        logger.info("Command loop terminato")

    def _process_command(self, command: Dict[str, Any], client_ip: Optional[str] = None) -> Dict[str, Any]:
        """
        Processa un comando ricevuto da un client.

        Args:
            command: Dizionario rappresentante il comando
            client_ip: Indirizzo IP del client (se disponibile)

        Returns:
            Dizionario di risposta
        """
        command_type = command.get('type', '')
        logger.info(f"Comando ricevuto: {command_type}")

        # Aggiorna il timestamp della connessione
        with self.client_mutex:
            self.client_connection_time = time.time()

        # Prepara una risposta base
        response = {
            "status": "ok",
            "type": f"{command_type}_response"
        }

        try:
            if command_type == 'PING':
                # Comando ping
                response['timestamp'] = time.time()

            elif command_type == 'GET_STATUS':
                # Aggiorna lo stato
                self.state['uptime'] = time.time() - self.state['start_time']

                # Aggiungi lo stato alla risposta
                response['state'] = self.state


            elif command_type == 'START_STREAM':
                # Verifica se lo streaming è già attivo
                if self.state["streaming"]:
                    logger.info("Richiesta di avvio streaming ma lo streaming è già attivo")
                    response['streaming'] = True
                    response['message'] = "Streaming già attivo"
                else:
                    # Avvia lo streaming
                    logger.info("Avvio streaming richiesto dal client")
                    self.start_streaming()
                    response['streaming'] = True
                    response['message'] = "Streaming avviato"

            elif command_type == 'STOP_STREAM':
                # Verifica se lo streaming è attivo
                if not self.state["streaming"]:
                    logger.info("Richiesta di arresto streaming ma lo streaming non è attivo")
                    response['streaming'] = False
                    response['message'] = "Streaming non attivo"
                else:
                    # Ferma lo streaming
                    logger.info("Arresto streaming richiesto dal client")
                    self.stop_streaming()
                    response['streaming'] = False
                    response['message'] = "Streaming arrestato"


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
                else:
                    response['status'] = 'error'
                    response['error'] = 'Errore nella cattura dei frame'

            elif command_type == 'DISCONNECT':
                # Il client si disconnette esplicitamente
                with self.client_mutex:
                    self.client_connected = False
                    logger.info(f"Client {self.client_ip} disconnesso (esplicito)")
                    self.client_ip = None
                response['disconnected'] = True

            else:
                # Comando sconosciuto
                response['status'] = 'error'
                response['error'] = f'Comando sconosciuto: {command_type}'

        except Exception as e:
            logger.error(f"Errore nell'elaborazione del comando {command_type}: {e}")
            response['status'] = 'error'
            response['error'] = str(e)

        return response

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

                # Applica la configurazione
                camera_config = camera.create_video_configuration(
                    main={"size": tuple(cam_config["resolution"]),
                          "format": cam_config["format"]},
                    controls={"FrameRate": cam_config["framerate"]}
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
        logger.info("Streaming video arrestato")

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
            capture_dir = LOG_DIR / 'captures'
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
    parser.add_argument('--broadcast-port', type=int, help='Porta per il broadcast (default: 5679)')
    parser.add_argument('--broadcast-interval', type=float, help='Intervallo di broadcast in secondi (default: 1.0)')
    args = parser.parse_args()

    # Crea e avvia il server
    server = UnLookServer(config_path=args.config)

    # Override della porta se specificata
    if args.port:
        server.config["server"]["command_port"] = args.port

    # Override della porta di broadcast se specificata
    if args.broadcast_port:
        server.config["server"]["broadcast_port"] = args.broadcast_port

    # Override dell'intervallo di broadcast se specificato
    if args.broadcast_interval:
        server.config["server"]["broadcast_interval"] = args.broadcast_interval

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