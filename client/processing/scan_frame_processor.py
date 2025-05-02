#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Modulo per l'elaborazione in tempo reale dei frame di scansione.
Versione completamente riprogettata per operare esclusivamente in-memory,
eliminando la dipendenza dal filesystem e ottimizzando le prestazioni.
Implementa un sistema di triangolazione real-time con elaborazione incrementale.
"""

import os
import time
import logging
import threading
import cv2
import numpy as np
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, Tuple, List, Set, Any, Callable
from collections import deque
import queue

# Configurazione logging
logger = logging.getLogger(__name__)


class CircularFrameBuffer:
    """
    Buffer circolare thread-safe per memorizzare i frame più recenti.
    Ottimizzato per accesso rapido e basso utilizzo di memoria.
    """

    def __init__(self, max_size=50):
        """
        Inizializza il buffer circolare.

        Args:
            max_size: Dimensione massima del buffer (numero di frame)
        """
        self._buffer = {}  # Dizionario indicizzato per pattern_index
        self._lock = threading.RLock()  # Lock rientrante per thread-safety
        self._max_size = max_size
        self._pattern_queue = deque(maxlen=max_size)  # Coda per mantenere l'ordine

    def add_frame(self, camera_index: int, pattern_index: int, frame: np.ndarray, metadata: Dict) -> bool:
        """
        Aggiunge un frame al buffer.

        Args:
            camera_index: Indice della camera (0=left, 1=right)
            pattern_index: Indice del pattern
            frame: Array NumPy contenente il frame
            metadata: Metadati associati al frame

        Returns:
            True se il frame è stato aggiunto con successo, False altrimenti
        """
        with self._lock:
            # Inizializza la struttura se necessario
            if pattern_index not in self._buffer:
                self._buffer[pattern_index] = {
                    'frames': {},
                    'metadata': metadata,
                    'timestamp': time.time()
                }
                self._pattern_queue.append(pattern_index)

            # Aggiungi il frame
            self._buffer[pattern_index]['frames'][camera_index] = frame.copy()

            # Se abbiamo superato la dimensione massima, rimuovi il frame più vecchio
            if len(self._buffer) > self._max_size:
                oldest_pattern = self._pattern_queue.popleft()
                if oldest_pattern in self._buffer:
                    del self._buffer[oldest_pattern]

            return True

    def get_frame(self, pattern_index: int, camera_index: int) -> Optional[np.ndarray]:
        """
        Ottiene un frame specifico dal buffer.

        Args:
            pattern_index: Indice del pattern
            camera_index: Indice della camera

        Returns:
            Frame come array NumPy o None se non disponibile
        """
        with self._lock:
            if pattern_index in self._buffer and camera_index in self._buffer[pattern_index]['frames']:
                return self._buffer[pattern_index]['frames'][camera_index].copy()
            return None

    def get_frame_pair(self, pattern_index: int) -> Optional[Tuple[np.ndarray, np.ndarray]]:
        """
        Ottiene una coppia di frame (left, right) per un pattern specifico.

        Args:
            pattern_index: Indice del pattern

        Returns:
            Tupla (left_frame, right_frame) o None se non disponibile
        """
        with self._lock:
            if pattern_index in self._buffer:
                frames = self._buffer[pattern_index]['frames']
                if 0 in frames and 1 in frames:
                    return frames[0].copy(), frames[1].copy()
            return None

    def get_patterns_with_complete_pairs(self) -> List[int]:
        """
        Restituisce gli indici dei pattern che hanno frame completi per entrambe le camere.

        Returns:
            Lista di indici di pattern con coppie complete
        """
        with self._lock:
            result = []
            for pattern_index, data in self._buffer.items():
                frames = data['frames']
                if 0 in frames and 1 in frames:
                    result.append(pattern_index)
            return sorted(result)

    def has_complete_pair(self, pattern_index: int) -> bool:
        """
        Verifica se un pattern ha una coppia completa di frame.

        Args:
            pattern_index: Indice del pattern

        Returns:
            True se il pattern ha frame per entrambe le camere, False altrimenti
        """
        with self._lock:
            if pattern_index in self._buffer:
                frames = self._buffer[pattern_index]['frames']
                return 0 in frames and 1 in frames
            return False

    def get_metadata(self, pattern_index: int) -> Optional[Dict]:
        """
        Ottiene i metadati associati a un pattern.

        Args:
            pattern_index: Indice del pattern

        Returns:
            Dizionario di metadati o None se non disponibile
        """
        with self._lock:
            if pattern_index in self._buffer:
                return self._buffer[pattern_index]['metadata'].copy()
            return None

    def clear(self):
        """Pulisce il buffer."""
        with self._lock:
            self._buffer.clear()
            self._pattern_queue.clear()

    def __len__(self):
        """Restituisce il numero di pattern nel buffer."""
        with self._lock:
            return len(self._buffer)

    def __contains__(self, pattern_index):
        """Verifica se un pattern è presente nel buffer."""
        with self._lock:
            return pattern_index in self._buffer

    def get_statistics(self) -> Dict:
        """
        Restituisce statistiche sul buffer.

        Returns:
            Dizionario con statistiche sul buffer
        """
        with self._lock:
            return {
                'total_patterns': len(self._buffer),
                'complete_pairs': len(self.get_patterns_with_complete_pairs()),
                'memory_usage_mb': sum(
                    sum(frame.nbytes for frame in data['frames'].values())
                    for data in self._buffer.values()
                ) / (1024 * 1024)
            }


class RealTimeTriangulator:
    """
    Componente per la triangolazione in tempo reale dei frame.
    Implementa algoritmi ottimizzati per l'elaborazione incrementale.
    """

    def __init__(self, output_dir=None):
        """
        Inizializza il triangolatore in tempo reale.

        Args:
            output_dir: Directory di output per salvare risultati (opzionale)
        """
        self.output_dir = output_dir or Path.home() / "UnLook" / "scans"
        self._lock = threading.RLock()
        self._calibration_data = None
        self._white_black_initialized = False
        self._white_frames = {0: None, 1: None}
        self._black_frames = {0: None, 1: None}
        self._shadow_masks = {0: None, 1: None}
        self._last_pointcloud = None
        self._pointcloud_lock = threading.RLock()

        # Eventi e flag per la sincronizzazione
        self._processing_event = threading.Event()
        self._stop_event = threading.Event()
        self._processing_thread = None
        self._is_processing = False

        # Callback per notifiche
        self._progress_callback = None
        self._completion_callback = None

    def set_callbacks(self, progress_callback=None, completion_callback=None):
        """
        Imposta le callback per le notifiche.

        Args:
            progress_callback: Funzione chiamata durante l'elaborazione (progress, message)
            completion_callback: Funzione chiamata al completamento (success, message, result)
        """
        self._progress_callback = progress_callback
        self._completion_callback = completion_callback

    def initialize(self, white_left, white_right, black_left, black_right):
        """
        Inizializza il triangolatore con i frame di riferimento.

        Args:
            white_left: Frame bianco camera sinistra
            white_right: Frame bianco camera destra
            black_left: Frame nero camera sinistra
            black_right: Frame nero camera destra

        Returns:
            True se l'inizializzazione è riuscita, False altrimenti
        """
        try:
            with self._lock:
                # Memorizza i frame di riferimento
                self._white_frames[0] = white_left.copy()
                self._white_frames[1] = white_right.copy()
                self._black_frames[0] = black_left.copy()
                self._black_frames[1] = black_right.copy()

                # Calcola le maschere di ombra
                self._compute_shadow_masks()

                # Carica i dati di calibrazione
                self._load_calibration_data()

                self._white_black_initialized = True
                logger.info("Triangolatore inizializzato con successo")
                return True
        except Exception as e:
            logger.error(f"Errore nell'inizializzazione del triangolatore: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False

    def _compute_shadow_masks(self):
        """Calcola le maschere di ombra dai frame di riferimento."""
        for camera_index in (0, 1):
            white = self._white_frames[camera_index]
            black = self._black_frames[camera_index]

            if white is None or black is None:
                continue

            # Calcola la maschera di ombra (1 dove il pixel è illuminato, 0 dove è in ombra)
            shadow_mask = np.zeros_like(black, dtype=np.uint8)
            threshold = 40  # Threshold per rilevare aree illuminate vs. in ombra
            shadow_mask[white > black + threshold] = 1

            self._shadow_masks[camera_index] = shadow_mask

    def _load_calibration_data(self):
        """Carica o crea i dati di calibrazione necessari per la triangolazione."""
        try:
            # Prima cerca un file di calibrazione locale
            calib_file = Path(self.output_dir) / "calibration.npz"

            if calib_file.exists():
                # Carica dati di calibrazione da file
                self._calibration_data = np.load(calib_file)
                logger.info(f"Dati di calibrazione caricati da {calib_file}")

                # Genera mappe di rettifica
                self._generate_rectification_maps()
            else:
                # Se non c'è un file di calibrazione, prova a scaricare dal server
                # oppure crea una calibrazione di default
                logger.warning("File di calibrazione non trovato, tentativo di ottenere dati dal server...")
                try:
                    self._download_calibration_from_server()
                except:
                    logger.warning("Impossibile ottenere la calibrazione dal server, utilizzo valori predefiniti")
                    self._create_default_calibration()
        except Exception as e:
            logger.error(f"Errore nel caricamento dei dati di calibrazione: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")

            # In caso di errore, crea una calibrazione di default
            self._create_default_calibration()

    def _download_calibration_from_server(self):
        """Tenta di scaricare i dati di calibrazione dal server."""
        try:
            # Cerca di ottenere un riferimento al scanner controller
            from client.controllers.scanner_controller import ScannerController
            scanner_controller = ScannerController()

            if scanner_controller and scanner_controller.selected_scanner:
                device_id = scanner_controller.selected_scanner.device_id
                connection_manager = scanner_controller._connection_manager

                # Invia comando per ottenere la calibrazione
                connection_manager.send_message(
                    device_id,
                    "GET_CALIBRATION"
                )

                # Attendi la risposta
                response = connection_manager.wait_for_response(
                    device_id,
                    "GET_CALIBRATION",
                    timeout=10.0
                )

                if response and response.get("status") == "ok":
                    calib_data = response.get("data")
                    if calib_data:
                        # Salva i dati di calibrazione
                        calib_file = Path(self.output_dir) / "calibration.npz"

                        # Il server potrebbe inviare i dati in formato base64
                        if isinstance(calib_data, str):
                            import base64
                            calib_data = base64.b64decode(calib_data)

                        with open(calib_file, "wb") as f:
                            f.write(calib_data)

                        # Carica il file appena salvato
                        self._calibration_data = np.load(calib_file)

                        # Genera mappe di rettifica
                        self._generate_rectification_maps()

                        logger.info("Calibrazione scaricata dal server con successo")
                        return True

                logger.warning("Impossibile ottenere la calibrazione dal server")
            else:
                logger.warning("Scanner non selezionato, impossibile scaricare la calibrazione")
        except Exception as e:
            logger.error(f"Errore nel download della calibrazione: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")

        return False

    def _create_default_calibration(self):
        """Crea una calibrazione predefinita per testing."""
        logger.warning("Creazione di una calibrazione predefinita (INACCURATA - solo per testing)")

        # Crea una calibrazione semplice predefinita (assume immagini 640x480)
        img_size = (640, 480)
        focal_length = 800  # Un valore di lunghezza focale ragionevole

        # Matrici delle camere
        K1 = np.array([
            [focal_length, 0, img_size[0] / 2],
            [0, focal_length, img_size[1] / 2],
            [0, 0, 1]
        ])
        K2 = K1.copy()

        # Coefficienti di distorsione (nessuna distorsione per default)
        d1 = np.zeros(5)
        d2 = np.zeros(5)

        # Matrice di rotazione (identità per camere allineate)
        R = np.eye(3)

        # Traslazione (assumiamo baseline di 10cm = 100mm lungo l'asse X)
        t = np.array([100, 0, 0])

        # Salva su file npz
        calib_file = Path(self.output_dir) / "calibration.npz"
        np.savez(calib_file,
                 M1=K1, M2=K2,
                 d1=d1, d2=d2,
                 R=R, t=t)

        # Carica il file appena creato
        self._calibration_data = np.load(calib_file)

        # Genera mappe di rettifica
        self._generate_rectification_maps()

    def _generate_rectification_maps(self):
        """Genera le mappe di rettifica dai dati di calibrazione."""
        if self._calibration_data is None:
            logger.error("Nessun dato di calibrazione disponibile")
            return False

        try:
            # Estrai parametri di calibrazione
            M1 = self._calibration_data['M1']
            M2 = self._calibration_data['M2']
            d1 = self._calibration_data['d1']
            d2 = self._calibration_data['d2']
            R = self._calibration_data['R']
            t = self._calibration_data['t']

            # Determina dimensione immagine dai frame di riferimento
            if self._white_frames[0] is not None:
                img = self._white_frames[0]
                img_size = (img.shape[1], img.shape[0])
            else:
                # Dimensione predefinita se non ci sono frame disponibili
                img_size = (640, 480)

            # Calcola parametri di rettifica
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

            # Genera mappe di rettifica
            self.map_x_l, self.map_y_l = cv2.initUndistortRectifyMap(
                M1, d1, R1, P1, img_size, cv2.CV_32FC1)

            self.map_x_r, self.map_y_r = cv2.initUndistortRectifyMap(
                M2, d2, R2, P2, img_size, cv2.CV_32FC1)

            # Memorizza matrice Q per riproiezione
            self.Q = Q

            logger.info("Mappe di rettifica generate con successo")
            return True

        except Exception as e:
            logger.error(f"Errore nella generazione delle mappe di rettifica: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False

    def start_processing(self):
        """Avvia il thread di elaborazione in tempo reale."""
        if self._is_processing:
            logger.warning("Elaborazione già in corso")
            return False

        # Reset degli eventi
        self._stop_event.clear()
        self._processing_event.clear()
        self._is_processing = True

        # Avvia il thread di elaborazione
        self._processing_thread = threading.Thread(target=self._processing_loop)
        self._processing_thread.daemon = True
        self._processing_thread.start()

        logger.info("Thread di elaborazione in tempo reale avviato")
        return True

    def stop_processing(self):
        """Ferma il thread di elaborazione in tempo reale."""
        if not self._is_processing:
            return

        # Segnala l'arresto
        self._stop_event.set()
        self._processing_event.set()  # Sblocca il thread se è in attesa
        self._is_processing = False

        # Attendi che il thread termini (con timeout)
        if self._processing_thread and self._processing_thread.is_alive():
            self._processing_thread.join(timeout=2.0)
            logger.info("Thread di elaborazione fermato")

    def _processing_loop(self):
        """Loop principale del thread di elaborazione in tempo reale."""
        logger.info("Loop di elaborazione in tempo reale avviato")

        try:
            while not self._stop_event.is_set():
                # Attendi il segnale di nuovi dati o timeout
                if not self._processing_event.wait(timeout=0.5):
                    continue

                # Reset dell'evento
                self._processing_event.clear()

                # Verifica che l'inizializzazione sia completa
                if not self._white_black_initialized:
                    logger.warning("Triangolatore non inizializzato, in attesa dei frame di riferimento")
                    continue

                try:
                    # Esegui la triangolazione incrementale
                    self._process_frame_batch()
                except Exception as e:
                    logger.error(f"Errore nell'elaborazione dei frame: {e}")
                    import traceback
                    logger.error(f"Traceback: {traceback.format_exc()}")

            logger.info("Loop di elaborazione in tempo reale terminato")

        except Exception as e:
            logger.error(f"Errore fatale nel thread di elaborazione: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            self._is_processing = False

    def _process_frame_batch(self):
        """
        Elabora un batch di frame per la triangolazione.
        Questa funzione viene chiamata dal thread di elaborazione.
        """
        # Questa funzione deve essere implementata dalla classe che eredita
        # In questo caso, sarà ScanFrameProcessor a fornire l'implementazione
        pass

    def triangulate_frames(self, frame_pairs):
        """
        Triangola una lista di coppie di frame.

        Args:
            frame_pairs: Lista di tuple (pattern_index, left_frame, right_frame)

        Returns:
            Nuvola di punti come array NumPy (Nx3) o None in caso di errore
        """
        try:
            if not self._white_black_initialized:
                logger.error("Triangolatore non inizializzato, impossibile triangolare")
                return None

            if not frame_pairs:
                logger.warning("Nessuna coppia di frame da triangolare")
                return None

            # Verifica che le mappe di rettifica siano disponibili
            if not hasattr(self, 'map_x_l') or not hasattr(self, 'map_y_l'):
                logger.error("Mappe di rettifica non disponibili")
                return None

            # Ordina i frame per indice di pattern
            frame_pairs.sort(key=lambda x: x[0])

            # Estrai le dimensioni dai frame
            height, width = frame_pairs[0][1].shape[:2]

            # Inizializza le mappe di disparità e confidenza
            disparity_map = np.zeros((height, width), dtype=np.float32)
            confidence_map = np.zeros((height, width), dtype=np.float32)

            # Applica la rettifica e l'elaborazione per ogni coppia di frame
            for i, (pattern_idx, left_frame, right_frame) in enumerate(frame_pairs):
                # Rettifica i frame
                left_rect = cv2.remap(left_frame, self.map_x_l, self.map_y_l, cv2.INTER_LINEAR)
                right_rect = cv2.remap(right_frame, self.map_x_r, self.map_y_r, cv2.INTER_LINEAR)

                # Calcola il peso del pattern
                pattern_weight = 2 ** (i // 2)  # Peso basato sulla posizione

                # Aggiorna la mappa di disparità con questo pattern
                self._update_disparity_from_pattern(
                    left_rect, right_rect,
                    self._shadow_masks[0], self._shadow_masks[1],
                    disparity_map, confidence_map,
                    pattern_weight
                )

                # Aggiorna il progresso
                if self._progress_callback:
                    progress = (i + 1) / len(frame_pairs) * 100
                    self._progress_callback(progress,
                                            f"Triangolazione pattern {pattern_idx}: {i + 1}/{len(frame_pairs)}")

            # Calcola la mappa di disparità finale
            valid_indices = confidence_map > 0
            disparity_map_final = np.zeros_like(disparity_map)
            disparity_map_final[valid_indices] = disparity_map[valid_indices] / confidence_map[valid_indices]

            # Applica filtro mediano per ridurre il rumore
            kernel_size = 3
            disparity_map_final = cv2.medianBlur(disparity_map_final.astype(np.float32), kernel_size)

            # Riproietta in 3D
            pointcloud = self._reproject_to_3d(disparity_map_final, self._shadow_masks[0])

            # Memorizza la nuvola di punti
            with self._pointcloud_lock:
                self._last_pointcloud = pointcloud

            # Chiama la callback di completamento
            if self._completion_callback and pointcloud is not None:
                self._completion_callback(True, f"Triangolazione completata: {len(pointcloud)} punti", pointcloud)

            return pointcloud

        except Exception as e:
            logger.error(f"Errore nella triangolazione: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return None

    def _update_disparity_from_pattern(self, pattern_l, pattern_r, shadow_mask_l, shadow_mask_r,
                                       disparity_map, confidence_map, pattern_weight=1.0):
        """
        Aggiorna la mappa di disparità basandosi su una coppia di pattern.
        Versione ottimizzata per l'elaborazione in-memory con NumPy.

        Args:
            pattern_l: Pattern della camera sinistra (array NumPy)
            pattern_r: Pattern della camera destra (array NumPy)
            shadow_mask_l: Maschera di ombra per la camera sinistra
            shadow_mask_r: Maschera di ombra per la camera destra
            disparity_map: Mappa di disparità da aggiornare
            confidence_map: Mappa di confidenza da aggiornare
            pattern_weight: Peso del pattern corrente
        """
        height, width = pattern_l.shape[:2]

        # Ottimizzazione: pre-calcola le aree valide per ridurre il numero di cicli
        valid_mask_l = shadow_mask_l > 0
        valid_rows, valid_cols = np.where(valid_mask_l)

        # Per ogni pixel valido nella maschera di ombra sinistra
        for idx in range(len(valid_rows)):
            y, x = valid_rows[idx], valid_cols[idx]

            # Valore del pixel nel pattern sinistro
            val_l = pattern_l[y, x]

            # Range di ricerca (cerca solo a sinistra, con range limitato)
            min_x = max(0, x - 200)  # Limita ricerca a 200 pixel a sinistra

            best_match_x = -1
            best_match_diff = 255  # Differenza massima possibile

            # Ottimizzazione: utilizza vettorizzazione NumPy per la ricerca
            # Estrai il segmento di riga da confrontare
            row_segment = pattern_r[y, min_x:x]
            row_mask = shadow_mask_r[y, min_x:x] > 0

            if np.any(row_mask):  # Verifica se ci sono pixel validi nella maschera
                # Calcola la differenza assoluta vettorizzata
                diffs = np.abs(row_segment - val_l).astype(np.float32)

                # Applica la maschera (invalida i pixel in ombra assegnando un valore alto)
                diffs[~row_mask] = 255

                # Trova il minimo
                min_diff_idx = np.argmin(diffs)
                best_match_diff = diffs[min_diff_idx]

                # Calcola l'indice nel sistema di coordinate originale
                if best_match_diff < 50:  # Soglia per una buona corrispondenza
                    best_match_x = min_x + min_diff_idx

            # Se abbiamo trovato una buona corrispondenza, aggiorna la mappa di disparità
            if best_match_x >= 0:
                disparity = x - best_match_x

                # Aggiorna disparity e confidence maps con la contribuzione pesata
                disparity_map[y, x] += disparity * pattern_weight
                confidence_map[y, x] += pattern_weight

    def _reproject_to_3d(self, disparity_map, mask):
        """
        Riproietta una mappa di disparità in una nuvola di punti 3D.

        Args:
            disparity_map: Mappa di disparità come array NumPy
            mask: Maschera di validità (1 per pixel validi, 0 per pixel invalidi)

        Returns:
            Array NumPy di punti 3D o None in caso di errore
        """
        try:
            # Verifica che la matrice Q sia disponibile
            if not hasattr(self, 'Q'):
                logger.error("Matrice Q non disponibile per la riproiezione")
                return None

            # Applica la maschera alla mappa di disparità
            masked_disparity = disparity_map.copy()
            masked_disparity[mask == 0] = 0

            # Riproietta in 3D
            points_3d = cv2.reprojectImageTo3D(masked_disparity, self.Q)

            # Filtra punti non validi
            valid_mask = (
                    ~np.isnan(points_3d).any(axis=2) &
                    ~np.isinf(points_3d).any(axis=2) &
                    (mask > 0)
            )

            # Estrai punti validi
            valid_points = points_3d[valid_mask]

            # Limita i punti a un range ragionevole
            max_range = 500  # mm
            range_mask = (
                    (np.abs(valid_points[:, 0]) < max_range) &
                    (np.abs(valid_points[:, 1]) < max_range) &
                    (np.abs(valid_points[:, 2]) < max_range)
            )

            filtered_points = valid_points[range_mask]

            # Se abbiamo troppi punti, campiona per migliorare le prestazioni
            if len(filtered_points) > 50000:
                # Campionamento casuale
                indices = np.random.choice(len(filtered_points), 50000, replace=False)
                filtered_points = filtered_points[indices]
            elif len(filtered_points) < 10:
                # Troppo pochi punti, probabilmente un errore
                logger.warning("Troppo pochi punti validi nella riproiezione")
                return None

            logger.info(f"Riproiezione completata: {len(filtered_points)} punti generati")
            return filtered_points

        except Exception as e:
            logger.error(f"Errore nella riproiezione 3D: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return None

    def get_last_pointcloud(self):
        """
        Restituisce l'ultima nuvola di punti generata.

        Returns:
            Array NumPy di punti 3D o None se non disponibile
        """
        with self._pointcloud_lock:
            if self._last_pointcloud is not None:
                return self._last_pointcloud.copy()
            return None


class BackgroundSaver:
    """
    Thread di background per il salvataggio opzionale dei frame su disco.
    Implementato come coda a bassa priorità per non interferire con l'elaborazione.
    """

    def __init__(self, output_dir):
        """
        Inizializza il thread di salvataggio in background.

        Args:
            output_dir: Directory di output per i file salvati
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self._queue = queue.Queue()
        self._thread = None
        self._stop_event = threading.Event()
        self._is_saving = False

    def start(self):
        """Avvia il thread di salvataggio in background."""
        if self._is_saving:
            return

        self._stop_event.clear()
        self._is_saving = True

        self._thread = threading.Thread(target=self._saving_loop)
        self._thread.daemon = True
        self._thread.start()

        logger.info("Thread di salvataggio in background avviato")

    def stop(self):
        """Ferma il thread di salvataggio in background."""
        if not self._is_saving:
            return

        self._stop_event.set()
        self._is_saving = False

        # Attendi che il thread termini (con timeout)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
            logger.info("Thread di salvataggio in background fermato")

    def _saving_loop(self):
        """Loop principale del thread di salvataggio."""
        logger.info("Loop di salvataggio in background avviato")

        try:
            while not self._stop_event.is_set():
                try:
                    # Estrai un elemento dalla coda (timeout per controllare periodicamente lo stop_event)
                    item = self._queue.get(timeout=0.5)

                    # Elabora l'elemento
                    self._save_item(item)

                    # Marca come completato
                    self._queue.task_done()

                except queue.Empty:
                    # Timeout nella get, continua il loop
                    continue
                except Exception as e:
                    logger.error(f"Errore nel loop di salvataggio: {e}")
                    import traceback
                    logger.error(f"Traceback: {traceback.format_exc()}")
                    time.sleep(1.0)  # Pausa per evitare loop di errori

            logger.info("Loop di salvataggio in background terminato")

        except Exception as e:
            logger.error(f"Errore fatale nel thread di salvataggio: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            self._is_saving = False

    def queue_frame(self, camera_index, pattern_index, pattern_name, scan_id, frame):
        """
        Accoda un frame per il salvataggio in background.

        Args:
            camera_index: Indice della camera (0=left, 1=right)
            pattern_index: Indice del pattern
            pattern_name: Nome del pattern
            scan_id: ID della scansione
            frame: Frame da salvare
        """
        if not self._is_saving:
            self.start()

        self._queue.put({
            'type': 'frame',
            'camera_index': camera_index,
            'pattern_index': pattern_index,
            'pattern_name': pattern_name,
            'scan_id': scan_id,
            'frame': frame.copy()
        })

    def queue_pointcloud(self, scan_id, pointcloud):
        """
        Accoda una nuvola di punti per il salvataggio in background.

        Args:
            scan_id: ID della scansione
            pointcloud: Nuvola di punti da salvare
        """
        if not self._is_saving:
            self.start()

        self._queue.put({
            'type': 'pointcloud',
            'scan_id': scan_id,
            'pointcloud': pointcloud.copy() if pointcloud is not None else None
        })

    def _save_item(self, item):
        """
        Salva un elemento dalla coda.

        Args:
            item: Elemento da salvare (frame o pointcloud)
        """
        try:
            if item['type'] == 'frame':
                self._save_frame(item)
            elif item['type'] == 'pointcloud':
                self._save_pointcloud(item)
        except Exception as e:
            logger.error(f"Errore nel salvataggio dell'elemento: {e}")

    def _save_frame(self, item):
        """
        Salva un frame su disco.

        Args:
            item: Dizionario con informazioni sul frame
        """
        try:
            camera_index = item['camera_index']
            pattern_index = item['pattern_index']
            pattern_name = item['pattern_name']
            scan_id = item['scan_id']
            frame = item['frame']

            # Crea directory se necessario
            scan_dir = self.output_dir / scan_id
            scan_dir.mkdir(parents=True, exist_ok=True)

            camera_dir = scan_dir / ("left" if camera_index == 0 else "right")
            camera_dir.mkdir(parents=True, exist_ok=True)

            # Componi nome file
            filename = f"{pattern_index:04d}_{pattern_name}.png"
            output_path = camera_dir / filename

            # Salva il frame
            success = cv2.imwrite(str(output_path), frame)

            if not success:
                logger.warning(f"cv2.imwrite fallito per {output_path}")
                # Fallback a PIL
                try:
                    from PIL import Image
                    img = Image.fromarray(frame)
                    img.save(str(output_path))
                    logger.debug(f"Frame salvato con PIL: {output_path}")
                except Exception as e2:
                    logger.error(f"Anche PIL ha fallito: {e2}")
                    # Ultimo tentativo: salva come NPY
                    np.save(str(output_path).replace('.png', '.npy'), frame)
                    logger.debug(f"Frame salvato come NPY: {output_path}.npy")
            else:
                logger.debug(f"Frame salvato su disco: {output_path}")

        except Exception as e:
            logger.error(f"Errore nel salvataggio del frame: {e}")

    def _save_pointcloud(self, item):
        """
        Salva una nuvola di punti su disco.

        Args:
            item: Dizionario con informazioni sulla nuvola di punti
        """
        try:
            scan_id = item['scan_id']
            pointcloud = item['pointcloud']

            if pointcloud is None or len(pointcloud) == 0:
                logger.warning("Nessun dato valido nella nuvola di punti")
                return

            # Crea directory se necessario
            scan_dir = self.output_dir / scan_id
            scan_dir.mkdir(parents=True, exist_ok=True)

            # Componi nome file
            output_path = scan_dir / "pointcloud.ply"

            # Salva la nuvola di punti
            try:
                # Usa Open3D se disponibile
                import open3d as o3d
                pcd = o3d.geometry.PointCloud()
                pcd.points = o3d.utility.Vector3dVector(pointcloud)

                # Opzionale: applica un filtro per rimuovere outlier
                try:
                    pcd, _ = pcd.remove_statistical_outlier(nb_neighbors=20, std_ratio=2.0)
                except Exception as e:
                    logger.warning(f"Errore nell'applicazione del filtro outlier: {e}")

                # Salva in formato PLY
                o3d.io.write_point_cloud(str(output_path), pcd)
                logger.info(f"Nuvola di punti salvata con Open3D: {output_path}")

            except ImportError:
                # Fallback a salvataggio manuale PLY
                with open(output_path, 'w') as f:
                    # Scrivi header
                    f.write("ply\n")
                    f.write("format ascii 1.0\n")
                    f.write(f"element vertex {len(pointcloud)}\n")
                    f.write("property float x\n")
                    f.write("property float y\n")
                    f.write("property float z\n")
                    f.write("end_header\n")

                    # Scrivi vertici
                    for point in pointcloud:
                        f.write(f"{point[0]} {point[1]} {point[2]}\n")

                logger.info(f"Nuvola di punti salvata manualmente: {output_path}")

        except Exception as e:
            logger.error(f"Errore nel salvataggio della nuvola di punti: {e}")


class ScanFrameProcessor:
    """
    Classe che gestisce i frame di scansione in modo real-time.
    Completamente riprogettata per operare in-memory con elaborazione incrementale.
    """

    def __init__(self, output_dir=None):
        """
        Inizializza il processore di frame di scansione.

        Args:
            output_dir: Directory di output per i file salvati (opzionale)
        """
        self.output_dir = output_dir or Path.home() / "UnLook" / "scans"
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Stato della scansione
        self.current_scan_id = None
        self.is_scanning = False
        self.frame_counters = {0: 0, 1: 0}
        self.pattern_info = {}

        # Buffer circolare per memorizzare i frame
        self._frame_buffer = CircularFrameBuffer(max_size=100)

        # Componente di triangolazione real-time
        self._triangulator = RealTimeTriangulator(output_dir=self.output_dir)

        # Thread di salvataggio in background (opzionale)
        self._saver = BackgroundSaver(output_dir=self.output_dir)

        # Thread di elaborazione incrementale
        self._processing_thread = None
        self._stop_event = threading.Event()
        self._new_frame_event = threading.Event()

        # Callback per notificare gli aggiornamenti
        self._progress_callback = None
        self._frame_callback = None

        # Lock per accesso thread-safe
        self._lock = threading.RLock()

        # Flag per il salvataggio su disco
        self._save_to_disk = True

        # Nuvola di punti real-time
        self._realtime_pointcloud = None
        self._pointcloud_lock = threading.RLock()

        # Numero di coppie minimo per iniziare la triangolazione
        self._min_pattern_pairs = 4

        # Stato di triangolazione
        self._last_processed_pattern = -1
        self._triangulation_active = False

    def set_callbacks(self, progress_callback=None, frame_callback=None):
        """
        Imposta le callback per le notifiche di avanzamento e frame.

        Args:
            progress_callback: Funzione chiamata quando lo stato di avanzamento cambia
            frame_callback: Funzione chiamata quando un nuovo frame è elaborato
        """
        self._progress_callback = progress_callback
        self._frame_callback = frame_callback

        # Configura anche il triangolatore
        self._triangulator.set_callbacks(
            progress_callback=lambda progress, message: self._on_triangulation_progress(progress, message),
            completion_callback=lambda success, message, result: self._on_triangulation_completed(success, message,
                                                                                                  result)
        )

    def _on_triangulation_progress(self, progress, message):
        """Callback per il progresso della triangolazione."""
        if self._progress_callback:
            self._progress_callback({
                "progress": progress,
                "message": message,
                "state": "TRIANGULATING",
                "frames_total": sum(self.frame_counters.values())
            })

    def _on_triangulation_completed(self, success, message, result):
        """Callback per il completamento della triangolazione."""
        if success and result is not None:
            # Memorizza la nuvola di punti
            with self._pointcloud_lock:
                self._realtime_pointcloud = result

            # Notifica la nuova nuvola di punti
            if self._frame_callback:
                self._frame_callback(-1, -1, {
                    "type": "pointcloud_update",
                    "pointcloud": result,
                    "num_points": len(result) if result is not None else 0,
                    "timestamp": time.time()
                })

            # Salva su disco se necessario
            if self._save_to_disk:
                self._saver.queue_pointcloud(self.current_scan_id, result)

    def start_scan(self, scan_id=None, num_patterns=24, pattern_type="PROGRESSIVE"):
        """
        Avvia una nuova sessione di scansione.

        Args:
            scan_id: ID della scansione (se None, ne genera uno basato sul timestamp)
            num_patterns: Numero totale di pattern attesi
            pattern_type: Tipo di pattern (PROGRESSIVE, GRAY_CODE, ecc.)

        Returns:
            ID della scansione
        """
        with self._lock:
            if self.is_scanning:
                logger.warning("Scansione già in corso")
                return self.current_scan_id

            # Genera ID scansione se non specificato
            if scan_id is None:
                scan_id = f"Scan_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

            self.current_scan_id = scan_id
            self.is_scanning = True
            self.frame_counters = {0: 0, 1: 0}
            self.pattern_info = {}

            # Reset del buffer
            self._frame_buffer.clear()

            # Reset della nuvola di punti
            with self._pointcloud_lock:
                self._realtime_pointcloud = None

            # Salva informazioni della scansione
            if self._save_to_disk:
                scan_dir = self.output_dir / scan_id
                scan_dir.mkdir(parents=True, exist_ok=True)

                # Crea sottodirectory per ciascuna camera
                (scan_dir / "left").mkdir(exist_ok=True)
                (scan_dir / "right").mkdir(exist_ok=True)

                # Salva configurazione
                config = {
                    "scan_id": scan_id,
                    "timestamp": datetime.now().isoformat(),
                    "num_patterns": num_patterns,
                    "pattern_type": pattern_type
                }

                try:
                    import json
                    with open(scan_dir / "scan_config.json", "w") as f:
                        json.dump(config, f, indent=2)
                except Exception as e:
                    logger.error(f"Errore nel salvataggio della configurazione: {e}")

            # Avvia il thread di salvataggio in background se necessario
            if self._save_to_disk:
                self._saver.start()

            # Avvia il thread di elaborazione real-time
            self._start_realtime_processing()

            logger.info(f"Iniziata nuova sessione di scansione con ID: {scan_id}")
            return scan_id

    def _start_realtime_processing(self):
        """Avvia il thread di elaborazione real-time."""
        # Reset degli eventi
        self._stop_event.clear()
        self._new_frame_event.clear()

        # Reset dello stato di triangolazione
        self._last_processed_pattern = -1
        self._triangulation_active = True

        # Avvia il thread di elaborazione
        self._processing_thread = threading.Thread(target=self._processing_loop)
        self._processing_thread.daemon = True
        self._processing_thread.start()

        logger.info("Thread di elaborazione real-time avviato")

    def _processing_loop(self):
        """Loop principale del thread di elaborazione real-time."""
        logger.info("Loop di elaborazione real-time avviato")

        try:
            # Frame di riferimento inizializzati
            white_black_initialized = False

            while not self._stop_event.is_set() and self.is_scanning:
                try:
                    # Attendi il segnale di nuovi frame o timeout
                    if not self._new_frame_event.wait(timeout=0.5):
                        continue

                    # Reset dell'evento
                    self._new_frame_event.clear()

                    # Verifica se abbiamo i frame white e black
                    if not white_black_initialized:
                        # Verifica se abbiamo i frame white (index 0) e black (index 1)
                        if self._frame_buffer.has_complete_pair(0) and self._frame_buffer.has_complete_pair(1):
                            # Estrai i frame white e black
                            white_left, white_right = self._frame_buffer.get_frame_pair(0)
                            black_left, black_right = self._frame_buffer.get_frame_pair(1)

                            # Inizializza il triangolatore
                            success = self._triangulator.initialize(white_left, white_right, black_left, black_right)

                            if success:
                                white_black_initialized = True
                                logger.info("Frame di riferimento inizializzati")
                            else:
                                logger.error("Errore nell'inizializzazione dei frame di riferimento")
                                time.sleep(1.0)  # Pausa per evitare loop di errori
                        else:
                            logger.debug("In attesa dei frame white e black...")
                            time.sleep(0.1)
                            continue

                    # Ora possiamo procedere con la triangolazione incrementale
                    if white_black_initialized:
                        # Ottieni tutti i pattern con coppie complete
                        pattern_indices = self._frame_buffer.get_patterns_with_complete_pairs()

                        # Filtra i pattern già elaborati
                        new_patterns = [idx for idx in pattern_indices
                                        if idx > 1 and idx > self._last_processed_pattern]

                        # Verifica se abbiamo abbastanza nuovi pattern per un aggiornamento
                        enough_for_update = (len(pattern_indices) >= self._min_pattern_pairs and
                                             len(new_patterns) >= 2)

                        if enough_for_update:
                            # Prepara le coppie di frame per la triangolazione
                            frame_pairs = []

                            # Aggiungi sempre white e black (indici 0 e 1)
                            white_pair = self._frame_buffer.get_frame_pair(0)
                            black_pair = self._frame_buffer.get_frame_pair(1)

                            if white_pair and black_pair:
                                frame_pairs.append((0, white_pair[0], white_pair[1]))
                                frame_pairs.append((1, black_pair[0], black_pair[1]))

                                # Aggiungi i pattern
                                for idx in pattern_indices:
                                    if idx > 1:  # Ignora white e black
                                        pair = self._frame_buffer.get_frame_pair(idx)
                                        if pair:
                                            frame_pairs.append((idx, pair[0], pair[1]))

                                # Ordina per indice pattern
                                frame_pairs.sort(key=lambda x: x[0])

                                # Triangola i frame
                                self._triangulator.triangulate_frames(frame_pairs)

                                # Aggiorna l'ultimo pattern elaborato
                                self._last_processed_pattern = max(pattern_indices)

                                logger.info(
                                    f"Triangolazione incrementale completata, ultimo pattern: {self._last_processed_pattern}")

                except Exception as e:
                    logger.error(f"Errore nell'elaborazione real-time: {e}")
                    import traceback
                    logger.error(f"Traceback: {traceback.format_exc()}")
                    time.sleep(1.0)  # Pausa per evitare loop di errori

            logger.info("Loop di elaborazione real-time terminato")

        except Exception as e:
            logger.error(f"Errore fatale nel thread di elaborazione: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            self._triangulation_active = False

    def process_frame(self, camera_index, frame, frame_info):
        """
        Elabora un frame di scansione in tempo reale.
        Versione riprogettata per operare completamente in-memory.

        Args:
            camera_index: Indice della camera (0=sinistra, 1=destra)
            frame: Frame come array NumPy
            frame_info: Informazioni sul frame (pattern_index, pattern_name, ecc.)

        Returns:
            True se il frame è stato elaborato correttamente, False altrimenti
        """
        if not self.is_scanning:
            logger.warning("ScanFrameProcessor: chiamata a process_frame ma is_scanning=False")
            return False

        try:
            # Estrai informazioni dal frame
            pattern_index = frame_info.get("pattern_index", -1)
            pattern_name = frame_info.get("pattern_name", "unknown")
            scan_id = frame_info.get("scan_id", self.current_scan_id)

            # Verifica e imposta scan_id
            if not self.current_scan_id and scan_id:
                self.current_scan_id = scan_id
            elif not scan_id and self.current_scan_id:
                scan_id = self.current_scan_id
            elif not scan_id and not self.current_scan_id:
                # Entrambi nulli, crea un nuovo ID
                timestamp = int(time.time())
                scan_id = f"Scan_{timestamp}"
                self.current_scan_id = scan_id
                logger.warning(f"ScanFrameProcessor: creato nuovo scan_id: {scan_id}")

            # Log di base
            logger.info(
                f"ScanFrameProcessor: elaborazione frame {pattern_index} ({pattern_name}) della camera {camera_index}")

            # Verifica integrità del frame
            if frame is None or frame.size == 0:
                logger.error(f"Frame {pattern_index} nullo o vuoto")
                return False

            # Aggiorna contatori e strutture
            self.frame_counters[camera_index] = self.frame_counters.get(camera_index, 0) + 1

            # Memorizza informazioni sul pattern
            if pattern_index not in self.pattern_info:
                self.pattern_info[pattern_index] = {
                    "name": pattern_name,
                    "timestamp": time.time()
                }

            # PRIORITÀ 1: Salva in memoria
            self._frame_buffer.add_frame(camera_index, pattern_index, frame, frame_info)

            # PRIORITÀ 2: Segnala al thread di elaborazione che c'è un nuovo frame
            self._new_frame_event.set()

            # PRIORITÀ 3: Salva su disco (in background)
            if self._save_to_disk:
                self._saver.queue_frame(camera_index, pattern_index, pattern_name, scan_id, frame)

            # Notifica callback
            if self._frame_callback:
                try:
                    self._frame_callback(camera_index, pattern_index, frame)
                except Exception as e:
                    logger.error(f"Errore nella frame_callback: {e}")

            # Aggiorna progress
            if self._progress_callback:
                try:
                    progress = self.get_scan_progress()
                    self._progress_callback(progress)
                except Exception as e:
                    logger.error(f"Errore nella progress_callback: {e}")

            return True

        except Exception as e:
            logger.error(f"ScanFrameProcessor: errore generale nell'elaborazione: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False

    def stop_scan(self):
        """
        Ferma la sessione di scansione corrente.

        Returns:
            Dizionario con statistiche sulla scansione
        """
        if not self.is_scanning:
            return {"success": False, "message": "Nessuna scansione attiva"}

        # Imposta i flag di arresto
        self.is_scanning = False
        self._stop_event.set()
        self._new_frame_event.set()  # Sblocca il thread se è in attesa
        self._triangulation_active = False

        # Attendi che il thread di elaborazione termini (con timeout)
        if self._processing_thread and self._processing_thread.is_alive():
            self._processing_thread.join(timeout=2.0)

        # Ferma il salvataggio in background
        if self._save_to_disk:
            self._saver.stop()

        # Genera statistiche
        stats = {
            "scan_id": self.current_scan_id,
            "frames_total": sum(self.frame_counters.values()),
            "frames_left": self.frame_counters.get(0, 0),
            "frames_right": self.frame_counters.get(1, 0),
            "patterns_received": len(self.pattern_info),
            "timestamp": datetime.now().isoformat(),
            "success": True
        }

        # Se la nuvola di punti è disponibile, aggiungila alle statistiche
        with self._pointcloud_lock:
            if self._realtime_pointcloud is not None:
                stats["pointcloud_points"] = len(self._realtime_pointcloud)

        logger.info(f"Scansione {self.current_scan_id} completata con {stats['frames_total']} frame totali")

        # Salva statistiche
        if self._save_to_disk:
            try:
                import json
                scan_dir = self.output_dir / self.current_scan_id
                with open(scan_dir / "scan_stats.json", "w") as f:
                    json.dump(stats, f, indent=2)
            except Exception as e:
                logger.error(f"Errore nel salvataggio delle statistiche: {e}")

        return stats

    def get_scan_progress(self):
        """
        Restituisce lo stato di avanzamento della scansione.

        Returns:
            Dizionario con informazioni sullo stato di avanzamento
        """
        if not self.is_scanning:
            return {"state": "IDLE", "progress": 0.0}

        # Calcolo progress in base al numero di pattern ricevuti
        # Questo dipende dalla configurazione della scansione
        # Assumiamo che ci siano white + black + 10 pattern verticali + 10 pattern orizzontali = 22
        expected_patterns = 22
        received_patterns = len(self.pattern_info)

        progress = min(100.0, (received_patterns / expected_patterns) * 100.0)

        # Ottieni conteggio per camera
        frames_left = self.frame_counters.get(0, 0)
        frames_right = self.frame_counters.get(1, 0)

        # Verifica se c'è una nuvola di punti in memoria
        has_pointcloud = False
        pointcloud_size = 0
        with self._pointcloud_lock:
            if self._realtime_pointcloud is not None:
                has_pointcloud = True
                pointcloud_size = len(self._realtime_pointcloud)

        return {
            "state": "SCANNING",
            "progress": progress,
            "patterns_received": received_patterns,
            "frames_total": sum(self.frame_counters.values()),
            "frames_left": frames_left,
            "frames_right": frames_right,
            "scan_id": self.current_scan_id,
            "has_pointcloud": has_pointcloud,
            "pointcloud_size": pointcloud_size,
            "buffer_stats": self._frame_buffer.get_statistics()
        }

    def get_realtime_pointcloud(self):
        """
        Restituisce l'ultima nuvola di punti generata in tempo reale.

        Returns:
            Array NumPy con la nuvola di punti o None se non disponibile
        """
        with self._pointcloud_lock:
            if self._realtime_pointcloud is not None:
                return self._realtime_pointcloud.copy()
        return None