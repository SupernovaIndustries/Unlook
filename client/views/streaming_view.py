#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Widget per la visualizzazione dello streaming video dual-camera degli scanner UnLook.
Versione migliorata con configurazioni integrate e gestione delle connessioni più robusta.
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
    QMessageBox, QTabWidget, QRadioButton, QButtonGroup, QLineEdit
)
from PySide6.QtCore import Qt, Signal, Slot, QTimer, QThread, QMutex, QMutexLocker
from PySide6.QtGui import QImage, QPixmap, QPainter, QColor, QPen, QFont

from client.models.scanner_model import Scanner, ScannerStatus
from client.utils.thread_safe_queue import ThreadSafeQueue

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
            try:
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
            except Exception as e:
                if self._running:  # Solo se il thread è ancora attivo
                    logger.error(f"Errore nel frame processor: {str(e)}")
                    time.sleep(0.1)  # Evita di sovraccaricare il sistema in caso di errori ripetuti

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
        self._stream_receiver = None
        self._connection_manager = None  # Memorizza il riferimento al connection manager
        self._retry_timer = QTimer()
        self._retry_timer.setInterval(1000)  # 1 secondo
        self._retry_timer.timeout.connect(self._check_connection)
        self._retry_count = 0
        self._max_retries = 5

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
        control_panel = QTabWidget()

        # Tab per i controlli di visualizzazione e fotocamera
        camera_controls = QWidget()
        camera_layout = QVBoxLayout(camera_controls)

        # Opzioni di visualizzazione
        view_options_group = QGroupBox("Opzioni di visualizzazione")
        view_options_layout = QVBoxLayout(view_options_group)

        # Checkboxes per le opzioni di visualizzazione
        options_layout = QHBoxLayout()
        self.grid_checkbox = QCheckBox("Mostra griglia")
        self.features_checkbox = QCheckBox("Mostra caratteristiche")
        self.enhance_checkbox = QCheckBox("Migliora contrasto")

        options_layout.addWidget(self.grid_checkbox)
        options_layout.addWidget(self.features_checkbox)
        options_layout.addWidget(self.enhance_checkbox)
        options_layout.addStretch(1)

        view_options_layout.addLayout(options_layout)
        camera_layout.addWidget(view_options_group)

        # Gruppo dei parametri del sensore
        sensor_group = QGroupBox("Parametri fotocamera")
        sensor_layout = QFormLayout(sensor_group)

        # Layout esposizione camera sinistra
        left_exposure_layout = QHBoxLayout()
        self.left_exposure_slider = QSlider(Qt.Horizontal)
        self.left_exposure_slider.setRange(0, 100)
        self.left_exposure_slider.setValue(50)
        self.left_exposure_value = QLabel("50")
        self.left_exposure_slider.valueChanged.connect(lambda v: self.left_exposure_value.setText(str(v)))
        left_exposure_layout.addWidget(self.left_exposure_slider)
        left_exposure_layout.addWidget(self.left_exposure_value)
        sensor_layout.addRow("Esposizione Camera SX:", left_exposure_layout)

        # Layout esposizione camera destra
        right_exposure_layout = QHBoxLayout()
        self.right_exposure_slider = QSlider(Qt.Horizontal)
        self.right_exposure_slider.setRange(0, 100)
        self.right_exposure_slider.setValue(50)
        self.right_exposure_value = QLabel("50")
        self.right_exposure_slider.valueChanged.connect(lambda v: self.right_exposure_value.setText(str(v)))
        right_exposure_layout.addWidget(self.right_exposure_slider)
        right_exposure_layout.addWidget(self.right_exposure_value)
        sensor_layout.addRow("Esposizione Camera DX:", right_exposure_layout)

        # Pulsante per applicare le impostazioni
        self.apply_settings_button = QPushButton("Applica impostazioni")
        self.apply_settings_button.setEnabled(False)
        self.apply_settings_button.clicked.connect(self._apply_camera_settings)
        sensor_layout.addRow("", self.apply_settings_button)

        camera_layout.addWidget(sensor_group)

        # Pulsante per la cattura
        capture_layout = QHBoxLayout()
        self.capture_button = QPushButton("Acquisisci Frame")
        self.capture_button.setEnabled(False)
        self.capture_button.clicked.connect(self.capture_frame)
        capture_layout.addStretch(1)
        capture_layout.addWidget(self.capture_button)
        camera_layout.addLayout(capture_layout)

        # Tab per i controlli di scansione
        scan_controls = QWidget()
        scan_layout = QVBoxLayout(scan_controls)

        # Gruppo di controlli per la scansione
        scan_group = QGroupBox("Parametri di Scansione")
        scan_form = QFormLayout(scan_group)

        # Nome scansione
        self.scan_name_edit = QLineEdit("Nuova scansione")
        scan_form.addRow("Nome scansione:", self.scan_name_edit)

        # Tipo di scansione
        scan_type_layout = QHBoxLayout()
        self.scan_type_group = QButtonGroup(self)
        self.scan_type_structured = QRadioButton("Luce strutturata")
        self.scan_type_tof = QRadioButton("Time-of-Flight")
        self.scan_type_structured.setChecked(True)
        self.scan_type_group.addButton(self.scan_type_structured)
        self.scan_type_group.addButton(self.scan_type_tof)
        scan_type_layout.addWidget(self.scan_type_structured)
        scan_type_layout.addWidget(self.scan_type_tof)
        scan_form.addRow("Tipo di scansione:", scan_type_layout)

        # Risoluzione
        self.resolution_combo = QComboBox()
        self.resolution_combo.addItem("Bassa (1mm)", 1.0)
        self.resolution_combo.addItem("Media (0.5mm)", 0.5)
        self.resolution_combo.addItem("Alta (0.2mm)", 0.2)
        scan_form.addRow("Risoluzione:", self.resolution_combo)

        # Qualità
        quality_layout = QHBoxLayout()
        self.quality_slider = QSlider(Qt.Horizontal)
        self.quality_slider.setRange(1, 5)
        self.quality_slider.setValue(3)
        self.quality_slider.setTickPosition(QSlider.TicksBelow)
        self.quality_slider.setTickInterval(1)

        self.quality_label = QLabel("3")
        self.quality_slider.valueChanged.connect(lambda v: self.quality_label.setText(str(v)))

        quality_layout.addWidget(self.quality_slider)
        quality_layout.addWidget(self.quality_label)
        scan_form.addRow("Qualità:", quality_layout)

        # Acquisizione colore
        self.color_checkbox = QCheckBox()
        scan_form.addRow("Acquisizione colore:", self.color_checkbox)

        scan_layout.addWidget(scan_group)

        # Pulsanti di azione per la scansione
        scan_buttons_layout = QHBoxLayout()

        self.start_scan_button = QPushButton("Avvia Scansione")
        self.start_scan_button.setEnabled(False)
        self.start_scan_button.clicked.connect(self._on_start_scan_clicked)

        self.save_scan_button = QPushButton("Salva Scansione")
        self.save_scan_button.setEnabled(False)
        self.save_scan_button.clicked.connect(self._on_save_scan_clicked)

        scan_buttons_layout.addWidget(self.start_scan_button)
        scan_buttons_layout.addWidget(self.save_scan_button)

        scan_layout.addLayout(scan_buttons_layout)

        # Aggiungi le schede al pannello di controllo
        control_panel.addTab(camera_controls, "Fotocamera")
        control_panel.addTab(scan_controls, "Scansione")

        main_layout.addWidget(control_panel)

    def _connect_signals(self):
        """Collega i segnali dei processori di frame."""
        for i, processor in enumerate(self._frame_processors):
            processor.new_frame_ready.connect(self._on_new_frame)

        # Collega i checkbox di visualizzazione
        self.grid_checkbox.toggled.connect(self._update_visualization_options)
        self.features_checkbox.toggled.connect(self._update_visualization_options)
        self.enhance_checkbox.toggled.connect(self._update_visualization_options)

    def _check_connection(self):
        """Controlla lo stato della connessione e riprova se necessario."""
        # Importa qui per evitare problemi di importazione circolare
        from client.network.connection_manager import ConnectionManager

        if not self._connection_manager:
            self._connection_manager = ConnectionManager()

        if not self._scanner:
            self._retry_timer.stop()
            return

        # Verifica se lo scanner è connesso
        if self._connection_manager.is_connected(self._scanner.device_id):
            logger.info(f"Connessione stabilita con {self._scanner.name}")

            # Connessione stabilita, prova ad avviare lo streaming
            self._retry_timer.stop()

            # Avvia il vero streaming - ora che la connessione è confermata
            self._start_actual_streaming()
        else:
            self._retry_count += 1
            logger.info(f"Tentativo di connessione {self._retry_count}/{self._max_retries}")

            if self._retry_count >= self._max_retries:
                logger.error(f"Impossibile connettersi a {self._scanner.name} dopo {self._max_retries} tentativi")
                self._retry_timer.stop()
                QMessageBox.warning(
                    self,
                    "Errore di connessione",
                    f"Impossibile connettersi a {self._scanner.name} dopo {self._max_retries} tentativi.\n"
                    "Assicurati che lo scanner sia acceso e correttamente configurato."
                )
            else:
                # Riprova a connettersi
                self._connection_manager.connect(
                    self._scanner.device_id,
                    self._scanner.ip_address,
                    self._scanner.port
                )

    def start_streaming(self, scanner: Scanner) -> bool:
        """
        Avvia lo streaming video dalle due camere dello scanner.

        Args:
            scanner: Scanner da cui ricevere lo streaming

        Returns:
            True se il processo di streaming è stato avviato, False altrimenti
        """
        if self._streaming:
            logger.warning("Streaming già attivo")
            return True

        # Memorizza lo scanner
        self._scanner = scanner

        # Importa qui per evitare problemi di importazione circolare
        from client.network.connection_manager import ConnectionManager

        self._connection_manager = ConnectionManager()

        # Verifica che lo scanner sia connesso prima di avviare lo streaming
        if not self._connection_manager.is_connected(scanner.device_id):
            logger.warning(f"Scanner {scanner.name} non connesso, tentativo di connessione")

            # Connetti allo scanner
            self._connection_manager.connect(scanner.device_id, scanner.ip_address, scanner.port)

            # Imposta il timer per controllare se la connessione viene stabilita
            self._retry_count = 0
            self._retry_timer.start()

            # Ritorna True per indicare che il processo è iniziato (anche se lo streaming non è ancora attivo)
            return True
        else:
            # Scanner già connesso, avvia subito lo streaming
            return self._start_actual_streaming()

    def _start_actual_streaming(self) -> bool:
        """
        Avvia effettivamente lo streaming dopo che la connessione è stata stabilita.

        Returns:
            True se lo streaming è stato avviato con successo, False altrimenti
        """
        try:
            # Crea un ricevitore di stream per questo scanner
            from client.network.stream_receiver import StreamReceiver
            stream_receiver = StreamReceiver(
                host=self._scanner.ip_address,
                port=self._scanner.port + 1  # La porta di streaming è command_port + 1
            )

            # Collega i segnali del ricevitore
            stream_receiver.frame_received.connect(self._on_frame_received)
            stream_receiver.stream_started.connect(self._on_stream_started)
            stream_receiver.stream_stopped.connect(self._on_stream_stopped)
            stream_receiver.stream_error.connect(self._on_stream_error)

            # Avvia il ricevitore
            if not stream_receiver.start():
                logger.error("Errore nell'avvio dello stream receiver")
                return False

            # Memorizza il ricevitore
            self._stream_receiver = stream_receiver

            # Invia un messaggio al server per avviare lo streaming
            if not self._connection_manager.send_message(self._scanner.device_id, "START_STREAM"):
                logger.error(f"Errore nell'invio del comando START_STREAM a {self._scanner.name}")
                stream_receiver.stop()
                self._stream_receiver = None
                return False

            # Avvia i processori di frame
            for processor in self._frame_processors:
                processor.start()

            # Cambia lo stato dello scanner
            self._scanner.status = ScannerStatus.STREAMING

            # Imposta lo stato di streaming
            self._streaming = True
            logger.info(f"Streaming avviato da {self._scanner.name}")

            # Abilita i pulsanti appropriati
            self.capture_button.setEnabled(True)
            self.start_scan_button.setEnabled(True)
            self.apply_settings_button.setEnabled(True)

            return True
        except Exception as e:
            logger.error(f"Errore nell'avvio dello streaming: {str(e)}")
            return False

    def stop_streaming(self):
        """Ferma lo streaming video."""
        if not self._streaming:
            return

        logger.info("Arresto dello streaming video...")

        # Ferma il timer di retry se attivo
        if self._retry_timer.isActive():
            self._retry_timer.stop()

        # Ferma il ricevitore di stream
        if self._stream_receiver:
            self._stream_receiver.stop()
            self._stream_receiver = None

        # Invia un messaggio al server per fermare lo streaming
        if self._scanner and self._connection_manager:
            if self._connection_manager.is_connected(self._scanner.device_id):
                self._connection_manager.send_message(self._scanner.device_id, "STOP_STREAM")

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

        # Disabilita i pulsanti
        self.capture_button.setEnabled(False)
        self.start_scan_button.setEnabled(False)
        self.save_scan_button.setEnabled(False)
        self.apply_settings_button.setEnabled(False)

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

    @Slot(int, np.ndarray)
    def _on_frame_received(self, camera_index: int, frame: np.ndarray):
        """Gestisce l'arrivo di un nuovo frame dallo stream."""
        # Questo metodo viene chiamato quando il StreamReceiver riceve un frame
        # Aggiungiamo il frame alla coda del processore appropriato
        if 0 <= camera_index < len(self._frame_queues):
            self._frame_queues[camera_index].put((camera_index, frame))

    @Slot(int)
    def _on_stream_started(self, camera_index: int):
        """Gestisce l'evento di avvio dello stream per una camera."""
        logger.info(f"Stream avviato per camera {camera_index}")

    @Slot(int)
    def _on_stream_stopped(self, camera_index: int):
        """Gestisce l'evento di arresto dello stream per una camera."""
        logger.info(f"Stream fermato per camera {camera_index}")

    @Slot(int, str)
    def _on_stream_error(self, camera_index: int, error: str):
        """Gestisce gli errori dello stream."""
        logger.error(f"Errore nello stream della camera {camera_index}: {error}")

    def _on_start_scan_clicked(self):
        """Gestisce il clic sul pulsante Avvia Scansione."""
        if not self._scanner or not self._streaming:
            QMessageBox.warning(
                self,
                "Errore",
                "Per avviare una scansione è necessario essere connessi a uno scanner."
            )
            return

        # Ottieni le impostazioni di scansione
        scan_name = self.scan_name_edit.text()
        scan_type = "structured_light" if self.scan_type_structured.isChecked() else "tof"
        resolution = self.resolution_combo.currentData()
        quality = self.quality_slider.value()
        color_capture = self.color_checkbox.isChecked()

        # Log informativo
        logger.info(f"Avvio scansione: {scan_name}, tipo: {scan_type}, res: {resolution}, qualità: {quality}")

        # Mostra un messaggio che indica che la scansione è in corso
        QMessageBox.information(
            self,
            "Scansione in corso",
            f"Scansione '{scan_name}' in corso.\nQuesta funzionalità è in fase di sviluppo."
        )

        # In futuro, qui implementeremo il codice per avviare la scansione effettiva
        # ...

        # Abilita il pulsante di salvataggio
        self.save_scan_button.setEnabled(True)

    def _on_save_scan_clicked(self):
        """Gestisce il clic sul pulsante Salva Scansione."""
        scan_name = self.scan_name_edit.text()
        safe_name = ''.join(c if c.isalnum() or c in '._- ' else '_' for c in scan_name)

        # Apri un dialogo per selezionare la posizione di salvataggio
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Salva Scansione",
            str(Path.home() / "UnLook" / "scans" / f"{safe_name}_{int(time.time())}.ply"),
            "PLY Files (*.ply);;All Files (*)"
        )

        if file_path:
            # Mostra un messaggio che indica che il salvataggio è in corso
            QMessageBox.information(
                self,
                "Salvataggio in corso",
                f"Il salvataggio della scansione '{scan_name}' è in corso.\n"
                "Questa funzionalità è in fase di sviluppo."
            )

            # In futuro, qui implementeremo il codice per salvare la scansione
            # ...

    def _apply_camera_settings(self):
        """Applica le impostazioni delle camere."""
        if not self._scanner or not self._connection_manager or not self._connection_manager.is_connected(
                self._scanner.device_id):
            QMessageBox.warning(
                self,
                "Errore",
                "Per applicare le impostazioni è necessario essere connessi a uno scanner."
            )
            return

        # Raccogli le impostazioni
        left_exposure = self.left_exposure_slider.value()
        right_exposure = self.right_exposure_slider.value()

        # Crea il payload di configurazione
        config = {
            "camera": {
                "left": {
                    "exposure": left_exposure
                },
                "right": {
                    "exposure": right_exposure
                }
            }
        }

        # Invia la configurazione al server
        if self._connection_manager.send_message(
                self._scanner.device_id,
                "SET_CONFIG",
                {"config": config}
        ):
            QMessageBox.information(
                self,
                "Impostazioni applicate",
                "Le impostazioni delle camere sono state applicate."
            )
        else:
            QMessageBox.warning(
                self,
                "Errore",
                "Impossibile applicare le impostazioni: errore di comunicazione."
            )

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
        saved_files = []
        for i, frame in frames:
            camera_name = "left" if i == 0 else "right"
            file_path = save_dir / f"unlook_{timestamp}_{camera_name}.png"

            # Salva l'immagine
            frame.save(str(file_path), "PNG")
            saved_files.append(str(file_path))
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