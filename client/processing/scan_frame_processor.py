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

        logger.info(f"Iniziata nuova sessione di scansione con ID: {scan_id}")
        return scan_id

    def process_frame(self, camera_index, frame, frame_info):
        """
        Elabora un frame di scansione in tempo reale.

        Args:
            camera_index: Indice della camera (0=sinistra, 1=destra)
            frame: Frame come array NumPy
            frame_info: Informazioni sul frame (pattern_index, pattern_name, ecc.)

        Returns:
            True se il frame è stato elaborato correttamente, False altrimenti
        """
        if not self.is_scanning:
            return False

        try:
            pattern_index = frame_info.get("pattern_index", 0)
            pattern_name = frame_info.get("pattern_name", "unknown")

            # Aggiorna il contatore
            self.frame_counters[camera_index] = self.frame_counters.get(camera_index, 0) + 1

            # Memorizza le informazioni sul pattern
            if pattern_index not in self.pattern_info:
                self.pattern_info[pattern_index] = {
                    "name": pattern_name,
                    "timestamp": time.time()
                }

            # Gestisci frame di riferimento bianchi/neri
            if pattern_name == "white":
                self.white_frames[camera_index] = frame.copy()
            elif pattern_name == "black":
                self.black_frames[camera_index] = frame.copy()

            # Salva il frame in memoria per la triangolazione
            if pattern_index not in self.pattern_frames:
                self.pattern_frames[pattern_index] = {}
            self.pattern_frames[pattern_index][camera_index] = frame.copy()

            # Salva anche su disco come backup
            scan_dir = self.output_dir / self.current_scan_id
            camera_dir = scan_dir / ("left" if camera_index == 0 else "right")
            camera_dir.mkdir(parents=True, exist_ok=True)

            output_path = camera_dir / f"{pattern_index:04d}_{pattern_name}.png"
            cv2.imwrite(str(output_path), frame)

            # Notifica callback se impostata
            if self._frame_callback:
                self._frame_callback(camera_index, pattern_index, frame)

            # Aggiorna progresso se callback impostata
            if self._progress_callback:
                progress = self.get_scan_progress()
                self._progress_callback(progress)

            # Verifica se abbiamo i frame bianchi e neri per entrambe le camere
            # Questo è importante per la triangolazione
            if (self.white_frames[0] is not None and self.white_frames[1] is not None and
                    self.black_frames[0] is not None and self.black_frames[1] is not None):
                # Se abbiamo frame bianchi e neri per entrambe le camere, possiamo
                # iniziare a calcolare le maschere di ombra per ciascuna camera
                pass

            # Log non troppo frequente per non intasare
            if pattern_index % 5 == 0 or pattern_name in ["white", "black"]:
                logger.info(f"Frame {pattern_index} ({pattern_name}) della camera {camera_index} elaborato")

            return True

        except Exception as e:
            logger.error(f"Errore nell'elaborazione del frame di scansione: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False

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