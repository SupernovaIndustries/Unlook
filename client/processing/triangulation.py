#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Module for 3D triangulation of structured light patterns.
Processes scan data acquired by the UnLook scanner to generate 3D point clouds.
Based on the algorithms from the Structured-light-stereo project, adapted for UnLook.
"""

import os
import sys
import time
import logging
import threading
import glob
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Union, Callable
import multiprocessing
from enum import Enum

import numpy as np
import cv2

# Optional imports for visualization - don't fail if not available
try:
    import open3d as o3d

    OPEN3D_AVAILABLE = True
except ImportError:
    OPEN3D_AVAILABLE = False
    logging.warning("Open3D not available. Visualization features will be disabled.")

# Import client modules for network communication
try:
    from client.network.connection_manager import ConnectionManager
    from client.models.scanner_model import Scanner, ScannerStatus
except ImportError:
    # Allow running the module standalone for testing
    logging.warning("Running in standalone mode without client modules.")
    ConnectionManager = None
    Scanner = None
    ScannerStatus = None

# Configure logger
logger = logging.getLogger(__name__)


class PatternType(Enum):
    """Types of projected patterns."""
    PROGRESSIVE = "PROGRESSIVE"
    GRAY_CODE = "GRAY_CODE"
    BINARY_CODE = "BINARY_CODE"
    PHASE_SHIFT = "PHASE_SHIFT"


class ScanProcessor:
    """
    Processes 3D scan data from structured light patterns.
    Handles downloading scan data, triangulation, and visualization.
    """

    def __init__(self, output_dir: Optional[str] = None):
        """
        Initialize the scan processor.

        Args:
            output_dir: Directory to save processed data (default: user's home directory)
        """
        # Set up output directory
        if output_dir is None:
            self.output_dir = Path.home() / "UnLook" / "scans"
        else:
            self.output_dir = Path(output_dir)

        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Scan data
        self.scan_id = None
        self.scan_dir = None
        self.left_images = []
        self.right_images = []
        self.pattern_type = PatternType.PROGRESSIVE
        self.num_patterns = 0

        # Camera calibration data
        self.calib_data = None

        # Rectification maps
        self.map_x_l = None
        self.map_y_l = None
        self.map_x_r = None
        self.map_y_r = None
        self.Q = None  # Reprojection matrix

        # Result data
        self.pointcloud = None
        self.processing_thread = None
        self._processing_complete = threading.Event()
        self._processing_cancelled = threading.Event()
        self._progress_callback = None
        self._completion_callback = None

        logger.info("ScanProcessor initialized")

    def set_callbacks(self, progress_callback: Optional[Callable[[float, str], None]] = None,
                      completion_callback: Optional[Callable[[bool, str, Any], None]] = None):
        """
        Set callbacks for progress updates and completion notification.

        Args:
            progress_callback: Function to call with progress updates (progress_percentage, status_message)
            completion_callback: Function to call when processing completes (success, message, result_data)
        """
        self._progress_callback = progress_callback
        self._completion_callback = completion_callback

    """def download_scan_data(self, scanner, scan_id) -> bool:
        "
        Scarica i dati della scansione dal server.

        Args:
            scanner: Oggetto scanner da cui scaricare i dati
            scan_id: ID della scansione da scaricare

        Returns:
            True se il download è riuscito, False altrimenti
        
        if not scanner or not scan_id:
            logger.error("Scanner o scan_id non validi")
            return False

        try:
            # Crea la directory per la scansione se non esiste
            scan_dir = self.output_dir / scan_id
            scan_dir.mkdir(parents=True, exist_ok=True)
            left_dir = scan_dir / "left"
            right_dir = scan_dir / "right"
            left_dir.mkdir(exist_ok=True)
            right_dir.mkdir(exist_ok=True)

            # Importa il connection manager
            from client.network.connection_manager import ConnectionManager
            connection_manager = ConnectionManager()

            # Richiedi l'elenco dei file
            logger.info(f"Richiesta elenco file per scansione {scan_id}")
            if self._progress_callback:
                self._progress_callback(10, "Richiesta elenco file...")

            # Invia il comando per ottenere l'elenco dei file
            if not connection_manager.send_message(
                    scanner.device_id,
                    "GET_SCAN_FILES",
                    {"scan_id": scan_id}
            ):
                logger.error("Impossibile inviare il comando GET_SCAN_FILES")
                return False

            # Attendi la risposta con un timeout di 30 secondi
            files_response = None
            start_time = time.time()

            while time.time() - start_time < 30.0:
                # Permetti all'interfaccia di processare eventi
                if 'QApplication' in globals():
                    QApplication.processEvents()

                if connection_manager.has_response(scanner.device_id, "GET_SCAN_FILES"):
                    files_response = connection_manager.get_response(scanner.device_id, "GET_SCAN_FILES")
                    break
                time.sleep(0.1)

            if not files_response or files_response.get("status") != "ok":
                logger.error("Nessuna risposta valida alla richiesta GET_SCAN_FILES")
                if self._progress_callback:
                    self._progress_callback(0, "Errore nella richiesta dell'elenco dei file")
                return False

            # Estrai la lista dei file
            files = files_response.get("files", [])
            if not files:
                logger.error("Nessun file disponibile per la scansione")
                if self._progress_callback:
                    self._progress_callback(0, "Nessun file disponibile per la scansione")
                return False

            logger.info(f"Trovati {len(files)} file da scaricare")

            # Inizializza contatore per il progresso
            total_files = len(files)
            downloaded_files = 0

            # Scarica ogni file
            for i, file_info in enumerate(files):
                if self._processing_cancelled.is_set():
                    logger.info("Download annullato dall'utente")
                    return False

                remote_path = file_info.get("path")
                # Crea il percorso locale in base al percorso remoto
                rel_path = file_info.get("relative_path", os.path.basename(remote_path))
                local_path = scan_dir / rel_path

                # Crea le directory intermedie se necessario
                os.makedirs(os.path.dirname(str(local_path)), exist_ok=True)

                # Aggiorna il progresso
                progress = 10 + (i / total_files) * 80  # Da 10% a 90%
                if self._progress_callback:
                    self._progress_callback(progress,
                                            f"Download file {i + 1}/{total_files}: {os.path.basename(remote_path)}")

                # Invia la richiesta per ottenere il file
                logger.debug(f"Richiesta file: {remote_path}")
                if not connection_manager.send_message(
                        scanner.device_id,
                        "GET_FILE",
                        {"path": remote_path}
                ):
                    logger.warning(f"Impossibile inviare richiesta per il file: {remote_path}")
                    continue

                # Attendi la risposta con un timeout di 30 secondi
                file_response = None
                file_start_time = time.time()

                while time.time() - file_start_time < 30.0:
                    # Permetti all'interfaccia di processare eventi
                    if 'QApplication' in globals():
                        QApplication.processEvents()

                    if connection_manager.has_response(scanner.device_id, "GET_FILE"):
                        file_response = connection_manager.get_response(scanner.device_id, "GET_FILE")
                        break
                    time.sleep(0.1)

                if not file_response or file_response.get("status") != "ok":
                    logger.warning(f"Errore nel download del file: {remote_path}")
                    continue

                # Salva il file
                file_data = file_response.get("data")
                if file_data:
                    try:
                        # Il server potrebbe inviare i dati in formato base64
                        if isinstance(file_data, str):
                            import base64
                            file_data = base64.b64decode(file_data)

                        with open(str(local_path), "wb") as f:
                            f.write(file_data)

                        downloaded_files += 1
                        logger.debug(f"File salvato: {local_path}")
                    except Exception as e:
                        logger.error(f"Errore nel salvataggio del file {local_path}: {e}")
                else:
                    logger.warning(f"Dati file vuoti per: {remote_path}")

            # Download della calibrazione
            if self._progress_callback:
                self._progress_callback(90, "Download dati di calibrazione...")

            try:
                # Invia richiesta per i dati di calibrazione
                connection_manager.send_message(
                    scanner.device_id,
                    "GET_CALIBRATION"
                )

                # Attendi la risposta
                calib_response = None
                calib_start_time = time.time()

                while time.time() - calib_start_time < 20.0:
                    # Permetti all'interfaccia di processare eventi
                    if 'QApplication' in globals():
                        QApplication.processEvents()

                    if connection_manager.has_response(scanner.device_id, "GET_CALIBRATION"):
                        calib_response = connection_manager.get_response(scanner.device_id, "GET_CALIBRATION")
                        break
                    time.sleep(0.1)

                if calib_response and calib_response.get("status") == "ok":
                    calib_data = calib_response.get("data")
                    if calib_data:
                        calib_file = scan_dir / "calibration.npz"
                        with open(str(calib_file), "wb") as f:
                            # Il server potrebbe inviare i dati in formato base64
                            if isinstance(calib_data, str):
                                import base64
                                calib_data = base64.b64decode(calib_data)
                            f.write(calib_data)
                        logger.info("Dati di calibrazione salvati")
            except Exception as e:
                logger.warning(f"Errore nel download dei dati di calibrazione: {e}")

            # Completamento
            if self._progress_callback:
                self._progress_callback(100, f"Download completato: {downloaded_files}/{total_files} file")

            # Imposta la directory corrente e carica le immagini
            self.scan_dir = scan_dir
            self.scan_id = scan_id
            self._find_scan_images()

            logger.info(f"Download completato: {downloaded_files}/{total_files} file scaricati")
            return downloaded_files > 0

        except Exception as e:
            logger.error(f"Errore nel download dei dati della scansione: {e}")
            if self._progress_callback:
                self._progress_callback(0, f"Errore: {str(e)}")
            return False"""

    def _request_scan_config(self, connection_manager, device_id):
        """Request scan configuration from the server."""
        try:
            connection_manager.send_message(device_id, "GET_SCAN_CONFIG")
            # Wait for response
            for _ in range(10):  # Try up to 10 times with a delay
                if connection_manager.has_response(device_id, "GET_SCAN_CONFIG"):
                    response = connection_manager.get_response(device_id, "GET_SCAN_CONFIG")
                    if response and response.get("status") == "ok":
                        return True, response.get("scan_config", {})
                time.sleep(0.1)
            return False, None
        except Exception as e:
            logger.error(f"Error requesting scan config: {e}")
            return False, None

    def _request_scan_files(self, connection_manager, device_id, scan_id):
        """Request list of scan files from the server."""
        try:
            connection_manager.send_message(device_id, "GET_SCAN_FILES",
                                            {"scan_id": scan_id})
            # Wait for response
            for _ in range(10):  # Try up to 10 times with a delay
                if connection_manager.has_response(device_id, "GET_SCAN_FILES"):
                    response = connection_manager.get_response(device_id, "GET_SCAN_FILES")
                    if response and response.get("status") == "ok":
                        return True, response.get("files", [])
                time.sleep(0.1)
            return False, None
        except Exception as e:
            logger.error(f"Error requesting scan files: {e}")
            return False, None

    def _download_file(self, connection_manager, device_id, remote_path, local_path):
        """Download a single file from the server."""
        try:
            # Request file data
            connection_manager.send_message(device_id, "GET_FILE",
                                            {"path": remote_path})

            # Wait for response
            for _ in range(20):  # Try up to 20 times with a delay
                if connection_manager.has_response(device_id, "GET_FILE"):
                    response = connection_manager.get_response(device_id, "GET_FILE")
                    if response and response.get("status") == "ok":
                        # Save file data
                        file_data = response.get("data")
                        if file_data:
                            with open(local_path, "wb") as f:
                                f.write(file_data)
                            return True
                    break
                time.sleep(0.1)

            return False
        except Exception as e:
            logger.error(f"Error downloading file: {e}")
            return False

    def _load_or_download_calibration(self, connection_manager, device_id):
        """
        Load existing calibration data or download from server.
        """
        # First check if calibration data exists locally
        calib_file = self.output_dir / "calibration.npz"

        if calib_file.exists():
            try:
                self.calib_data = np.load(calib_file)
                logger.info("Loaded calibration data from local file")

                # Generate rectification maps
                self._generate_rectification_maps()
                return True
            except Exception as e:
                logger.error(f"Error loading calibration data: {e}")

        # If not found locally, try to download
        try:
            logger.info("Downloading calibration data from server")
            connection_manager.send_message(device_id, "GET_CALIBRATION")

            # Wait for response
            for _ in range(10):
                if connection_manager.has_response(device_id, "GET_CALIBRATION"):
                    response = connection_manager.get_response(device_id, "GET_CALIBRATION")
                    if response and response.get("status") == "ok":
                        calib_data = response.get("data")
                        if calib_data:
                            # Save calibration data
                            with open(calib_file, "wb") as f:
                                f.write(calib_data)

                            # Load the saved data
                            self.calib_data = np.load(calib_file)

                            # Generate rectification maps
                            self._generate_rectification_maps()
                            return True
                    break
                time.sleep(0.1)

            # If we got here, we couldn't download calibration
            logger.warning("Failed to download calibration data. Using default values.")
            self._create_default_calibration()
            return False

        except Exception as e:
            logger.error(f"Error downloading calibration data: {e}")
            self._create_default_calibration()
            return False

    def _create_default_calibration(self):
        """Create default calibration data for testing."""
        # This is a fallback for when no calibration is available
        # In a real system, proper calibration is essential
        logger.warning("Creating default calibration (INACCURATE - for testing only)")

        # Create a simple default calibration (assumes 640x480 images)
        img_size = (640, 480)
        focal_length = 800  # A reasonable default focal length

        # Camera matrices
        K1 = np.array([
            [focal_length, 0, img_size[0] / 2],
            [0, focal_length, img_size[1] / 2],
            [0, 0, 1]
        ])
        K2 = K1.copy()

        # Distortion coefficients (no distortion for default)
        d1 = np.zeros(5)
        d2 = np.zeros(5)

        # Rotation matrix (identity for aligned cameras)
        R = np.eye(3)

        # Translation (assume baseline of 10cm = 100mm along X axis)
        t = np.array([100, 0, 0])

        # Save to npz file
        calib_file = self.output_dir / "calibration.npz"
        np.savez(calib_file,
                 M1=K1, M2=K2,
                 d1=d1, d2=d2,
                 R=R, t=t)

        # Load the saved file
        self.calib_data = np.load(calib_file)

        # Generate rectification maps
        self._generate_rectification_maps()

    def _generate_rectification_maps(self):
        """Generate rectification maps from calibration data."""
        if self.calib_data is None:
            return False

        try:
            # Extract calibration parameters
            M1 = self.calib_data['M1']
            M2 = self.calib_data['M2']
            d1 = self.calib_data['d1']
            d2 = self.calib_data['d2']
            R = self.calib_data['R']
            t = self.calib_data['t']

            # Determine image size from first image if available
            if self.left_images and len(self.left_images) > 0:
                img = cv2.imread(self.left_images[0])
                img_size = (img.shape[1], img.shape[0])
            else:
                # Default size if no images are available
                img_size = (640, 480)

            # Compute rectification parameters
            R1, R2, P1, P2, Q, roi1, roi2 = cv2.stereoRectify(
                cameraMatrix1=M1,
                cameraMatrix2=M2,
                distCoeffs1=d1,
                distCoeffs2=d2,
                imageSize=img_size,
                R=R,
                T=t,
                flags=cv2.CALIB_ZERO_DISPARITY,
                alpha=0
            )

            # Generate rectification maps
            self.map_x_l, self.map_y_l = cv2.initUndistortRectifyMap(
                M1, d1, R1, P1, img_size, cv2.CV_32FC1)

            self.map_x_r, self.map_y_r = cv2.initUndistortRectifyMap(
                M2, d2, R2, P2, img_size, cv2.CV_32FC1)

            # Store Q matrix for reprojection
            self.Q = Q

            logger.info("Successfully generated rectification maps")
            return True

        except Exception as e:
            logger.error(f"Error generating rectification maps: {e}")
            return False

    def _find_scan_images(self):
        """
        Trova e ordina tutte le immagini di scansione nella directory con maggiore robustezza.
        Versione completamente riscritta per gestire più casi e formati.
        """
        # Reset delle liste
        self.left_images = []
        self.right_images = []

        # Verifica che la directory esista
        if not self.scan_dir or not os.path.isdir(self.scan_dir):
            logger.error(f"Directory di scansione non trovata: {self.scan_dir}")
            return False

        # Log completo del contenuto della directory per debug
        logger.info(f"Contenuto directory root: {os.listdir(self.scan_dir)}")

        # Cerca le sottodirectory left e right
        left_dir = os.path.join(self.scan_dir, "left")
        right_dir = os.path.join(self.scan_dir, "right")

        # Verifica esistenza sottodirectory
        if not os.path.isdir(left_dir):
            logger.error(f"Directory 'left' non trovata: {left_dir}")
            # Cerca direttamente nella directory padre
            logger.info("Tentativo di ricerca direttamente nella directory scan...")
            self._find_images_in_root()
            return len(self.left_images) > 0 and len(self.right_images) > 0

        if not os.path.isdir(right_dir):
            logger.error(f"Directory 'right' non trovata: {right_dir}")
            # Cerca direttamente nella directory padre
            logger.info("Tentativo di ricerca direttamente nella directory scan...")
            self._find_images_in_root()
            return len(self.left_images) > 0 and len(self.right_images) > 0

        # Log del contenuto delle sottodirectory
        logger.info(f"Contenuto directory left: {os.listdir(left_dir)}")
        logger.info(f"Contenuto directory right: {os.listdir(right_dir)}")

        # Estensioni da cercare
        extensions = ['*.png', '*.jpg', '*.jpeg', '*.npy']

        # Cerca file in ciascuna sottodirectory
        left_images = []
        right_images = []

        for ext in extensions:
            left_images.extend(glob.glob(os.path.join(left_dir, ext)))
            right_images.extend(glob.glob(os.path.join(right_dir, ext)))

        # Ordina per nome
        left_images.sort()
        right_images.sort()

        # Verifica che ci siano immagini
        if not left_images:
            logger.error(f"Nessuna immagine trovata in: {left_dir}")
            return False

        if not right_images:
            logger.error(f"Nessuna immagine trovata in: {right_dir}")
            return False

        # Salva le liste
        self.left_images = left_images
        self.right_images = right_images

        # Se il numero di immagini è diverso, tronca alla lista più corta
        if len(self.left_images) != len(self.right_images):
            logger.warning(f"Numero immagini diverso: left={len(self.left_images)}, right={len(self.right_images)}")
            min_len = min(len(self.left_images), len(self.right_images))
            self.left_images = self.left_images[:min_len]
            self.right_images = self.right_images[:min_len]

        # Log di riepilogo
        self.num_patterns = len(self.left_images)
        logger.info(f"Trovate {self.num_patterns} coppie di immagini")

        # Log dettagliato delle prime immagini
        if self.num_patterns > 0:
            logger.info(f"Prima immagine left: {self.left_images[0]}")
            logger.info(f"Prima immagine right: {self.right_images[0]}")

        # Determina il tipo di pattern dai nomi dei file
        self._detect_pattern_type()

        return self.num_patterns > 0

    def _find_images_in_root(self):
        """
        Cerca immagini direttamente nella directory principale della scansione.
        Utile come fallback quando le sottodirectory non sono trovate.
        """
        logger.info(f"Cerco immagini nella root: {self.scan_dir}")

        # Estensioni da cercare
        extensions = ['*.png', '*.jpg', '*.jpeg', '*.npy']

        # Liste per ogni camera
        left_images = []
        right_images = []

        # Cerca immagini con prefissi o suffissi che indicano left/right
        for ext in extensions:
            # Cerca file con pattern specifici nei nomi
            left_patterns = [
                os.path.join(self.scan_dir, f"left_*{ext.replace('*', '')}"),
                os.path.join(self.scan_dir, f"*_left{ext.replace('*', '')}"),
                os.path.join(self.scan_dir, f"camera0*{ext.replace('*', '')}"),
                os.path.join(self.scan_dir, f"cam0*{ext.replace('*', '')}")
            ]

            right_patterns = [
                os.path.join(self.scan_dir, f"right_*{ext.replace('*', '')}"),
                os.path.join(self.scan_dir, f"*_right{ext.replace('*', '')}"),
                os.path.join(self.scan_dir, f"camera1*{ext.replace('*', '')}"),
                os.path.join(self.scan_dir, f"cam1*{ext.replace('*', '')}")
            ]

            # Cerca per ogni pattern
            for pattern in left_patterns:
                left_images.extend(glob.glob(pattern))

            for pattern in right_patterns:
                right_images.extend(glob.glob(pattern))

        # Se abbiamo trovato immagini, ordiniamole e salviamole
        if left_images and right_images:
            left_images.sort()
            right_images.sort()

            self.left_images = left_images
            self.right_images = right_images

            # Tronca se necessario
            min_len = min(len(self.left_images), len(self.right_images))
            self.left_images = self.left_images[:min_len]
            self.right_images = self.right_images[:min_len]

            self.num_patterns = min_len

            logger.info(f"Trovate {self.num_patterns} coppie nella directory root")
            return True

        logger.error("Nessuna immagine trovata con pattern left/right nella directory root")
        return False

    def _detect_pattern_type(self):
        """Detect pattern type from image filenames or scan config."""
        # Default to PROGRESSIVE
        self.pattern_type = PatternType.PROGRESSIVE

        # Try to load from config file
        config_file = self.scan_dir / "scan_config.json"
        if config_file.exists():
            try:
                with open(config_file, 'r') as f:
                    config = json.load(f)
                pattern_type_str = config.get('pattern_type', 'PROGRESSIVE')
                try:
                    self.pattern_type = PatternType(pattern_type_str)
                except ValueError:
                    pass
            except Exception as e:
                logger.error(f"Error loading scan config: {e}")

        # Also check filenames for pattern type hints
        if self.left_images:
            filename = os.path.basename(self.left_images[0])
            if 'gray' in filename.lower():
                self.pattern_type = PatternType.GRAY_CODE
            elif 'binary' in filename.lower():
                self.pattern_type = PatternType.BINARY_CODE
            elif 'phase' in filename.lower():
                self.pattern_type = PatternType.PHASE_SHIFT

        logger.info(f"Detected pattern type: {self.pattern_type.name}")

    def load_local_scan(self, scan_dir: str) -> bool:
        """
        Load scan data from a local directory.

        Args:
            scan_dir: Directory containing scan data

        Returns:
            True if load was successful, False otherwise
        """
        try:
            self.scan_dir = Path(scan_dir)
            self.scan_id = self.scan_dir.name

            # Assicura che la directory principale esista
            self.scan_dir.mkdir(parents=True, exist_ok=True)

            # Crea le sottodirectory necessarie
            left_dir = self.scan_dir / "left"
            right_dir = self.scan_dir / "right"
            left_dir.mkdir(exist_ok=True)
            right_dir.mkdir(exist_ok=True)

            # Find scan images
            success = self._find_scan_images()
            if not success:
                logger.warning(f"No scan images found in {scan_dir}, but directories are prepared")

            # Load calibration data if available
            calib_file = self.scan_dir / "calibration.npz"
            if not calib_file.exists():
                calib_file = self.output_dir / "calibration.npz"

            if calib_file.exists():
                self.calib_data = np.load(calib_file)
                self._generate_rectification_maps()
            else:
                logger.warning("No calibration data found, using default values")
                self._create_default_calibration()

            logger.info(f"Successfully loaded scan from {scan_dir}")
            return True

        except Exception as e:
            logger.error(f"Error loading local scan: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False

    def process_scan(self, use_threading: bool = True, incremental: bool = False) -> bool:
        """
        Process the scan data to generate a 3D point cloud.

        Args:
            use_threading: Whether to run processing in a separate thread
            incremental: Whether this is an incremental processing for real-time visualization

        Returns:
            True if processing started successfully, False otherwise
        """
        if not self.scan_dir or not self.left_images or not self.right_images:
            logger.error("No scan data loaded")
            return False

        if not self.calib_data or self.map_x_l is None:
            logger.error("No calibration data loaded")
            return False

        # Reset processing state
        self._processing_complete.clear()
        self._processing_cancelled.clear()

        # Save the incremental flag
        self._incremental_mode = incremental

        if use_threading:
            # Start processing in a separate thread
            self.processing_thread = threading.Thread(target=self._process_scan_thread)
            self.processing_thread.daemon = True
            self.processing_thread.start()
            return True
        else:
            # Run processing in the current thread
            return self._process_scan_thread()

    def _process_scan_thread(self) -> bool:
        """Thread function for scan processing."""
        try:
            logger.info(f"Starting scan processing for {self.scan_id}")
            start_time = time.time()

            # Choose processing method based on pattern type
            if self.pattern_type == PatternType.GRAY_CODE:
                success = self._process_gray_code()
            elif self.pattern_type == PatternType.BINARY_CODE:
                success = self._process_binary_code()
            else:
                # Default to PROGRESSIVE for other types
                success = self._process_progressive()

            # Calculate total processing time
            processing_time = time.time() - start_time
            logger.info(f"Scan processing completed in {processing_time:.1f} seconds")

            # Signal completion
            self._processing_complete.set()

            # Call completion callback if provided
            if self._completion_callback:
                if success:
                    message = f"Processing completed in {processing_time:.1f} seconds"
                    self._completion_callback(True, message, self.pointcloud)
                else:
                    self._completion_callback(False, "Processing failed", None)

            return success

        except Exception as e:
            logger.error(f"Error processing scan: {e}")

            # Call completion callback with error
            if self._completion_callback:
                self._completion_callback(False, f"Error processing scan: {e}", None)

            return False

    def _process_progressive(self) -> bool:
        """
        Process progressive pattern scan with incremental pointcloud generation.
        This is similar to gray code but with progressive refinement and real-time updates.
        """
        try:
            # Flag per distinguere tra modalità completa e incrementale
            incremental_mode = getattr(self, '_incremental_mode', False)

            if incremental_mode:
                logger.info("Processing progressive pattern scan in incremental mode")
            else:
                logger.info("Processing progressive pattern scan with full resolution")

            # Check if we have at least white/black and some pattern images
            if len(self.left_images) < 4:
                logger.error("Not enough images for processing")
                return False

            # Ensure calibration data is available
            if self.map_x_l is None:
                self._generate_rectification_maps()

            # Load white and black reference images
            white_l = cv2.imread(self.left_images[0], cv2.IMREAD_GRAYSCALE)
            white_r = cv2.imread(self.right_images[0], cv2.IMREAD_GRAYSCALE)
            black_l = cv2.imread(self.left_images[1], cv2.IMREAD_GRAYSCALE)
            black_r = cv2.imread(self.right_images[1], cv2.IMREAD_GRAYSCALE)

            # Check image sizes
            if (white_l is None or white_r is None or
                    black_l is None or black_r is None):
                logger.error("Failed to load white/black reference images")
                return False

            logger.info(f"Reference image sizes: white_l={white_l.shape}, white_r={white_r.shape}")

            # Rectify reference images
            white_l_rect = cv2.remap(white_l, self.map_x_l, self.map_y_l, cv2.INTER_LINEAR)
            white_r_rect = cv2.remap(white_r, self.map_x_r, self.map_y_r, cv2.INTER_LINEAR)
            black_l_rect = cv2.remap(black_l, self.map_x_l, self.map_y_l, cv2.INTER_LINEAR)
            black_r_rect = cv2.remap(black_r, self.map_x_r, self.map_y_r, cv2.INTER_LINEAR)

            # Compute shadow masks (areas with sufficient contrast between white and black)
            shadow_mask_l = np.zeros_like(black_l_rect)
            shadow_mask_r = np.zeros_like(black_r_rect)
            black_threshold = 40  # Threshold for detecting shadowed areas
            shadow_mask_l[white_l_rect > black_l_rect + black_threshold] = 1
            shadow_mask_r[white_r_rect > black_r_rect + black_threshold] = 1

            # Get image dimensions
            height, width = shadow_mask_l.shape[:2]

            # Initialize disparity maps
            disparity_map = np.zeros((height, width), dtype=np.float32)
            confidence_map = np.zeros((height, width), dtype=np.float32)

            # Calcola il numero di pattern effettivamente disponibili (esclusi white/black)
            pattern_images = len(self.left_images) - 2

            # In modalità incrementale, potremmo elaborare un numero inferiore di pattern
            if incremental_mode:
                # Usiamo tutti i pattern disponibili, ma ottimizziamo per la velocità
                pattern_pairs = pattern_images // 2  # Consideriamo coppie orizz/vert
                if pattern_pairs > 8 and incremental_mode:
                    # In modalità incrementale, limita per maggiore velocità
                    pattern_pairs = min(8, pattern_pairs)
            else:
                pattern_pairs = pattern_images // 2  # Tutte le coppie orizz/vert

            logger.info(f"Processing {pattern_pairs} pattern pairs out of {pattern_images} available patterns")

            # Store incremental pointclouds
            incremental_pointclouds = []
            last_reprojection_index = -1

            for i in range(pattern_pairs):
                # Report progress
                progress = (i + 1) / pattern_pairs * 100
                if self._progress_callback:
                    self._progress_callback(progress, f"Processing patterns: {i + 1}/{pattern_pairs}")

                # Check for cancellation
                if self._processing_cancelled.is_set():
                    logger.info("Processing cancelled")
                    return False

                # Load and rectify horizontal pattern
                h_idx = 2 + i
                if h_idx < len(self.left_images):
                    h_pattern_l = cv2.imread(self.left_images[h_idx], cv2.IMREAD_GRAYSCALE)
                    h_pattern_r = cv2.imread(self.right_images[h_idx], cv2.IMREAD_GRAYSCALE)

                    if h_pattern_l is None or h_pattern_r is None:
                        logger.warning(f"Failed to load pattern images at index {h_idx}")
                        continue

                    h_pattern_l_rect = cv2.remap(h_pattern_l, self.map_x_l, self.map_y_l, cv2.INTER_LINEAR)
                    h_pattern_r_rect = cv2.remap(h_pattern_r, self.map_x_r, self.map_y_r, cv2.INTER_LINEAR)

                    # Process horizontal pattern
                    self._update_disparity_from_pattern(
                        h_pattern_l_rect, h_pattern_r_rect,
                        shadow_mask_l, shadow_mask_r,
                        disparity_map, confidence_map,
                        pattern_weight=2 ** i
                    )

                # Load and rectify vertical pattern if available
                v_idx = 2 + pattern_pairs + i
                if v_idx < len(self.left_images):
                    v_pattern_l = cv2.imread(self.left_images[v_idx], cv2.IMREAD_GRAYSCALE)
                    v_pattern_r = cv2.imread(self.right_images[v_idx], cv2.IMREAD_GRAYSCALE)

                    if v_pattern_l is None or v_pattern_r is None:
                        logger.warning(f"Failed to load pattern images at index {v_idx}")
                        continue

                    v_pattern_l_rect = cv2.remap(v_pattern_l, self.map_x_l, self.map_y_l, cv2.INTER_LINEAR)
                    v_pattern_r_rect = cv2.remap(v_pattern_r, self.map_x_r, self.map_y_r, cv2.INTER_LINEAR)

                    # Process vertical pattern
                    self._update_disparity_from_pattern(
                        v_pattern_l_rect, v_pattern_r_rect,
                        shadow_mask_l, shadow_mask_r,
                        disparity_map, confidence_map,
                        pattern_weight=2 ** i
                    )

                # Generate incremental pointcloud every few patterns or at the end
                # In modalità incrementale, generiamo più frequentemente
                update_interval = 2 if incremental_mode else 3
                if ((i > 0 and (i % update_interval == 0 or i == pattern_pairs - 1)) and
                        last_reprojection_index != i):
                    # Calculate intermediate disparity map
                    valid_indices = confidence_map > 0
                    current_disparity = np.zeros_like(disparity_map)
                    current_disparity[valid_indices] = disparity_map[valid_indices] / confidence_map[valid_indices]

                    # Apply median filter to remove noise
                    # In modalità incrementale, usiamo un kernel più piccolo per velocità
                    kernel_size = 3 if incremental_mode else 5
                    current_disparity = cv2.medianBlur(current_disparity.astype(np.float32), kernel_size)

                    # Reproject to 3D (temporary pointcloud)
                    temp_pointcloud = self._reproject_to_3d_incremental(current_disparity, shadow_mask_l)

                    if temp_pointcloud is not None and len(temp_pointcloud) > 0:
                        # Store incremental pointcloud
                        incremental_pointclouds.append(temp_pointcloud)

                        # Update the pointcloud property for external access
                        self.pointcloud = temp_pointcloud

                        # Call completion callback with incremental update
                        if self._completion_callback:
                            message = f"Incremental update ({i + 1}/{pattern_pairs} patterns processed)"
                            self._completion_callback(True, message, temp_pointcloud)

                    last_reprojection_index = i

            # Calculate final disparity map
            valid_indices = confidence_map > 0
            disparity_map_final = np.zeros_like(disparity_map)
            disparity_map_final[valid_indices] = disparity_map[valid_indices] / confidence_map[valid_indices]

            # Apply median filter to remove noise
            kernel_size = 3 if incremental_mode else 5
            disparity_map_final = cv2.medianBlur(disparity_map_final.astype(np.float32), kernel_size)

            # Salva mappe di disparità solo in modalità non incrementale
            if not incremental_mode:
                # Save disparity map for visualization
                disparity_colored = cv2.applyColorMap(
                    cv2.convertScaleAbs(disparity_map_final,
                                        alpha=255 / np.max(disparity_map_final) if np.max(
                                            disparity_map_final) > 0 else 0),
                    cv2.COLORMAP_JET
                )
                cv2.imwrite(str(self.scan_dir / "disparity_map.png"), disparity_colored)

            # Final reproject to 3D
            if incremental_mode:
                # In modo incrementale, usiamo la versione rapida
                final_pointcloud = self._reproject_to_3d_incremental(disparity_map_final, shadow_mask_l)
                self.pointcloud = final_pointcloud

                # Chiamiamo la callback di completamento
                if self._completion_callback and final_pointcloud is not None:
                    self._completion_callback(True, "Incremental processing complete", final_pointcloud)

                return True
            else:
                # In modalità completa, usiamo la versione standard con tutti i filtri
                return self._reproject_to_3d(disparity_map_final, shadow_mask_l)

        except Exception as e:
            logger.error(f"Error in progressive pattern processing: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False

    def _reproject_to_3d_incremental(self, disparity_map, mask):
        """
        Reproject disparity map to 3D points for incremental updates.
        Optimized for speed in real-time visualization.

        Args:
            disparity_map: Current disparity map
            mask: Mask for valid pixels

        Returns:
            Numpy array of 3D points
        """
        try:
            # Ensure we have valid disparity and calibration
            if disparity_map is None or self.Q is None:
                logger.error("Missing disparity map or calibration for reprojection")
                return None

            # Create point cloud from disparity map
            logger.info("Reprojecting to 3D points (incremental)")

            # Apply mask to disparity map
            masked_disparity = disparity_map.copy()
            masked_disparity[mask == 0] = 0

            # Reproject to 3D
            points_3d = cv2.reprojectImageTo3D(masked_disparity, self.Q)

            # Filter invalid points
            mask = (
                    ~np.isnan(points_3d).any(axis=2) &
                    ~np.isinf(points_3d).any(axis=2) &
                    (mask > 0)
            )

            # Extract valid points
            valid_points = points_3d[mask]

            # Limit points to reasonable range
            max_range = 500  # mm
            in_range_mask = (
                    (np.abs(valid_points[:, 0]) < max_range) &
                    (np.abs(valid_points[:, 1]) < max_range) &
                    (np.abs(valid_points[:, 2]) < max_range)
            )

            valid_points = valid_points[in_range_mask]

            # If we have too many points, randomly sample for performance
            if len(valid_points) > 50000:
                # Random sampling for performance in incremental updates
                sample_indices = np.random.choice(len(valid_points), 50000, replace=False)
                valid_points = valid_points[sample_indices]
            elif len(valid_points) < 10:
                # Troppo pochi punti, potrebbe esserci un problema
                logger.warning("Too few valid points in reprojection, likely an error")
                return None

            logger.info(f"Generated incremental point cloud with {len(valid_points)} points")
            return valid_points

        except Exception as e:
            logger.error(f"Error in incremental 3D reprojection: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return None

    def _process_gray_code(self) -> bool:
        """
        Process Gray code pattern scan.
        This uses the more accurate Gray code algorithm.
        """
        try:
            logger.info("Processing Gray code pattern scan")

            # Check if we have enough images
            if len(self.left_images) < 6:  # White, black, and at least 4 pattern images
                logger.error("Not enough images for Gray code processing")
                return False

            # Use OpenCV's structured light module if available
            if hasattr(cv2, 'structured_light_GrayCodePattern'):
                return self._process_gray_code_opencv()
            else:
                # Fallback to custom implementation
                return self._process_gray_code_custom()

        except Exception as e:
            logger.error(f"Error in Gray code processing: {e}")
            return False

    def _process_gray_code_opencv(self) -> bool:
        """Process Gray code pattern using OpenCV's built-in module."""
        try:
            # Create Gray code pattern object
            proj_width = 1920  # Projected pattern width
            proj_height = 1080  # Projected pattern height

            graycode = cv2.structured_light_GrayCodePattern.create(
                width=proj_width, height=proj_height)

            # Set threshold parameters
            white_threshold = 5  # For positive-negative difference
            black_threshold = 40  # For white-black shading detection
            graycode.setWhiteThreshold(white_threshold)
            graycode.setBlackThreshold(black_threshold)

            # Get number of pattern images (excluding white/black)
            num_required_imgs = graycode.getNumberOfPatternImages()
            logger.info(f"Gray code requires {num_required_imgs} pattern images")

            # Ensure we have enough images
            if len(self.left_images) < num_required_imgs + 2:
                logger.error(
                    f"Not enough images for Gray code: have {len(self.left_images)}, need {num_required_imgs + 2}")
                return False

            # Rectify all images
            rect_list_l, rect_list_r = [], []
            for i in range(num_required_imgs + 2):
                img_l = cv2.imread(self.left_images[i], cv2.IMREAD_GRAYSCALE)
                img_r = cv2.imread(self.right_images[i], cv2.IMREAD_GRAYSCALE)

                l_rect = cv2.remap(img_l, self.map_x_l, self.map_y_l, cv2.INTER_LINEAR)
                r_rect = cv2.remap(img_r, self.map_x_r, self.map_y_r, cv2.INTER_LINEAR)

                rect_list_l.append(l_rect)
                rect_list_r.append(r_rect)

                # Update progress
                if self._progress_callback:
                    progress = (i + 1) / (num_required_imgs + 2) * 50  # First 50% is rectification
                    self._progress_callback(progress, f"Rectifying images: {i + 1}/{num_required_imgs + 2}")

            # Decode patterns
            pattern_list = [rect_list_l[:-2], rect_list_r[:-2]]
            white_list = [rect_list_l[-2], rect_list_r[-2]]
            black_list = [rect_list_l[-1], rect_list_r[-1]]

            logger.info("Decoding Gray code patterns")
            ret, disparity_l = graycode.decode(
                pattern_list,
                np.zeros_like(pattern_list[0]),
                black_list,
                white_list
            )

            if not ret:
                logger.error("Failed to decode Gray code patterns")
                return False

            # Save disparity map for visualization
            disparity_colored = cv2.applyColorMap(
                cv2.convertScaleAbs(disparity_l, alpha=255 / np.max(disparity_l) if np.max(disparity_l) > 0 else 0),
                cv2.COLORMAP_JET
            )
            cv2.imwrite(str(self.scan_dir / "disparity_map.png"), disparity_colored)

            # Update progress
            if self._progress_callback:
                self._progress_callback(75, "Creating point cloud...")

            # Create shadow mask
            shadow_mask_l = np.zeros_like(disparity_l, dtype=np.uint8)
            shadow_mask_l[disparity_l > 0] = 1

            # Reproject to 3D
            self._reproject_to_3d(disparity_l, shadow_mask_l)

            return True

        except Exception as e:
            logger.error(f"Error in OpenCV Gray code processing: {e}")
            return False

    def _process_gray_code_custom(self) -> bool:
        """
        Custom implementation of Gray code processing.
        Used as fallback when OpenCV's structured light module is not available.
        """
        # This is a simplified implementation
        logger.warning("Using custom Gray code implementation (less accurate)")

        try:
            # Load and rectify white/black reference images
            white_l = cv2.imread(self.left_images[0], cv2.IMREAD_GRAYSCALE)
            white_r = cv2.imread(self.right_images[0], cv2.IMREAD_GRAYSCALE)
            black_l = cv2.imread(self.left_images[1], cv2.IMREAD_GRAYSCALE)
            black_r = cv2.imread(self.right_images[1], cv2.IMREAD_GRAYSCALE)

            white_l_rect = cv2.remap(white_l, self.map_x_l, self.map_y_l, cv2.INTER_LINEAR)
            white_r_rect = cv2.remap(white_r, self.map_x_r, self.map_y_r, cv2.INTER_LINEAR)
            black_l_rect = cv2.remap(black_l, self.map_x_l, self.map_y_l, cv2.INTER_LINEAR)
            black_r_rect = cv2.remap(black_r, self.map_x_r, self.map_y_r, cv2.INTER_LINEAR)

            # Create shadow masks
            shadow_mask_l = np.zeros_like(black_l_rect)
            shadow_mask_r = np.zeros_like(black_r_rect)
            black_threshold = 40
            shadow_mask_l[white_l_rect > black_l_rect + black_threshold] = 1
            shadow_mask_r[white_r_rect > black_r_rect + black_threshold] = 1

            # Get image dimensions
            height, width = shadow_mask_l.shape[:2]

            # Process the pattern images (starting from index 2)
            pattern_images = len(self.left_images) - 2

            # Binary codes for each pixel position
            binary_codes_l = np.zeros((height, width, pattern_images), dtype=np.uint8)
            binary_codes_r = np.zeros((height, width, pattern_images), dtype=np.uint8)

            for i in range(pattern_images):
                img_idx = i + 2  # Skip white and black images

                # Load and rectify pattern image
                pattern_l = cv2.imread(self.left_images[img_idx], cv2.IMREAD_GRAYSCALE)
                pattern_r = cv2.imread(self.right_images[img_idx], cv2.IMREAD_GRAYSCALE)

                pattern_l_rect = cv2.remap(pattern_l, self.map_x_l, self.map_y_l, cv2.INTER_LINEAR)
                pattern_r_rect = cv2.remap(pattern_r, self.map_x_r, self.map_y_r, cv2.INTER_LINEAR)

                # Threshold to get binary code
                binary_codes_l[:, :, i] = (pattern_l_rect > (white_l_rect + black_l_rect) / 2).astype(np.uint8)
                binary_codes_r[:, :, i] = (pattern_r_rect > (white_r_rect + black_r_rect) / 2).astype(np.uint8)

                # Update progress
                if self._progress_callback:
                    progress = (i + 1) / pattern_images * 50  # First 50% is coding
                    self._progress_callback(progress, f"Processing patterns: {i + 1}/{pattern_images}")

            # Decode Gray codes to get disparity map
            disparity_map = np.zeros((height, width), dtype=np.float32)

            # For each pixel in the left image
            for y in range(height):
                for x in range(width):
                    # Skip pixels in shadow
                    if shadow_mask_l[y, x] == 0:
                        continue

                    # Get binary code for current pixel
                    code_l = binary_codes_l[y, x, :]

                    # Look for matching code in right image (along the same scanline)
                    best_match_x = -1
                    best_match_diff = pattern_images  # Maximum possible difference

                    for x_r in range(width):
                        # Skip pixels in shadow in right image
                        if shadow_mask_r[y, x_r] == 0 or x_r >= x:  # Only look for matches to the left
                            continue

                        # Get binary code for right image pixel
                        code_r = binary_codes_r[y, x_r, :]

                        # Calculate Hamming distance (number of different bits)
                        diff = np.sum(code_l != code_r)

                        # Update best match if this is better
                        if diff < best_match_diff:
                            best_match_diff = diff
                            best_match_x = x_r

                    # If we found a match with low difference, calculate disparity
                    if best_match_x >= 0 and best_match_diff < pattern_images / 4:  # Allow some errors
                        disparity_map[y, x] = x - best_match_x

                # Update progress for each scanline
                if self._progress_callback and y % 10 == 0:
                    progress = 50 + (y / height) * 40  # 50-90% is matching
                    self._progress_callback(progress, f"Matching pixels: {y}/{height}")

            # Save disparity map for visualization
            disparity_colored = cv2.applyColorMap(
                cv2.convertScaleAbs(disparity_map,
                                    alpha=255 / np.max(disparity_map) if np.max(disparity_map) > 0 else 0),
                cv2.COLORMAP_JET
            )
            cv2.imwrite(str(self.scan_dir / "disparity_map.png"), disparity_colored)

            # Clean up disparity map with filtering
            disparity_map = cv2.medianBlur(disparity_map, 5)

            # Update progress
            if self._progress_callback:
                self._progress_callback(90, "Creating point cloud...")

            # Reproject to 3D
            self._reproject_to_3d(disparity_map, shadow_mask_l)

            return True

        except Exception as e:
            logger.error(f"Error in custom Gray code processing: {e}")
            return False

    def _process_binary_code(self) -> bool:
        """
        Process binary code pattern scan.
        Similar to Gray code but with standard binary encoding.
        """
        # Binary code is similar to Gray code, but with standard binary encoding
        # For now, we'll use the same implementation
        return self._process_gray_code()

    def _update_disparity_from_pattern(self, pattern_l, pattern_r, shadow_mask_l, shadow_mask_r,
                                       disparity_map, confidence_map, pattern_weight=1.0):
        """
        Update disparity map based on a single pattern pair.
        Used for progressive pattern processing.
        """
        height, width = pattern_l.shape[:2]

        # For each scanline
        for y in range(height):
            # Skip if processing is cancelled
            if self._processing_cancelled.is_set():
                return

            # For each pixel in left image
            for x in range(width):
                # Skip pixels in shadow
                if shadow_mask_l[y, x] == 0:
                    continue

                # Get pixel value in left image
                val_l = pattern_l[y, x]

                # Search for best match in right image (along same scanline)
                best_match_x = -1
                best_match_diff = 255  # Maximum possible difference

                # Search range (limit to reasonable disparity range)
                min_x = max(0, x - 200)  # Only look for matches to the left
                max_x = x

                for x_r in range(min_x, max_x):
                    # Skip pixels in shadow in right image
                    if shadow_mask_r[y, x_r] == 0:
                        continue

                    # Get pixel value in right image
                    val_r = pattern_r[y, x_r]

                    # Calculate absolute difference
                    diff = abs(val_l - val_r)

                    # Update best match if this is better
                    if diff < best_match_diff:
                        best_match_diff = diff
                        best_match_x = x_r

                # If we found a good match, update disparity
                if best_match_x >= 0 and best_match_diff < 50:  # Threshold for good match
                    disparity = x - best_match_x

                    # Update disparity and confidence maps with weighted contribution
                    disparity_map[y, x] += disparity * pattern_weight
                    confidence_map[y, x] += pattern_weight

    def _reproject_to_3d(self, disparity_map, mask):
        """
        Reproject disparity map to 3D points.
        """
        try:
            # Ensure we have valid disparity and calibration
            if disparity_map is None or self.Q is None:
                logger.error("Missing disparity map or calibration for reprojection")
                return False

            # Create point cloud from disparity map
            logger.info("Reprojecting to 3D points")

            # Apply mask to disparity map
            masked_disparity = disparity_map.copy()
            masked_disparity[mask == 0] = 0

            # Reproject to 3D
            points_3d = cv2.reprojectImageTo3D(masked_disparity, self.Q)

            # Filter invalid points
            mask = (
                    ~np.isnan(points_3d).any(axis=2) &
                    ~np.isinf(points_3d).any(axis=2) &
                    (mask > 0)
            )

            # Extract valid points
            valid_points = points_3d[mask]

            # Optional: Limit points to reasonable range (e.g., 1m cube around origin)
            max_range = 500  # mm
            in_range_mask = (
                    (np.abs(valid_points[:, 0]) < max_range) &
                    (np.abs(valid_points[:, 1]) < max_range) &
                    (np.abs(valid_points[:, 2]) < max_range)
            )

            valid_points = valid_points[in_range_mask]

            # Store points in result
            self.pointcloud = valid_points

            logger.info(f"Generated point cloud with {len(valid_points)} points")

            # Save point cloud to PLY file
            self.save_point_cloud(str(self.scan_dir / "pointcloud.ply"))

            # Update progress
            if self._progress_callback:
                self._progress_callback(100, f"Point cloud created with {len(valid_points)} points")

            return True

        except Exception as e:
            logger.error(f"Error in 3D reprojection: {e}")
            return False

    def save_point_cloud(self, filename: str) -> bool:
        """
        Save point cloud to a file.

        Args:
            filename: Output filename (should end with .ply)

        Returns:
            True if save was successful, False otherwise
        """
        if self.pointcloud is None or len(self.pointcloud) == 0:
            logger.error("No point cloud data to save")
            return False

        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(filename), exist_ok=True)

            # Check if Open3D is available for better PLY export
            if OPEN3D_AVAILABLE:
                # Convert to Open3D point cloud
                pcd = o3d.geometry.PointCloud()
                pcd.points = o3d.utility.Vector3dVector(self.pointcloud)

                # Optional: Apply statistical outlier removal
                try:
                    pcd, _ = pcd.remove_statistical_outlier(nb_neighbors=20, std_ratio=2.0)
                except Exception as e:
                    logger.warning(f"Error applying outlier removal: {e}")

                # Save to file
                o3d.io.write_point_cloud(filename, pcd)
                logger.info(f"Point cloud saved to {filename} using Open3D")
            else:
                # Manual PLY export
                with open(filename, 'w') as f:
                    # Write header
                    f.write("ply\n")
                    f.write("format ascii 1.0\n")
                    f.write(f"element vertex {len(self.pointcloud)}\n")
                    f.write("property float x\n")
                    f.write("property float y\n")
                    f.write("property float z\n")
                    f.write("end_header\n")

                    # Write vertices
                    for point in self.pointcloud:
                        f.write(f"{point[0]} {point[1]} {point[2]}\n")

                logger.info(f"Point cloud saved to {filename} using manual export")

            return True

        except Exception as e:
            logger.error(f"Error saving point cloud: {e}")
            return False

    def cancel_processing(self):
        """Cancel ongoing processing."""
        self._processing_cancelled.set()

        if self.processing_thread and self.processing_thread.is_alive():
            # Wait for thread to terminate (with timeout)
            self.processing_thread.join(timeout=2.0)
            logger.info("Processing cancelled")

    def wait_for_completion(self, timeout: Optional[float] = None) -> bool:
        """
        Wait for processing to complete.

        Args:
            timeout: Maximum time to wait in seconds (None for no timeout)

        Returns:
            True if processing completed, False if timed out or cancelled
        """
        return self._processing_complete.wait(timeout)

    def visualize_point_cloud(self):
        """
        Visualize the point cloud using Open3D.
        Only works if Open3D is available.
        """
        if not OPEN3D_AVAILABLE:
            logger.error("Open3D not available for visualization")
            return False

        if self.pointcloud is None or len(self.pointcloud) == 0:
            logger.error("No point cloud data to visualize")
            return False

        try:
            # Convert to Open3D point cloud
            pcd = o3d.geometry.PointCloud()
            pcd.points = o3d.utility.Vector3dVector(self.pointcloud)

            # Add a coordinate frame for reference
            coord_frame = o3d.geometry.TriangleMesh.create_coordinate_frame(size=20)

            # Visualize
            o3d.visualization.draw_geometries([pcd, coord_frame])
            return True

        except Exception as e:
            logger.error(f"Error visualizing point cloud: {e}")
            return False


# Interactive testing when run as a script
if __name__ == "__main__":
    # Set up logging
    logging.basicConfig(level=logging.INFO)

    # Check if a scan directory was provided
    if len(sys.argv) > 1:
        scan_dir = sys.argv[1]

        # Create processor
        processor = ScanProcessor()


        # Define progress callback
        def progress_callback(progress, message):
            print(f"Progress: {progress:.1f}% - {message}")


        # Define completion callback
        def completion_callback(success, message, result):
            if success:
                print(f"Processing completed: {message}")
                print(f"Result: {len(result)} points")

                # Visualize if Open3D is available
                if OPEN3D_AVAILABLE:
                    processor.visualize_point_cloud()
            else:
                print(f"Processing failed: {message}")


        # Set callbacks
        processor.set_callbacks(progress_callback, completion_callback)

        # Load and process scan
        if processor.load_local_scan(scan_dir):
            processor.process_scan(use_threading=False)
        else:
            print(f"Failed to load scan from {scan_dir}")
    else:
        print("Usage: python triangulation.py <scan_directory>")
        print("Example: python triangulation.py ~/UnLook/scans/20250425_123456")