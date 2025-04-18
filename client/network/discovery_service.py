#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Servizio di scoperta degli scanner UnLook sulla rete locale.
"""

import json
import logging
import socket
import struct
from typing import Dict, Any

from PySide6.QtCore import QObject, Signal, QThread, QTimer, Slot

# Costanti di protocollo
DISCOVERY_PORT = 5678
DISCOVERY_GROUP = "239.255.255.250"
DISCOVERY_MESSAGE = "UNLOOK_DISCOVER"
DISCOVERY_INTERVAL = 1000  # ms

logger = logging.getLogger(__name__)


class DiscoveryWorker(QThread):
    """
    Worker thread che gestisce la scoperta degli scanner tramite multicast UDP.
    """
    device_found = Signal(str, str, int)

    def __init__(self):
        super().__init__()
        self._running = False
        self._socket = None

    def run(self):
        """Esegue il loop principale di ascolto per le risposte degli scanner."""
        try:
            # Crea il socket multicast
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

            # Imposta il timeout del socket
            self._socket.settimeout(0.5)

            # Associa a tutte le interfacce
            self._socket.bind(('', DISCOVERY_PORT))

            # Iscriviti al gruppo multicast
            mreq = struct.pack('4sL', socket.inet_aton(DISCOVERY_GROUP), socket.INADDR_ANY)
            self._socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

            logger.info("Discovery worker avviato")
            self._running = True

            # Loop principale
            while self._running:
                try:
                    # Attendi risposta
                    data, addr = self._socket.recvfrom(1024)
                    if data:
                        self._process_response(data, addr)
                except socket.timeout:
                    # Timeout è normale, continua
                    continue
        except Exception as e:
            logger.error(f"Errore nel discovery worker: {str(e)}")
        finally:
            # Pulizia
            if self._socket:
                try:
                    self._socket.close()
                except:
                    pass
            logger.info("Discovery worker terminato")

    def _process_response(self, data: bytes, addr: tuple):
        """Processa una risposta ricevuta da uno scanner."""
        try:
            response_str = data.decode('utf-8')
            # Controlla se è una risposta JSON valida
            if response_str.startswith('{') and response_str.endswith('}'):
                response = json.loads(response_str)

                # Verifica se è una risposta valida di UnLook
                if response.get('type') == 'UNLOOK_ANNOUNCE':
                    device_id = response.get('device_id')
                    port = response.get('port', 5000)
                    ip_address = addr[0]

                    if device_id:
                        logger.debug(f"Scanner trovato: {device_id} a {ip_address}:{port}")
                        self.device_found.emit(device_id, ip_address, port)
        except Exception as e:
            logger.error(f"Errore nel processare la risposta: {str(e)}")

    def stop(self):
        """Ferma il worker."""
        self._running = False
        # Forzare l'uscita dall'attesa del recvfrom
        if self._socket:
            self._socket.close()


class DiscoverySender(QObject):
    """
    Gestisce l'invio periodico di messaggi di scoperta.
    """

    def __init__(self):
        super().__init__()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._send_discovery)
        self._socket = None

    def start(self):
        """Avvia l'invio periodico di messaggi di scoperta."""
        try:
            # Crea il socket per l'invio
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            self._socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)

            # Avvia il timer
            self._timer.start(DISCOVERY_INTERVAL)
            logger.info("Discovery sender avviato")
        except Exception as e:
            logger.error(f"Errore nell'avvio del discovery sender: {str(e)}")

    def stop(self):
        """Ferma l'invio di messaggi di scoperta."""
        self._timer.stop()
        if self._socket:
            try:
                self._socket.close()
                self._socket = None
            except:
                pass
        logger.info("Discovery sender fermato")

    @Slot()
    def _send_discovery(self):
        """Invia un messaggio di scoperta multicast."""
        if not self._socket:
            return

        try:
            # Prepara il messaggio di scoperta
            discover_msg = {
                "type": "UNLOOK_DISCOVER",
                "client_version": "1.0.0"
            }

            # Invia il messaggio
            message = json.dumps(discover_msg).encode('utf-8')
            self._socket.sendto(message, (DISCOVERY_GROUP, DISCOVERY_PORT))
            logger.debug("Messaggio di scoperta inviato")
        except Exception as e:
            logger.error(f"Errore nell'invio del messaggio di scoperta: {str(e)}")


class DiscoveryService(QObject):
    """
    Servizio che coordina la scoperta degli scanner UnLook sulla rete locale.
    """
    device_discovered = Signal(str, str, int)  # device_id, ip_address, port

    def __init__(self):
        super().__init__()
        self._worker = DiscoveryWorker()
        self._sender = DiscoverySender()

        # Collega i segnali
        self._worker.device_found.connect(self.device_discovered)

    def start(self):
        """Avvia il servizio di scoperta."""
        self._worker.start()
        self._sender.start()

    def stop(self):
        """Ferma il servizio di scoperta."""
        self._sender.stop()
        self._worker.stop()
        # Attendi che il worker termini
        if self._worker.isRunning():
            self._worker.wait(2000)  # Timeout di 2 secondi