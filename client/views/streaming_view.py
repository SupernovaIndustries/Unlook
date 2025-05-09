#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Widget per la visualizzazione dello streaming video dual-camera degli scanner UnLook.
Versione ottimizzata con eliminazione delle code e buffer per ridurre la latenza.
"""

import logging
import cv2
import numpy as np
import time
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple, Dict, List, Any

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QFormLayout, QComboBox, QSlider, QCheckBox,
    QSpinBox, QDoubleSpinBox, QFrame, QSplitter, QFileDialog,
    QMessageBox, QTabWidget, QRadioButton, QButtonGroup, QLineEdit,
    QProgressDialog, QStyle, QStyleOption, QStyleFactory, QApplication
)
from PySide6.QtCore import Qt, Signal, Slot, QTimer, QMutex, QMutexLocker, QPoint
from PySide6.QtGui import QImage, QPixmap, QPainter, QColor, QPen, QFont, QPalette

from client.models.scanner_model import Scanner, ScannerStatus
from client.network.stream_receiver import StreamReceiver

logger = logging.getLogger(__name__)


class StreamView(QWidget):
    """
    Widget che visualizza lo stream di una singola camera.
    Versione ottimizzata con elaborazione in linea e senza buffer.
    """

    def __init__(self, camera_index: int, parent=None):
        super().__init__(parent)
        self.camera_index = camera_index
        self._frame = None
        self._last_frame_time = 0
        self._fps = 0
        self._frame_count = 0
        self._last_update_time = time.time()
        self._healthy = False
        self._lag_ms = 0
        self._max_lag_warning = 200  # ms, soglia per avviso lag

        # Opzioni di visualizzazione
        self._enhance_contrast = False
        self._show_grid = False
        self._show_features = False

        # Mutex per proteggere l'accesso al frame e alle opzioni
        self._mutex = QMutex()

        # Configurazione dell'interfaccia
        self._setup_ui()

        # Timer per controllare lo stato di salute
        self._health_timer = QTimer(self)
        self._health_timer.timeout.connect(self._check_health)
        self._health_timer.start(1000)  # Ogni secondo

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

        # Messaggio iniziale
        font = self.display_label.font()
        font.setPointSize(12)
        self.display_label.setFont(font)
        self.display_label.setText("Camera non attiva\nIn attesa dei frame...")
        self.display_label.setStyleSheet("background-color: black; color: white;")

        layout.addWidget(self.display_label)

        # Etichette di informazione
        self.info_label = QLabel("Camera non attiva")
        self.info_label.setAlignment(Qt.AlignCenter)

        self.lag_label = QLabel("Lag: N/A")
        self.lag_label.setAlignment(Qt.AlignCenter)
        self.lag_label.setStyleSheet("color: green;")

        # Layout per informazioni
        info_layout = QHBoxLayout()
        info_layout.addWidget(self.info_label)
        info_layout.addWidget(self.lag_label)

        layout.addLayout(info_layout)

    @Slot(np.ndarray, float)
    def update_frame(self, frame: np.ndarray, timestamp: float = None):
        """
        Aggiorna il frame visualizzato, elaborando direttamente senza buffer.
        Versione ottimizzata per ridurre al minimo la latenza.

        Args:
            frame: Frame in formato numpy array
            timestamp: Timestamp del frame (per calcolo del lag)
        """
        if frame is None or not isinstance(frame, np.ndarray) or frame.size == 0:
            logger.warning(f"Frame nullo o non valido ricevuto per camera {self.camera_index}")
            return

        # Acquisiamo il lock solo per la parte di elaborazione, mantenendolo il più breve possibile
        with QMutexLocker(self._mutex):
            # Applica elaborazione se abilitata
            processed_frame = self._process_frame(frame.copy())

            # Controllo di prestazioni - saltiamo la conversione QImage se l'UI non è visibile
            if not self.isVisible():
                # Solo aggiornamento statistiche
                self._frame_count += 1
                self._last_frame_time = time.time()
                if timestamp is not None:
                    self._lag_ms = int((self._last_frame_time - timestamp) * 1000)
                self._healthy = True
                return

            # Converti in QImage per visualizzare (ottimizzato)
            height, width = processed_frame.shape[:2]
            bytes_per_line = processed_frame.strides[0]

            # Ottimizzazione: non copiare dati inutilmente
            if len(processed_frame.shape) == 3 and processed_frame.shape[2] == 3:
                # Immagine a colori BGR (OpenCV) -> RGB (Qt)
                rgb_frame = cv2.cvtColor(processed_frame, cv2.COLOR_BGR2RGB)
                qt_image = QImage(rgb_frame.data, width, height,
                                  bytes_per_line, QImage.Format_RGB888)
            else:
                # Immagine in scala di grigi
                qt_image = QImage(processed_frame.data, width, height,
                                  processed_frame.strides[0], QImage.Format_Grayscale8)

            # Crea un QPixmap direttamente dall'immagine
            pixmap = QPixmap.fromImage(qt_image)

            # Salva una copia leggera del frame per l'acquisizione
            self._frame = qt_image

        # Incrementa contatore
        self._frame_count += 1

        # Calcola FPS e lag
        current_time = time.time()
        if self._last_frame_time > 0:
            time_diff = current_time - self._last_frame_time
            if time_diff > 0:
                instantaneous_fps = 1.0 / time_diff
                # Media mobile per stabilizzare
                alpha = 0.1
                self._fps = (1.0 - alpha) * self._fps + alpha * instantaneous_fps

        self._last_frame_time = current_time

        # Calcola lag se è stato fornito un timestamp
        if timestamp is not None:
            now = time.time()
            self._lag_ms = int((now - timestamp) * 1000)
            self._update_lag_label()
        else:
            self.lag_label.setText("Lag: N/A")
            self.lag_label.setStyleSheet("color: gray;")

        # Aggiorna stato di salute
        self._healthy = True

        # Calcola dimensione per mantenere aspect ratio
        scaled_pixmap = pixmap.scaled(
            self.display_label.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation if self._frame_count % 2 == 0 else Qt.FastTransformation
            # Alternanza per bilanciare qualità/velocità
        )

        # Mostra il frame
        self.display_label.setPixmap(scaled_pixmap)
        self.display_label.setStyleSheet("")  # Rimuovi stile sfondo nero

        # Aggiorna etichetta informativa solo occasionalmente per ridurre overhead UI
        if self._frame_count % 10 == 0:
            camera_name = "Sinistra" if self.camera_index == 0 else "Destra"
            size_text = f"{width}x{height}"
            fps_text = f"{self._fps:.1f} FPS" if self._fps > 0 else ""

            self.info_label.setText(f"Camera {camera_name} | {size_text} | {fps_text}")

    def _process_frame(self, frame: np.ndarray) -> np.ndarray:
        """
        Elabora un frame applicando le opzioni di visualizzazione.
        Versione ottimizzata per prestazioni ed efficienza.

        Args:
            frame: Frame da elaborare

        Returns:
            Frame elaborato
        """
        try:
            # Per migliorare le prestazioni, evitiamo conversioni inutili di formato
            is_color = len(frame.shape) == 3 and frame.shape[2] >= 3

            # Se nessuna elaborazione è abilitata, restituisci il frame originale
            if not hasattr(self, '_enhance_contrast') or not hasattr(self, '_show_grid') or not hasattr(self,
                                                                                                        '_show_features'):
                # Inizializza le opzioni se mancanti
                if not hasattr(self, '_enhance_contrast'):
                    self._enhance_contrast = False
                if not hasattr(self, '_show_grid'):
                    self._show_grid = False
                if not hasattr(self, '_show_features'):
                    self._show_features = False

            if not (self._enhance_contrast or self._show_grid or self._show_features):
                return frame

            # Solo se necessario, crea una copia in scala di grigi per elaborazione
            if is_color:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            else:
                gray = frame.copy() if self._enhance_contrast or self._show_features else frame

            # Applica miglioramento del contrasto se abilitato
            if self._enhance_contrast:
                # Equalizzazione adattiva dell'istogramma (CLAHE)
                clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
                enhanced = clahe.apply(gray)

                # Se il frame originale era a colori, applica miglioramento solo alla luminosità
                if is_color:
                    # Converti in HSV
                    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
                    # Sostituisci canale V (luminosità)
                    hsv[:, :, 2] = enhanced
                    # Torna a BGR
                    frame = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
                else:
                    frame = enhanced

            # Applica griglia se abilitata
            if self._show_grid:
                height, width = frame.shape[:2]
                grid_size = min(50, max(width, height) // 10)  # Adatta dimensione griglia

                grid_color = (0, 255, 0) if is_color else 200
                grid_thickness = 1

                # Disegna linee principali
                for y in range(0, height, grid_size):
                    cv2.line(frame, (0, y), (width, y), grid_color, grid_thickness)
                for x in range(0, width, grid_size):
                    cv2.line(frame, (x, 0), (x, height), grid_color, grid_thickness)

            # Rileva e disegna caratteristiche se abilitato
            if self._show_features:
                # Usa rilevatore veloce con limite di punti
                max_features = 100
                feature_detector = cv2.FastFeatureDetector_create(threshold=30)

                # Rileva keypoints
                keypoints = feature_detector.detect(gray, None)

                # Limita numero di keypoints
                if len(keypoints) > max_features:
                    keypoints = sorted(keypoints, key=lambda x: -x.response)[:max_features]

                # Disegna keypoints
                feature_color = (0, 0, 255)  # Rosso
                if is_color:
                    cv2.drawKeypoints(frame, keypoints, frame, feature_color,
                                      cv2.DRAW_MATCHES_FLAGS_DEFAULT)
                else:
                    # Converti a colore se necessario
                    color_frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
                    cv2.drawKeypoints(color_frame, keypoints, color_frame, feature_color,
                                      cv2.DRAW_MATCHES_FLAGS_DEFAULT)
                    frame = color_frame

            return frame
        except Exception as e:
            logger.error(f"Errore in _process_frame: {e}")
            # In caso di errore, restituisci il frame originale
            return frame

    def _update_status(self, message):
        """
        Aggiorna in modo sicuro il messaggio di stato nell'interfaccia utente.
        Gestisce diversi possibili layout dell'interfaccia per massima compatibilità.

        Args:
            message: Il messaggio di stato da visualizzare
        """
        # Log del messaggio di stato
        logger.debug(f"Stato streaming: {message}")

        # Prova diversi possibili elementi dell'interfaccia per aggiornare lo stato
        try:
            # Opzione 1: attributo status_label diretto
            if hasattr(self, 'status_label'):
                self.status_label.setText(message)
                return

            # Opzione 2: status_label nel pannello di controllo
            if hasattr(self, 'control_panel') and hasattr(self.control_panel, 'status_label'):
                self.control_panel.status_label.setText(message)
                return

            # Opzione 3: info_label (possibile alternativa)
            if hasattr(self, 'info_label'):
                self.info_label.setText(message)
                return

            # Opzione 4: Cerca la statusbar nella finestra principale
            main_window = self.window()
            if hasattr(main_window, 'status_bar'):
                main_window.status_bar.showMessage(message, 3000)  # Mostra per 3 secondi
                return

            # Opzione 5: Nessuna opzione disponibile, solo log
            logger.info(f"Nessuna UI per stato: {message}")
        except Exception as e:
            # In caso di errore, registra solo il messaggio
            logger.warning(f"Errore nell'aggiornamento dello stato UI: {e}")
        finally:
            # Logga sempre il messaggio
            logger.info(f"Stato streaming: {message}")


    def _update_lag_label(self):
        """
        Aggiorna l'etichetta del lag e imposta il colore appropriato.
        Versione con limiti di lag più realistici per dual camera.
        """
        # Valori soglia ottimizzati per un Raspberry Pi
        if self._lag_ms < 200:  # Ottimo
            self.lag_label.setStyleSheet("color: green; font-weight: bold;")
        elif self._lag_ms < 400:  # Accettabile
            self.lag_label.setStyleSheet("color: orange; font-weight: bold;")
        else:  # Problematico
            self.lag_label.setStyleSheet("color: red; font-weight: bold;")

        self.lag_label.setText(f"Lag: {self._lag_ms}ms")

        # Logga avvisi solo per lag molto elevato e non troppo frequentemente
        if self._lag_ms > self._max_lag_warning:
            # Evita spam nel log usando un contatore
            if not hasattr(self, '_lag_warning_count'):
                self._lag_warning_count = 0

            self._lag_warning_count += 1

            # Logga solo ogni 10 rilevamenti di lag alto
            if self._lag_warning_count % 10 == 1:
                logger.warning(f"Lag elevato su camera {self.camera_index}: {self._lag_ms}ms")

    def clear(self):
        """Pulisce la visualizzazione."""
        self.display_label.clear()
        self.display_label.setStyleSheet("background-color: black; color: white;")
        self.display_label.setText("Camera non attiva")
        self.info_label.setText("Camera non attiva")
        self.lag_label.setText("Lag: N/A")
        self.lag_label.setStyleSheet("color: gray;")
        self._frame = None
        self._last_frame_time = 0
        self._fps = 0
        self._frame_count = 0
        self._healthy = False
        self._lag_ms = 0

    def get_current_frame(self) -> Optional[QImage]:
        """Restituisce il frame attuale."""
        return self._frame

    def get_stats(self) -> Dict[str, Any]:
        """Restituisce le statistiche di questo stream."""
        return {
            "fps": self._fps,
            "frame_count": self._frame_count,
            "healthy": self._healthy,
            "lag_ms": self._lag_ms,
            "last_frame_time": self._last_frame_time
        }

    def set_visualization_options(self, show_grid: bool, show_features: bool, enhance_contrast: bool):
        """Imposta le opzioni di visualizzazione."""
        with QMutexLocker(self._mutex):
            self._show_grid = show_grid
            self._show_features = show_features
            self._enhance_contrast = enhance_contrast

    def _check_health(self):
        """Controlla lo stato di salute dello stream."""
        current_time = time.time()

        # Se non abbiamo ricevuto frame negli ultimi 3 secondi, lo stream non è sano
        if self._healthy and current_time - self._last_frame_time > 3.0:
            self._healthy = False
            logger.warning(f"Nessun frame ricevuto negli ultimi 3 secondi per camera {self.camera_index}")

            # Indicatore visivo
            if self._frame is None:
                # Se non abbiamo mai ricevuto un frame, mostra messaggio
                self.display_label.setText("Camera non attiva\nNessun frame ricevuto")
            else:
                # Mostra l'ultimo frame con indicatore di problemi
                pixmap = QPixmap.fromImage(self._frame)
                scaled_pixmap = pixmap.scaled(
                    self.display_label.size(),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )

                # Aggiungi bordo rosso
                painter = QPainter(scaled_pixmap)
                pen = QPen(QColor(255, 0, 0))  # Rosso
                pen.setWidth(4)
                painter.setPen(pen)
                painter.drawRect(0, 0, scaled_pixmap.width() - 1, scaled_pixmap.height() - 1)
                painter.end()

                self.display_label.setPixmap(scaled_pixmap)

            # Aggiorna etichetta informativa
            camera_name = "Sinistra" if self.camera_index == 0 else "Destra"
            self.info_label.setText(f"Camera {camera_name} | CONNESSIONE PERSA")
            self.lag_label.setText("Lag: N/A")
            self.lag_label.setStyleSheet("color: red; font-weight: bold;")

        elif not self._healthy and self._frame_count > 0:
            # Se abbiamo ricevuto frame ma lo stream non è sano, aggiorna visualizzazione
            if self._frame:
                pixmap = QPixmap.fromImage(self._frame)
                scaled_pixmap = pixmap.scaled(
                    self.display_label.size(),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
                self.display_label.setPixmap(scaled_pixmap)


class DualStreamView(QWidget):
    """
    Widget che visualizza lo streaming simultaneo delle due camere.
    Versione ottimizzata per ridurre lag e eliminare code.
    """

    def __init__(self, scanner_controller=None, parent=None):
        super().__init__(parent)
        self._scanner = None
        self._streaming = False
        self._stream_receiver = None
        self._connection_manager = None
        self._retry_timer = QTimer()
        self._retry_timer.setInterval(1000)
        self._retry_timer.timeout.connect(self._check_connection)
        self._retry_count = 0
        self._max_retries = 5
        self._frame_count = 0

        # Aggiungi il riferimento al scanner_controller
        self.scanner_controller = scanner_controller
        self.selected_scanner = None

        # Configura l'interfaccia
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

        # Pulsanti di controllo sotto le camere
        control_buttons = QHBoxLayout()

        # Pulsante avvia/ferma streaming
        self.toggle_stream_button = QPushButton("Avvia Streaming")
        self.toggle_stream_button.clicked.connect(self._on_toggle_stream_clicked)
        self.toggle_stream_button.setEnabled(False)

        # Pulsante cattura frame
        self.capture_button = QPushButton("Acquisisci Frame")
        self.capture_button.clicked.connect(self.capture_frame)
        self.capture_button.setEnabled(False)

        control_buttons.addWidget(self.toggle_stream_button)
        control_buttons.addWidget(self.capture_button)
        control_buttons.addStretch(1)

        # Rimuoviamo il pulsante "Avvia Scansione"
        # self.start_scan_button = QPushButton("Avvia Scansione")
        # self.start_scan_button.clicked.connect(self._on_start_scan_clicked)
        # self.start_scan_button.setEnabled(False)
        # control_buttons.addWidget(self.start_scan_button)

        main_layout.addLayout(control_buttons)

        # Pannello di controllo
        control_panel = QTabWidget()

        # Tab per i controlli di visualizzazione e fotocamera
        camera_controls = QWidget()
        camera_layout = QVBoxLayout(camera_controls)

        # Opzioni di visualizzazione
        view_options_group = QGroupBox("Opzioni di visualizzazione")
        view_options_layout = QVBoxLayout(view_options_group)

        # Checkbox per le opzioni
        options_layout = QHBoxLayout()
        self.grid_checkbox = QCheckBox("Mostra griglia")
        self.features_checkbox = QCheckBox("Mostra caratteristiche")
        self.enhance_checkbox = QCheckBox("Migliora contrasto")

        # Collega i cambiamenti nelle checkbox
        self.grid_checkbox.toggled.connect(self._update_visualization_options)
        self.features_checkbox.toggled.connect(self._update_visualization_options)
        self.enhance_checkbox.toggled.connect(self._update_visualization_options)

        options_layout.addWidget(self.grid_checkbox)
        options_layout.addWidget(self.features_checkbox)
        options_layout.addWidget(self.enhance_checkbox)
        options_layout.addStretch(1)

        view_options_layout.addLayout(options_layout)
        camera_layout.addWidget(view_options_group)

        # Gruppo dei parametri del sensore con tab per le due camere
        self.camera_tabs = QTabWidget()

        # Crea le tab per i controlli delle camere
        left_cam_tab, right_cam_tab = self._setup_camera_controls()

        # Aggiungi le tab al widget
        self.camera_tabs.addTab(left_cam_tab, "Camera Sinistra")
        self.camera_tabs.addTab(right_cam_tab, "Camera Destra")

        # Pulsante per applicare le impostazioni
        apply_layout = QHBoxLayout()
        self.apply_settings_button = QPushButton("Applica impostazioni fotocamera")
        self.apply_settings_button.setEnabled(False)
        self.apply_settings_button.clicked.connect(self._apply_camera_settings)
        apply_layout.addStretch(1)
        apply_layout.addWidget(self.apply_settings_button)

        # Aggiungi i controlli al layout
        camera_layout.addWidget(self.camera_tabs)
        camera_layout.addLayout(apply_layout)

        # Rimuoviamo la tab per i controlli di scansione
        # scan_controls = QWidget()
        # scan_layout = QVBoxLayout(scan_controls)
        # ...
        # control_panel.addTab(scan_controls, "Scansione")

        # Aggiungi solo la tab Fotocamera al pannello di controllo
        control_panel.addTab(camera_controls, "Fotocamera")

        main_layout.addWidget(control_panel)

    def _setup_camera_controls(self):
        """Configura i controlli avanzati della camera."""
        # Tab Camera Sinistra
        left_cam_tab = QWidget()
        left_cam_layout = QFormLayout(left_cam_tab)

        # Sezione modalità camera
        left_mode_group = QGroupBox("Modalità camera")
        left_mode_layout = QVBoxLayout(left_mode_group)

        self.left_mode_color = QRadioButton("Colore")
        self.left_mode_grayscale = QRadioButton("Scala di grigi")

        # Imposta colore come predefinito
        self.left_mode_color.setChecked(True)

        self.left_mode_buttongroup = QButtonGroup()
        self.left_mode_buttongroup.addButton(self.left_mode_color, 0)
        self.left_mode_buttongroup.addButton(self.left_mode_grayscale, 1)

        left_mode_layout.addWidget(self.left_mode_color)
        left_mode_layout.addWidget(self.left_mode_grayscale)

        left_cam_layout.addRow(left_mode_group)

        # Esposizione camera sinistra
        left_exposure_layout = QHBoxLayout()
        self.left_exposure_slider = QSlider(Qt.Horizontal)
        self.left_exposure_slider.setRange(0, 100)
        self.left_exposure_slider.setValue(50)
        self.left_exposure_slider.setTickPosition(QSlider.TicksBelow)
        self.left_exposure_slider.setTickInterval(10)

        self.left_exposure_value = QLabel("50")
        self.left_exposure_slider.valueChanged.connect(lambda v: self.left_exposure_value.setText(str(v)))

        left_exposure_layout.addWidget(self.left_exposure_slider)
        left_exposure_layout.addWidget(self.left_exposure_value)
        left_cam_layout.addRow("Esposizione:", left_exposure_layout)

        # Guadagno camera sinistra
        left_gain_layout = QHBoxLayout()
        self.left_gain_slider = QSlider(Qt.Horizontal)
        self.left_gain_slider.setRange(0, 100)
        self.left_gain_slider.setValue(50)
        self.left_gain_slider.setTickPosition(QSlider.TicksBelow)
        self.left_gain_slider.setTickInterval(10)

        self.left_gain_value = QLabel("50")
        self.left_gain_slider.valueChanged.connect(lambda v: self.left_gain_value.setText(str(v)))

        left_gain_layout.addWidget(self.left_gain_slider)
        left_gain_layout.addWidget(self.left_gain_value)
        left_cam_layout.addRow("Guadagno:", left_gain_layout)

        # Altri controlli avanzati in un gruppo separato
        left_advanced_group = QGroupBox("Controlli avanzati")
        left_advanced_layout = QFormLayout(left_advanced_group)

        # Luminosità camera sinistra
        left_brightness_layout = QHBoxLayout()
        self.left_brightness_slider = QSlider(Qt.Horizontal)
        self.left_brightness_slider.setRange(0, 100)
        self.left_brightness_slider.setValue(50)
        self.left_brightness_value = QLabel("50")
        self.left_brightness_slider.valueChanged.connect(lambda v: self.left_brightness_value.setText(str(v)))
        left_brightness_layout.addWidget(self.left_brightness_slider)
        left_brightness_layout.addWidget(self.left_brightness_value)
        left_advanced_layout.addRow("Luminosità:", left_brightness_layout)

        # Contrasto camera sinistra
        left_contrast_layout = QHBoxLayout()
        self.left_contrast_slider = QSlider(Qt.Horizontal)
        self.left_contrast_slider.setRange(0, 100)
        self.left_contrast_slider.setValue(50)
        self.left_contrast_value = QLabel("50")
        self.left_contrast_slider.valueChanged.connect(lambda v: self.left_contrast_value.setText(str(v)))
        left_contrast_layout.addWidget(self.left_contrast_slider)
        left_contrast_layout.addWidget(self.left_contrast_value)
        left_advanced_layout.addRow("Contrasto:", left_contrast_layout)

        # Nitidezza camera sinistra
        left_sharpness_layout = QHBoxLayout()
        self.left_sharpness_slider = QSlider(Qt.Horizontal)
        self.left_sharpness_slider.setRange(0, 100)
        self.left_sharpness_slider.setValue(50)
        self.left_sharpness_value = QLabel("50")
        self.left_sharpness_slider.valueChanged.connect(lambda v: self.left_sharpness_value.setText(str(v)))
        left_sharpness_layout.addWidget(self.left_sharpness_slider)
        left_sharpness_layout.addWidget(self.left_sharpness_value)
        left_advanced_layout.addRow("Nitidezza:", left_sharpness_layout)

        # Saturazione camera sinistra (solo per modalità colore)
        left_saturation_layout = QHBoxLayout()
        self.left_saturation_slider = QSlider(Qt.Horizontal)
        self.left_saturation_slider.setRange(0, 100)
        self.left_saturation_slider.setValue(50)
        self.left_saturation_value = QLabel("50")
        self.left_saturation_slider.valueChanged.connect(lambda v: self.left_saturation_value.setText(str(v)))
        left_saturation_layout.addWidget(self.left_saturation_slider)
        left_saturation_layout.addWidget(self.left_saturation_value)
        left_advanced_layout.addRow("Saturazione:", left_saturation_layout)

        # Aggiungi il gruppo avanzato
        left_cam_layout.addRow(left_advanced_group)

        # Salva i riferimenti alle righe di saturazione per poter controllare la visibilità
        self.left_saturation_row = (
            left_advanced_layout.itemAt(left_advanced_layout.rowCount() - 1, QFormLayout.LabelRole).widget(),
            left_advanced_layout.itemAt(left_advanced_layout.rowCount() - 1, QFormLayout.FieldRole).widget())

        # Collegamento tra modalità e saturazione per camera sinistra
        self.left_mode_color.toggled.connect(lambda checked: self._update_saturation_visibility(checked, True))
        self.left_mode_grayscale.toggled.connect(lambda checked: self._update_saturation_visibility(not checked, True))

        # Tab Camera Destra (struttura analoga)
        right_cam_tab = QWidget()
        right_cam_layout = QFormLayout(right_cam_tab)

        # Sezione modalità camera
        right_mode_group = QGroupBox("Modalità camera")
        right_mode_layout = QVBoxLayout(right_mode_group)

        self.right_mode_color = QRadioButton("Colore")
        self.right_mode_grayscale = QRadioButton("Scala di grigi")

        # Imposta colore come predefinito
        self.right_mode_color.setChecked(True)

        self.right_mode_buttongroup = QButtonGroup()
        self.right_mode_buttongroup.addButton(self.right_mode_color, 0)
        self.right_mode_buttongroup.addButton(self.right_mode_grayscale, 1)

        right_mode_layout.addWidget(self.right_mode_color)
        right_mode_layout.addWidget(self.right_mode_grayscale)

        right_cam_layout.addRow(right_mode_group)

        # Esposizione camera destra
        right_exposure_layout = QHBoxLayout()
        self.right_exposure_slider = QSlider(Qt.Horizontal)
        self.right_exposure_slider.setRange(0, 100)
        self.right_exposure_slider.setValue(50)
        self.right_exposure_slider.setTickPosition(QSlider.TicksBelow)
        self.right_exposure_slider.setTickInterval(10)

        self.right_exposure_value = QLabel("50")
        self.right_exposure_slider.valueChanged.connect(lambda v: self.right_exposure_value.setText(str(v)))

        right_exposure_layout.addWidget(self.right_exposure_slider)
        right_exposure_layout.addWidget(self.right_exposure_value)
        right_cam_layout.addRow("Esposizione:", right_exposure_layout)

        # Guadagno camera destra
        right_gain_layout = QHBoxLayout()
        self.right_gain_slider = QSlider(Qt.Horizontal)
        self.right_gain_slider.setRange(0, 100)
        self.right_gain_slider.setValue(50)
        self.right_gain_slider.setTickPosition(QSlider.TicksBelow)
        self.right_gain_slider.setTickInterval(10)

        self.right_gain_value = QLabel("50")
        self.right_gain_slider.valueChanged.connect(lambda v: self.right_gain_value.setText(str(v)))

        right_gain_layout.addWidget(self.right_gain_slider)
        right_gain_layout.addWidget(self.right_gain_value)
        right_cam_layout.addRow("Guadagno:", right_gain_layout)

        # Altri controlli avanzati in un gruppo separato
        right_advanced_group = QGroupBox("Controlli avanzati")
        right_advanced_layout = QFormLayout(right_advanced_group)

        # Luminosità camera destra
        right_brightness_layout = QHBoxLayout()
        self.right_brightness_slider = QSlider(Qt.Horizontal)
        self.right_brightness_slider.setRange(0, 100)
        self.right_brightness_slider.setValue(50)
        self.right_brightness_value = QLabel("50")
        self.right_brightness_slider.valueChanged.connect(lambda v: self.right_brightness_value.setText(str(v)))
        right_brightness_layout.addWidget(self.right_brightness_slider)
        right_brightness_layout.addWidget(self.right_brightness_value)
        right_advanced_layout.addRow("Luminosità:", right_brightness_layout)

        # Contrasto camera destra
        right_contrast_layout = QHBoxLayout()
        self.right_contrast_slider = QSlider(Qt.Horizontal)
        self.right_contrast_slider.setRange(0, 100)
        self.right_contrast_slider.setValue(50)
        self.right_contrast_value = QLabel("50")
        self.right_contrast_slider.valueChanged.connect(lambda v: self.right_contrast_value.setText(str(v)))
        right_contrast_layout.addWidget(self.right_contrast_slider)
        right_contrast_layout.addWidget(self.right_contrast_value)
        right_advanced_layout.addRow("Contrasto:", right_contrast_layout)

        # Nitidezza camera destra
        right_sharpness_layout = QHBoxLayout()
        self.right_sharpness_slider = QSlider(Qt.Horizontal)
        self.right_sharpness_slider.setRange(0, 100)
        self.right_sharpness_slider.setValue(50)
        self.right_sharpness_value = QLabel("50")
        self.right_sharpness_slider.valueChanged.connect(lambda v: self.right_sharpness_value.setText(str(v)))
        right_sharpness_layout.addWidget(self.right_sharpness_slider)
        right_sharpness_layout.addWidget(self.right_sharpness_value)
        right_advanced_layout.addRow("Nitidezza:", right_sharpness_layout)

        # Saturazione camera destra (solo per modalità colore)
        right_saturation_layout = QHBoxLayout()
        self.right_saturation_slider = QSlider(Qt.Horizontal)
        self.right_saturation_slider.setRange(0, 100)
        self.right_saturation_slider.setValue(50)
        self.right_saturation_value = QLabel("50")
        self.right_saturation_slider.valueChanged.connect(lambda v: self.right_saturation_value.setText(str(v)))
        right_saturation_layout.addWidget(self.right_saturation_slider)
        right_saturation_layout.addWidget(self.right_saturation_value)
        right_advanced_layout.addRow("Saturazione:", right_saturation_layout)

        # Aggiungi il gruppo avanzato
        right_cam_layout.addRow(right_advanced_group)

        # Salva i riferimenti alle righe di saturazione per poter controllare la visibilità
        self.right_saturation_row = (
            right_advanced_layout.itemAt(right_advanced_layout.rowCount() - 1, QFormLayout.LabelRole).widget(),
            right_advanced_layout.itemAt(right_advanced_layout.rowCount() - 1, QFormLayout.FieldRole).widget())

        # Collegamento tra modalità e saturazione per camera destra
        self.right_mode_color.toggled.connect(lambda checked: self._update_saturation_visibility(checked, False))
        self.right_mode_grayscale.toggled.connect(
            lambda checked: self._update_saturation_visibility(not checked, False))

        return left_cam_tab, right_cam_tab

    def _update_saturation_visibility(self, visible: bool, is_left_camera: bool):
        """
        Aggiorna la visibilità del controllo saturazione in base alla modalità della camera.

        Args:
            visible: True per mostrare, False per nascondere
            is_left_camera: True per camera sinistra, False per destra
        """
        if is_left_camera:
            # Usa i riferimenti diretti salvati durante l'inizializzazione
            label, widget = self.left_saturation_row
            if label and widget:
                label.setVisible(visible)
                widget.setVisible(visible)
        else:
            # Usa i riferimenti diretti salvati durante l'inizializzazione
            label, widget = self.right_saturation_row
            if label and widget:
                label.setVisible(visible)
                widget.setVisible(visible)

    def _connect_signals(self):
        """Collega i segnali."""
        # Segnali delle opzioni di visualizzazione già collegati in _setup_ui
        pass

    @Slot()
    def _update_visualization_options(self):
        """Aggiorna le opzioni di visualizzazione."""
        show_grid = self.grid_checkbox.isChecked()
        show_features = self.features_checkbox.isChecked()
        enhance_contrast = self.enhance_checkbox.isChecked()

        # Configura opzioni negli StreamView
        for view in self.stream_views:
            view.set_visualization_options(show_grid, show_features, enhance_contrast)

    def _on_toggle_stream_clicked(self):
        """Gestisce il clic sul pulsante avvia/ferma streaming."""
        if self._streaming:
            # Ferma lo streaming
            self.stop_streaming()
            self.toggle_stream_button.setText("Avvia Streaming")
        else:
            # Avvia lo streaming
            if self._scanner:
                success = self.start_streaming(self._scanner)
                if success:
                    self.toggle_stream_button.setText("Ferma Streaming")

    """def _on_start_scan_clicked(self):
        #Gestisce il clic sul pulsante Avvia Scansione.
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
        logger.info(f"Avvio scansione: {scan_name}, tipo: {scan_type}, risoluzione: {resolution}, qualità: {quality}")

        # Mostra un messaggio che indica che la scansione è in corso
        QMessageBox.information(
            self,
            "Scansione in corso",
            f"Scansione '{scan_name}' in corso.\nQuesta funzionalità è in fase di sviluppo."
        )

        # Abilita il pulsante di salvataggio
        self.save_scan_button.setEnabled(True)"""

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

    # !/usr/bin/env python3
    # -*- coding: utf-8 -*-

    """
    Correzione per il crash durante il cambio di modalità colore/scala di grigi.
    Sostituire questa parte nella classe StreamingView in client/views/streaming_view.py
    """

    def _apply_camera_settings(self):
        """
        Applica le impostazioni delle camere con sincronizzazione robusta delle modalità.
        """
        if not self.selected_scanner or not self.scanner_controller or not self.scanner_controller.is_connected(
                self.selected_scanner.device_id):
            QMessageBox.warning(
                self,
                "Errore",
                "Per applicare le impostazioni è necessario essere connessi a uno scanner."
            )
            return

        # Prima di tutto, valida che entrambe le modalità siano identiche
        left_mode = "color" if self.left_mode_color.isChecked() else "grayscale"
        right_mode = "color" if self.right_mode_color.isChecked() else "grayscale"

        # Forza automaticamente la sincronizzazione delle modalità
        if left_mode != right_mode:
            logger.info(f"Sincronizzazione automatica delle modalità: {left_mode} → entrambe le camere")

            # Imposta entrambe le camere alla stessa modalità (quella sinistra)
            if left_mode == "color":
                self.right_mode_color.setChecked(True)
                self.right_mode_grayscale.setChecked(False)
            else:
                self.right_mode_color.setChecked(False)
                self.right_mode_grayscale.setChecked(True)

            right_mode = left_mode

            # Aggiorna la visibilità della saturazione in base alla modalità
            self._update_saturation_visibility(left_mode == "color", False)

            QMessageBox.information(
                self,
                "Sincronizzazione modalità",
                f"Le modalità delle camere sono state sincronizzate in {left_mode.upper()}.\n"
                "Per il corretto funzionamento, entrambe le camere devono utilizzare la stessa modalità."
            )

        # Raccogli tutti i parametri
        config = {
            "camera": {
                "left": {
                    "mode": left_mode,
                    "exposure": self.left_exposure_slider.value(),
                    "gain": self.left_gain_slider.value(),
                    "brightness": self.left_brightness_slider.value(),
                    "contrast": self.left_contrast_slider.value(),
                    "sharpness": self.left_sharpness_slider.value(),
                    "saturation": self.left_saturation_slider.value() if left_mode == "color" else 50
                },
                "right": {
                    "mode": right_mode,
                    "exposure": self.right_exposure_slider.value(),
                    "gain": self.right_gain_slider.value(),
                    "brightness": self.right_brightness_slider.value(),
                    "contrast": self.right_contrast_slider.value(),
                    "sharpness": self.right_sharpness_slider.value(),
                    "saturation": self.right_saturation_slider.value() if right_mode == "color" else 50
                }
            }
        }

        # Verifica se lo streaming è attivo
        streaming_was_active = hasattr(self, '_streaming_active') and self._streaming_active

        # Se lo streaming è attivo, fermalo prima di applicare le modifiche
        if streaming_was_active:
            self.stop_streaming()
            time.sleep(0.5)  # Pausa breve per assicurarsi che lo streaming sia fermato

        # Invia la configurazione con dialog di progresso
        dialog = QProgressDialog("Applicazione delle impostazioni in corso...", None, 0, 100, self)
        dialog.setWindowTitle("Attendere")
        dialog.setMinimumDuration(300)
        dialog.setValue(20)
        dialog.setCancelButton(None)  # Rimuove il pulsante di annullamento
        dialog.setWindowModality(Qt.WindowModal)
        dialog.show()

        try:
            # Invia la configurazione
            command_success = self.scanner_controller.send_command(
                self.selected_scanner.device_id,
                "SET_CONFIG",
                {"config": config}
            )

            dialog.setValue(60)
            QApplication.processEvents()

            if command_success:
                # Attendi la risposta
                response = self.scanner_controller.wait_for_response(
                    self.selected_scanner.device_id,
                    "SET_CONFIG",
                    timeout=10.0  # Timeout più lungo per il cambio di configurazione
                )

                dialog.setValue(80)
                QApplication.processEvents()

                if response and response.get("status") == "ok":
                    time.sleep(0.5)  # Breve pausa per applicare le modifiche
                    dialog.setValue(100)
                    QMessageBox.information(
                        self,
                        "Impostazioni applicate",
                        "Le impostazioni delle camere sono state applicate con successo."
                    )
                else:
                    QMessageBox.warning(
                        self,
                        "Avviso",
                        "La configurazione è stata inviata, ma non è stato possibile confermare l'applicazione."
                    )
            else:
                QMessageBox.warning(
                    self,
                    "Errore",
                    "Impossibile inviare la configurazione al server."
                )

        except Exception as e:
            logger.error(f"Errore nell'applicazione delle impostazioni: {e}")
            QMessageBox.critical(
                self,
                "Errore",
                f"Si è verificato un errore durante l'applicazione delle impostazioni:\n{str(e)}"
            )

        finally:
            # Chiudi il dialog
            dialog.close()

            # Riavvia lo streaming se era attivo
            if streaming_was_active:
                time.sleep(1.0)  # Attendi un po' prima di riavviare lo streaming
                self.start_streaming(self.selected_scanner)

    def _send_keep_alive(self):
        """
        Invia un messaggio PING periodico al server per mantenere viva la connessione.
        CORREZIONE: Migliorato con informazioni client e gestione errori.
        """
        if self._scanner and self._connection_manager:
            try:
                import socket
                # Ottieni l'IP locale
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
                s.close()

                # Invia il ping con l'IP del client
                success = self._connection_manager.send_message(
                    self._scanner.device_id,
                    "PING",
                    {
                        "timestamp": time.time(),
                        "client_ip": local_ip
                    }
                )

                if success:
                    logger.debug("Ping inviato con successo")
                else:
                    logger.warning("Impossibile inviare ping - probabile disconnessione")

                    # Se non riusciamo a inviare il ping, verifichiamo la connessione
                    if not self._connection_manager.is_connected(self._scanner.device_id):
                        logger.warning("Connessione persa durante lo streaming")
                        # Ferma lo streaming se attivo
                        if self._streaming:
                            self.stop_streaming()
            except Exception as e:
                logger.error(f"Errore nell'invio del keepalive: {e}")

    def start_streaming(self, scanner=None):
        """
        Avvia lo streaming dalle camere dello scanner.

        Args:
            scanner: Scanner da cui ricevere lo stream (opzionale, usa selected_scanner se None)
        """
        if scanner:
            self.selected_scanner = scanner

        if not self.selected_scanner:
            logger.warning("Impossibile avviare lo streaming: nessuno scanner selezionato")
            return False

        # Verifica se lo streaming è già attivo
        if hasattr(self, '_streaming_active') and self._streaming_active:
            logger.info(f"Streaming già attivo da {self.selected_scanner.name}")
            return True

        try:
            # Visualizza messaggio di stato nei log
            logger.info(f"Avvio streaming da {self.selected_scanner.name}...")

            # Ottieni le informazioni di connessione
            device_id = self.selected_scanner.device_id
            host = self.selected_scanner.ip_address
            port = self.selected_scanner.port + 1  # La porta di streaming è quella di comando + 1

            logger.info(f"Avvio streaming da {host}:{port} (Device ID: {device_id})")

            # Verifica che la connessione sia attiva
            if not self.scanner_controller.is_connected(device_id):
                # Prova a connetterti prima
                logger.info("Tentativo di connessione prima di avviare lo streaming...")
                success = self.scanner_controller.connect_to_scanner(device_id)
                if not success:
                    logger.error("Impossibile connettersi allo scanner")
                    return False

            # Inizializza il ricevitore di streaming
            try:
                if hasattr(self, 'stream_receiver') and self.stream_receiver:
                    # Stop any existing stream
                    self.stop_streaming()
                    # Release resources
                    self.stream_receiver.deleteLater()
                    self.stream_receiver = None
            except Exception as e:
                logger.error(f"Errore nella pulizia dello stream_receiver esistente: {e}")

            # Crea un nuovo ricevitore
            self.stream_receiver = StreamReceiver(host, port)

            # Configura il processore di scansione per il direct routing
            try:
                # Importa ScanFrameProcessor solo quando necessario
                from client.processing.scan_frame_processor import ScanFrameProcessor

                # Crea o ottieni il processore di frame
                if not hasattr(self, '_scan_processor') or self._scan_processor is None:
                    output_dir = Path.home() / "UnLook" / "scans"
                    output_dir.mkdir(parents=True, exist_ok=True)
                    self._scan_processor = ScanFrameProcessor(output_dir=output_dir)

                    # Configura callback per reindirizzare la visualizzazione
                    self._scan_processor.set_callbacks(
                        progress_callback=self._on_scan_progress,
                        frame_callback=self._on_scan_frame
                    )

                    # Avvia subito la scansione in modalità real-time
                    scan_id = f"RealTimeScan_{int(time.time())}"
                    self._scan_processor.start_scan(scan_id=scan_id)
                    logger.info(f"Scansione real-time avviata automaticamente: {scan_id}")

                # Configura il routing diretto
                self.stream_receiver.set_frame_processor(self._scan_processor)
                self.stream_receiver.enable_direct_routing(True)
                logger.info("Direct routing abilitato per scansione real-time")
            except Exception as e:
                logger.error(f"Errore nella configurazione della scansione real-time: {e}")

            # Collega i segnali
            self.stream_receiver.frame_received.connect(self._on_frame_received)
            self.stream_receiver.connected.connect(self._on_stream_connected)
            self.stream_receiver.disconnected.connect(self._on_stream_disconnected)
            self.stream_receiver.error.connect(self._on_stream_error)  # Ora con firma corretta

            # Invia il comando di avvio dello streaming
            command_success = self.scanner_controller.send_command(
                device_id,
                "START_STREAM",
                {
                    "dual_camera": True,
                    "quality": 90,
                    "target_fps": 30
                }
            )

            if not command_success:
                logger.error("Impossibile inviare il comando START_STREAM")
                return False

            # Attendi la risposta
            response = self.scanner_controller.wait_for_response(
                device_id,
                "START_STREAM",
                timeout=5.0
            )

            if not response or response.get("status") != "ok":
                error_msg = "Errore risposta server" if not response else response.get("message", "Errore sconosciuto")
                logger.error(f"Risposta START_STREAM non valida: {error_msg}")
                return False

            # Avvia il ricevitore di streaming
            self.stream_receiver.start()

            # Imposta lo stato di streaming attivo
            self._streaming_active = True

            # Aggiorna lo stato dello scanner
            if self.selected_scanner.status != ScannerStatus.STREAMING:
                self.selected_scanner.status = ScannerStatus.STREAMING

            # Avvia il timer per il monitoraggio FPS se esiste
            if hasattr(self, '_fps_timer'):
                self._fps_timer.start(1000)  # Aggiorna una volta al secondo

            # Resetta i contatori FPS se esistono
            if hasattr(self, '_frame_count_left'):
                self._frame_count_left = 0
            if hasattr(self, '_frame_count_right'):
                self._frame_count_right = 0
            if hasattr(self, '_last_fps_update'):
                self._last_fps_update = time.time()

            # Aggiorna l'interfaccia del pannello di controllo se esiste
            if hasattr(self, 'control_panel') and hasattr(self.control_panel, 'streaming_button'):
                self.control_panel.streaming_button.setText("Ferma Stream")

            logger.info(f"Streaming avviato con successo da {self.selected_scanner.name}")
            return True

        except Exception as e:
            logger.error(f"Errore nell'avvio dello streaming: {e}")
            # Assicurati che lo stato sia coerente
            self._streaming_active = False
            return False

    def is_streaming(self):
        """
        Verifica se lo streaming è attualmente attivo.

        Returns:
            bool: True se lo streaming è attivo, False altrimenti
        """
        return hasattr(self, '_streaming_active') and self._streaming_active

    def _start_actual_streaming(self) -> bool:
        """
        Avvia effettivamente lo streaming dopo che la connessione è stata stabilita.
        Versione migliorata per supportare entrambe le camere e ridurre il lag.

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

            # Abilita la modalità ad alte prestazioni per ridurre il lag
            if hasattr(stream_receiver, 'set_high_performance'):
                stream_receiver.set_high_performance(True)
                logger.info("Modalità ad alte prestazioni attivata per lo streaming")

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

            # Invia un messaggio al server per avviare lo streaming con parametri ottimizzati
            streaming_config = {
                "target_fps": 30,  # Target FPS desiderato
                "quality": 85,  # Qualità JPEG ottimizzata per bilanciare qualità e latenza
                "dual_camera": True  # Richiedi esplicitamente entrambe le camere
            }

            if not self._connection_manager.send_message(
                    self._scanner.device_id,
                    "START_STREAM",
                    streaming_config
            ):
                logger.error(f"Errore nell'invio del comando START_STREAM a {self._scanner.name}")
                stream_receiver.stop()
                self._stream_receiver = None
                return False

            # Cambia lo stato dello scanner
            self._scanner.status = ScannerStatus.STREAMING

            # Imposta lo stato di streaming
            self._streaming = True
            logger.info(
                f"Streaming avviato da {self._scanner.name} con target FPS={streaming_config['target_fps']}, quality={streaming_config['quality']}")

            # Aggiorna i pulsanti dell'interfaccia
            self._update_ui_buttons()

            # Indica l'inizio dello streaming nelle etichette
            for view in self.stream_views:
                camera_name = "Sinistra" if view.camera_index == 0 else "Destra"
                view.info_label.setText(f"Camera {camera_name} | Connessione in corso...")

            # Imposta un timer per verificare se entrambe le camere sono attive
            self._camera_check_timer = QTimer(self)
            self._camera_check_timer.timeout.connect(self._check_dual_camera)
            self._camera_check_timer.setSingleShot(True)
            self._camera_check_timer.start(5000)  # Verifica dopo 5 secondi

            return True
        except Exception as e:
            logger.error(f"Errore nell'avvio dello streaming: {str(e)}")
            return False

    def _check_dual_camera(self):
        """
        Verifica se entrambe le camere sono attive.
        Se solo una camera è attiva, mostra un avviso.
        """
        if not self._streaming or not self._stream_receiver:
            return

        # Controlla quali camere sono attive nel ricevitore
        cameras_active = getattr(self._stream_receiver, '_cameras_active', set())

        if cameras_active and len(cameras_active) == 1:
            # Solo una camera è attiva
            active_camera = list(cameras_active)[0]
            missing_camera = 1 if active_camera == 0 else 0
            camera_name = "sinistra" if missing_camera == 0 else "destra"

            logger.warning(
                f"Solo la camera {active_camera} è attiva. La camera {missing_camera} ({camera_name}) non sta inviando dati.")

            # Mostra un messaggio all'utente
            QMessageBox.warning(
                self,
                "Avviso camera",
                f"Solo una camera è attiva. La camera {camera_name} non sta inviando dati.\n\n"
                "Verifica che entrambe le camere siano collegate correttamente al Raspberry Pi."
            )
        elif not cameras_active:
            logger.warning("Nessuna camera sta inviando dati.")

            # Mostra un messaggio all'utente
            QMessageBox.warning(
                self,
                "Avviso camera",
                "Nessuna camera sta inviando dati.\n\n"
                "Verifica che le camere siano collegate correttamente al Raspberry Pi."
            )

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

            # Abilita il pulsante di streaming
            self.toggle_stream_button.setEnabled(True)

            # Aggiorna pulsanti di interfaccia
            self._update_ui_buttons()

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

    def _update_ui_buttons(self):
        """Aggiorna lo stato dei pulsanti in base allo stato corrente."""
        is_connected = self._scanner and self._scanner.status in (ScannerStatus.CONNECTED, ScannerStatus.STREAMING)
        is_streaming = self._streaming

        self.toggle_stream_button.setEnabled(is_connected)
        self.toggle_stream_button.setText("Ferma Streaming" if is_streaming else "Avvia Streaming")

        self.capture_button.setEnabled(is_streaming)
        """self.start_scan_button.setEnabled(is_streaming)
        self.save_scan_button.setEnabled(False)"""
        self.apply_settings_button.setEnabled(is_connected)

    def stop_streaming(self):
        """
        Ferma lo streaming in modo sicuro con gestione migliorata delle risorse.

        Returns:
            bool: True se lo stop è avvenuto con successo, False altrimenti
        """
        if not hasattr(self, '_streaming_active') or not self._streaming_active:
            logger.debug("Streaming non attivo, nessuna azione necessaria")
            return True

        logger.info("Arresto dello streaming...")

        try:
            # Invia comando di stop solo se c'è uno scanner selezionato e connesso
            if self.selected_scanner and self.scanner_controller.is_connected(self.selected_scanner.device_id):
                # Invia il comando STOP_STREAM
                command_success = self.scanner_controller.send_command(
                    self.selected_scanner.device_id,
                    "STOP_STREAM"
                )

                if not command_success:
                    logger.warning("Impossibile inviare il comando STOP_STREAM")
                else:
                    logger.info("Comando STOP_STREAM inviato con successo")

                # Aggiorna lo stato dello scanner (anche se il comando fallisce)
                if self.selected_scanner.status == ScannerStatus.STREAMING:
                    self.selected_scanner.status = ScannerStatus.CONNECTED

            # Ferma il ricevitore di streaming in modo sicuro
            if hasattr(self, 'stream_receiver') and self.stream_receiver:
                try:
                    # Disconnetti i segnali prima di fermare il ricevitore
                    try:
                        self.stream_receiver.frame_received.disconnect()
                        self.stream_receiver.connected.disconnect()
                        self.stream_receiver.disconnected.disconnect()
                        self.stream_receiver.error.disconnect()
                    except Exception as e:
                        logger.debug(f"Errore nella disconnessione dei segnali: {e}")

                    # Ferma il ricevitore
                    self.stream_receiver.stop()

                    # Non eseguire deleteLater qui, potrebbe causare crash
                except Exception as e:
                    logger.error(f"Errore nell'arresto del ricevitore: {e}")

            # Ferma il timer FPS
            if hasattr(self, '_fps_timer') and self._fps_timer.isActive():
                self._fps_timer.stop()

            # Svuota le etichette video se esistono
            if hasattr(self, 'left_video_label'):
                self.left_video_label.clear()
            if hasattr(self, 'right_video_label'):
                self.right_video_label.clear()

            # Pulisci le label FPS se esistono
            if hasattr(self, 'fps_label_left'):
                self.fps_label_left.setText("0 FPS")
            if hasattr(self, 'fps_label_right'):
                self.fps_label_right.setText("0 FPS")

            # Aggiorna lo stato di streaming
            self._streaming_active = False

            # Aggiorna l'interfaccia
            if hasattr(self, 'control_panel') and hasattr(self.control_panel, 'streaming_button'):
                self.control_panel.streaming_button.setText("Avvia Stream")

            logger.info("Streaming arrestato con successo")
            return True

        except Exception as e:
            logger.error(f"Errore nell'arresto dello streaming: {e}")
            # Assicurati che lo stato sia coerente anche in caso di errore
            self._streaming_active = False
            return False

    def is_streaming(self):
        """
        Verifica se lo streaming è attualmente attivo.

        Returns:
            bool: True se lo streaming è attivo, False altrimenti
        """
        return hasattr(self, '_streaming_active') and self._streaming_active

    @Slot(int, np.ndarray, float)
    def _on_frame_received(self, camera_index: int, frame: np.ndarray, timestamp: float):
        """
        Gestisce l'arrivo di un nuovo frame.
        Versione ottimizzata per ridurre la latenza.
        """
        try:
            # Verifiche preliminari rapide per evitare elaborazioni inutili
            if frame is None or frame.size == 0:
                return

            # Verifica se l'indice della camera è valido
            if camera_index < 0 or camera_index >= len(self.stream_views):
                return

            # Incrementa contatore frame (solo ogni 100 frame per debug)
            if not hasattr(self, '_frame_counter'):
                self._frame_counter = [0, 0]

            self._frame_counter[camera_index] += 1

            # Log limitato per ridurre overhead
            if self._frame_counter[camera_index] % 100 == 0:
                logger.debug(f"Frame #{self._frame_counter[camera_index]} ricevuto per camera {camera_index}")

            # Calcolo latenza (con verifica validità timestamp)
            if timestamp > 0:
                latency_ms = int((time.time() - timestamp) * 1000)
                # Log solo in caso di latenza anomala (> 500ms)
                if latency_ms > 500 and self._frame_counter[camera_index] % 30 == 0:
                    logger.warning(f"Latenza elevata per camera {camera_index}: {latency_ms}ms")

            # Passa il frame direttamente alla view specifica (senza copie aggiuntive)
            self.stream_views[camera_index].update_frame(frame, timestamp)

        except Exception as e:
            logger.error(f"Errore in _on_frame_received: {e}")

    @Slot(int)
    def _on_stream_started(self, camera_index: int):
        """Gestisce l'evento di avvio dello stream per una camera."""
        logger.info(f"Stream avviato per camera {camera_index}")

        # Aggiorna lo stato visivo della camera
        camera_name = "Sinistra" if camera_index == 0 else "Destra"
        if camera_index < len(self.stream_views):
            self.stream_views[camera_index].info_label.setText(f"Camera {camera_name} | Connessa")

    @Slot()
    def _on_stream_connected(self):
        """Gestisce l'evento di connessione dello stream."""
        logger.info("Stream connesso")

        # Aggiorna l'interfaccia utente
        for i, view in enumerate(self.stream_views):
            camera_name = "Sinistra" if i == 0 else "Destra"
            view.info_label.setText(f"Camera {camera_name} | Connessione stabilita")

        # Aggiorna lo stato
        self._streaming_active = True
        self.toggle_stream_button.setText("Ferma Streaming")
        self.capture_button.setEnabled(True)

    @Slot()
    def _on_stream_disconnected(self):
        """Gestisce l'evento di disconnessione dello stream."""
        logger.info("Stream disconnesso")

        # Aggiorna lo stato solo se lo streaming era attivo
        if hasattr(self, '_streaming_active') and self._streaming_active:
            self._streaming_active = False
            self.toggle_stream_button.setText("Avvia Streaming")
            self.capture_button.setEnabled(False)

            # Pulisci le visualizzazioni delle camere
            for view in self.stream_views:
                view.clear()

    @Slot(int)
    def _on_stream_stopped(self, camera_index: int):
        """Gestisce l'evento di arresto dello stream per una camera."""
        logger.info(f"Stream fermato per camera {camera_index}")

        # Aggiorna lo stato visivo della camera
        camera_name = "Sinistra" if camera_index == 0 else "Destra"
        if camera_index < len(self.stream_views):
            self.stream_views[camera_index].info_label.setText(f"Camera {camera_name} | Disconnessa")

    @Slot(str)
    def _on_stream_error(self, error: str):
        """Gestisce gli errori dello stream."""
        logger.error(f"Errore nello stream: {error}")

        # Aggiorna lo stato visivo di entrambe le camere dato che non sappiamo quale ha generato l'errore
        for camera_index, view in enumerate(self.stream_views):
            camera_name = "Sinistra" if camera_index == 0 else "Destra"
            view.info_label.setText(f"Camera {camera_name} | ERRORE")
            view.lag_label.setText(f"Errore: {error[:20]}...")
            view.lag_label.setStyleSheet("color: red; font-weight: bold;")

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