#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Widget per la visualizzazione dello streaming video dual-camera degli scanner UnLook.
"""

import logging
import cv2
import numpy as np
import time
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple, Dict, List

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QFormLayout, QComboBox, QSlider, QCheckBox,
    QSpinBox, QDoubleSpinBox, QFrame, QSplitter, QFileDialog,
    QMessageBox
)
from PySide6.QtCore import Qt, Signal, Slot, QTimer, QThread, QMutex, QMutexLocker
from PySide6.QtGui import QImage, QPixmap, QPainter, QColor, QPen

from models.scanner_model import Scanner, ScannerStatus
from utils.thread_safe_queue import ThreadSafeQueue

logger = logging.getLogger(__name__)


class FrameProcessor(QThread):
    """
    Thread dedicato all'elaborazione dei frame ricevuti dallo scanner.
    """
    new_frame_ready = Signal(int, QImage)  # camera_index, qimage

    def __init__(self, frame_queue):
        super().__init__()
        self._frame_queue = frame_queue
        self._running = False
        self._mutex = QMutex()

        # Opzioni di visualizzazione
        self._show_grid = False
        self._show_features = False
        self._enhance_contrast = False

    def run(self):
        """Esegue il loop principale di elaborazione dei frame."""
        self._running = True
        logger.info("Frame processor avviato")

        while self._running:
            # Attendi un nuovo frame dalla coda
            camera_index, frame = self._frame_queue.get(block=True, timeout=0.1)

            # Se la coda è vuota, continua
            if frame is None:
                continue

            # Elabora il frame
            processed_frame = self._process_frame(frame)

            # Converti in QImage
            height, width = processed_frame.shape[:2]
            bytes_per_line = 3 * width

            # OpenCV usa BGR, Qt usa RGB
            if len(processed_frame.shape) == 3 and processed_frame.shape[2] == 3:
                # Immagine a colori
                rgb_image = cv2.cvtColor(processed_frame, cv2.COLOR_BGR2RGB)
                qimage = QImage(rgb_image.data, width, height, bytes_per_line, QImage.Format_RGB888)
            else:
                # Immagine in scala di grigi
                qimage = QImage(processed_frame.data, width, height, width, QImage.Format_Grayscale8)

            # Emetti il segnale con il frame elaborato
            self.new_frame_ready.emit(camera_index, qimage)

    def _process_frame(self, frame):
        """
        Elabora un frame applicando le opzioni di visualizzazione.

        Args:
            frame: Frame OpenCV da elaborare

        Returns:
            Frame elaborato
        """
        with QMutexLocker(self._mutex):
            # Crea una copia del frame per l'elaborazione
            processed = frame.copy()

            # Converti in scala di grigi se necessario
            if len(processed.shape) == 3 and processed.shape[2] == 3:
                gray = cv2.cvtColor(processed, cv2.COLOR_BGR2GRAY)
            else:
                gray = processed

            # Applica miglioramento del contrasto se abilitato
            if self._enhance_contrast:
                # Equalizzazione dell'istogramma adattiva (CLAHE)
                clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
                enhanced = clahe.apply(gray)

                # Se il frame originale era a colori, applica il miglioramento solo alla luminosità
                if len(processed.shape) == 3 and processed.shape[2] == 3:
                    # Converti in HSV
                    hsv = cv2.cvtColor(processed, cv2.COLOR_BGR2HSV)
                    # Sostituisci il canale V (luminosità)
                    hsv[:, :, 2] = enhanced
                    # Torna in BGR
                    processed = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
                else:
                    processed = enhanced

            # Applica una griglia se abilitata
            if self._show_grid:
                height, width = processed.shape[:2]
                grid_size = 50  # Dimensione delle celle della griglia

                # Disegna linee orizzontali
                for y in range(0, height, grid_size):
                    if len(processed.shape) == 3:
                        cv2.line(processed, (0, y), (width, y), (0, 255, 0), 1)
                    else:
                        cv2.line(processed, (0, y), (width, y), 200, 1)

                # Disegna linee verticali
                for x in range(0, width, grid_size):
                    if len(processed.shape) == 3:
                        cv2.line(processed, (x, 0), (x, height), (0, 255, 0), 1)
                    else:
                        cv2.line(processed, (x, 0), (x, height), 200, 1)

            # Rileva e disegna caratteristiche se abilitato
            if self._show_features:
                # Crea un rilevatore di feature
                feature_detector = cv2.FastFeatureDetector_create(threshold=25)

                # Rileva keypoints
                keypoints = feature_detector.detect(gray, None)

                # Disegna keypoints sul frame
                if len(processed.shape) == 3:
                    processed = cv2.drawKeypoints(
                        processed, keypoints, None, (0, 0, 255),
                        cv2.DRAW_MATCHES_FLAGS_DRAW_RICH_KEYPOINTS
                    )
                else:
                    processed = cv2.drawKeypoints(
                        cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR), keypoints, None,
                        (0, 0, 255), cv2.DRAW_MATCHES_FLAGS_DRAW_RICH_KEYPOINTS
                    )

            return processed

    def set_options(self, show_grid: bool, show_features: bool, enhance_contrast: bool):
        """Imposta le opzioni di visualizzazione."""
        with QMutexLocker(self._mutex):
            self._show_grid = show_grid
            self._show_features = show_features
            self._enhance_contrast = enhance_contrast

    def stop(self):
        """Ferma il thread di elaborazione."""
        self._running = False
        # Attendi la terminazione
        self.wait(1000)
        logger.info("Frame processor fermato")


class StreamView(QWidget):
    """
    Widget che visualizza lo stream di una singola camera.
    """

    def __init__(self, camera_index: int, parent=None):
        super().__init__(parent)
        self.camera_index = camera_index
        self._frame = None
        self._last_frame_time = 0
        self._fps = 0

        # Configura l'interfaccia utente
        self._setup_ui()

    def _setup_ui(self):
        """Configura l'interfaccia utente."""
        # Layout principale
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Etichetta per il display
        self.display_label = QLabel()
        self.display_label.setAlignment(Qt.AlignCenter)
        self.display_label.setMinimumSize(320, 240)
        self.display_label.setStyleSheet("background-color: black;")
        layout.addWidget(self.display_label)

        # Etichetta per FPS e informazioni
        self.info_label = QLabel("Camera non attiva")
        self.info_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.info_label)

    @Slot(QImage)
    def update_frame(self, frame: QImage):
        """Aggiorna il frame visualizzato."""
        if not frame:
            return

        # Calcola FPS
        current_time = time.time()
        if self._last_frame_time > 0:
            time_diff = current_time - self._last_frame_time
            if time_diff > 0:
                instantaneous_fps = 1.0 / time_diff
                # Media mobile per stabilizzare il valore di FPS
                alpha = 0.1  # Fattore di smoothing
                self._fps = (1.0 - alpha) * self._fps + alpha * instantaneous_fps

        self._last_frame_time = current_time

        # Salva una copia del frame
        self._frame = frame.copy()

        # Adatta il frame alle dimensioni del display
        pixmap = QPixmap.fromImage(frame)
        scaled_pixmap = pixmap.scaled(
            self.display_label.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )

        # Aggiorna il display
        self.display_label.setPixmap(scaled_pixmap)

        # Aggiorna l'etichetta informativa
        camera_name = "Sinistra" if self.camera_index == 0 else "Destra"
        size_text = f"{frame.width()}x{frame.height()}"
        fps_text = f"{self._fps:.1f} FPS" if self._fps > 0 else ""

        self.info_label.setText(f"Camera {camera_name} | {size_text} | {fps_text}")

    def clear(self):
        """Pulisce il display."""
        self.display_label.clear()
        self.display_label.setStyleSheet("background-color: black;")
        self.info_label.setText("Camera non attiva")
        self._frame = None
        self._last_frame_time = 0
        self._fps = 0

    def get_current_frame(self) -> Optional[QImage]:
        """Restituisce il frame corrente."""
        return self._frame

    def resizeEvent(self, event):
        """Gestisce il ridimensionamento del widget."""
        super().resizeEvent(event)

        # Riscala il frame se presente
        if self._frame and not self.display_label.pixmap().isNull():
            pixmap = QPixmap.fromImage(self._frame)
            scaled_pixmap = pixmap.scaled(
                self.display_label.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            self.display_label.setPixmap(scaled_pixmap)


class DualStreamView(QWidget):
    """
    Widget che visualizza lo streaming simultaneo delle due camere dello scanner.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scanner: Optional[Scanner] = None
        self._streaming = False

        # Code per i frame
        self._frame_queues = [ThreadSafeQueue(), ThreadSafeQueue()]

        # Processori di frame
        self._frame_processors = [
            FrameProcessor(self._frame_queues[0]),
            FrameProcessor(self._frame_queues[1])
        ]

        # Configura l'interfaccia utente
        self._setup_ui()

        # Collega i segnali
        self._connect_signals()

    def _setup_ui(self):
        """Configura l'interfaccia utente."""
        # Layout principale
        main_layout = QVBoxLayout(self)

        # Contenitore per gli stream
        streams_container = QWidget()
        streams_layout = QHBoxLayout(streams_container)

        # Splitter per dividere gli stream
        splitter = QSplitter(Qt.Horizontal)

        # Crea i widget di visualizzazione
        self.stream_views = [
            StreamView(0),  # Camera sinistra
            StreamView(1)  # Camera destra
        ]

        # Aggiungi i widget allo splitter
        for view in self.stream_views:
            splitter.addWidget(view)

        # Imposta dimensioni iniziali uguali
        splitter.setSizes([self.width() // 2, self.width() // 2])

        streams_layout.addWidget(splitter)
        main_layout.addWidget(streams_container)

        # Pannello di controllo
        control_panel = QGroupBox("Controlli di visualizzazione")
        control_layout = QVBoxLayout(control_panel)

        # Opzioni di visualizzazione
        view_options_layout = QHBoxLayout()

        self.grid_checkbox = QCheckBox("Mostra griglia")
        self.features_checkbox = QCheckBox("Mostra caratteristiche")
        self.enhance_checkbox = QCheckBox("Migliora contrasto")

        view_options_layout.addWidget(self.grid_checkbox)
        view_options_layout.addWidget(self.features_checkbox)
        view_options_layout.addWidget(self.enhance_checkbox)
        view_options_layout.addStretch(1)

        # Pulsante per l'acquisizione di frame
        self.capture_button = QPushButton("Acquisisci frame")
        self.capture_button.setEnabled(False)
        self.capture_button.clicked.connect(self.capture_frame)
        view_options_layout.addWidget(self.capture_button)

        control_layout.addLayout(view_options_layout)

        # Aggiungi il pannello di controllo al layout principale
        main_layout.addWidget(control_panel)

        # Configura i segnali delle opzioni di visualizzazione
        self.grid_checkbox.toggled.connect(self._update_visualization_options)
        self.features_checkbox.toggled.connect(self._update_visualization_options)
        self.enhance_checkbox.toggled.connect(self._update_visualization_options)

    def _connect_signals(self):
        """Collega i segnali dei processori di frame."""
        for i, processor in enumerate(self._frame_processors):
            processor.new_frame_ready.connect(self._on_new_frame)

    def start_streaming(self, scanner: Scanner) -> bool:
        """
        Avvia lo streaming video dalle due camere dello scanner.

        Args:
            scanner: Scanner da cui ricevere lo streaming

        Returns:
            True se lo streaming è stato avviato, False altrimenti
        """
        if self._streaming:
            logger.warning("Streaming già attivo")
            return True

        # Memorizza lo scanner
        self._scanner = scanner

        # TODO: Avvia lo streaming effettivo dalle camere
        # Per ora, simuliamo lo streaming con immagini di test

        # Cambia lo stato dello scanner
        scanner.status = ScannerStatus.STREAMING

        # Avvia i processori di frame
        for processor in self._frame_processors:
            processor.start()

        # Imposta lo stato di streaming
        self._streaming = True
        logger.info(f"Streaming avviato da {scanner.name}")

        # Abilita il pulsante di acquisizione
        self.capture_button.setEnabled(True)

        # Crea immagini di test per simulare lo streaming
        self._simulate_streaming()

        return True

    def stop_streaming(self):
        """Ferma lo streaming video."""
        if not self._streaming:
            return

        # Ferma i processori di frame
        for processor in self._frame_processors:
            processor.stop()

        # Pulisci le viste
        for view in self.stream_views:
            view.clear()

        # Reimposta lo stato dello scanner se presente
        if self._scanner and self._scanner.status == ScannerStatus.STREAMING:
            self._scanner.status = ScannerStatus.CONNECTED

        # Reimposta lo stato di streaming
        self._streaming = False
        logger.info("Streaming fermato")

        # Disabilita il pulsante di acquisizione
        self.capture_button.setEnabled(False)

    def is_streaming(self) -> bool:
        """Verifica se lo streaming è attivo."""
        return self._streaming

    @Slot(int, QImage)
    def _on_new_frame(self, camera_index: int, frame: QImage):
        """Gestisce l'arrivo di un nuovo frame."""
        # Aggiorna la vista corrispondente
        if 0 <= camera_index < len(self.stream_views):
            self.stream_views[camera_index].update_frame(frame)

    @Slot()
    def _update_visualization_options(self):
        """Aggiorna le opzioni di visualizzazione dei processori di frame."""
        show_grid = self.grid_checkbox.isChecked()
        show_features = self.features_checkbox.isChecked()
        enhance_contrast = self.enhance_checkbox.isChecked()

        for processor in self._frame_processors:
            processor.set_options(show_grid, show_features, enhance_contrast)

    def _simulate_streaming(self):
        """
        Crea immagini di test per simulare lo streaming.
        Questo metodo è solo per sviluppo/test e verrà sostituito con il
        vero streaming dalle camere.
        """

        def create_test_frames():
            # Crea immagini di test
            for i in range(30):  # Simula 30 frame
                # Crea un'immagine di test per la camera sinistra
                left_frame = np.zeros((480, 640, 3), dtype=np.uint8)
                cv2.putText(
                    left_frame, f"Camera Sinistra - Frame {i + 1}",
                    (50, 240), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2
                )
                cv2.circle(left_frame, (320, 240), 50 + i * 2, (0, 0, 255), 2)

                # Crea un'immagine di test per la camera destra
                right_frame = np.zeros((480, 640, 3), dtype=np.uint8)
                cv2.putText(
                    right_frame, f"Camera Destra - Frame {i + 1}",
                    (50, 240), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2
                )
                cv2.rectangle(
                    right_frame,
                    (320 - i * 5, 240 - i * 3),
                    (320 + i * 5, 240 + i * 3),
                    (255, 0, 0), 2
                )

                # Aggiungi le immagini alle code
                self._frame_queues[0].put((0, left_frame))
                self._frame_queues[1].put((1, right_frame))

                # Pausa tra i frame
                time.sleep(0.1)

            # Loop infinito
            while self._streaming:
                # Crea immagini casuali
                left_frame = np.random.randint(0, 256, (480, 640, 3), dtype=np.uint8)
                cv2.putText(
                    left_frame, "Camera Sinistra - Live",
                    (50, 240), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2
                )

                right_frame = np.random.randint(0, 256, (480, 640, 3), dtype=np.uint8)
                cv2.putText(
                    right_frame, "Camera Destra - Live",
                    (50, 240), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2
                )

                # Aggiungi le immagini alle code
                self._frame_queues[0].put((0, left_frame))
                self._frame_queues[1].put((1, right_frame))

                # Pausa tra i frame
                time.sleep(0.1)

        # Avvia un thread per simulare lo streaming
        import threading
        thread = threading.Thread(target=create_test_frames)
        thread.daemon = True
        thread.start()

    def capture_frame(self) -> bool:
        """
        Acquisisce i frame correnti dalle due camere.

        Returns:
            True se l'acquisizione è riuscita, False altrimenti
        """
        if not self._streaming:
            logger.warning("Impossibile acquisire i frame: streaming non attivo")
            return False

        # Ottieni i frame correnti
        frames = []
        for i, view in enumerate(self.stream_views):
            frame = view.get_current_frame()
            if frame:
                frames.append((i, frame))

        if not frames:
            logger.warning("Nessun frame disponibile per l'acquisizione")
            return False

        # Crea la directory per i frame acquisiti
        save_dir = Path.home() / "UnLook" / "captures"
        save_dir.mkdir(parents=True, exist_ok=True)

        # Timestamp per il nome del file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Salva i frame
        for i, frame in frames:
            camera_name = "left" if i == 0 else "right"
            file_path = save_dir / f"unlook_{timestamp}_{camera_name}.png"

            # Salva l'immagine
            frame.save(str(file_path), "PNG")
            logger.info(f"Frame acquisito: {file_path}")

        # Chiedi all'utente se vuole aprire la directory
        response = QMessageBox.question(
            self,
            "Frame acquisiti",
            f"Frame acquisiti in:\n{save_dir}\n\nVuoi aprire la directory?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if response == QMessageBox.Yes:
            # Apri la directory (in modo multipiattaforma)
            import os
            import subprocess
            import platform

            if platform.system() == "Windows":
                os.startfile(str(save_dir))
            elif platform.system() == "Darwin":  # macOS
                subprocess.call(["open", str(save_dir)])
            else:  # Linux
                subprocess.call(["xdg-open", str(save_dir)])

        return True