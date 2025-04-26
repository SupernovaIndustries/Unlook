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
            i2c_address = int(os.environ.get("UNLOOK_I2C_ADDRESS", "0x1b"), 16)  # Default a 0x1b per il tuo scanner

            logger.info(
                f"Tentativo di inizializzazione controller di scansione con bus={i2c_bus}, address=0x{i2c_address:02X}")

            # Crea il controller
            self._scan_controller = StructuredLightController(
                i2c_bus=i2c_bus,
                i2c_address=i2c_address
            )

            # Imposta la callback per l'acquisizione dei frame
            self._scan_controller.set_frame_capture_callback(self._capture_frame_callback)

            # Verifica che il controller sia stato creato correttamente
            if self._scan_controller:
                logger.info(
                    f"Controller di scansione inizializzato con successo (bus={i2c_bus}, address=0x{i2c_address:02X})")

                # Prova a inizializzare il proiettore per verificare che funzioni
                projector_test = self._scan_controller.initialize_projector()
                if projector_test:
                    logger.info("Test proiettore riuscito: proiettore inizializzato con successo")
                else:
                    logger.error(f"Test proiettore fallito: {self._scan_controller.error_message}")

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
        Avvia una scansione 3D.

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

            # Imposta il flag di scansione
            self._is_scanning = True
            self._cancel_scan = False

            # Aggiorna le statistiche
            self._scan_stats = {
                'start_time': time.time(),
                'end_time': 0,
                'total_frames': 0,
                'errors': 0
            }

            # Avvia la scansione in un thread separato
            logger.info(f"Avvio scansione {scan_id} con configurazione: {self._scan_config}")
            self._scan_thread = threading.Thread(
                target=self._scan_thread_function,
                args=(scan_id, scan_dir)
            )
            self._scan_thread.daemon = True
            self._scan_thread.start()

            # Verifica che il thread sia partito
            if not self._scan_thread.is_alive():
                logger.error("Il thread di scansione non è partito")
                self._is_scanning = False
                return {
                    'status': 'error',
                    'message': 'Errore nell\'avvio del thread di scansione',
                    'scan_id': None
                }

            return {
                'status': 'success',
                'message': 'Scansione avviata con successo',
                'scan_id': scan_id
            }

        except Exception as e:
            logger.error(f"Errore nell'avvio della scansione: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            self._is_scanning = False

            return {
                'status': 'error',
                'message': f'Errore nell\'avvio della scansione: {str(e)}',
                'scan_id': None
            }

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

    def check_scan_capability(self) -> Dict[str, Any]:
        """
        Verifica la capacità di scansione 3D del sistema.

        Returns:
            Dizionario con lo stato delle capacità di scansione
        """
        result = {
            'capability_available': self._scan_controller is not None,
            'details': {}
        }

        if not self._scan_controller:
            # Prova a inizializzare il controller
            init_success = self._initialize_scan_controller()
            result['capability_available'] = init_success
            result['details']['controller_initialized'] = init_success

            if not init_success:
                result['details']['error'] = "Impossibile inizializzare il controller di scansione"
                return result
        else:
            result['details']['controller_initialized'] = True

        # Verifica il proiettore
        try:
            projector_success = self._scan_controller.initialize_projector()
            result['details']['projector_initialized'] = projector_success

            if not projector_success:
                result['details']['projector_error'] = self._scan_controller.error_message
        except Exception as e:
            result['details']['projector_initialized'] = False
            result['details']['projector_error'] = str(e)

        # Verifica le camere
        result['details']['cameras_available'] = len(self.server.cameras) > 0
        result['details']['dual_camera'] = len(self.server.cameras) > 1

        return result

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

    def _scan_thread_function(self, scan_id: str, scan_dir: Path):
        """
        Funzione principale del thread di scansione.

        Args:
            scan_id: ID della scansione
            scan_dir: Directory per i dati della scansione
        """
        try:
            # Assicura che la directory di scansione esista
            scan_dir.mkdir(parents=True, exist_ok=True)

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

            # Avvia la scansione
            logger.info(f"Avvio scansione effettiva con pattern {pattern_type.name}")
            success = self._scan_controller.start_scan(
                pattern_type=pattern_type,
                num_patterns=self._scan_config['num_patterns'],
                exposure_time=self._scan_config['exposure_time'],
                quality=self._scan_config['quality']
            )

            if not success:
                raise Exception(f"Errore nell'avvio della scansione: {self._scan_controller.error_message}")

            # Attendi il completamento della scansione
            while (self._scan_controller.state == ScanningState.SCANNING or
                   self._scan_controller.state == ScanningState.INITIALIZING):
                if self._cancel_scan:
                    logger.info("Scansione annullata dall'utente")
                    break
                time.sleep(0.1)

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

                # Aggiorna le statistiche
                self._scan_stats['end_time'] = time.time()
                self._scan_stats['total_frames'] = self._scan_controller.scan_stats['captured_frames']

                # Salva il risultato nella directory di scansione
                result_file = scan_dir / "scan_result.json"
                with open(result_file, 'w') as f:
                    json.dump({
                        'scan_id': scan_id,
                        'status': 'completed',
                        'stats': self._scan_stats,
                        'frames_captured': self._scan_controller.scan_stats['captured_frames'],
                        'duration': self._scan_stats['end_time'] - self._scan_stats['start_time']
                    }, f, indent=2)

            elif self._cancel_scan:
                logger.info(f"Scansione {scan_id} annullata dall'utente")

                # Aggiorna le statistiche
                self._scan_stats['end_time'] = time.time()
                self._scan_stats['total_frames'] = self._scan_controller.scan_stats['captured_frames']

                # Salva il risultato nella directory di scansione
                result_file = scan_dir / "scan_result.json"
                with open(result_file, 'w') as f:
                    json.dump({
                        'scan_id': scan_id,
                        'status': 'cancelled',
                        'stats': self._scan_stats,
                        'frames_captured': self._scan_controller.scan_stats['captured_frames'],
                        'duration': self._scan_stats['end_time'] - self._scan_stats['start_time']
                    }, f, indent=2)

            else:
                logger.error(f"Scansione {scan_id} fallita: {self._scan_controller.error_message}")

                # Aggiorna le statistiche
                self._scan_stats['end_time'] = time.time()
                self._scan_stats['total_frames'] = self._scan_controller.scan_stats['captured_frames']
                self._scan_stats['errors'] = self._scan_controller.scan_stats['errors']

                # Salva il risultato nella directory di scansione
                result_file = scan_dir / "scan_result.json"
                with open(result_file, 'w') as f:
                    json.dump({
                        'scan_id': scan_id,
                        'status': 'error',
                        'error_message': self._scan_controller.error_message,
                        'stats': self._scan_stats,
                        'frames_captured': self._scan_controller.scan_stats['captured_frames'],
                        'duration': self._scan_stats['end_time'] - self._scan_stats['start_time']
                    }, f, indent=2)

        except Exception as e:
            logger.error(f"Errore nel thread di scansione: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")

            # Aggiorna le statistiche
            self._scan_stats['end_time'] = time.time()
            self._scan_stats['errors'] += 1

            # Aggiorna lo stato
            self._scan_status = {
                'state': 'ERROR',
                'progress': 0.0,
                'error': str(e)
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

    def _capture_frame_callback(self, pattern_index: int) -> Tuple[np.ndarray, np.ndarray]:
        """
        Callback per l'acquisizione dei frame dalle camere.

        Args:
            pattern_index: Indice del pattern corrente

        Returns:
            Tupla (frame_left, frame_right) con i frame acquisiti
        """
        try:
            logger.debug(f"Acquisizione frame per pattern {pattern_index}")

            # Cattura i frame dalle camere del server
            left_frame = None
            right_frame = None

            for cam_info in self.server.cameras:
                try:
                    if cam_info["name"] == "left":
                        # Cattura il frame dalla camera sinistra
                        left_frame = cam_info["camera"].capture_array()
                    elif cam_info["name"] == "right":
                        # Cattura il frame dalla camera destra
                        right_frame = cam_info["camera"].capture_array()
                except Exception as e:
                    logger.error(f"Errore nell'acquisizione del frame dalla camera {cam_info['name']}: {e}")

            # Verifica che entrambi i frame siano stati acquisiti
            if left_frame is None or right_frame is None:
                raise Exception("Impossibile acquisire i frame dalle camere")

            # Converti il formato se necessario
            if len(left_frame.shape) == 3 and cam_info.get("mode") == "grayscale":
                left_frame = cv2.cvtColor(left_frame, cv2.COLOR_RGB2GRAY)

            if len(right_frame.shape) == 3 and cam_info.get("mode") == "grayscale":
                right_frame = cv2.cvtColor(right_frame, cv2.COLOR_RGB2GRAY)

            return (left_frame, right_frame)

        except Exception as e:
            logger.error(f"Errore nella callback di acquisizione frame: {e}")
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