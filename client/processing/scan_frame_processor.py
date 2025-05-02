#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Modulo per l'elaborazione in tempo reale dei frame di scansione.
Gestisce l'acquisizione, la memorizzazione e la pre-elaborazione dei frame
per la successiva triangolazione 3D.
"""

import os
import time
import logging
import cv2
import threading
import numpy as np
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, Tuple, List, Set, Any

# Configurazione logging
logger = logging.getLogger(__name__)


class ScanFrameProcessor:
    """
    Classe che gestisce i frame di scansione in modo real-time.
    Prepara il terreno per la scansione 3D in tempo reale.
    """

    def __init__(self, output_dir=None):
        """
        Inizializza il processore di frame di scansione.

        Args:
            output_dir: Directory di output per i frame salvati
        """
        self.output_dir = output_dir or Path.home() / "UnLook" / "scans"
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.current_scan_id = None
        self.frame_counters = {0: 0, 1: 0}  # Contatori per ciascuna camera
        self.pattern_info = {}  # Informazioni sui pattern
        self.is_scanning = False

        # Per la triangolazione in tempo reale
        self.white_frames = {0: None, 1: None}  # Frame di riferimento bianchi
        self.black_frames = {0: None, 1: None}  # Frame di riferimento neri
        self.pattern_frames = {}  # Dizionario di frame per pattern

        # Callback per notificare gli aggiornamenti
        self._progress_callback = None
        self._frame_callback = None

    def set_callbacks(self, progress_callback=None, frame_callback=None):
        """
        Imposta le callback per le notifiche di avanzamento e frame.

        Args:
            progress_callback: Funzione chiamata quando lo stato di avanzamento cambia
            frame_callback: Funzione chiamata quando un nuovo frame è elaborato
        """
        self._progress_callback = progress_callback
        self._frame_callback = frame_callback

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
        if scan_id is None:
            scan_id = f"Scan_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        self.current_scan_id = scan_id
        self.is_scanning = True
        self.frame_counters = {0: 0, 1: 0}
        self.pattern_info = {}
        self.white_frames = {0: None, 1: None}
        self.black_frames = {0: None, 1: None}
        self.pattern_frames = {}

        # Salva informazioni della scansione
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

        # Avvia l'elaborazione in tempo reale
        self._start_realtime_processing()

        logger.info(f"Iniziata nuova sessione di scansione con ID: {scan_id}")
        return scan_id

    def process_frame(self, camera_index, frame, frame_info):
        """
        Elabora un frame di scansione in tempo reale.
        Versione ottimizzata con salvataggio sia in memoria che su disco.

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

            # Verifica frame duplicati
            if pattern_index in self.pattern_frames:
                if camera_index in self.pattern_frames[pattern_index]:
                    logger.debug(f"Frame {pattern_index} già elaborato per camera {camera_index}, ignorato")
                    return True

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

            # Inizializza struttura dati
            if pattern_index not in self.pattern_frames:
                self.pattern_frames[pattern_index] = {}

            # PRIORITÀ 1: Salva in memoria (per elaborazione in tempo reale)
            self.pattern_frames[pattern_index][camera_index] = frame.copy()

            # Gestisci frame di riferimento
            if pattern_name == "white":
                self.white_frames[camera_index] = frame.copy()
                logger.info(f"Memorizzato frame di riferimento WHITE per camera {camera_index}")
            elif pattern_name == "black":
                self.black_frames[camera_index] = frame.copy()
                logger.info(f"Memorizzato frame di riferimento BLACK per camera {camera_index}")

            # PRIORITÀ 2: Salva su disco per backup e analisi successiva
            try:
                # Prepara percorso
                scan_dir = Path(self.output_dir) / self.current_scan_id
                scan_dir.mkdir(parents=True, exist_ok=True)

                camera_dir = scan_dir / ("left" if camera_index == 0 else "right")
                camera_dir.mkdir(parents=True, exist_ok=True)

                # Componi percorso file
                output_path = camera_dir / f"{pattern_index:04d}_{pattern_name}.png"

                # Avvia un thread separato per il salvataggio su disco
                # così da non bloccare l'elaborazione in tempo reale
                def save_frame_thread(frame, path):
                    try:
                        # Salva con OpenCV
                        success = cv2.imwrite(str(path), frame)
                        if not success:
                            logger.error(f"ScanFrameProcessor: cv2.imwrite ha fallito per {path}")
                            # Fallback a PIL
                            try:
                                from PIL import Image
                                img = Image.fromarray(frame)
                                img.save(str(path))
                                logger.info(f"ScanFrameProcessor: salvataggio con PIL riuscito: {path}")
                            except Exception as e2:
                                logger.error(f"ScanFrameProcessor: anche PIL ha fallito: {e2}")
                    except Exception as e:
                        logger.error(f"ScanFrameProcessor: errore nel salvataggio del frame: {e}")

                # Avvia thread di salvataggio (asincrono)
                import threading
                save_thread = threading.Thread(target=save_frame_thread, args=(frame.copy(), output_path))
                save_thread.daemon = True
                save_thread.start()

            except Exception as e:
                logger.error(f"ScanFrameProcessor: errore nella preparazione del salvataggio su disco: {e}")
                # Non bloccare il flusso per errori di salvataggio

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

            # IMPORTANTE: Segnala al thread di elaborazione che è disponibile un nuovo frame
            # Verifica se abbiamo una coppia completa (camera 0 e 1) per questo pattern
            is_pair_complete = (pattern_index in self.pattern_frames and
                                0 in self.pattern_frames[pattern_index] and
                                1 in self.pattern_frames[pattern_index])

            # Se la coppia è completa, segnala al thread di elaborazione
            if is_pair_complete and hasattr(self, '_processing_event'):
                self._processing_event.set()
                logger.debug(f"Coppia completa per pattern {pattern_index}, segnalato al thread di elaborazione")

            return True

        except Exception as e:
            logger.error(f"ScanFrameProcessor: errore generale nell'elaborazione: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False

    def _ensure_calibration(self):
        """
        Assicura che i dati di calibrazione siano disponibili per la triangolazione.
        Usa il ScanProcessor per caricare o creare i dati necessari.

        Returns:
            Tuple (calib_data, P1, P2, Q, map_x_l, map_y_l, map_x_r, map_y_r) o None in caso di errore
        """
        try:
            # Importa il processore di triangolazione
            from client.processing.triangulation import ScanProcessor, PatternType

            # Se abbiamo già i dati di calibrazione in memoria, li riutilizziamo
            if hasattr(self, '_calibration_data') and self._calibration_data is not None:
                return self._calibration_data

            # Altrimenti, crea un processore temporaneo per caricare la calibrazione
            processor = ScanProcessor(self.output_dir)

            # Carica la calibrazione da file o crea una calibrazione di default
            calib_file = Path(self.output_dir) / "calibration.npz"

            if calib_file.exists():
                # Carica da file
                processor.calib_data = np.load(calib_file)
                logger.info("Dati di calibrazione caricati da file locale")
            else:
                # Tenta di caricare dal server se possibile
                try:
                    # Se l'applicazione ha un scanner_controller attivo, usa quello
                    # Questa è una supposizione, potrebbe essere necessario passarlo come parametro
                    from client.controllers.scanner_controller import ScannerController
                    scanner_controller = ScannerController()

                    if scanner_controller and scanner_controller.selected_scanner:
                        logger.info("Tentativo di caricamento calibrazione dal server")
                        device_id = scanner_controller.selected_scanner.device_id
                        connection_manager = scanner_controller._connection_manager

                        success = processor._load_or_download_calibration(connection_manager, device_id)
                        if success:
                            logger.info("Calibrazione scaricata dal server con successo")
                        else:
                            logger.warning("Impossibile scaricare calibrazione, uso valori di default")
                            processor._create_default_calibration()
                    else:
                        logger.warning("Scanner non selezionato, creazione calibrazione di default")
                        processor._create_default_calibration()
                except Exception as e:
                    logger.error(f"Errore nel caricamento della calibrazione: {e}")
                    logger.warning("Creazione calibrazione di default")
                    processor._create_default_calibration()

            # Genera le mappe di rettificazione se necessario
            if processor.map_x_l is None:
                processor._generate_rectification_maps()
                logger.info("Mappe di rettificazione generate")

            # Memorizza i dati per uso futuro
            self._calibration_data = (
                processor.calib_data,
                processor.Q,
                processor.map_x_l,
                processor.map_y_l,
                processor.map_x_r,
                processor.map_y_r
            )

            return self._calibration_data

        except Exception as e:
            logger.error(f"Errore nell'inizializzazione della calibrazione: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return None
    def _start_realtime_processing(self):
        """
        Avvia l'elaborazione in tempo reale dei frame ricevuti.
        Versione ottimizzata con elaborazione diretta in memoria.
        """
        try:
            logger.info("Avvio elaborazione in tempo reale ottimizzata")

            # Importazione delle librerie necessarie
            import threading
            import queue
            from client.processing.triangulation import ScanProcessor, PatternType

            # Inizializza le strutture dati per l'elaborazione
            self._realtime_pointcloud = None
            self._pointcloud_lock = threading.Lock()
            self._frame_queue = queue.Queue(maxsize=100)  # Coda per comunicazione tra thread
            self._processing_event = threading.Event()  # Per segnalare che è disponibile un set completo

            # Flag per tracciare lo stato di elaborazione realtime
            self._realtime_processing_active = True

            # Variabili per tenere traccia dello stato dell'elaborazione
            self._last_processed_pattern = -1
            self._min_patterns_for_update = 4  # Richiede almeno 4 pattern per un aggiornamento (2 white/black + 2 pattern)

            # Crea un oggetto ScanProcessor già configurato
            processor = ScanProcessor(self.output_dir)

            # Configura le callback
            def progress_callback(progress, message):
                logger.debug(f"Elaborazione in tempo reale: {progress}%, {message}")
                if self._progress_callback:
                    self._progress_callback({
                        "progress": progress,
                        "message": message,
                        "state": "TRIANGULATING",
                        "frames_total": sum(self.frame_counters.values())
                    })

            def completion_callback(success, message, result):
                if not success:
                    logger.error(f"Errore nella triangolazione: {message}")
                    return

                logger.info(f"Aggiornamento nuvola di punti: {len(result) if result is not None else 0} punti")
                if success and result is not None:
                    with self._pointcloud_lock:
                        self._realtime_pointcloud = result
                        # Notifica nuova nuvola disponibile
                        if hasattr(self, "_frame_callback") and self._frame_callback:
                            try:
                                self._frame_callback(-1, -1, {
                                    "type": "pointcloud_update",
                                    "pointcloud": result,
                                    "num_points": len(result),
                                    "timestamp": time.time()
                                })
                            except Exception as e:
                                logger.error(f"Errore nella callback pointcloud: {e}")

            processor.set_callbacks(progress_callback, completion_callback)

            # Thread per l'elaborazione che consuma dalla coda
            def processing_thread():
                logger.info("Thread di elaborazione avviato")

                try:
                    while self.is_scanning and self._realtime_processing_active:
                        try:
                            # Attende l'evento che segnala disponibilità di un set completo
                            if not self._processing_event.wait(timeout=1.0):
                                continue

                            # Reset dell'evento
                            self._processing_event.clear()

                            # Controllo delle condizioni per l'elaborazione
                            pattern_indices = sorted(self.pattern_frames.keys())

                            # Verifica se abbiamo i frame di riferimento (white e black)
                            white_black_present = (
                                    0 in pattern_indices and 1 in pattern_indices and
                                    0 in self.pattern_frames and 1 in self.pattern_frames and
                                    0 in self.pattern_frames[0] and 1 in self.pattern_frames[0] and
                                    0 in self.pattern_frames[1] and 1 in self.pattern_frames[1]
                            )

                            # Verifica se abbiamo abbastanza nuovi pattern
                            enough_new_patterns = (
                                    len(pattern_indices) >= self._min_patterns_for_update and
                                    max(pattern_indices) > self._last_processed_pattern and
                                    (max(pattern_indices) - self._last_processed_pattern >= 2 or
                                     self._last_processed_pattern < self._min_patterns_for_update)
                            )

                            if white_black_present and enough_new_patterns:
                                logger.info(f"Avvio elaborazione incrementale con {len(pattern_indices)} pattern")

                                # Utilizzo diretto dei frame in memoria
                                # Estrazione white e black frames
                                white_left = self.pattern_frames[0][0].copy()
                                white_right = self.pattern_frames[0][1].copy()
                                black_left = self.pattern_frames[1][0].copy()
                                black_right = self.pattern_frames[1][1].copy()

                                # Calcolo maschere di ombra
                                shadow_mask_left = np.zeros_like(black_left, dtype=np.uint8)
                                shadow_mask_right = np.zeros_like(black_right, dtype=np.uint8)
                                threshold = 40  # Soglia per rilevazione ombre
                                shadow_mask_left[white_left > black_left + threshold] = 1
                                shadow_mask_right[white_right > black_right + threshold] = 1

                                # Raccolta dei pattern per l'elaborazione (escludendo white/black)
                                pattern_pairs = []
                                for idx in pattern_indices:
                                    if idx < 2:  # Salta white e black
                                        continue

                                    if idx in self.pattern_frames and 0 in self.pattern_frames[idx] and 1 in \
                                            self.pattern_frames[idx]:
                                        left_frame = self.pattern_frames[idx][0].copy()
                                        right_frame = self.pattern_frames[idx][1].copy()
                                        pattern_pairs.append((idx, left_frame, right_frame))

                                # Ordina per indice pattern
                                pattern_pairs.sort(key=lambda x: x[0])

                                # Elabora direttamente in memoria
                                if len(pattern_pairs) >= 2:  # Almeno 2 pattern oltre a white/black
                                    # Crea mappe di disparità incrementali
                                    height, width = white_left.shape[:2]
                                    disparity_map = np.zeros((height, width), dtype=np.float32)
                                    confidence_map = np.zeros((height, width), dtype=np.float32)

                                    # Elabora direttamente i pattern
                                    for i, (pattern_idx, left, right) in enumerate(pattern_pairs):
                                        pattern_weight = 2 ** (i // 2)  # Peso basato sulla posizione

                                        # Aggiorna la mappa di disparità con questo pattern
                                        self._update_disparity_from_pattern(
                                            left, right,
                                            shadow_mask_left, shadow_mask_right,
                                            disparity_map, confidence_map,
                                            pattern_weight
                                        )

                                    # Calcola la mappa di disparità finale
                                    valid_indices = confidence_map > 0
                                    disparity_map_final = np.zeros_like(disparity_map)
                                    disparity_map_final[valid_indices] = disparity_map[valid_indices] / confidence_map[
                                        valid_indices]

                                    # Filtro mediano per ridurre il rumore
                                    kernel_size = 3
                                    disparity_map_final = cv2.medianBlur(disparity_map_final.astype(np.float32),
                                                                         kernel_size)

                                    # Riproiezione in 3D (se available)
                                    if hasattr(processor, '_reproject_to_3d_incremental'):
                                        # Utilizza il metodo diretto di triangolazione
                                        if processor.calib_data is None:
                                            # Tenta di caricare la calibrazione dal server o da file
                                            try:
                                                processor._load_or_download_calibration(None, None)
                                            except:
                                                # Usa calibrazione di default
                                                processor._create_default_calibration()
                                                processor._generate_rectification_maps()

                                        # Esegue la riproiezione 3D
                                        pointcloud = processor._reproject_to_3d_incremental(disparity_map_final,
                                                                                            shadow_mask_left)

                                        # Aggiorna la nuvola di punti
                                        if pointcloud is not None and len(pointcloud) > 100:
                                            completion_callback(True, f"Nuvola aggiornata con {len(pointcloud)} punti",
                                                                pointcloud)

                                    self._last_processed_pattern = max(pattern_indices)
                                    logger.info(
                                        f"Elaborazione incrementale completata, ultimo pattern: {self._last_processed_pattern}")

                            # Ritardo per non sovraccaricare la CPU
                            time.sleep(0.2)

                        except Exception as e:
                            logger.error(f"Errore nell'elaborazione in tempo reale: {e}")
                            import traceback
                            logger.error(f"Traceback: {traceback.format_exc()}")
                            time.sleep(1.0)  # Pausa più lunga in caso di errore

                    logger.info("Thread di elaborazione in tempo reale terminato normalmente")

                except Exception as e:
                    logger.error(f"Errore fatale nel thread di elaborazione in tempo reale: {e}")
                    import traceback
                    logger.error(f"Traceback: {traceback.format_exc()}")

            # Avvia il thread di elaborazione
            self._realtime_processing_thread = threading.Thread(target=processing_thread)
            self._realtime_processing_thread.daemon = True
            self._realtime_processing_thread.start()

            logger.info("Elaborazione in tempo reale ottimizzata avviata")

        except Exception as e:
            logger.error(f"Errore nell'avvio dell'elaborazione in tempo reale: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")

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

    def compute_shadow_mask(self, camera_index):
        """
        Calcola la maschera di ombra per una camera.
        Richiede che siano presenti i frame di riferimento bianchi e neri.

        Args:
            camera_index: Indice della camera (0=sinistra, 1=destra)

        Returns:
            Maschera di ombra come array NumPy o None in caso di errore
        """
        if (self.white_frames[camera_index] is None or
                self.black_frames[camera_index] is None):
            return None

        try:
            white = self.white_frames[camera_index]
            black = self.black_frames[camera_index]

            # Calcola la maschera di ombra
            shadow_mask = np.zeros_like(black, dtype=np.uint8)
            threshold = 40  # Soglia per la rilevazione delle ombre
            shadow_mask[white > black + threshold] = 1

            return shadow_mask
        except Exception as e:
            logger.error(f"Errore nel calcolo della maschera di ombra: {e}")
            return None

    def _reproject_3d_pointcloud(self, disparity_map, mask):
        """
        Riproietta una mappa di disparità in una nuvola di punti 3D.
        Versione ottimizzata che opera direttamente in memoria.

        Args:
            disparity_map: Mappa di disparità come array NumPy
            mask: Maschera di validità (1 per pixel validi, 0 per pixel invalidi)

        Returns:
            Array NumPy di punti 3D o None in caso di errore
        """
        try:
            # Assicura che la calibrazione sia disponibile
            calibration = self._ensure_calibration()
            if calibration is None:
                logger.error("Impossibile ottenere i dati di calibrazione per la riproiezione")
                return None

            _, Q, _, _, _, _ = calibration

            # Applica la maschera alla mappa di disparità
            masked_disparity = disparity_map.copy()
            masked_disparity[mask == 0] = 0

            # Riproietta in 3D
            points_3d = cv2.reprojectImageTo3D(masked_disparity, Q)

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
    def stop_scan(self):
        """
        Ferma la sessione di scansione corrente.

        Returns:
            Dizionario con statistiche sulla scansione
        """
        if not self.is_scanning:
            return {"success": False, "message": "Nessuna scansione attiva"}

        self.is_scanning = False

        stats = {
            "scan_id": self.current_scan_id,
            "frames_total": sum(self.frame_counters.values()),
            "frames_left": self.frame_counters.get(0, 0),
            "frames_right": self.frame_counters.get(1, 0),
            "patterns_received": len(self.pattern_frames),
            "timestamp": datetime.now().isoformat(),
            "success": True
        }

        logger.info(f"Scansione {self.current_scan_id} completata con {stats['frames_total']} frame totali")

        # Salva statistiche
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
        received_patterns = len(self.pattern_frames)

        progress = min(100.0, (received_patterns / expected_patterns) * 100.0)

        # Ottieni conteggio per camera
        frames_left = self.frame_counters.get(0, 0)
        frames_right = self.frame_counters.get(1, 0)

        return {
            "state": "SCANNING",
            "progress": progress,
            "patterns_received": received_patterns,
            "frames_total": sum(self.frame_counters.values()),
            "frames_left": frames_left,
            "frames_right": frames_right,
            "scan_id": self.current_scan_id
        }

    def get_frame_pairs(self):
        """
        Restituisce le coppie di frame corrispondenti per la triangolazione.

        Returns:
            Lista di tuple (pattern_index, left_frame, right_frame)
        """
        result = []

        for pattern_index, frames_dict in self.pattern_frames.items():
            # Verifica se abbiamo frame per entrambe le camere
            if 0 in frames_dict and 1 in frames_dict:
                left_frame = frames_dict[0]
                right_frame = frames_dict[1]
                result.append((pattern_index, left_frame, right_frame))

        # Ordina per indice pattern
        result.sort(key=lambda x: x[0])
        return result