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
        Versione ottimizzata per migliori prestazioni e robustezza.

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

            # OTTIMIZZAZIONE: Verifica rapida per frame duplicati
            if pattern_index in self.pattern_frames.get(camera_index, {}):
                logger.debug(f"Frame {pattern_index} già ricevuto per camera {camera_index}, ignorato")
                return True

            # Aggiorna il contatore
            self.frame_counters[camera_index] = self.frame_counters.get(camera_index, 0) + 1

            # Memorizza le informazioni sul pattern
            if pattern_index not in self.pattern_info:
                self.pattern_info[pattern_index] = {
                    "name": pattern_name,
                    "timestamp": time.time()
                }

            # OTTIMIZZAZIONE: Inizializza la struttura dati per il pattern e la camera se non esiste
            if pattern_index not in self.pattern_frames:
                self.pattern_frames[pattern_index] = {}

            # OTTIMIZZAZIONE: Memorizza in RAM invece di salvare subito su disco
            self.pattern_frames[pattern_index][camera_index] = frame.copy()

            # Gestisci frame di riferimento bianchi/neri
            if pattern_name == "white":
                self.white_frames[camera_index] = frame.copy()
            elif pattern_name == "black":
                self.black_frames[camera_index] = frame.copy()

            # OTTIMIZZAZIONE: Salva su disco in modo asincrono solo periodicamente
            # o per frame critici (white, black)
            if pattern_name in ["white", "black"] or pattern_index % 5 == 0 or not hasattr(self,
                                                                                           '_last_saved_pattern_index') or pattern_index >= self._last_saved_pattern_index + 5:
                import threading

                def save_frame_async(camera_index, frame, pattern_index, pattern_name, scan_dir):
                    try:
                        camera_dir = scan_dir / ("left" if camera_index == 0 else "right")
                        camera_dir.mkdir(parents=True, exist_ok=True)

                        output_path = camera_dir / f"{pattern_index:04d}_{pattern_name}.png"
                        cv2.imwrite(str(output_path), frame)
                        logger.debug(f"Frame {pattern_index} salvato su disco in modo asincrono")
                    except Exception as e:
                        logger.error(f"Errore nel salvataggio asincrono del frame: {e}")

                scan_dir = self.output_dir / self.current_scan_id

                # Avvia thread per salvataggio asincrono
                save_thread = threading.Thread(
                    target=save_frame_async,
                    args=(camera_index, frame.copy(), pattern_index, pattern_name, scan_dir)
                )
                save_thread.daemon = True
                save_thread.start()

                self._last_saved_pattern_index = pattern_index

            # OTTIMIZZAZIONE: Inizia a elaborare i dati non appena abbiamo frame sufficienti
            # I frame white e black sono essenziali, insieme ad almeno un pattern
            if (self.white_frames[0] is not None and self.white_frames[1] is not None and
                    self.black_frames[0] is not None and self.black_frames[1] is not None and
                    len(self.pattern_frames) >= 3):  # Abbiamo white, black e almeno un pattern

                # Se non abbiamo ancora avviato l'elaborazione in tempo reale, avviala
                if not hasattr(self, '_realtime_processing_started') or not self._realtime_processing_started:
                    self._start_realtime_processing()
                    self._realtime_processing_started = True

            # Notifica callback se impostata
            if self._frame_callback:
                self._frame_callback(camera_index, pattern_index, frame)

            # Aggiorna progresso se callback impostata
            if self._progress_callback:
                progress = self.get_scan_progress()
                self._progress_callback(progress)

            # Log non troppo frequente per non intasare
            if pattern_index % 5 == 0 or pattern_name in ["white", "black"]:
                logger.info(f"Frame {pattern_index} ({pattern_name}) della camera {camera_index} elaborato")

            return True

        except Exception as e:
            logger.error(f"Errore nell'elaborazione del frame di scansione: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False

    def _start_realtime_processing(self):
        """
        Avvia l'elaborazione in tempo reale dei frame ricevuti.
        Esegue la triangolazione progressiva man mano che i frame vengono ricevuti.
        """
        try:
            logger.info("Avvio elaborazione in tempo reale")

            # Inizializza le strutture dati per l'elaborazione
            self._realtime_pointcloud = None
            self._realtime_processing_thread = None

            # Avvia un thread per l'elaborazione in background
            import threading

            def realtime_processing_thread():
                try:
                    # Importa il processore di triangolazione
                    from client.processing.triangulation import ScanProcessor, PatternType

                    # Inizializza il processore
                    processor = ScanProcessor(self.output_dir)

                    # Configura le callback
                    def progress_callback(progress, message):
                        logger.debug(f"Elaborazione in tempo reale: {progress}%, {message}")

                    def completion_callback(success, message, result):
                        logger.info(f"Aggiornamento nuvola di punti: {message}")
                        if success and result is not None:
                            with self._pointcloud_lock:
                                self._realtime_pointcloud = result

                    processor.set_callbacks(progress_callback, completion_callback)

                    # Crea una directory temporanea per l'elaborazione
                    import tempfile
                    temp_dir = tempfile.mkdtemp(prefix="unlook_realtime_")
                    temp_path = Path(temp_dir)

                    # Loop di elaborazione
                    last_processed_pattern = -1
                    while self.is_scanning:
                        try:
                            # Ottieni tutti i pattern disponibili
                            pattern_indices = sorted(self.pattern_frames.keys())

                            # Verifica se ci sono nuovi pattern da elaborare
                            if pattern_indices and pattern_indices[-1] > last_processed_pattern:
                                # Prepara i dati per l'elaborazione
                                for idx in range(last_processed_pattern + 1, pattern_indices[-1] + 1):
                                    if idx in self.pattern_frames and 0 in self.pattern_frames[idx] and 1 in \
                                            self.pattern_frames[idx]:
                                        # Salva temporaneamente i frame per l'elaborazione
                                        left_dir = temp_path / "left"
                                        right_dir = temp_path / "right"
                                        left_dir.mkdir(exist_ok=True)
                                        right_dir.mkdir(exist_ok=True)

                                        # Ottieni i frame
                                        left_frame = self.pattern_frames[idx][0]
                                        right_frame = self.pattern_frames[idx][1]

                                        # Determina il nome del pattern
                                        pattern_name = self.pattern_info.get(idx, {}).get("name", f"pattern_{idx}")

                                        # Salva i frame temporaneamente
                                        cv2.imwrite(str(left_dir / f"{idx:04d}_{pattern_name}.png"), left_frame)
                                        cv2.imwrite(str(right_dir / f"{idx:04d}_{pattern_name}.png"), right_frame)

                                # Aggiorna l'ultimo pattern elaborato
                                last_processed_pattern = pattern_indices[-1]

                                # Carica e elabora i dati
                                processor.load_local_scan(temp_dir)
                                processor.process_scan(use_threading=False)

                                # Aggiungi un ritardo per non sovraccaricare la CPU
                                time.sleep(0.5)
                            else:
                                # Nessun nuovo pattern, attendi
                                time.sleep(0.2)

                        except Exception as e:
                            logger.error(f"Errore nell'elaborazione in tempo reale: {e}")
                            time.sleep(1.0)  # Pausa più lunga in caso di errore

                    # Pulizia
                    import shutil
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    logger.info("Thread di elaborazione in tempo reale terminato")

                except Exception as e:
                    logger.error(f"Errore fatale nel thread di elaborazione in tempo reale: {e}")
                    import traceback
                    logger.error(f"Traceback: {traceback.format_exc()}")

            # Crea il mutex per proteggere l'accesso alla nuvola di punti
            self._pointcloud_lock = threading.Lock()

            # Avvia il thread
            self._realtime_processing_thread = threading.Thread(target=realtime_processing_thread)
            self._realtime_processing_thread.daemon = True
            self._realtime_processing_thread.start()

            logger.info("Elaborazione in tempo reale avviata")

        except Exception as e:
            logger.error(f"Errore nell'avvio dell'elaborazione in tempo reale: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")

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