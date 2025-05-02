#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Modulo di gestione scansione 3D per UnLook Scanner.
Integra il controller di luce strutturata con il server principale.
"""

import threading
import logging
import time
import json
import os
import zmq
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
import numpy as np
import cv2

# Configura logging
logger = logging.getLogger(__name__)

# Importa il controller di luce strutturata
try:
    from server.projector.structured_light import (
        StructuredLightController,
        ScanPatternType,
        ScanningState
    )
except ImportError:
    try:
        from projector.structured_light import (
            StructuredLightController,
            ScanPatternType,
            ScanningState
        )
    except ImportError:
        logger.error("Impossibile importare il controller di luce strutturata")


class ScanManager:
    """
    Gestisce le funzionalità di scansione 3D per il server UnLook.
    Coordina l'interazione tra il controller di luce strutturata e il server.
    """

    def __init__(self, server):
        """
        Inizializza il gestore di scansione 3D.

        Args:
            server: Istanza del server UnLook
        """
        self.server = server
        self._scan_controller = None
        self._scan_thread = None
        self._is_scanning = False
        self._cancel_scan = False
        self._scan_status = {
            'state': 'IDLE',
            'progress': 0.0,
            'error': None
        }
        self._scan_config = {
            'pattern_type': 'PROGRESSIVE',
            'num_patterns': 12,
            'exposure_time': 0.5,
            'quality': 3
        }

        # Directory per i dati di scansione
        scan_dir_env = os.environ.get("UNLOOK_SCAN_DIR")
        if scan_dir_env:
            self._scan_data_dir = Path(scan_dir_env)
        else:
            # Fallback alla directory relativa al progetto
            self._scan_data_dir = Path(__file__).parent / "scans"  # server/scans

        self._scan_data_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Directory scansioni impostata a: {self._scan_data_dir}")

        # Statistiche di scansione
        self._scan_stats = {
            'start_time': 0,
            'end_time': 0,
            'total_frames': 0,
            'errors': 0
        }

        # Statistiche di scansione
        self._scan_stats = {
            'start_time': 0,
            'end_time': 0,
            'total_frames': 0,
            'errors': 0
        }

        # Crea il controller di luce strutturata
        try:
            self._initialize_scan_controller()
        except Exception as e:
            logger.error(f"Errore nell'inizializzazione del controller di scansione: {e}")

    def _initialize_scan_controller(self):
        """
        Inizializza il controller di luce strutturata.

        Returns:
            bool: True se inizializzazione riuscita, False altrimenti
        """
        try:
            # Ottieni i parametri I2C dalla configurazione del server
            i2c_bus = int(os.environ.get("UNLOOK_I2C_BUS", 3))

            # Gestisci correttamente l'indirizzo I2C in formato stringa esadecimale
            i2c_address_str = os.environ.get("UNLOOK_I2C_ADDRESS", "0x1b")
            try:
                i2c_address = int(i2c_address_str, 16) if i2c_address_str.startswith("0x") else int(i2c_address_str)
            except ValueError:
                logger.error(f"Indirizzo I2C non valido: {i2c_address_str}, uso il valore predefinito 0x1b")
                i2c_address = 0x1b

            logger.info(
                f"Tentativo di inizializzazione controller di scansione con bus={i2c_bus}, address=0x{i2c_address:02X}")

            # Crea una nuova directory per questa scansione
            scan_id = time.strftime("%Y%m%d_%H%M%S")
            scan_dir = self._scan_data_dir / scan_id

            # Crea il controller passando la directory
            self._scan_controller = StructuredLightController(
                i2c_bus=i2c_bus,
                i2c_address=i2c_address,
                capture_dir=str(scan_dir)
            )

            self._scan_controller._server = self.server

            # Imposta la callback per l'acquisizione dei frame
            self._scan_controller.set_frame_capture_callback(self._capture_frame_callback)

            # Verifica che il controller sia stato creato correttamente
            if self._scan_controller:
                logger.info(
                    f"Controller di scansione inizializzato con successo (bus={i2c_bus}, address=0x{i2c_address:02X})")
                return True
            else:
                logger.error("Errore: controller di scansione non inizializzato correttamente")
                return False

        except Exception as e:
            logger.error(f"Errore nell'inizializzazione del controller di scansione: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False

    def start_scan(self, scan_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Avvia una scansione 3D con migliore gestione degli errori.

        Args:
            scan_config: Configurazione della scansione (opzionale)

        Returns:
            Dizionario con lo stato dell'operazione
        """
        if self._is_scanning:
            return {
                'status': 'error',
                'message': 'Scansione già in corso',
                'scan_id': None
            }

        # Aggiorna la configurazione se fornita
        if scan_config:
            self._update_scan_config(scan_config)

        # Crea un nuovo ID di scansione basato sul timestamp
        scan_id = time.strftime("%Y%m%d_%H%M%S")
        scan_dir = self._scan_data_dir / scan_id

        try:
            # Verifica che il controller di scansione sia disponibile
            if not self._scan_controller:
                logger.error("Il controller di scansione non è inizializzato")
                success = self._initialize_scan_controller()
                if not success:
                    error_msg = "Impossibile inizializzare il controller di scansione"
                    logger.error(error_msg)
                    return {
                        'status': 'error',
                        'message': error_msg,
                        'scan_id': None
                    }

            # Inizializza il controller proiettore se necessario
            logger.info("Inizializzazione proiettore...")
            if not self._scan_controller.initialize_projector():
                error_msg = f"Errore nell'inizializzazione del proiettore: {self._scan_controller.error_message}"
                logger.error(error_msg)
                return {
                    'status': 'error',
                    'message': error_msg,
                    'scan_id': None
                }

            # Prepara il risultato di successo da restituire immediatamente
            result = {
                'status': 'success',
                'message': 'Scansione avviata con successo',
                'scan_id': scan_id
            }

            # Converti il tipo di pattern
            pattern_type_map = {
                'PROGRESSIVE': ScanPatternType.PROGRESSIVE,
                'GRAY_CODE': ScanPatternType.GRAY_CODE,
                'BINARY_CODE': ScanPatternType.BINARY_CODE,
                'PHASE_SHIFT': ScanPatternType.PHASE_SHIFT
            }

            pattern_type = pattern_type_map.get(
                self._scan_config['pattern_type'],
                ScanPatternType.PROGRESSIVE
            )

            # Imposta il flag di scansione prima di avviare il thread
            self._is_scanning = True
            self._cancel_scan = False

            # Aggiorna statistiche e stato immediatamente
            self._scan_stats = {
                'start_time': time.time(),
                'end_time': 0,
                'total_frames': 0,
                'errors': 0
            }

            self._scan_status = {
                'state': 'INITIALIZING',
                'progress': 0.0,
                'elapsed_time': 0,
                'captured_frames': 0,
                'errors': 0,
                'error_message': ""
            }

            # Avvia la scansione in un thread separato per non bloccare la risposta
            self._scan_thread = threading.Thread(
                target=self._scan_thread_function,
                args=(scan_id, scan_dir, pattern_type)
            )
            self._scan_thread.daemon = True
            self._scan_thread.start()

            # Log che indica che il thread è stato avviato
            logger.info(f"Thread di scansione avviato per scan_id: {scan_id}")

            # Restituisci immediatamente il risultato di successo
            return result

        except Exception as e:
            logger.error(f"Errore nell'avvio della scansione: {e}")
            # Assicurati che i flag di stato siano coerenti
            self._is_scanning = False
            self._scan_status = {
                'state': 'ERROR',
                'progress': 0.0,
                'error_message': str(e)
            }
            return {
                'status': 'error',
                'message': f'Errore nell\'avvio della scansione: {str(e)}',
                'scan_id': None
            }

    def _scan_thread_function(self, scan_id: str, scan_dir: Path, pattern_type: ScanPatternType):
        """
        Funzione principale del thread di scansione con migliore gestione degli errori.

        Args:
            scan_id: ID della scansione
            scan_dir: Directory per i dati della scansione
            pattern_type: Tipo di pattern da utilizzare
        """
        try:
            # Assicura che la directory di scansione esista
            scan_dir.mkdir(parents=True, exist_ok=True)

            # Aggiorna immediatamente lo stato
            self._scan_status = {
                'state': 'SCANNING',
                'progress': 0.0,
                'elapsed_time': 0,
                'captured_frames': 0,
                'errors': 0,
                'error_message': ""
            }

            # Avvia la scansione effettiva
            logger.info(f"Avvio scansione effettiva con pattern {pattern_type.name}")
            success = self._scan_controller.start_scan(
                pattern_type=pattern_type,
                num_patterns=self._scan_config['num_patterns'],
                exposure_time=self._scan_config['exposure_time'],
                quality=self._scan_config['quality']
            )

            if not success:
                error_msg = f"Errore nell'avvio della scansione: {self._scan_controller.error_message}"
                logger.error(error_msg)
                self._scan_status = {
                    'state': 'ERROR',
                    'progress': 0.0,
                    'elapsed_time': time.time() - self._scan_stats['start_time'],
                    'error_message': error_msg
                }
                self._is_scanning = False
                return

            # Attendi il completamento della scansione
            while (self._scan_controller.state == ScanningState.SCANNING or
                   self._scan_controller.state == ScanningState.INITIALIZING):
                if self._cancel_scan:
                    logger.info("Scansione annullata dall'utente")
                    break

                # Aggiorna lo stato ad ogni ciclo
                controller_status = self._scan_controller.get_scan_status()
                self._scan_status = {
                    'state': controller_status['state'],
                    'progress': controller_status['progress'],
                    'elapsed_time': time.time() - self._scan_stats['start_time'],
                    'captured_frames': controller_status.get('captured_frames', 0),
                    'errors': controller_status.get('errors', 0),
                    'error_message': controller_status.get('error_message', "")
                }

                time.sleep(0.5)  # Controllo più frequente

            # Salva il file di configurazione della scansione
            config_file = scan_dir / "scan_config.json"
            with open(config_file, 'w') as f:
                json.dump({
                    'scan_id': scan_id,
                    'timestamp': time.strftime("%Y-%m-%d %H:%M:%S"),
                    'config': self._scan_config,
                    'status': self._scan_controller.get_scan_status()
                }, f, indent=2)

            # Verifica il risultato finale
            if self._scan_controller.state == ScanningState.COMPLETED:
                logger.info(f"Scansione {scan_id} completata con successo")

                # Aggiorna le statistiche e lo stato
                self._scan_stats['end_time'] = time.time()
                self._scan_stats['total_frames'] = self._scan_controller.scan_stats.get('captured_frames', 0)

                self._scan_status = {
                    'state': 'COMPLETED',
                    'progress': 100.0,
                    'elapsed_time': self._scan_stats['end_time'] - self._scan_stats['start_time'],
                    'captured_frames': self._scan_controller.scan_stats.get('captured_frames', 0),
                    'errors': 0,
                    'error_message': ""
                }

                # Salva il risultato nella directory di scansione
                result_file = scan_dir / "scan_result.json"
                with open(result_file, 'w') as f:
                    json.dump({
                        'scan_id': scan_id,
                        'status': 'completed',
                        'stats': self._scan_stats,
                        'frames_captured': self._scan_controller.scan_stats.get('captured_frames', 0),
                        'duration': self._scan_stats['end_time'] - self._scan_stats['start_time']
                    }, f, indent=2)

            elif self._cancel_scan:
                logger.info(f"Scansione {scan_id} annullata dall'utente")

                # Aggiorna le statistiche e lo stato
                self._scan_stats['end_time'] = time.time()
                self._scan_stats['total_frames'] = self._scan_controller.scan_stats.get('captured_frames', 0)

                self._scan_status = {
                    'state': 'CANCELLED',
                    'progress': 0.0,
                    'elapsed_time': self._scan_stats['end_time'] - self._scan_stats['start_time'],
                    'captured_frames': self._scan_controller.scan_stats.get('captured_frames', 0),
                    'errors': 0,
                    'error_message': "Scansione annullata dall'utente"
                }

                # Salva il risultato nella directory di scansione
                result_file = scan_dir / "scan_result.json"
                with open(result_file, 'w') as f:
                    json.dump({
                        'scan_id': scan_id,
                        'status': 'cancelled',
                        'stats': self._scan_stats,
                        'frames_captured': self._scan_controller.scan_stats.get('captured_frames', 0),
                        'duration': self._scan_stats['end_time'] - self._scan_stats['start_time']
                    }, f, indent=2)

            else:
                logger.error(f"Scansione {scan_id} fallita: {self._scan_controller.error_message}")

                # Aggiorna le statistiche e lo stato
                self._scan_stats['end_time'] = time.time()
                self._scan_stats['total_frames'] = self._scan_controller.scan_stats.get('captured_frames', 0)
                self._scan_stats['errors'] = self._scan_controller.scan_stats.get('errors', 0)

                self._scan_status = {
                    'state': 'ERROR',
                    'progress': 0.0,
                    'elapsed_time': self._scan_stats['end_time'] - self._scan_stats['start_time'],
                    'captured_frames': self._scan_controller.scan_stats.get('captured_frames', 0),
                    'errors': self._scan_controller.scan_stats.get('errors', 0),
                    'error_message': self._scan_controller.error_message
                }

                # Salva il risultato nella directory di scansione
                result_file = scan_dir / "scan_result.json"
                with open(result_file, 'w') as f:
                    json.dump({
                        'scan_id': scan_id,
                        'status': 'error',
                        'error_message': self._scan_controller.error_message,
                        'stats': self._scan_stats,
                        'frames_captured': self._scan_controller.scan_stats.get('captured_frames', 0),
                        'duration': self._scan_stats['end_time'] - self._scan_stats['start_time']
                    }, f, indent=2)

        except Exception as e:
            logger.error(f"Errore nel thread di scansione: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")

            # Aggiorna le statistiche e lo stato
            self._scan_stats['end_time'] = time.time()
            self._scan_stats['errors'] += 1

            self._scan_status = {
                'state': 'ERROR',
                'progress': 0.0,
                'elapsed_time': self._scan_stats['end_time'] - self._scan_stats['start_time'],
                'error_message': str(e)
            }

            # Salva il risultato nella directory di scansione (se possibile)
            try:
                result_file = scan_dir / "scan_result.json"
                with open(result_file, 'w') as f:
                    json.dump({
                        'scan_id': scan_id,
                        'status': 'error',
                        'error_message': str(e),
                        'stats': self._scan_stats
                    }, f, indent=2)
            except:
                pass

        finally:
            # Resetta lo stato di scansione
            self._is_scanning = False

    def stop_scan(self) -> Dict[str, Any]:
        """
        Interrompe una scansione in corso.

        Returns:
            Dizionario con lo stato dell'operazione
        """
        if not self._is_scanning:
            return {
                'status': 'error',
                'message': 'Nessuna scansione in corso'
            }

        try:
            # Imposta il flag di annullamento
            self._cancel_scan = True

            # Annulla la scansione nel controller
            if self._scan_controller:
                self._scan_controller.cancel_scan()

            # Attendi il completamento del thread (con timeout)
            if self._scan_thread and self._scan_thread.is_alive():
                self._scan_thread.join(timeout=3.0)

            # Aggiorna lo stato
            self._is_scanning = False

            return {
                'status': 'success',
                'message': 'Scansione interrotta con successo'
            }

        except Exception as e:
            logger.error(f"Errore nell'interruzione della scansione: {e}")

            return {
                'status': 'error',
                'message': f'Errore nell\'interruzione della scansione: {str(e)}'
            }

    def get_scan_status(self) -> Dict[str, Any]:
        """
        Restituisce lo stato attuale della scansione.

        Returns:
            Dizionario con lo stato della scansione
        """
        # Se non è in corso una scansione, restituisci lo stato salvato
        if not self._is_scanning:
            return self._scan_status

        # Altrimenti, ottieni lo stato dal controller
        if self._scan_controller:
            controller_status = self._scan_controller.get_scan_status()

            # Aggiorna lo stato locale
            self._scan_status = {
                'state': controller_status['state'],
                'progress': controller_status['progress'],
                'elapsed_time': controller_status['elapsed_time'],
                'captured_frames': controller_status['captured_frames'],
                'errors': controller_status['errors'],
                'error_message': controller_status['error_message']
            }

        return self._scan_status

    def get_scan_config(self) -> Dict[str, Any]:
        """
        Restituisce la configurazione attuale della scansione.

        Returns:
            Dizionario con la configurazione della scansione
        """
        return self._scan_config

    def notify_client_new_frames(self, frame_info: Dict[str, Any], left_frame_data: bytes,
                                 right_frame_data: bytes) -> bool:
        """
        Notifica il client di nuovi frame acquisiti durante la scansione.
        Versione migliorata che usa lo stream socket esistente invece di crearne uno dedicato.

        Args:
            frame_info: Informazioni sul frame (indice, nome pattern, timestamp)
            left_frame_data: Dati del frame sinistro codificati in JPEG
            right_frame_data: Dati del frame destro codificati in JPEG

        Returns:
            True se la notifica è stata inviata con successo, False altrimenti
        """
        try:
            pattern_index = frame_info.get('pattern_index', 'sconosciuto')
            logger.info(f"Tentativo invio frame {pattern_index} al client")

            # Verifica riferimento al server
            if not hasattr(self, 'server') or not self.server:
                logger.warning("Nessun riferimento al server disponibile")
                return False

            # Utilizziamo il socket di streaming esistente invece di crearne uno dedicato
            if not hasattr(self.server, 'stream_socket') or not self.server.stream_socket:
                logger.error("Socket di streaming non disponibile")
                return False

            # Invia il frame sinistro
            try:
                # Crea l'header con metadata che identifica questo come frame di scansione
                left_header = {
                    "camera": 0,  # Camera sinistra
                    "frame": pattern_index,
                    "timestamp": time.time(),
                    "format": "jpeg",
                    "is_scan_frame": True,  # Flag per identificare i frame di scansione
                    "scan_id": frame_info.get('scan_id', getattr(self, 'current_scan_id', None)),
                    "pattern_index": pattern_index,
                    "pattern_name": frame_info.get('pattern_name', '')
                }

                # Invia header e dati usando lo stesso pattern dello streaming video
                self.server.stream_socket.send_json(left_header, zmq.SNDMORE)
                self.server.stream_socket.send(left_frame_data, copy=False)

                # Breve pausa per evitare sovraccarico del socket
                time.sleep(0.01)

                # Crea l'header per il frame destro
                right_header = {
                    "camera": 1,  # Camera destra
                    "frame": pattern_index,
                    "timestamp": time.time(),
                    "format": "jpeg",
                    "is_scan_frame": True,  # Flag per identificare i frame di scansione
                    "scan_id": frame_info.get('scan_id', getattr(self, 'current_scan_id', None)),
                    "pattern_index": pattern_index,
                    "pattern_name": frame_info.get('pattern_name', '')
                }

                # Invia header e dati usando lo stesso pattern dello streaming video
                self.server.stream_socket.send_json(right_header, zmq.SNDMORE)
                self.server.stream_socket.send(right_frame_data, copy=False)

                logger.info(f"Frame {pattern_index} inviato tramite socket di streaming")
                return True

            except zmq.ZMQError as e:
                logger.error(f"Errore ZMQ nell'invio frame: {e}")
                return False

        except Exception as e:
            logger.error(f"Errore nella notifica dei frame al client: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False

    def check_scan_capability(self) -> Dict[str, Any]:
        """
        Verifica la capacità di scansione 3D del sistema.

        Returns:
            Dizionario con lo stato delle capacità di scansione
        """
        try:
            # Verifica le capacità di scansione
            result = {
                "capability_available": False,  # Sarà True solo se tutte le verifiche passano
                "details": {
                    "i2c_bus": os.environ.get("UNLOOK_I2C_BUS", "non impostato"),
                    "i2c_address": os.environ.get("UNLOOK_I2C_ADDRESS", "non impostato")
                }
            }

            # Verifica il controller
            if not self._scan_controller:
                logger.info("Tentativo di inizializzazione controller di scansione")
                try:
                    init_success = self._initialize_scan_controller()
                    result["details"]["controller_initialized"] = init_success
                    if not init_success:
                        result["details"]["error"] = "Impossibile inizializzare il controller di scansione"
                        return result
                except Exception as e:
                    logger.error(f"Errore nell'inizializzazione del controller: {e}")
                    result["details"]["controller_initialized"] = False
                    result["details"]["error"] = f"Errore nell'inizializzazione del controller: {str(e)}"
                    return result
            else:
                result["details"]["controller_initialized"] = True

            # Verifica il proiettore
            try:
                logger.info("Tentativo di inizializzazione proiettore")
                projector_success = self._scan_controller.initialize_projector()
                result["details"]["projector_initialized"] = projector_success

                if not projector_success:
                    result["details"]["projector_error"] = self._scan_controller.error_message
                    return result
            except Exception as e:
                logger.error(f"Errore nell'inizializzazione del proiettore: {e}")
                result["details"]["projector_initialized"] = False
                result["details"]["projector_error"] = str(e)
                return result

            # Verifica le camere
            cameras_available = len(self.server.cameras) > 0
            result["details"]["cameras_available"] = cameras_available
            result["details"]["dual_camera"] = len(self.server.cameras) > 1

            if not cameras_available:
                result["details"]["camera_error"] = "Nessuna camera disponibile"
                return result

            # Se tutto è OK, imposta capability_available a True
            result["capability_available"] = True
            return result

        except Exception as e:
            logger.error(f"Errore nella verifica delle capacità di scansione: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {
                "capability_available": False,
                "details": {"error": str(e)}
            }

    def _update_scan_config(self, scan_config: Dict[str, Any]):
        """
        Aggiorna la configurazione della scansione.

        Args:
            scan_config: Nuova configurazione della scansione
        """
        if 'pattern_type' in scan_config:
            self._scan_config['pattern_type'] = scan_config['pattern_type']

        if 'num_patterns' in scan_config:
            self._scan_config['num_patterns'] = max(4, min(24, int(scan_config['num_patterns'])))

        if 'exposure_time' in scan_config:
            self._scan_config['exposure_time'] = max(0.1, min(2.0, float(scan_config['exposure_time'])))

        if 'quality' in scan_config:
            self._scan_config['quality'] = max(1, min(5, int(scan_config['quality'])))

        logger.info(f"Configurazione di scansione aggiornata: {self._scan_config}")

    def _capture_frame_callback(self, pattern_index: int) -> Tuple[np.ndarray, np.ndarray]:
        """
        Callback per l'acquisizione dei frame dalle camere e invio al client.
        Versione ottimizzata per ridurre la latenza e migliorare l'efficienza.

        Args:
            pattern_index: Indice del pattern corrente

        Returns:
            Tupla (frame_left, frame_right) con i frame acquisiti
        """
        try:
            logger.info(f"Acquisizione frame per pattern {pattern_index}")

            # Prima verifica che le camere siano disponibili
            if not self.server.cameras or len(self.server.cameras) < 2:
                logger.error("Camere non disponibili o insufficienti")
                return (None, None)

            # Cattura i frame dalle camere del server
            left_frame = None
            right_frame = None

            # OTTIMIZZAZIONE: Ritenta l'acquisizione fino a 3 volte in caso di fallimento
            for attempt in range(3):
                try:
                    for cam_info in self.server.cameras:
                        if cam_info["name"] == "left":
                            left_frame = cam_info["camera"].capture_array()
                        elif cam_info["name"] == "right":
                            right_frame = cam_info["camera"].capture_array()

                    # Se entrambi i frame sono stati acquisiti, esci dal ciclo
                    if left_frame is not None and right_frame is not None:
                        break

                except Exception as e:
                    logger.error(f"Errore nell'acquisizione del frame (tentativo {attempt + 1}/3): {e}")
                    time.sleep(0.1)  # Breve pausa prima di riprovare

            # Verifica finale
            if left_frame is None or right_frame is None:
                logger.error("Impossibile acquisire i frame dalle camere dopo più tentativi")
                return (None, None)

            # Converti il formato se necessario
            for cam_info in self.server.cameras:
                if cam_info["name"] == "left" and len(left_frame.shape) == 3 and cam_info.get("mode") == "grayscale":
                    left_frame = cv2.cvtColor(left_frame, cv2.COLOR_RGB2GRAY)
                elif cam_info["name"] == "right" and len(right_frame.shape) == 3 and cam_info.get(
                        "mode") == "grayscale":
                    right_frame = cv2.cvtColor(right_frame, cv2.COLOR_RGB2GRAY)

            # Determina il nome del pattern in base all'indice
            pattern_name = ""
            if pattern_index == 0:
                pattern_name = "white"
            elif pattern_index == 1:
                pattern_name = "black"
            elif pattern_index < 2 + self._scan_config['num_patterns']:
                pattern_name = f"vertical_{pattern_index - 2}"
            else:
                pattern_name = f"horizontal_{pattern_index - 2 - self._scan_config['num_patterns']}"

            # OTTIMIZZAZIONE: Usa il socket di streaming esistente ed evita salvataggio su disco prima dell'invio
            if hasattr(self.server, "stream_socket") and self.server.stream_socket:
                try:
                    # OTTIMIZZAZIONE: Adatta qualità in base all'indice pattern
                    # Frame di riferimento (white, black) con qualità alta, pattern con qualità media
                    quality = 95 if pattern_index <= 1 else 85
                    encode_params = [cv2.IMWRITE_JPEG_QUALITY, quality]

                    _, left_encoded = cv2.imencode('.jpg', left_frame, encode_params)
                    _, right_encoded = cv2.imencode('.jpg', right_frame, encode_params)

                    # Crea header con metadati dettagliati
                    scan_id = getattr(self, 'current_scan_id', None)
                    timestamp = time.time()

                    # OTTIMIZZAZIONE: Aggiungi metadati per controllo di flusso
                    client_id = getattr(self.server, 'client_ip', None)
                    total_patterns = self._scan_config[
                                         'num_patterns'] * 2 + 2  # white, black, patterns orizzontali e verticali
                    progress = min(100, (pattern_index / total_patterns) * 100)

                    # OTTIMIZZAZIONE: Verifica con polling che il socket sia pronto prima dell'invio
                    poller = zmq.Poller()
                    poller.register(self.server.stream_socket, zmq.POLLOUT)

                    if poller.poll(100):  # Timeout di 100ms
                        # Socket pronto per l'invio del frame sinistro
                        left_header = {
                            "camera": 0,  # Camera sinistra
                            "frame": pattern_index,
                            "timestamp": timestamp,
                            "format": "jpeg",
                            "is_scan_frame": True,  # Flag per identificare i frame di scansione
                            "scan_id": scan_id,
                            "pattern_index": pattern_index,
                            "pattern_name": pattern_name,
                            "client_id": client_id,
                            "total_patterns": total_patterns,
                            "progress": progress
                        }

                        self.server.stream_socket.send_json(left_header, zmq.SNDMORE)
                        self.server.stream_socket.send(left_encoded.tobytes(), copy=False)

                        # Breve pausa per evitare congestione
                        time.sleep(0.01)

                        # Invia frame destro
                        right_header = {
                            "camera": 1,  # Camera destra
                            "frame": pattern_index,
                            "timestamp": timestamp,
                            "format": "jpeg",
                            "is_scan_frame": True,
                            "scan_id": scan_id,
                            "pattern_index": pattern_index,
                            "pattern_name": pattern_name,
                            "client_id": client_id,
                            "total_patterns": total_patterns,
                            "progress": progress
                        }

                        self.server.stream_socket.send_json(right_header, zmq.SNDMORE)
                        self.server.stream_socket.send(right_encoded.tobytes(), copy=False)

                        logger.info(f"Frame {pattern_index} ({pattern_name}) inviato tramite socket di streaming")
                    else:
                        logger.warning(f"Socket di streaming non pronto per l'invio del frame {pattern_index}")

                except zmq.ZMQError as e:
                    logger.error(f"Errore ZMQ nell'invio del frame: {e}")
                except Exception as e:
                    logger.error(f"Errore generale nell'invio del frame: {e}")
            else:
                logger.error("Socket di streaming non disponibile nel server")

            # OTTIMIZZAZIONE: Salva i frame su disco come backup, in modo asincrono
            try:
                import threading

                def save_frames_async(left_frame, right_frame, scan_dir, pattern_index, pattern_name):
                    try:
                        # Assicurati che le directory esistano
                        os.makedirs(scan_dir / "left", exist_ok=True)
                        os.makedirs(scan_dir / "right", exist_ok=True)

                        # Salva i frame
                        left_path = scan_dir / "left" / f"{pattern_index:04d}_{pattern_name}.png"
                        right_path = scan_dir / "right" / f"{pattern_index:04d}_{pattern_name}.png"

                        cv2.imwrite(str(left_path), left_frame)
                        cv2.imwrite(str(right_path), right_frame)

                        logger.debug(f"Frame {pattern_index} salvato su disco in modo asincrono")
                    except Exception as e:
                        logger.error(f"Errore nel salvataggio asincrono dei frame: {e}")

                scan_dir = getattr(self, '_scan_dir',
                                   self._scan_data_dir / getattr(self, 'current_scan_id', str(int(time.time()))))

                # Avvia thread per il salvataggio asincrono
                save_thread = threading.Thread(
                    target=save_frames_async,
                    args=(left_frame.copy(), right_frame.copy(), scan_dir, pattern_index, pattern_name)
                )
                save_thread.daemon = True
                save_thread.start()

            except Exception as e:
                logger.error(f"Errore nell'avvio del thread di salvataggio: {e}")

            return (left_frame, right_frame)

        except Exception as e:
            logger.error(f"Errore nella callback di acquisizione frame: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return (None, None)

    def cleanup(self):
        """Pulizia delle risorse."""
        try:
            # Interrompi una eventuale scansione in corso
            if self._is_scanning:
                self.stop_scan()

            # Pulisci il controller
            if self._scan_controller:
                self._scan_controller.close()
                self._scan_controller = None

            logger.info("Risorse del gestore di scansione rilasciate")

        except Exception as e:
            logger.error(f"Errore nella pulizia del gestore di scansione: {e}")
    def sync_pattern_projection(self, pattern_index: int) -> Dict[str, Any]:
        """
        Sincronizza la proiezione di un pattern specifico.

        Args:
            pattern_index: Indice del pattern da proiettare

        Returns:
            Dizionario con risultato dell'operazione
        """
        try:
            if not self._scan_controller:
                return {
                    'status': 'error',
                    'message': 'Controller di scansione non inizializzato',
                    'pattern_index': pattern_index
                }

            # Verifica che il controller sia disponibile
            if not self._scan_controller.is_projector_initialized():
                # Prova a inizializzare
                if not self._scan_controller.initialize_projector():
                    return {
                        'status': 'error',
                        'message': f'Inizializzazione proiettore fallita: {self._scan_controller.error_message}',
                        'pattern_index': pattern_index
                    }

            # Pattern speciali: 0=white, 1=black
            pattern_name = ""
            if pattern_index == 0:
                pattern_name = "white"
                self._scan_controller.project_pattern(0, is_white=True)
            elif pattern_index == 1:
                pattern_name = "black"
                self._scan_controller.project_pattern(0, is_white=False)
            else:
                # Calcola se è un pattern orizzontale o verticale
                num_patterns = self._scan_config.get('num_patterns', 12)
                is_horizontal = pattern_index >= (2 + num_patterns)

                if is_horizontal:
                    effective_idx = pattern_index - 2 - num_patterns
                    pattern_name = f"horizontal_{effective_idx}"
                else:
                    effective_idx = pattern_index - 2
                    pattern_name = f"vertical_{effective_idx}"

                # Proietta pattern
                self._scan_controller.project_pattern(
                    effective_idx,
                    is_horizontal=is_horizontal,
                    is_inverted=False
                )

            # Attendi che il pattern sia effettivamente proiettato
            time.sleep(0.05)  # 50ms di attesa per la stabilizzazione

            return {
                'status': 'success',
                'message': f'Pattern {pattern_name} proiettato con successo',
                'pattern_index': pattern_index,
                'pattern_name': pattern_name,
                'timestamp': time.time()
            }

        except Exception as e:
            logger.error(f"Errore nella sincronizzazione del pattern {pattern_index}: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")

            return {
                'status': 'error',
                'message': f'Errore nella proiezione del pattern: {str(e)}',
                'pattern_index': pattern_index
            }