#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Controller per scansione 3D a luce strutturata.
Gestisce la generazione di pattern e la sincronizzazione con le camere.
Integra con la libreria DLPC342X per il controllo del proiettore DLP.
"""

import time
import logging
import threading
import os
import numpy as np
import cv2
from enum import Enum
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Callable, Any

# Importa il controller del proiettore
try:
    from server.projector.dlp342x import DLPC342XController, OperatingMode, Color, BorderEnable
except ImportError:
    try:
        from projector.dlp342x import DLPC342XController, OperatingMode, Color, BorderEnable
    except ImportError:
        from dlp342x import DLPC342XController, OperatingMode, Color, BorderEnable

# Configura logging
logger = logging.getLogger(__name__)


class ScanPatternType(Enum):
    """Tipi di pattern per la scansione a luce strutturata."""
    GRAY_CODE = 1  # Sequenza Gray Code classica
    BINARY_CODE = 2  # Sequenza binaria standard
    PHASE_SHIFT = 3  # Pattern a spostamento di fase (sinusoidali)
    PROGRESSIVE = 4  # Linee progressive che si assottigliano


class ScanningState(Enum):
    """Stati possibili durante la scansione."""
    IDLE = 0  # In attesa
    INITIALIZING = 1  # Inizializzazione
    SCANNING = 2  # Scansione in corso
    PROCESSING = 3  # Elaborazione dei dati
    COMPLETED = 4  # Scansione completata
    ERROR = 5  # Errore durante la scansione


class StructuredLightController:
    """
    Controller per la scansione 3D a luce strutturata.
    Gestisce la proiezione di pattern e l'acquisizione sincronizzata.
    """

    def __init__(self,
                 i2c_bus: int = 3,
                 i2c_address: int = 0x1b,
                 capture_dir: str = None):
        """
        Inizializza il controller di scansione a luce strutturata.

        Args:
            i2c_bus: Bus I2C per il proiettore (default: 3)
            i2c_address: Indirizzo I2C del proiettore (default: 0x1b)
            capture_dir: Directory per salvare i frame acquisiti
        """
        # Stato della scansione
        self.state = ScanningState.IDLE
        self.error_message = ""

        # Configurazione del proiettore
        self.i2c_bus = i2c_bus
        self.i2c_address = i2c_address
        self._projector = None

        # Directory per i frame acquisiti
        if capture_dir is None:
            base_dir = Path(__file__).parent.parent.parent / "scans"
            self.capture_dir = base_dir / time.strftime("%Y%m%d_%H%M%S")
        else:
            self.capture_dir = Path(capture_dir)

        # Assicura che la directory esista
        self.capture_dir.mkdir(parents=True, exist_ok=True)
        self.left_dir = self.capture_dir / "left"
        self.right_dir = self.capture_dir / "right"
        self.left_dir.mkdir(exist_ok=True)
        self.right_dir.mkdir(exist_ok=True)

        # Parametri di scansione
        self.pattern_type = ScanPatternType.PROGRESSIVE
        self.num_patterns = 20  # Numero totale di pattern da proiettare
        self.exposure_time = 0.5  # Tempo di esposizione per ogni pattern (secondi)
        self.quality = 3  # Qualità della scansione (1-5)

        # Thread di scansione
        self._scan_thread = None
        self._cancel_scan = False

        # Callback per l'acquisizione dei frame
        self._frame_capture_callback = None

        # Statistiche della scansione
        self.scan_stats = {
            'start_time': 0,
            'end_time': 0,
            'total_patterns': 0,
            'completed_patterns': 0,
            'captured_frames': 0,
            'errors': 0
        }

        # Pattern corrente e frame acquisiti
        self.current_pattern_index = -1
        self.frame_pairs = []  # Lista di tuple (frame_left, frame_right)

        logger.info("Controller luce strutturata inizializzato")

    def initialize_projector(self) -> bool:
        """
        Inizializza la connessione con il proiettore DLP e imposta lo sfondo nero.

        Returns:
            True se l'inizializzazione è riuscita, False altrimenti
        """
        try:
            # Inizializza il controller del proiettore
            self._projector = DLPC342XController(
                bus=self.i2c_bus,
                address=self.i2c_address
            )

            # Testa la connessione impostando la modalità
            self._projector.set_operating_mode(OperatingMode.TestPatternGenerator)
            time.sleep(0.5)  # Attendi che il proiettore risponda

            # Imposta un pattern iniziale (nero) per verifica
            self._projector.generate_solid_field(Color.Black)

            # Imposta il bordo nero
            try:
                self._projector.set_display_border(BorderEnable.Disable)
                logger.info("Bordo proiettore disabilitato")
            except Exception as border_err:
                logger.warning(f"Impossibile disabilitare il bordo: {border_err}")

            logger.info("Proiettore DLP inizializzato correttamente e impostato a nero")
            return True

        except Exception as e:
            self.error_message = f"Errore nell'inizializzazione del proiettore: {str(e)}"
            logger.error(self.error_message)
            return False

    def close(self):
        """Chiude la connessione con il proiettore e rilascia le risorse."""
        if self._projector:
            try:
                # Imposta un pattern nero
                self._projector.generate_solid_field(Color.Black)
                # Disabilita il bordo
                try:
                    self._projector.set_display_border(BorderEnable.Disable)
                except:
                    pass
                # Torna alla modalità video
                self._projector.set_operating_mode(OperatingMode.ExternalVideoPort)
                # Chiudi la connessione
                self._projector.close()
                logger.info("Proiettore DLP chiuso correttamente e impostato a nero")
            except Exception as e:
                logger.error(f"Errore nella chiusura del proiettore: {e}")

    def set_frame_capture_callback(self, callback: Callable):
        """
        Imposta la funzione di callback per l'acquisizione dei frame.
        La callback dovrebbe accettare un indice di pattern e restituire una coppia di frame (sx, dx).

        Args:
            callback: Funzione che acquisisce i frame dalle camere
        """
        self._frame_capture_callback = callback

    def start_scan(self,
                   pattern_type: ScanPatternType = ScanPatternType.PROGRESSIVE,
                   num_patterns: int = 20,
                   exposure_time: float = 0.5,
                   quality: int = 3) -> bool:
        """
        Avvia una scansione 3D in un thread separato.

        Args:
            pattern_type: Tipo di pattern da utilizzare
            num_patterns: Numero di pattern da proiettare
            exposure_time: Tempo di esposizione per ogni pattern (secondi)
            quality: Qualità della scansione (1-5)

        Returns:
            True se la scansione è stata avviata, False altrimenti
        """
        if self.state == ScanningState.SCANNING:
            logger.warning("Scansione già in corso")
            return False

        # Aggiorna i parametri di scansione
        self.pattern_type = pattern_type
        self.num_patterns = num_patterns
        self.exposure_time = exposure_time
        self.quality = quality

        # Reset delle statistiche
        self.scan_stats = {
            'start_time': time.time(),
            'end_time': 0,
            'total_patterns': num_patterns * 2 + 2,  # Orizzontali + verticali + bianco + nero
            'completed_patterns': 0,
            'captured_frames': 0,
            'errors': 0
        }

        # Verifica che il proiettore sia disponibile
        if not self._projector:
            success = self.initialize_projector()
            if not success:
                return False

        # Verifica che la callback per l'acquisizione dei frame sia impostata
        if not self._frame_capture_callback:
            self.error_message = "Nessuna callback per l'acquisizione dei frame impostata"
            logger.error(self.error_message)
            return False

        # Reset del flag di annullamento
        self._cancel_scan = False

        # Avvia il thread di scansione
        self._scan_thread = threading.Thread(
            target=self._scanning_thread,
            args=(pattern_type, num_patterns, exposure_time, quality)
        )
        self._scan_thread.daemon = True
        self._scan_thread.start()

        self.state = ScanningState.SCANNING
        logger.info(f"Scansione avviata con {num_patterns} pattern, tipo={pattern_type.name}")
        return True

    def cancel_scan(self):
        """Annulla una scansione in corso."""
        if self.state == ScanningState.SCANNING:
            self._cancel_scan = True
            logger.info("Richiesta di annullamento scansione ricevuta")

    def get_scan_progress(self) -> float:
        """
        Restituisce lo stato di avanzamento della scansione come percentuale.

        Returns:
            Percentuale di completamento (0-100)
        """
        if self.state != ScanningState.SCANNING or self.scan_stats['total_patterns'] == 0:
            return 0.0

        progress = (self.scan_stats['completed_patterns'] / self.scan_stats['total_patterns']) * 100.0
        return min(100.0, progress)

    def get_scan_status(self) -> Dict[str, Any]:
        """
        Restituisce informazioni sullo stato attuale della scansione.

        Returns:
            Dizionario con lo stato della scansione
        """
        elapsed_time = 0
        if self.scan_stats['start_time'] > 0:
            if self.scan_stats['end_time'] > 0:
                elapsed_time = self.scan_stats['end_time'] - self.scan_stats['start_time']
            else:
                elapsed_time = time.time() - self.scan_stats['start_time']

        return {
            'state': self.state.name,
            'progress': self.get_scan_progress(),
            'elapsed_time': elapsed_time,
            'completed_patterns': self.scan_stats['completed_patterns'],
            'total_patterns': self.scan_stats['total_patterns'],
            'captured_frames': self.scan_stats['captured_frames'],
            'errors': self.scan_stats['errors'],
            'error_message': self.error_message
        }

    def _scanning_thread(self,
                         pattern_type: ScanPatternType,
                         num_patterns: int,
                         exposure_time: float,
                         quality: int):
        """
        Thread principale per la scansione 3D.

        Args:
            pattern_type: Tipo di pattern da utilizzare
            num_patterns: Numero di pattern da proiettare
            exposure_time: Tempo di esposizione per ogni pattern (secondi)
            quality: Qualità della scansione (1-5)
        """
        try:
            # Inizializzazione
            self.state = ScanningState.INITIALIZING
            logger.info("Inizializzazione scansione...")

            # Imposta il proiettore in modalità pattern
            self._projector.set_operating_mode(OperatingMode.TestPatternGenerator)
            time.sleep(0.5)  # Attendi che il proiettore cambi modalità

            # Crea la lista per memorizzare i frame acquisiti
            self.frame_pairs = []

            # Seleziona il tipo di pattern da proiettare
            if pattern_type == ScanPatternType.PROGRESSIVE:
                success = self._project_progressive_patterns(num_patterns, exposure_time, quality)
            elif pattern_type == ScanPatternType.GRAY_CODE:
                success = self._project_gray_code_patterns(num_patterns, exposure_time, quality)
            elif pattern_type == ScanPatternType.BINARY_CODE:
                success = self._project_binary_code_patterns(num_patterns, exposure_time, quality)
            elif pattern_type == ScanPatternType.PHASE_SHIFT:
                success = self._project_phase_shift_patterns(num_patterns, exposure_time, quality)
            else:
                raise ValueError(f"Tipo di pattern non supportato: {pattern_type}")

            # Verifica il risultato della scansione
            if success and not self._cancel_scan:
                self.state = ScanningState.COMPLETED
                logger.info("Scansione completata con successo")
            elif self._cancel_scan:
                logger.info("Scansione annullata dall'utente")
                self.state = ScanningState.IDLE
            else:
                self.state = ScanningState.ERROR
                logger.error(f"Errore durante la scansione: {self.error_message}")

            # Torna alla modalità video
            self._projector.set_operating_mode(OperatingMode.ExternalVideoPort)

        except Exception as e:
            self.error_message = f"Errore nella scansione: {str(e)}"
            logger.error(self.error_message)
            self.state = ScanningState.ERROR
            self.scan_stats['errors'] += 1

            # Tenta di tornare alla modalità video
            try:
                self._projector.set_operating_mode(OperatingMode.ExternalVideoPort)
            except:
                pass

        finally:
            # Aggiorna il timestamp di fine
            self.scan_stats['end_time'] = time.time()

    def _project_progressive_patterns(self, num_patterns: int, exposure_time: float, quality: int) -> bool:
        """
        Proietta una sequenza di pattern con linee progressive (sempre più sottili).

        Args:
            num_patterns: Numero di pattern da proiettare per ogni direzione (orizzontale/verticale)
            exposure_time: Tempo di esposizione per ogni pattern (secondi)
            quality: Qualità della scansione (modifica alcuni parametri)

        Returns:
            True se la sequenza è stata completata, False altrimenti
        """
        try:
            # Adatta i parametri in base alla qualità
            pattern_pause = max(0.1, exposure_time * (1 + (quality - 3) * 0.2))

            # Calcola il numero totale di pattern
            total_patterns = num_patterns * 2 + 2  # Orizzontali + verticali + bianco + nero
            self.scan_stats['total_patterns'] = total_patterns

            # Pattern bianco di riferimento
            logger.info("Proiezione pattern bianco di riferimento...")
            self._projector.generate_solid_field(Color.White)
            time.sleep(0.2)  # Breve pausa per stabilizzazione del proiettore

            # Cattura il pattern bianco
            self.current_pattern_index = 0
            if not self._capture_and_save_frame(0, "white"):
                return False

            time.sleep(pattern_pause - 0.2)  # Completa il tempo di esposizione

            # Pattern nero di riferimento
            logger.info("Proiezione pattern nero di riferimento...")
            self._projector.generate_solid_field(Color.Black)
            time.sleep(0.2)  # Breve pausa per stabilizzazione del proiettore

            # Cattura il pattern nero
            self.current_pattern_index = 1
            if not self._capture_and_save_frame(1, "black"):
                return False

            time.sleep(pattern_pause - 0.2)  # Completa il tempo di esposizione

            # Sequenza di linee verticali (diventano sempre più sottili)
            logger.info("Inizio sequenza linee verticali...")

            for i in range(num_patterns):
                if self._cancel_scan:
                    return False

                # Calcola la larghezza delle linee per questo step
                # Inizia con linee larghe e dimezza ad ogni passo
                width = max(1, int(128 / (2 ** (i * quality / 3))))

                logger.info(f"Proiezione linee verticali, passo {i + 1}/{num_patterns}, larghezza={width}")

                self._projector.generate_vertical_lines(
                    background_color=Color.Black,
                    foreground_color=Color.White,
                    foreground_line_width=width,
                    background_line_width=width
                )

                # Breve pausa per stabilizzazione del proiettore
                time.sleep(0.2)

                # Cattura il frame
                self.current_pattern_index = 2 + i
                if not self._capture_and_save_frame(self.current_pattern_index, f"vertical_{i}"):
                    return False

                # Completa il tempo di esposizione
                time.sleep(pattern_pause - 0.2)

                # Aggiorna il contatore dei pattern completati
                self.scan_stats['completed_patterns'] += 1

            # Sequenza di linee orizzontali (diventano sempre più sottili)
            logger.info("Inizio sequenza linee orizzontali...")

            for i in range(num_patterns):
                if self._cancel_scan:
                    return False

                # Calcola la larghezza delle linee per questo step
                width = max(1, int(128 / (2 ** (i * quality / 3))))

                logger.info(f"Proiezione linee orizzontali, passo {i + 1}/{num_patterns}, larghezza={width}")

                self._projector.generate_horizontal_lines(
                    background_color=Color.Black,
                    foreground_color=Color.White,
                    foreground_line_width=width,
                    background_line_width=width
                )

                # Breve pausa per stabilizzazione del proiettore
                time.sleep(0.2)

                # Cattura il frame
                self.current_pattern_index = 2 + num_patterns + i
                if not self._capture_and_save_frame(self.current_pattern_index, f"horizontal_{i}"):
                    return False

                # Completa il tempo di esposizione
                time.sleep(pattern_pause - 0.2)

                # Aggiorna il contatore dei pattern completati
                self.scan_stats['completed_patterns'] += 1

            return True

        except Exception as e:
            self.error_message = f"Errore durante la proiezione dei pattern progressivi: {str(e)}"
            logger.error(self.error_message)
            return False

    def _project_gray_code_patterns(self, num_patterns: int, exposure_time: float, quality: int) -> bool:
        """
        Proietta una sequenza di pattern Gray code per codifica binaria di alta precisione.

        Args:
            num_patterns: Numero di bit per dimensione
            exposure_time: Tempo di esposizione per ogni pattern (secondi)
            quality: Qualità della scansione

        Returns:
            True se la sequenza è stata completata, False altrimenti
        """
        try:
            # Adatta i parametri in base alla qualità
            pattern_pause = max(0.1, exposure_time * (1 + (quality - 3) * 0.2))

            # Calcola il numero totale di pattern
            total_patterns = num_patterns * 2 + 2  # Orizzontali + verticali + bianco + nero
            self.scan_stats['total_patterns'] = total_patterns

            # Pattern bianco e nero di riferimento
            logger.info("Proiezione pattern bianco di riferimento...")
            self._projector.generate_solid_field(Color.White)
            time.sleep(0.2)
            self.current_pattern_index = 0
            if not self._capture_and_save_frame(0, "white"):
                return False
            time.sleep(pattern_pause - 0.2)

            logger.info("Proiezione pattern nero di riferimento...")
            self._projector.generate_solid_field(Color.Black)
            time.sleep(0.2)
            self.current_pattern_index = 1
            if not self._capture_and_save_frame(1, "black"):
                return False
            time.sleep(pattern_pause - 0.2)

            # Pattern Gray code verticali
            logger.info("Inizio sequenza Gray code verticale...")

            for i in range(num_patterns):
                if self._cancel_scan:
                    return False

                # Calcola la larghezza delle linee in base al bit corrente
                width = max(1, int(512 / (2 ** i)))

                logger.info(f"Proiezione Gray code verticale, bit {i + 1}/{num_patterns}, larghezza={width}")

                self._projector.generate_vertical_lines(
                    background_color=Color.Black,
                    foreground_color=Color.White,
                    foreground_line_width=width,
                    background_line_width=width
                )

                time.sleep(0.2)
                self.current_pattern_index = 2 + i
                if not self._capture_and_save_frame(self.current_pattern_index, f"gray_v_{i}"):
                    return False
                time.sleep(pattern_pause - 0.2)

                # Inverti lo schema (per robustezza del codice Gray)
                self._projector.generate_vertical_lines(
                    background_color=Color.White,
                    foreground_color=Color.Black,
                    foreground_line_width=width,
                    background_line_width=width
                )

                time.sleep(0.2)
                self.current_pattern_index = 2 + i + num_patterns
                if not self._capture_and_save_frame(self.current_pattern_index, f"gray_v_inv_{i}"):
                    return False
                time.sleep(pattern_pause - 0.2)

                # Aggiorna il contatore dei pattern completati
                self.scan_stats['completed_patterns'] += 2

            # Pattern Gray code orizzontali
            logger.info("Inizio sequenza Gray code orizzontale...")

            for i in range(num_patterns):
                if self._cancel_scan:
                    return False

                # Calcola la larghezza delle linee in base al bit corrente
                width = max(1, int(512 / (2 ** i)))

                logger.info(f"Proiezione Gray code orizzontale, bit {i + 1}/{num_patterns}, larghezza={width}")

                self._projector.generate_horizontal_lines(
                    background_color=Color.Black,
                    foreground_color=Color.White,
                    foreground_line_width=width,
                    background_line_width=width
                )

                time.sleep(0.2)
                self.current_pattern_index = 2 + 2 * num_patterns + i
                if not self._capture_and_save_frame(self.current_pattern_index, f"gray_h_{i}"):
                    return False
                time.sleep(pattern_pause - 0.2)

                # Inverti lo schema (per robustezza del codice Gray)
                self._projector.generate_horizontal_lines(
                    background_color=Color.White,
                    foreground_color=Color.Black,
                    foreground_line_width=width,
                    background_line_width=width
                )

                time.sleep(0.2)
                self.current_pattern_index = 2 + 2 * num_patterns + i + num_patterns
                if not self._capture_and_save_frame(self.current_pattern_index, f"gray_h_inv_{i}"):
                    return False
                time.sleep(pattern_pause - 0.2)

                # Aggiorna il contatore dei pattern completati
                self.scan_stats['completed_patterns'] += 2

            return True

        except Exception as e:
            self.error_message = f"Errore durante la proiezione dei pattern Gray code: {str(e)}"
            logger.error(self.error_message)
            return False

    def _project_binary_code_patterns(self, num_patterns: int, exposure_time: float, quality: int) -> bool:
        """
        Proietta una sequenza di pattern con codifica binaria standard.
        Implementazione semplificata rispetto al Gray code.

        Args:
            num_patterns: Numero di bit per dimensione
            exposure_time: Tempo di esposizione per ogni pattern (secondi)
            quality: Qualità della scansione

        Returns:
            True se la sequenza è stata completata, False altrimenti
        """
        # Implementazione molto simile al Gray code, ma senza sequenze invertite
        try:
            # Adatta i parametri in base alla qualità
            pattern_pause = max(0.1, exposure_time * (1 + (quality - 3) * 0.2))

            # Calcola il numero totale di pattern
            total_patterns = num_patterns * 2 + 2  # Orizzontali + verticali + bianco + nero
            self.scan_stats['total_patterns'] = total_patterns

            # Pattern bianco e nero di riferimento
            logger.info("Proiezione pattern bianco di riferimento...")
            self._projector.generate_solid_field(Color.White)
            time.sleep(0.2)
            self.current_pattern_index = 0
            if not self._capture_and_save_frame(0, "white"):
                return False
            time.sleep(pattern_pause - 0.2)

            logger.info("Proiezione pattern nero di riferimento...")
            self._projector.generate_solid_field(Color.Black)
            time.sleep(0.2)
            self.current_pattern_index = 1
            if not self._capture_and_save_frame(1, "black"):
                return False
            time.sleep(pattern_pause - 0.2)

            # Pattern binari verticali
            logger.info("Inizio sequenza binaria verticale...")

            for i in range(num_patterns):
                if self._cancel_scan:
                    return False

                # Calcola la larghezza delle linee in base al bit corrente
                width = max(1, int(512 / (2 ** i)))

                logger.info(f"Proiezione binaria verticale, bit {i + 1}/{num_patterns}, larghezza={width}")

                self._projector.generate_vertical_lines(
                    background_color=Color.Black,
                    foreground_color=Color.White,
                    foreground_line_width=width,
                    background_line_width=width
                )

                time.sleep(0.2)
                self.current_pattern_index = 2 + i
                if not self._capture_and_save_frame(self.current_pattern_index, f"binary_v_{i}"):
                    return False
                time.sleep(pattern_pause - 0.2)

                # Aggiorna il contatore dei pattern completati
                self.scan_stats['completed_patterns'] += 1

            # Pattern binari orizzontali
            logger.info("Inizio sequenza binaria orizzontale...")

            for i in range(num_patterns):
                if self._cancel_scan:
                    return False

                # Calcola la larghezza delle linee in base al bit corrente
                width = max(1, int(512 / (2 ** i)))

                logger.info(f"Proiezione binaria orizzontale, bit {i + 1}/{num_patterns}, larghezza={width}")

                self._projector.generate_horizontal_lines(
                    background_color=Color.Black,
                    foreground_color=Color.White,
                    foreground_line_width=width,
                    background_line_width=width
                )

                time.sleep(0.2)
                self.current_pattern_index = 2 + num_patterns + i
                if not self._capture_and_save_frame(self.current_pattern_index, f"binary_h_{i}"):
                    return False
                time.sleep(pattern_pause - 0.2)

                # Aggiorna il contatore dei pattern completati
                self.scan_stats['completed_patterns'] += 1

            return True

        except Exception as e:
            self.error_message = f"Errore durante la proiezione dei pattern binari: {str(e)}"
            logger.error(self.error_message)
            return False

    def _project_phase_shift_patterns(self, num_patterns: int, exposure_time: float, quality: int) -> bool:
        """
        Proietta una sequenza di pattern a spostamento di fase (sinusoidali).
        Nota: Questa funzione è uno stub e non è supportata dall'hardware attuale.

        Args:
            num_patterns: Numero di pattern da proiettare
            exposure_time: Tempo di esposizione per ogni pattern (secondi)
            quality: Qualità della scansione

        Returns:
            False (non supportato dall'hardware attuale)
        """
        # Questo metodo è solo uno stub per completezza, ma non è supportato dal controller DLPC342X attuale
        self.error_message = "Pattern a spostamento di fase non supportati dal proiettore DLP"
        logger.error(self.error_message)
        return False

    def _capture_and_save_frame(self, pattern_index: int, pattern_name: str) -> bool:
        """
        Acquisisce e salva i frame dalle due camere per il pattern corrente.
        Versione ottimizzata che gestisce meglio l'invio dei frame al client,
        la compressione e la gestione degli errori.

        Args:
            pattern_index: Indice del pattern corrente
            pattern_name: Nome descrittivo del pattern

        Returns:
            True se l'acquisizione è riuscita, False altrimenti
        """
        start_time = time.time()

        try:
            # Verifica che la callback sia impostata
            if not self._frame_capture_callback:
                self.error_message = "Nessuna callback per l'acquisizione dei frame impostata"
                logger.error(self.error_message)
                return False

            # Acquisisce i frame dalle camere attraverso la callback
            frames = self._frame_capture_callback(pattern_index)

            # Verifica che i frame siano validi
            if not frames or len(frames) != 2:
                self.error_message = f"Acquisizione frame non valida per pattern {pattern_name}"
                logger.error(self.error_message)
                return False

            frame_left, frame_right = frames

            # Verifica che i frame non siano vuoti
            if frame_left is None or frame_right is None:
                self.error_message = f"Frame vuoti per pattern {pattern_name}"
                logger.error(self.error_message)
                return False

            # Salva i frame localmente
            try:
                left_file = self.left_dir / f"{pattern_index:04d}_{pattern_name}.png"
                right_file = self.right_dir / f"{pattern_index:04d}_{pattern_name}.png"

                save_success = True
                try:
                    cv2.imwrite(str(left_file), frame_left)
                except Exception as e:
                    logger.error(f"Errore nel salvataggio del frame sinistro: {e}")
                    save_success = False

                try:
                    cv2.imwrite(str(right_file), frame_right)
                except Exception as e:
                    logger.error(f"Errore nel salvataggio del frame destro: {e}")
                    save_success = False

                if not save_success:
                    logger.warning(f"Problemi nel salvataggio di uno o entrambi i frame per pattern {pattern_name}")
            except Exception as save_err:
                logger.error(f"Errore critico nel salvataggio dei frame: {save_err}")
                # Continuiamo comunque per tentare l'invio al client

            # Salva i frame anche nella lista per eventuale elaborazione successiva
            self.frame_pairs.append((frame_left, frame_right))

            # Invia i frame al client in tempo reale se possibile
            try:
                # Codifica i frame in formato JPEG per una trasmissione più efficiente
                encode_params = [cv2.IMWRITE_JPEG_QUALITY, 90]
                _, left_encoded = cv2.imencode('.jpg', frame_left, encode_params)
                _, right_encoded = cv2.imencode('.jpg', frame_right, encode_params)

                # Informazioni sul frame per il client
                frame_info = {
                    "pattern_index": pattern_index,
                    "pattern_name": pattern_name,
                    "timestamp": time.time()
                }

                # Notifica il client attraverso il server
                # Se abbiamo un riferimento al ScanManager
                if hasattr(self, '_parent_scan_manager') and self._parent_scan_manager:
                    if hasattr(self._parent_scan_manager, 'notify_client_new_frames'):
                        self._parent_scan_manager.notify_client_new_frames(
                            frame_info,
                            left_encoded.tobytes(),
                            right_encoded.tobytes()
                        )
                        logger.info(f"Frame {pattern_index} inviato al client via parent_scan_manager")

                # Se abbiamo un riferimento diretto al server
                elif hasattr(self, '_server') and self._server:
                    if hasattr(self._server, 'scan_manager') and self._server.scan_manager:
                        if hasattr(self._server.scan_manager, 'notify_client_new_frames'):
                            self._server.scan_manager.notify_client_new_frames(
                                frame_info,
                                left_encoded.tobytes(),
                                right_encoded.tobytes()
                            )
                            logger.info(f"Frame {pattern_index} inviato al client via server.scan_manager")
                else:
                    logger.warning("Nessun riferimento al server o scan_manager disponibile")

            except Exception as e:
                logger.warning(f"Impossibile inviare i frame al client: {e}")
                import traceback
                logger.warning(f"Traceback: {traceback.format_exc()}")
                # Non fallire se l'invio al client non riesce

            # Aggiorna le statistiche
            self.scan_stats['captured_frames'] += 2

            # Calcola il tempo totale di acquisizione per debugging
            elapsed_ms = (time.time() - start_time) * 1000
            logger.debug(f"Frame acquisiti per pattern {pattern_name} (indice {pattern_index}) in {elapsed_ms:.1f}ms")

            return True

        except Exception as e:
            self.error_message = f"Errore nell'acquisizione dei frame per pattern {pattern_name}: {str(e)}"
            logger.error(self.error_message)
            self.scan_stats['errors'] += 1

            import traceback
            logger.debug(f"Traceback completo: {traceback.format_exc()}")

            return False
    def process_scan_data(self, output_file: str = None) -> bool:
        """
        Elabora i dati acquisiti durante la scansione per generare la nuvola di punti.
        Nota: Questa è una funzione stub che dovrà essere implementata in base al codice
        di triangolazione disponibile.

        Args:
            output_file: File di output per la nuvola di punti (.ply)

        Returns:
            True se l'elaborazione è riuscita, False altrimenti
        """
        if self.state != ScanningState.COMPLETED:
            logger.warning("Impossibile elaborare i dati: la scansione non è stata completata")
            return False

        # Qui dovrà essere implementata la logica per elaborare i dati e generare la nuvola di punti
        # Questa logica dovrà essere basata sul codice di triangolazione disponibile nella repository
        # Structured-light-stereo

        logger.info("Elaborazione dei dati della scansione non ancora implementata")
        return False


# Test standalone
if __name__ == "__main__":
    # Configura logging
    logging.basicConfig(level=logging.INFO)

    # Crea il controller
    controller = StructuredLightController()

    # Inizializza il proiettore
    if controller.initialize_projector():
        print("Proiettore inizializzato correttamente")


        # Esempio di callback per simulare l'acquisizione dei frame
        def capture_frames(pattern_index):
            # Crea frame simulati (640x480 grigio)
            frame_left = np.zeros((480, 640), dtype=np.uint8) + 128
            frame_right = np.zeros((480, 640), dtype=np.uint8) + 128
            print(f"Simulazione acquisizione frame per pattern {pattern_index}")
            return (frame_left, frame_right)


        # Imposta la callback
        controller.set_frame_capture_callback(capture_frames)

        # Avvia una scansione di test
        controller.start_scan(
            pattern_type=ScanPatternType.PROGRESSIVE,
            num_patterns=4,
            exposure_time=0.5,
            quality=1
        )

        # Attendi il completamento della scansione
        while controller.state == ScanningState.SCANNING:
            progress = controller.get_scan_progress()
            print(f"Progresso: {progress:.1f}%")
            time.sleep(1.0)

        # Stampa lo stato finale
        print(f"Stato finale: {controller.state.name}")
        if controller.state == ScanningState.ERROR:
            print(f"Errore: {controller.error_message}")

        # Chiudi il controller
        controller.close()
    else:
        print(f"Errore nell'inizializzazione del proiettore: {controller.error_message}")