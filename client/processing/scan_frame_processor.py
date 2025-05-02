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

        # Avvia l'elaborazione in tempo reale
        self._start_realtime_processing()

        logger.info(f"Iniziata nuova sessione di scansione con ID: {scan_id}")
        return scan_id

    def process_frame(self, camera_index, frame, frame_info):
        """
        Elabora un frame di scansione in tempo reale.
        Versione completamente riscritta per maggiore affidabilità.

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

            # Memorizza frame in RAM
            self.pattern_frames[pattern_index][camera_index] = frame.copy()

            # Gestisci frame di riferimento
            if pattern_name == "white":
                self.white_frames[camera_index] = frame.copy()
                logger.info(f"Memorizzato frame di riferimento WHITE per camera {camera_index}")
            elif pattern_name == "black":
                self.black_frames[camera_index] = frame.copy()
                logger.info(f"Memorizzato frame di riferimento BLACK per camera {camera_index}")

            # Prepara percorso di salvataggio ASSOLUTO
            scan_dir = Path(self.output_dir) / self.current_scan_id
            scan_dir.mkdir(parents=True, exist_ok=True)

            # In questa versione, salviamo SEMPRE i frame, non solo periodicamente
            # Salvataggio SINCRONO per garantire che i file siano scritti
            try:
                # Prepara percorso
                camera_dir = scan_dir / ("left" if camera_index == 0 else "right")
                camera_dir.mkdir(parents=True, exist_ok=True)

                # Componi percorso file
                output_path = camera_dir / f"{pattern_index:04d}_{pattern_name}.png"

                # Salva con OpenCV
                success = cv2.imwrite(str(output_path), frame)

                if not success:
                    logger.error(f"ScanFrameProcessor: cv2.imwrite ha fallito per {output_path}")
                    raise RuntimeError("cv2.imwrite ha restituito False")

                # Verifica esistenza file
                if not os.path.exists(str(output_path)):
                    logger.error(f"ScanFrameProcessor: file {output_path} non esiste dopo cv2.imwrite!")
                    raise FileNotFoundError(f"File {output_path} non trovato dopo il salvataggio")

                file_size = os.path.getsize(str(output_path))
                logger.info(f"ScanFrameProcessor: frame {pattern_index} salvato: {output_path} ({file_size} bytes)")

                # Salvataggio riuscito, aggiorna stato
                self._last_saved_pattern_index = pattern_index

            except Exception as e:
                logger.error(f"ScanFrameProcessor: errore nel salvataggio primario: {e}")

                # Fallback 1: PIL
                try:
                    from PIL import Image
                    img = Image.fromarray(frame)
                    img.save(str(output_path))
                    logger.info(f"ScanFrameProcessor: salvataggio con PIL riuscito: {output_path}")
                except Exception as e2:
                    logger.error(f"ScanFrameProcessor: anche PIL ha fallito: {e2}")

                    # Fallback 2: NumPy binario
                    try:
                        npy_path = str(output_path).replace('.png', '.npy')
                        np.save(npy_path, frame)
                        logger.info(f"ScanFrameProcessor: salvataggio numpy riuscito: {npy_path}")
                    except Exception as e3:
                        logger.error(f"ScanFrameProcessor: tutti i metodi di salvataggio hanno fallito: {e3}")
                        # Non solleviamo l'eccezione per non interrompere il flusso

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

            # Log di completamento
            logger.info(f"ScanFrameProcessor: frame {pattern_index} elaborato completamente")
            return True

        except Exception as e:
            logger.error(f"ScanFrameProcessor: errore generale nell'elaborazione: {e}")
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
            self._pointcloud_lock = threading.Lock()

            # Flag per tracciare lo stato di elaborazione realtime
            self._realtime_processing_active = True

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
                        if self._progress_callback:
                            self._progress_callback({
                                "progress": progress,
                                "message": message,
                                "state": "TRIANGULATING",
                                "frames_total": sum(self.frame_counters.values())
                            })

                    def completion_callback(success, message, result):
                        logger.info(f"Aggiornamento nuvola di punti: {message}")
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

                    # Crea una directory temporanea per l'elaborazione
                    import tempfile
                    temp_dir = tempfile.mkdtemp(prefix="unlook_realtime_")
                    temp_path = Path(temp_dir)

                    # Loop di elaborazione con controllo più frequente
                    last_processed_pattern = -1
                    min_patterns_for_update = 4  # Richiede almeno 4 pattern per un aggiornamento (2 white/black + 2 pattern)

                    update_interval = 2  # Aggiorna ogni 2 nuovi pattern

                    while self.is_scanning and self._realtime_processing_active:
                        try:
                            # Ottieni tutti i pattern disponibili
                            pattern_indices = sorted(self.pattern_frames.keys())

                            # Verifica se abbiamo white+black+almeno 2 pattern
                            white_black_present = False
                            if 0 in pattern_indices and 1 in pattern_indices:
                                white_black_present = (0 in self.pattern_frames and
                                                       0 in self.pattern_frames[0] and
                                                       1 in self.pattern_frames[0] and
                                                       1 in self.pattern_frames and
                                                       0 in self.pattern_frames[1] and
                                                       1 in self.pattern_frames[1])

                            # Se abbiamo un numero sufficiente di nuovi pattern e i frame di riferimento
                            if (pattern_indices and
                                    max(pattern_indices) >= min_patterns_for_update and
                                    white_black_present and
                                    max(pattern_indices) > last_processed_pattern and
                                    (max(pattern_indices) - last_processed_pattern >= update_interval or
                                     last_processed_pattern < min_patterns_for_update)):

                                logger.info(f"Avvio elaborazione incrementale con {len(pattern_indices)} pattern")

                                # Prepara i dati per l'elaborazione
                                # Prima elimina eventuali file precedenti dalla directory temporanea
                                for f in os.listdir(temp_dir):
                                    try:
                                        os.remove(os.path.join(temp_dir, f))
                                    except:
                                        pass

                                # Ricrea le sottodirectory
                                left_dir = temp_path / "left"
                                right_dir = temp_path / "right"
                                left_dir.mkdir(exist_ok=True)
                                right_dir.mkdir(exist_ok=True)

                                # Salva i frame di riferimento
                                if 0 in self.pattern_frames and 1 in self.pattern_frames:
                                    # Salva white frames (pattern 0)
                                    if 0 in self.pattern_frames[0] and 1 in self.pattern_frames[0]:
                                        cv2.imwrite(str(left_dir / "0000_white.png"), self.pattern_frames[0][0])
                                        cv2.imwrite(str(right_dir / "0000_white.png"), self.pattern_frames[0][1])

                                    # Salva black frames (pattern 1)
                                    if 0 in self.pattern_frames[1] and 1 in self.pattern_frames[1]:
                                        cv2.imwrite(str(left_dir / "0001_black.png"), self.pattern_frames[1][0])
                                        cv2.imwrite(str(right_dir / "0001_black.png"), self.pattern_frames[1][1])

                                # Salva pattern frames (da pattern 2 in poi)
                                num_patterns_saved = 0
                                for idx in pattern_indices:
                                    if idx < 2:  # Salta white e black che abbiamo già salvato
                                        continue

                                    if idx in self.pattern_frames and 0 in self.pattern_frames[idx] and 1 in \
                                            self.pattern_frames[idx]:
                                        # Ottieni i frame
                                        left_frame = self.pattern_frames[idx][0]
                                        right_frame = self.pattern_frames[idx][1]

                                        # Determina il nome del pattern
                                        pattern_name = self.pattern_info.get(idx, {}).get("name", f"pattern_{idx}")

                                        # Salva i frame temporaneamente
                                        cv2.imwrite(str(left_dir / f"{idx:04d}_{pattern_name}.png"), left_frame)
                                        cv2.imwrite(str(right_dir / f"{idx:04d}_{pattern_name}.png"), right_frame)
                                        num_patterns_saved += 1

                                # Aggiorna l'ultimo pattern elaborato
                                last_processed_pattern = max(pattern_indices)

                                # Se abbiamo salvato abbastanza pattern, elabora
                                if num_patterns_saved >= 2:  # Almeno 2 pattern oltre a white/black
                                    logger.info(f"Elaborazione di {num_patterns_saved} pattern...")

                                    # Carica e elabora i dati
                                    processor.load_local_scan(temp_dir)

                                    # Avvia elaborazione con flag per elaborazione incrementale
                                    processor.process_scan(use_threading=False, incremental=True)

                                    logger.info(f"Elaborazione incrementale completata")

                            # Pausa per ridurre carico CPU
                            time.sleep(0.5)

                        except Exception as e:
                            logger.error(f"Errore nell'elaborazione in tempo reale: {e}")
                            import traceback
                            logger.error(f"Traceback: {traceback.format_exc()}")
                            time.sleep(1.0)  # Pausa più lunga in caso di errore

                    # Pulizia
                    try:
                        import shutil
                        shutil.rmtree(temp_dir, ignore_errors=True)
                    except:
                        pass

                    logger.info("Thread di elaborazione in tempo reale terminato")

                except Exception as e:
                    logger.error(f"Errore fatale nel thread di elaborazione in tempo reale: {e}")
                    import traceback
                    logger.error(f"Traceback: {traceback.format_exc()}")

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