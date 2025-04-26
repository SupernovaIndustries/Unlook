#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Widget per la gestione e visualizzazione delle scansioni 3D con UnLook.
Gestisce l'avvio della scansione, il download dei dati, la triangolazione e la visualizzazione.
"""

import logging
import time
import os
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFileDialog,
    QGroupBox, QFormLayout, QComboBox, QSlider, QCheckBox, QMessageBox,
    QSpinBox, QDoubleSpinBox, QFrame, QSplitter, QTabWidget, QRadioButton,
    QButtonGroup, QLineEdit, QProgressBar, QToolButton, QDialog, QScrollArea,
    QTextEdit
)
from PySide6.QtCore import Qt, Signal, Slot, QTimer, QSize, QSettings
from PySide6.QtGui import QIcon, QFont, QColor, QPixmap, QImage

# Importa il modulo di triangolazione
try:
    from client.processing.triangulation import ScanProcessor, PatternType
except ImportError:
    logger = logging.getLogger(__name__)
    logger.error("Impossibile importare il modulo di triangolazione. La visualizzazione 3D sarà disabilitata.")


    # Classi mock per quando il modulo non è disponibile
    class PatternType:
        PROGRESSIVE = "PROGRESSIVE"
        GRAY_CODE = "GRAY_CODE"
        BINARY_CODE = "BINARY_CODE"
        PHASE_SHIFT = "PHASE_SHIFT"


    class ScanProcessor:
        def __init__(self, *args, **kwargs):
            pass

# Verifica se Open3D è disponibile per la visualizzazione 3D
try:
    import open3d as o3d

    OPEN3D_AVAILABLE = True
except ImportError:
    OPEN3D_AVAILABLE = False

# Verifica se OpenCV è disponibile per la visualizzazione delle immagini
try:
    import cv2
    import numpy as np

    OPENCV_AVAILABLE = True
except ImportError:
    OPENCV_AVAILABLE = False

# Configura logging
logger = logging.getLogger(__name__)


class ScanOptionsDialog(QDialog):
    """Dialog per configurare le opzioni di scansione."""

    def __init__(self, parent=None, current_config=None):
        super().__init__(parent)
        self.setWindowTitle("Opzioni di Scansione 3D")
        self.setMinimumWidth(400)

        # Inizializza con configurazione corrente o default
        self.config = current_config or {
            "pattern_type": "PROGRESSIVE",
            "num_patterns": 12,
            "exposure_time": 0.5,
            "quality": 3
        }

        # Configura l'interfaccia
        self._setup_ui()
        self._update_ui_from_config()

    def _setup_ui(self):
        """Configura l'interfaccia del dialog."""
        layout = QVBoxLayout(self)

        # Gruppo principale per le opzioni
        options_group = QGroupBox("Parametri di Scansione")
        form_layout = QFormLayout(options_group)

        # Tipo di pattern
        self.pattern_type_combo = QComboBox()
        self.pattern_type_combo.addItem("Pattern Progressivi", "PROGRESSIVE")
        self.pattern_type_combo.addItem("Gray Code", "GRAY_CODE")
        self.pattern_type_combo.addItem("Binary Code", "BINARY_CODE")
        self.pattern_type_combo.addItem("Phase Shift", "PHASE_SHIFT")
        form_layout.addRow("Tipo di Pattern:", self.pattern_type_combo)

        # Numero di pattern
        self.num_patterns_spin = QSpinBox()
        self.num_patterns_spin.setRange(4, 24)
        self.num_patterns_spin.setSingleStep(2)
        self.num_patterns_spin.setToolTip("Numero di pattern per direzione (orizzontale/verticale)")
        form_layout.addRow("Numero di Pattern:", self.num_patterns_spin)

        # Tempo di esposizione
        self.exposure_spin = QDoubleSpinBox()
        self.exposure_spin.setRange(0.1, 2.0)
        self.exposure_spin.setSingleStep(0.1)
        self.exposure_spin.setDecimals(1)
        self.exposure_spin.setSuffix(" sec")
        form_layout.addRow("Tempo di Esposizione:", self.exposure_spin)

        # Qualità
        quality_layout = QHBoxLayout()
        self.quality_slider = QSlider(Qt.Horizontal)
        self.quality_slider.setRange(1, 5)
        self.quality_slider.setTickPosition(QSlider.TicksBelow)
        self.quality_slider.setTickInterval(1)

        self.quality_label = QLabel("3")
        self.quality_slider.valueChanged.connect(lambda v: self.quality_label.setText(str(v)))

        quality_layout.addWidget(self.quality_slider)
        quality_layout.addWidget(self.quality_label)
        form_layout.addRow("Qualità:", quality_layout)

        layout.addWidget(options_group)

        # Pulsanti di azione
        button_layout = QHBoxLayout()
        self.cancel_button = QPushButton("Annulla")
        self.cancel_button.clicked.connect(self.reject)

        self.ok_button = QPushButton("OK")
        self.ok_button.clicked.connect(self.accept)
        self.ok_button.setDefault(True)

        button_layout.addStretch(1)
        button_layout.addWidget(self.cancel_button)
        button_layout.addWidget(self.ok_button)

        layout.addLayout(button_layout)

    def _update_ui_from_config(self):
        """Aggiorna l'interfaccia in base alla configurazione."""
        # Imposta tipo di pattern
        index = self.pattern_type_combo.findData(self.config.get("pattern_type", "PROGRESSIVE"))
        if index >= 0:
            self.pattern_type_combo.setCurrentIndex(index)

        # Imposta numero di pattern
        self.num_patterns_spin.setValue(self.config.get("num_patterns", 12))

        # Imposta tempo di esposizione
        self.exposure_spin.setValue(self.config.get("exposure_time", 0.5))

        # Imposta qualità
        self.quality_slider.setValue(self.config.get("quality", 3))
        self.quality_label.setText(str(self.quality_slider.value()))

    def get_config(self):
        """Restituisce la configurazione corrente."""
        return {
            "pattern_type": self.pattern_type_combo.currentData(),
            "num_patterns": self.num_patterns_spin.value(),
            "exposure_time": self.exposure_spin.value(),
            "quality": self.quality_slider.value()
        }


class PointCloudViewerDialog(QDialog):
    """Dialog per visualizzare la nuvola di punti 3D."""

    def __init__(self, parent=None, pointcloud_path=None, screenshot_path=None):
        super().__init__(parent)
        self.setWindowTitle("Visualizzatore Nuvola di Punti 3D")
        self.setMinimumSize(800, 600)

        self.pointcloud_path = pointcloud_path
        self.screenshot_path = screenshot_path

        # Configura l'interfaccia
        self._setup_ui()

        # Carica la nuvola di punti se disponibile
        if pointcloud_path and OPEN3D_AVAILABLE:
            self.load_pointcloud(pointcloud_path)

    def _setup_ui(self):
        """Configura l'interfaccia del visualizzatore."""
        layout = QVBoxLayout(self)

        # Se Open3D è disponibile, mostreremo un'immagine della nuvola di punti
        # altrimenti solo un messaggio informativo
        if OPEN3D_AVAILABLE:
            if self.screenshot_path and os.path.exists(self.screenshot_path):
                # Mostra lo screenshot della nuvola di punti
                self.image_label = QLabel()
                self.image_label.setAlignment(Qt.AlignCenter)
                pixmap = QPixmap(self.screenshot_path)
                self.image_label.setPixmap(pixmap.scaled(
                    self.width(), self.height(),
                    Qt.KeepAspectRatio, Qt.SmoothTransformation
                ))
                layout.addWidget(self.image_label)
            else:
                # Crea un placeholder per l'immagine
                self.image_label = QLabel("Caricamento nuvola di punti in corso...")
                self.image_label.setAlignment(Qt.AlignCenter)
                layout.addWidget(self.image_label)
        else:
            # Open3D non disponibile
            info_label = QLabel(
                "La visualizzazione 3D richiede Open3D.\n"
                "Installa Open3D con: pip install open3d"
            )
            info_label.setAlignment(Qt.AlignCenter)
            info_label.setStyleSheet("color: #666;")
            layout.addWidget(info_label)

        # Informazioni sulla nuvola di punti
        if self.pointcloud_path:
            info_text = f"File: {os.path.basename(self.pointcloud_path)}\n"
            if os.path.exists(self.pointcloud_path):
                info_text += f"Dimensione: {os.path.getsize(self.pointcloud_path) / 1024:.1f} KB\n"

                # Se Open3D è disponibile, aggiungi informazioni sul numero di punti
                if OPEN3D_AVAILABLE:
                    try:
                        pcd = o3d.io.read_point_cloud(self.pointcloud_path)
                        num_points = len(pcd.points)
                        info_text += f"Numero di punti: {num_points:,}\n"
                    except:
                        pass
            else:
                info_text += "File non trovato\n"

            info_label = QLabel(info_text)
            info_label.setAlignment(Qt.AlignCenter)
            layout.addWidget(info_label)

        # Pulsanti di azione
        button_layout = QHBoxLayout()

        # Pulsante per aprire la nuvola di punti con software esterno
        if self.pointcloud_path and os.path.exists(self.pointcloud_path):
            self.open_external_button = QPushButton("Apri con Software Esterno")
            self.open_external_button.clicked.connect(self._open_pointcloud_external)
            button_layout.addWidget(self.open_external_button)

        # Pulsante per aprire la directory
        if self.pointcloud_path:
            self.open_dir_button = QPushButton("Apri Directory")
            self.open_dir_button.clicked.connect(self._open_directory)
            button_layout.addWidget(self.open_dir_button)

        # Pulsante di chiusura
        self.close_button = QPushButton("Chiudi")
        self.close_button.clicked.connect(self.accept)
        button_layout.addWidget(self.close_button)

        layout.addLayout(button_layout)

    def load_pointcloud(self, pointcloud_path):
        """Carica e visualizza la nuvola di punti."""
        if not OPEN3D_AVAILABLE:
            return

        try:
            # Carica la nuvola di punti
            pcd = o3d.io.read_point_cloud(pointcloud_path)

            # Visualizza la nuvola e genera uno screenshot
            vis = o3d.visualization.Visualizer()
            vis.create_window(visible=False)
            vis.add_geometry(pcd)

            # Aggiungi un sistema di coordinate per riferimento
            coord_frame = o3d.geometry.TriangleMesh.create_coordinate_frame(size=20)
            vis.add_geometry(coord_frame)

            # Ottimizza la vista
            vis.get_render_option().point_size = 2.0
            vis.get_render_option().background_color = np.array([0.9, 0.9, 0.9])
            vis.get_view_control().set_zoom(0.8)
            vis.poll_events()
            vis.update_renderer()

            # Salva lo screenshot se non è già stato specificato
            if not self.screenshot_path:
                self.screenshot_path = os.path.join(
                    os.path.dirname(pointcloud_path),
                    os.path.basename(pointcloud_path).replace(".ply", "_preview.png")
                )

            # Cattura e salva lo screenshot
            vis.capture_screen_image(self.screenshot_path)
            vis.destroy_window()

            # Aggiorna l'immagine nell'interfaccia
            if hasattr(self, "image_label"):
                pixmap = QPixmap(self.screenshot_path)
                self.image_label.setPixmap(pixmap.scaled(
                    self.width(), self.height(),
                    Qt.KeepAspectRatio, Qt.SmoothTransformation
                ))

        except Exception as e:
            logger.error(f"Errore nella visualizzazione della nuvola di punti: {e}")
            if hasattr(self, "image_label"):
                self.image_label.setText(f"Errore nel caricamento della nuvola di punti:\n{str(e)}")

    def resizeEvent(self, event):
        """Gestisce il ridimensionamento della finestra."""
        super().resizeEvent(event)

        # Ridimensiona l'immagine se disponibile
        if hasattr(self, "image_label") and self.screenshot_path and os.path.exists(self.screenshot_path):
            pixmap = QPixmap(self.screenshot_path)
            self.image_label.setPixmap(pixmap.scaled(
                self.width(), self.height(),
                Qt.KeepAspectRatio, Qt.SmoothTransformation
            ))

    def _open_pointcloud_external(self):
        """Apre la nuvola di punti con un software esterno."""
        if not self.pointcloud_path or not os.path.exists(self.pointcloud_path):
            return

        try:
            import platform
            import subprocess

            if platform.system() == "Windows":
                os.startfile(self.pointcloud_path)
            elif platform.system() == "Darwin":  # macOS
                subprocess.call(["open", self.pointcloud_path])
            else:  # Assume Linux
                subprocess.call(["xdg-open", self.pointcloud_path])
        except Exception as e:
            logger.error(f"Errore nell'apertura del file con software esterno: {e}")
            QMessageBox.warning(
                self,
                "Errore",
                f"Impossibile aprire il file con un software esterno:\n{str(e)}"
            )

    def _open_directory(self):
        """Apre la directory contenente la nuvola di punti."""
        if not self.pointcloud_path:
            return

        try:
            directory = os.path.dirname(self.pointcloud_path)

            import platform
            import subprocess

            if platform.system() == "Windows":
                os.startfile(directory)
            elif platform.system() == "Darwin":  # macOS
                subprocess.call(["open", directory])
            else:  # Assume Linux
                subprocess.call(["xdg-open", directory])
        except Exception as e:
            logger.error(f"Errore nell'apertura della directory: {e}")
            QMessageBox.warning(
                self,
                "Errore",
                f"Impossibile aprire la directory:\n{str(e)}"
            )


class LogViewerDialog(QDialog):
    """Dialog per visualizzare i log della scansione."""

    def __init__(self, parent=None, log_text=""):
        super().__init__(parent)
        self.setWindowTitle("Log della Scansione")
        self.setMinimumSize(600, 400)

        layout = QVBoxLayout(self)

        # Area di testo per i log
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setPlainText(log_text)
        layout.addWidget(self.log_text)

        # Pulsante di chiusura
        button_layout = QHBoxLayout()
        self.close_button = QPushButton("Chiudi")
        self.close_button.clicked.connect(self.accept)
        button_layout.addStretch(1)
        button_layout.addWidget(self.close_button)

        layout.addLayout(button_layout)

    def append_log(self, text):
        """Aggiunge testo al log."""
        current_text = self.log_text.toPlainText()
        new_text = current_text + "\n" + text if current_text else text
        self.log_text.setPlainText(new_text)
        # Scrolla alla fine
        self.log_text.moveCursor(self.log_text.textCursor().End)


class ScanView(QWidget):
    """
    Widget principale per la gestione delle scansioni 3D.
    Permette di avviare scansioni, configurare parametri,
    scegliere directory di output e visualizzare risultati.
    """

    # Segnali
    scan_started = Signal(dict)  # Configurazione scansione
    scan_completed = Signal(str)  # Percorso della scansione
    scan_failed = Signal(str)  # Messaggio di errore

    def __init__(self, scanner_controller=None, parent=None):
        super().__init__(parent)
        self.scanner_controller = scanner_controller

        # Stato della scansione
        self.is_scanning = False
        self.selected_scanner = None
        self.current_scan_id = None
        self.scan_log = ""

        # Processor per la triangolazione
        self.scan_processor = ScanProcessor()

        # Directory di output per le scansioni e nuvole di punti
        self.output_dir = self._get_default_output_dir()

        # Configurazione della scansione
        self.scan_config = {
            "pattern_type": "PROGRESSIVE",
            "num_patterns": 12,
            "exposure_time": 0.5,
            "quality": 3
        }

        # Configura l'interfaccia
        self._setup_ui()

        # Timer per aggiornare lo stato periodicamente
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self._update_scan_status)
        self.status_timer.start(1000)  # Aggiorna ogni secondo

        # Aggiungi un timer per il controllo della connessione
        self.connection_timer = QTimer(self)
        self.connection_timer.timeout.connect(self._check_connection_status)
        self.connection_timer.start(2000)  # Controlla ogni 2 secondi

    def _check_connection_status(self):
        """Controlla periodicamente lo stato della connessione."""
        if self.scanner_controller and self.selected_scanner:
            # Verifica direttamente con il connection manager invece di usare scanner.status
            is_connected = self.scanner_controller.is_connected(self.selected_scanner.device_id)

            # Aggiorna l'interfaccia solo se lo stato è cambiato
            if self.start_scan_button.isEnabled() != is_connected:
                self.start_scan_button.setEnabled(is_connected)

                if is_connected:
                    self.status_label.setText(f"Connesso a {self.selected_scanner.name}")
                else:
                    self.status_label.setText("Scanner non connesso")

                    # Se stiamo eseguendo una scansione ma lo scanner è disconnesso, ferma la scansione
                    if self.is_scanning:
                        self._handle_scan_error("Connessione con lo scanner persa")
    def _setup_ui(self):
        """Configura l'interfaccia utente."""
        # Layout principale
        main_layout = QVBoxLayout(self)

        # Sezione superiore: configurazione e controlli
        top_section = QWidget()
        top_layout = QHBoxLayout(top_section)

        # Riquadro sinistro: Configurazione
        config_group = QGroupBox("Configurazione Scansione")
        config_layout = QFormLayout(config_group)

        # Selettore directory di output
        output_dir_layout = QHBoxLayout()
        self.output_dir_edit = QLineEdit(str(self.output_dir))
        self.output_dir_edit.setReadOnly(True)

        self.browse_button = QToolButton()
        self.browse_button.setText("...")
        self.browse_button.clicked.connect(self._select_output_dir)

        output_dir_layout.addWidget(self.output_dir_edit)
        output_dir_layout.addWidget(self.browse_button)

        config_layout.addRow("Directory di Output:", output_dir_layout)

        # Nome della scansione
        self.scan_name_edit = QLineEdit()
        self.scan_name_edit.setText(f"Scan_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        config_layout.addRow("Nome Scansione:", self.scan_name_edit)

        # Tipo di pattern (mostra solo la selezione corrente)
        self.pattern_type_label = QLabel(self._get_pattern_type_name(self.scan_config["pattern_type"]))
        config_layout.addRow("Tipo di Pattern:", self.pattern_type_label)

        # Numero di pattern
        self.num_patterns_label = QLabel(str(self.scan_config["num_patterns"]))
        config_layout.addRow("Numero di Pattern:", self.num_patterns_label)

        # Pulsante per modificare le opzioni avanzate
        self.options_button = QPushButton("Opzioni Avanzate...")
        self.options_button.clicked.connect(self._show_options_dialog)
        config_layout.addRow("", self.options_button)

        top_layout.addWidget(config_group)

        # Riquadro destro: Controlli
        controls_group = QGroupBox("Controlli Scansione")
        controls_layout = QVBoxLayout(controls_group)

        # Stato corrente
        self.status_label = QLabel("Pronto")
        self.status_label.setAlignment(Qt.AlignCenter)
        controls_layout.addWidget(self.status_label)

        # Barra di progresso
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        controls_layout.addWidget(self.progress_bar)

        # Pulsanti di azione
        action_layout = QHBoxLayout()

        self.start_scan_button = QPushButton("Avvia Scansione")
        self.start_scan_button.clicked.connect(self._start_scan)
        self.start_scan_button.setEnabled(False)  # Disabilitato finché non viene selezionato uno scanner

        self.stop_scan_button = QPushButton("Ferma Scansione")
        self.stop_scan_button.clicked.connect(self._stop_scan)
        self.stop_scan_button.setEnabled(False)  # Disabilitato finché non è in corso una scansione

        action_layout.addWidget(self.start_scan_button)
        action_layout.addWidget(self.stop_scan_button)

        controls_layout.addLayout(action_layout)

        # Pulsanti per il post-scansione
        post_scan_layout = QHBoxLayout()

        self.process_button = QPushButton("Elabora Scansione")
        self.process_button.clicked.connect(self._process_scan)
        self.process_button.setEnabled(False)  # Disabilitato finché non c'è una scansione completata

        self.view_log_button = QPushButton("Visualizza Log")
        self.view_log_button.clicked.connect(self._show_log_dialog)
        self.view_log_button.setEnabled(False)  # Disabilitato finché non c'è una scansione completata

        post_scan_layout.addWidget(self.process_button)
        post_scan_layout.addWidget(self.view_log_button)

        controls_layout.addLayout(post_scan_layout)

        top_layout.addWidget(controls_group)

        main_layout.addWidget(top_section)

        # Separatore
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        main_layout.addWidget(separator)

        # Sezione inferiore: Risultati della scansione
        self.results_group = QGroupBox("Risultati della Scansione")
        results_layout = QVBoxLayout(self.results_group)

        # Area con scroll per le informazioni sulla scansione e immagini
        results_scroll = QScrollArea()
        results_scroll.setWidgetResizable(True)
        results_scroll.setMinimumHeight(200)

        results_content = QWidget()
        self.results_content_layout = QVBoxLayout(results_content)

        # Placeholder iniziale
        placeholder_label = QLabel(
            "Nessuna scansione disponibile. Avvia una nuova scansione per visualizzare i risultati.")
        placeholder_label.setAlignment(Qt.AlignCenter)
        placeholder_label.setStyleSheet("color: #666;")
        self.results_content_layout.addWidget(placeholder_label)

        results_scroll.setWidget(results_content)
        results_layout.addWidget(results_scroll)

        # Pulsanti di azione per i risultati
        results_actions = QHBoxLayout()

        self.load_scan_button = QPushButton("Carica Scansione...")
        self.load_scan_button.clicked.connect(self._load_existing_scan)

        self.view_3d_button = QPushButton("Visualizza Nuvola di Punti")
        self.view_3d_button.clicked.connect(self._view_pointcloud)
        self.view_3d_button.setEnabled(False)  # Disabilitato finché non c'è una nuvola di punti

        results_actions.addWidget(self.load_scan_button)
        results_actions.addStretch(1)
        results_actions.addWidget(self.view_3d_button)

        results_layout.addLayout(results_actions)

        main_layout.addWidget(self.results_group)

    def _get_default_output_dir(self):
        """Restituisce la directory di output predefinita."""
        # Prova a leggere dalle impostazioni
        settings = QSettings()
        saved_dir = settings.value("scan/output_dir")
        if saved_dir and os.path.isdir(saved_dir):
            return Path(saved_dir)

        # Altrimenti usa la directory predefinita
        return Path.home() / "UnLook" / "scans"

    def _get_pattern_type_name(self, pattern_type):
        """Restituisce il nome leggibile del tipo di pattern."""
        pattern_names = {
            "PROGRESSIVE": "Pattern Progressivi",
            "GRAY_CODE": "Gray Code",
            "BINARY_CODE": "Binary Code",
            "PHASE_SHIFT": "Phase Shift"
        }
        return pattern_names.get(pattern_type, pattern_type)

    def _select_output_dir(self):
        """Mostra un dialogo per selezionare la directory di output."""
        directory = QFileDialog.getExistingDirectory(
            self,
            "Seleziona Directory di Output",
            str(self.output_dir),
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks
        )

        if directory:
            self.output_dir = Path(directory)
            self.output_dir_edit.setText(str(self.output_dir))

            # Salva nelle impostazioni
            settings = QSettings()
            settings.setValue("scan/output_dir", str(self.output_dir))

    def _show_options_dialog(self):
        """Mostra il dialogo per configurare le opzioni avanzate."""
        dialog = ScanOptionsDialog(self, self.scan_config)
        if dialog.exec():
            self.scan_config = dialog.get_config()

            # Aggiorna l'interfaccia con i nuovi valori
            self.pattern_type_label.setText(self._get_pattern_type_name(self.scan_config["pattern_type"]))
            self.num_patterns_label.setText(str(self.scan_config["num_patterns"]))

    def _update_scan_status(self):
        """Aggiorna lo stato della scansione."""
        if not self.is_scanning or not self.scanner_controller:
            return

        # Aggiorna lo scanner selezionato
        if not self.selected_scanner:
            self.selected_scanner = self.scanner_controller.selected_scanner

        if not self.selected_scanner:
            return

        try:
            # Ottieni lo stato dal server
            command_success = self.scanner_controller.send_command(
                self.selected_scanner.device_id,
                "GET_SCAN_STATUS"
            )

            if not command_success:
                logger.warning("Impossibile ottenere lo stato della scansione")
                return

            # Attendi la risposta
            response = self.scanner_controller.wait_for_response(
                self.selected_scanner.device_id,
                "GET_SCAN_STATUS",
                timeout=1.0
            )

            if not response:
                return

            # Estrai lo stato della scansione
            scan_status = response.get("scan_status", {})
            state = scan_status.get("state", "IDLE")
            progress = scan_status.get("progress", 0.0)
            error_message = scan_status.get("error_message", "")

            # Aggiorna l'interfaccia
            self.status_label.setText(f"Stato: {state}")
            self.progress_bar.setValue(int(progress))

            # Aggiungi al log
            if state != "IDLE" and state != "COMPLETED":
                log_entry = f"[{datetime.now().strftime('%H:%M:%S')}] Stato: {state}, Progresso: {progress:.1f}%"
                if error_message:
                    log_entry += f", Errore: {error_message}"

                if log_entry not in self.scan_log:
                    self.scan_log += log_entry + "\n"

            # Controlla se la scansione è completata o in errore
            if state == "COMPLETED":
                self._handle_scan_completed()
            elif state == "ERROR":
                self._handle_scan_error(error_message)

        except Exception as e:
            logger.error(f"Errore nell'aggiornamento dello stato della scansione: {e}")

    def refresh_scanner_state(self):
        """
        Aggiorna lo stato dello scanner quando la tab diventa attiva.
        CORREZIONE: Aggiunto ping esplicito e verifica della connessione.
        """
        if self.scanner_controller and self.scanner_controller.selected_scanner:
            self.selected_scanner = self.scanner_controller.selected_scanner

            # CORREZIONE: Invia un ping esplicito per verificare la connessione
            if self.selected_scanner:
                try:
                    import socket
                    # Ottieni l'IP locale
                    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    s.connect(("8.8.8.8", 80))
                    local_ip = s.getsockname()[0]
                    s.close()

                    # Invia un ping con l'IP del client
                    self.scanner_controller.send_command(
                        self.selected_scanner.device_id,
                        "PING",
                        {
                            "timestamp": time.time(),
                            "client_ip": local_ip
                        }
                    )
                except Exception as e:
                    logger.error(f"Errore nell'invio del ping di refresh: {e}")

            # Aggiorna la UI in base allo stato corrente della connessione
            connected = self.scanner_controller.is_connected(self.selected_scanner.device_id)
            self.start_scan_button.setEnabled(connected)

            if connected:
                self.status_label.setText(f"Connesso a {self.selected_scanner.name}")
            else:
                self.status_label.setText("Scanner non connesso")

    def _start_scan(self):
        """Avvia una nuova scansione."""
        if self.is_scanning:
            return

        if not self.scanner_controller or not self.scanner_controller.selected_scanner:
            QMessageBox.warning(
                self,
                "Errore",
                "Nessuno scanner selezionato. Seleziona uno scanner prima di avviare la scansione."
            )
            return

        # Aggiorna lo scanner selezionato
        self.selected_scanner = self.scanner_controller.selected_scanner

        # Verifica che lo scanner sia connesso
        if not self.scanner_controller.is_connected(self.selected_scanner.device_id):
            # Se lo scanner non è connesso, proviamo a riconnetterci
            logger.info(f"Scanner {self.selected_scanner.name} non connesso, tentativo di riconnessione automatico")
            success = self.scanner_controller.connect_to_scanner(self.selected_scanner.device_id)

            if not success:
                QMessageBox.warning(
                    self,
                    "Errore",
                    "Lo scanner selezionato non è connesso. Connettiti prima di avviare la scansione."
                )
                return

            # Breve pausa per assicurarsi che la connessione sia stabilita
            time.sleep(0.5)

        # Prepara il percorso della scansione
        scan_name = self.scan_name_edit.text()
        if not scan_name:
            scan_name = f"Scan_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # Genera un ID unico per la scansione
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.current_scan_id = f"{scan_name}_{timestamp}"

        # Prepara la configurazione
        scan_config = self.scan_config.copy()

        # Aggiorna l'interfaccia
        self.progress_bar.setValue(0)
        self.status_label.setText("Inizializzazione scansione...")
        self.start_scan_button.setEnabled(False)
        self.stop_scan_button.setEnabled(True)
        self.options_button.setEnabled(False)
        self.browse_button.setEnabled(False)
        self.scan_name_edit.setEnabled(False)

        # Reset del log
        self.scan_log = f"[{datetime.now().strftime('%H:%M:%S')}] Avvio scansione: {self.current_scan_id}\n"
        self.scan_log += f"[{datetime.now().strftime('%H:%M:%S')}] Tipo di pattern: {scan_config['pattern_type']}\n"
        self.scan_log += f"[{datetime.now().strftime('%H:%M:%S')}] Numero di pattern: {scan_config['num_patterns']}\n"
        self.scan_log += f"[{datetime.now().strftime('%H:%M:%S')}] Tempo di esposizione: {scan_config['exposure_time']} sec\n"
        self.scan_log += f"[{datetime.now().strftime('%H:%M:%S')}] Qualità: {scan_config['quality']}\n"

        # Invia il comando di avvio scansione al server
        try:
            logger.info(f"Avvio scansione: {self.current_scan_id}")

            command_success = self.scanner_controller.send_command(
                self.selected_scanner.device_id,
                "START_SCAN",
                {"scan_config": scan_config}
            )

            if not command_success:
                self._handle_scan_error("Impossibile inviare il comando di avvio scansione")
                return

            # Attendi la risposta
            response = self.scanner_controller.wait_for_response(
                self.selected_scanner.device_id,
                "START_SCAN",
                timeout=5.0
            )

            if not response:
                self._handle_scan_error("Nessuna risposta dal server")
                return

            # Verifica lo stato della risposta
            if response.get("status") != "success":
                error_message = response.get("message", "Errore sconosciuto")
                self._handle_scan_error(error_message)
                return

            # Salva l'ID della scansione
            self.current_scan_id = response.get("scan_id", self.current_scan_id)

            # Aggiorna il log
            self.scan_log += f"[{datetime.now().strftime('%H:%M:%S')}] Scansione avviata con ID: {self.current_scan_id}\n"

            # Imposta lo stato di scansione attiva
            self.is_scanning = True

            # Emetti il segnale di scansione avviata
            self.scan_started.emit(scan_config)

            # Abilita il pulsante di visualizzazione del log
            self.view_log_button.setEnabled(True)

        except Exception as e:
            logger.error(f"Errore nell'avvio della scansione: {e}")
            self._handle_scan_error(str(e))

    def _stop_scan(self):
        """Interrompe la scansione in corso."""
        if not self.is_scanning or not self.selected_scanner:
            return

        # Chiedi conferma all'utente
        reply = QMessageBox.question(
            self,
            "Interrompere la scansione",
            "Sei sicuro di voler interrompere la scansione in corso?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        # Aggiorna l'interfaccia
        self.status_label.setText("Interruzione scansione...")

        # Aggiorna il log
        self.scan_log += f"[{datetime.now().strftime('%H:%M:%S')}] Richiesta interruzione scansione\n"

        # Invia il comando di interruzione
        try:
            command_success = self.scanner_controller.send_command(
                self.selected_scanner.device_id,
                "STOP_SCAN"
            )

            if not command_success:
                logger.warning("Impossibile inviare il comando di interruzione")
                self.scan_log += f"[{datetime.now().strftime('%H:%M:%S')}] Errore nell'invio del comando di interruzione\n"
                return

            # Attendi la risposta
            response = self.scanner_controller.wait_for_response(
                self.selected_scanner.device_id,
                "STOP_SCAN",
                timeout=15.0
            )

            # Aggiorna il log
            self.scan_log += f"[{datetime.now().strftime('%H:%M:%S')}] Scansione interrotta\n"

            # Reset dello stato
            self.is_scanning = False

            # Aggiorna l'interfaccia
            self._reset_ui_after_scan()

        except Exception as e:
            logger.error(f"Errore nell'interruzione della scansione: {e}")
            self.scan_log += f"[{datetime.now().strftime('%H:%M:%S')}] Errore nell'interruzione: {str(e)}\n"

    def _handle_scan_completed(self):
        """Gestisce il completamento della scansione."""
        if not self.is_scanning:
            return

        # Aggiorna il log
        self.scan_log += f"[{datetime.now().strftime('%H:%M:%S')}] Scansione completata con successo\n"

        # Aggiorna lo stato
        self.is_scanning = False

        # Aggiorna l'interfaccia
        self.status_label.setText("Scansione completata")
        self.progress_bar.setValue(100)

        # Reset dell'interfaccia
        self._reset_ui_after_scan()

        # Abilita i pulsanti di post-scansione
        self.process_button.setEnabled(True)
        self.view_log_button.setEnabled(True)

        # Aggiorna la sezione dei risultati
        self._update_results_section()

        # Emetti il segnale di completamento
        scan_path = os.path.join(str(self.output_dir), self.current_scan_id)
        self.scan_completed.emit(scan_path)

        # Chiedi all'utente se vuole elaborare i dati
        reply = QMessageBox.question(
            self,
            "Scansione Completata",
            "La scansione è stata completata con successo. Vuoi elaborare i dati ora?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )

        if reply == QMessageBox.Yes:
            self._process_scan()

    def _handle_scan_error(self, error_message):
        """Gestisce un errore durante la scansione."""
        # Aggiorna il log
        self.scan_log += f"[{datetime.now().strftime('%H:%M:%S')}] Errore nella scansione: {error_message}\n"

        # Aggiorna lo stato
        self.is_scanning = False

        # Aggiorna l'interfaccia
        self.status_label.setText(f"Errore: {error_message}")

        # Reset dell'interfaccia
        self._reset_ui_after_scan()

        # Abilita il pulsante di visualizzazione del log
        self.view_log_button.setEnabled(True)

        # Mostra un messaggio di errore
        QMessageBox.critical(
            self,
            "Errore nella Scansione",
            f"Si è verificato un errore durante la scansione:\n{error_message}"
        )

        # Emetti il segnale di errore
        self.scan_failed.emit(error_message)

    def _reset_ui_after_scan(self):
        """Ripristina l'interfaccia utente dopo una scansione."""
        self.start_scan_button.setEnabled(True)
        self.stop_scan_button.setEnabled(False)
        self.options_button.setEnabled(True)
        self.browse_button.setEnabled(True)
        self.scan_name_edit.setEnabled(True)

    def _process_scan(self):
        """Elabora i dati della scansione per generare la nuvola di punti 3D."""
        if not self.current_scan_id:
            QMessageBox.warning(
                self,
                "Errore",
                "Nessuna scansione disponibile da elaborare."
            )
            return

        # Verifica che il modulo di triangolazione sia disponibile
        if not hasattr(self, 'scan_processor') or not self.scan_processor:
            QMessageBox.critical(
                self,
                "Errore",
                "Il modulo di triangolazione non è disponibile. Verifica l'installazione."
            )
            return

        # Percorso della scansione
        scan_path = os.path.join(str(self.output_dir), self.current_scan_id)

        # Verifica che la directory della scansione esista
        if not os.path.isdir(scan_path):
            # Prova a cercare la scansione sul server e scaricarla

            if not self.selected_scanner or not self.scanner_controller:
                QMessageBox.warning(
                    self,
                    "Errore",
                    f"Directory della scansione non trovata: {scan_path}\n"
                    "Verifica che la scansione sia stata completata."
                )
                return

            # Chiedi all'utente se vuole scaricare i dati
            reply = QMessageBox.question(
                self,
                "Scaricare Dati",
                f"I dati della scansione non sono presenti in locale.\n"
                f"Vuoi scaricarli dallo scanner?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )

            if reply == QMessageBox.Yes:
                # Scarica i dati
                success = self._download_scan_data()
                if not success:
                    return
            else:
                return

        # Aggiorna il log
        self.scan_log += f"[{datetime.now().strftime('%H:%M:%S')}] Inizio elaborazione della scansione\n"

        # Configura le callback per il progresso
        def progress_callback(progress, message):
            self.progress_bar.setValue(int(progress))
            self.status_label.setText(message)

            # Aggiorna il log occasionalmente
            if int(progress) % 10 == 0:
                self.scan_log += f"[{datetime.now().strftime('%H:%M:%S')}] Progresso: {int(progress)}%, {message}\n"

        def completion_callback(success, message, result):
            if success:
                # Aggiorna il log
                self.scan_log += f"[{datetime.now().strftime('%H:%M:%S')}] Elaborazione completata: {message}\n"

                # Aggiorna l'interfaccia
                self.status_label.setText("Elaborazione completata")
                self.progress_bar.setValue(100)

                # Abilita il pulsante di visualizzazione 3D
                self.view_3d_button.setEnabled(True)

                # Aggiorna la sezione dei risultati
                self._update_results_section(has_pointcloud=True)

                # Mostra un messaggio
                QMessageBox.information(
                    self,
                    "Elaborazione Completata",
                    f"L'elaborazione della scansione è stata completata con successo.\n"
                    f"Sono stati generati {len(result):,} punti.\n\n"
                    f"Vuoi visualizzare la nuvola di punti ora?"
                )

                # Visualizza la nuvola di punti
                self._view_pointcloud()
            else:
                # Aggiorna il log
                self.scan_log += f"[{datetime.now().strftime('%H:%M:%S')}] Errore nell'elaborazione: {message}\n"

                # Aggiorna l'interfaccia
                self.status_label.setText(f"Errore nell'elaborazione: {message}")

                # Mostra un messaggio di errore
                QMessageBox.critical(
                    self,
                    "Errore nell'Elaborazione",
                    f"Si è verificato un errore durante l'elaborazione della scansione:\n{message}"
                )

        # Configura il processor
        self.scan_processor.set_callbacks(progress_callback, completion_callback)

        # Carica la scansione
        if not self.scan_processor.load_local_scan(scan_path):
            QMessageBox.critical(
                self,
                "Errore",
                f"Impossibile caricare i dati della scansione da: {scan_path}"
            )
            return

        # Aggiorna l'interfaccia
        self.status_label.setText("Elaborazione in corso...")
        self.progress_bar.setValue(0)
        self.process_button.setEnabled(False)

        # Avvia l'elaborazione
        success = self.scan_processor.process_scan(use_threading=True)

        if not success:
            # Reset dell'interfaccia
            self.status_label.setText("Errore nell'avvio dell'elaborazione")
            self.process_button.setEnabled(True)

            # Mostra un messaggio di errore
            QMessageBox.critical(
                self,
                "Errore",
                "Impossibile avviare l'elaborazione della scansione."
            )

    def _download_scan_data(self):
        """Scarica i dati della scansione dal server."""
        if not self.selected_scanner or not self.scanner_controller:
            QMessageBox.warning(
                self,
                "Errore",
                "Nessuno scanner selezionato per il download."
            )
            return False

        if not self.current_scan_id:
            QMessageBox.warning(
                self,
                "Errore",
                "Nessuna scansione disponibile per il download."
            )
            return False

        # Aggiorna l'interfaccia
        self.status_label.setText("Download dati in corso...")
        self.progress_bar.setValue(0)

        # Aggiorna il log
        self.scan_log += f"[{datetime.now().strftime('%H:%M:%S')}] Inizio download dei dati della scansione\n"

        # Scarica i dati
        try:
            # Assicura che il processor sia disponibile
            if not hasattr(self, 'scan_processor') or not self.scan_processor:
                self.scan_processor = ScanProcessor(str(self.output_dir))

            # Configura una callback per il progresso
            def download_progress(progress, message):
                self.progress_bar.setValue(int(progress))
                self.status_label.setText(message)

                # Aggiorna il log occasionalmente
                if int(progress) % 10 == 0:
                    self.scan_log += f"[{datetime.now().strftime('%H:%M:%S')}] Download: {int(progress)}%, {message}\n"

            self.scan_processor.set_callbacks(download_progress, None)

            # Esegui il download
            success = self.scan_processor.download_scan_data(
                self.selected_scanner,
                self.current_scan_id
            )

            if not success:
                # Aggiorna il log
                self.scan_log += f"[{datetime.now().strftime('%H:%M:%S')}] Errore nel download dei dati\n"

                # Aggiorna l'interfaccia
                self.status_label.setText("Errore nel download dei dati")

                # Mostra un messaggio di errore
                QMessageBox.critical(
                    self,
                    "Errore",
                    "Impossibile scaricare i dati della scansione dal server."
                )
                return False

            # Aggiorna il log
            self.scan_log += f"[{datetime.now().strftime('%H:%M:%S')}] Download completato con successo\n"

            # Aggiorna l'interfaccia
            self.status_label.setText("Download completato")
            self.progress_bar.setValue(100)

            return True

        except Exception as e:
            logger.error(f"Errore nel download dei dati: {e}")

            # Aggiorna il log
            self.scan_log += f"[{datetime.now().strftime('%H:%M:%S')}] Errore nel download: {str(e)}\n"

            # Aggiorna l'interfaccia
            self.status_label.setText(f"Errore nel download: {str(e)}")

            # Mostra un messaggio di errore
            QMessageBox.critical(
                self,
                "Errore",
                f"Si è verificato un errore durante il download dei dati:\n{str(e)}"
            )

            return False

    def _load_existing_scan(self):
        """Carica una scansione esistente."""
        # Seleziona la directory
        directory = QFileDialog.getExistingDirectory(
            self,
            "Seleziona Directory della Scansione",
            str(self.output_dir),
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks
        )

        if not directory:
            return

        # Verifica che sia una directory di scansione valida
        scan_id = os.path.basename(directory)
        left_dir = os.path.join(directory, "left")
        right_dir = os.path.join(directory, "right")

        if not os.path.isdir(left_dir) or not os.path.isdir(right_dir):
            QMessageBox.warning(
                self,
                "Directory Non Valida",
                f"La directory selezionata non sembra contenere una scansione valida:\n{directory}\n\n"
                "Verifica che la directory contenga le sottodirectory 'left' e 'right'."
            )
            return

        # Aggiorna lo stato
        self.current_scan_id = scan_id

        # Aggiorna l'interfaccia
        self.status_label.setText(f"Scansione caricata: {scan_id}")

        # Verifica se esiste già una nuvola di punti
        pointcloud_path = os.path.join(directory, "pointcloud.ply")
        has_pointcloud = os.path.isfile(pointcloud_path)

        # Abilita/disabilita i pulsanti appropriati
        self.process_button.setEnabled(True)
        self.view_3d_button.setEnabled(has_pointcloud)

        # Aggiorna la sezione dei risultati
        self._update_results_section(has_pointcloud)

        # Carica il log se disponibile
        self._load_scan_log(directory)

    def _load_scan_log(self, scan_dir):
        """Carica il log della scansione se disponibile."""
        log_file = os.path.join(scan_dir, "scan_log.txt")

        if os.path.isfile(log_file):
            try:
                with open(log_file, 'r') as f:
                    self.scan_log = f.read()
                    self.view_log_button.setEnabled(True)
            except Exception as e:
                logger.error(f"Errore nel caricamento del log: {e}")
                self.scan_log = f"[{datetime.now().strftime('%H:%M:%S')}] Scansione caricata da: {scan_dir}\n"
        else:
            self.scan_log = f"[{datetime.now().strftime('%H:%M:%S')}] Scansione caricata da: {scan_dir}\n"

    def _show_log_dialog(self):
        """Mostra il dialogo con i log della scansione."""
        dialog = LogViewerDialog(self, self.scan_log)
        dialog.exec()

    def _view_pointcloud(self):
        """Visualizza la nuvola di punti 3D."""
        if not self.current_scan_id:
            return

        # Percorso della nuvola di punti
        scan_dir = os.path.join(str(self.output_dir), self.current_scan_id)
        pointcloud_path = os.path.join(scan_dir, "pointcloud.ply")

        # Verifica che il file esista
        if not os.path.isfile(pointcloud_path):
            QMessageBox.warning(
                self,
                "File Non Trovato",
                f"Nuvola di punti non trovata:\n{pointcloud_path}\n\n"
                "Elabora prima la scansione per generare la nuvola di punti."
            )
            return

        # Percorso dello screenshot se esiste
        screenshot_path = os.path.join(scan_dir, "pointcloud_preview.png")
        if not os.path.isfile(screenshot_path):
            screenshot_path = None

        # Mostra il visualizzatore
        dialog = PointCloudViewerDialog(self, pointcloud_path, screenshot_path)
        dialog.exec()

    def _update_results_section(self, has_pointcloud=False):
        """Aggiorna la sezione dei risultati della scansione."""
        if not self.current_scan_id:
            return

        # Percorso della scansione
        scan_dir = os.path.join(str(self.output_dir), self.current_scan_id)

        # Pulisci il layout corrente
        while self.results_content_layout.count():
            item = self.results_content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Aggiungi le informazioni sulla scansione
        info_label = QLabel(f"Scansione: {self.current_scan_id}")
        info_label.setFont(QFont("Arial", 12, QFont.Bold))
        self.results_content_layout.addWidget(info_label)

        # Aggiungi dettagli dalla configurazione se disponibile
        config_file = os.path.join(scan_dir, "scan_config.json")
        if os.path.isfile(config_file):
            try:
                with open(config_file, 'r') as f:
                    config = json.load(f)

                    details = "Dettagli Scansione:\n"

                    if "config" in config:
                        scan_config = config["config"]
                        details += f"- Tipo di Pattern: {self._get_pattern_type_name(scan_config.get('pattern_type', 'PROGRESSIVE'))}\n"
                        details += f"- Numero di Pattern: {scan_config.get('num_patterns', 'N/A')}\n"
                        details += f"- Tempo di Esposizione: {scan_config.get('exposure_time', 'N/A')} sec\n"
                        details += f"- Qualità: {scan_config.get('quality', 'N/A')}\n"

                    if "timestamp" in config:
                        details += f"- Data: {config.get('timestamp', 'N/A')}\n"

                    details_label = QLabel(details)
                    self.results_content_layout.addWidget(details_label)
            except Exception as e:
                logger.error(f"Errore nel caricamento della configurazione: {e}")

        # Verifica se c'è una nuvola di punti
        pointcloud_path = os.path.join(scan_dir, "pointcloud.ply")
        if os.path.isfile(pointcloud_path):
            pointcloud_info = f"Nuvola di Punti: {os.path.basename(pointcloud_path)}\n"
            pointcloud_info += f"- Dimensione: {os.path.getsize(pointcloud_path) / 1024:.1f} KB\n"

            # Se Open3D è disponibile, ottieni il numero di punti
            if OPEN3D_AVAILABLE:
                try:
                    pcd = o3d.io.read_point_cloud(pointcloud_path)
                    num_points = len(pcd.points)
                    pointcloud_info += f"- Numero di Punti: {num_points:,}\n"
                except Exception as e:
                    logger.error(f"Errore nella lettura della nuvola di punti: {e}")

            pointcloud_label = QLabel(pointcloud_info)
            self.results_content_layout.addWidget(pointcloud_label)
        elif has_pointcloud:
            pointcloud_label = QLabel("La nuvola di punti non è stata trovata.")
            self.results_content_layout.addWidget(pointcloud_label)
        else:
            pointcloud_label = QLabel("Nessuna nuvola di punti disponibile. Elabora la scansione per generarla.")
            self.results_content_layout.addWidget(pointcloud_label)

        # Aggiungi anteprima se disponibile
        preview_path = os.path.join(scan_dir, "pointcloud_preview.png")

        if os.path.isfile(preview_path):
            preview_label = QLabel()
            preview_label.setAlignment(Qt.AlignCenter)
            pixmap = QPixmap(preview_path)
            preview_label.setPixmap(pixmap.scaled(
                400, 300,
                Qt.KeepAspectRatio, Qt.SmoothTransformation
            ))
            self.results_content_layout.addWidget(preview_label)
        elif OPENCV_AVAILABLE and os.path.isdir(os.path.join(scan_dir, "left")):
            # Se non c'è un'anteprima della nuvola, mostra un'immagine acquisita
            try:
                # Cerca immagini nella directory left
                left_images = glob.glob(os.path.join(scan_dir, "left", "*.png"))

                if left_images:
                    # Prendi una delle immagini (preferibilmente white)
                    sample_image = next((img for img in left_images if "white" in img.lower()), left_images[0])

                    # Carica l'immagine
                    img = cv2.imread(sample_image)

                    # Scalala per la visualizzazione
                    scale = min(400 / img.shape[1], 300 / img.shape[0])
                    width = int(img.shape[1] * scale)
                    height = int(img.shape[0] * scale)
                    img_resized = cv2.resize(img, (width, height))

                    # Converti in formato Qt
                    img_rgb = cv2.cvtColor(img_resized, cv2.COLOR_BGR2RGB)
                    h, w, c = img_rgb.shape
                    qimg = QImage(img_rgb.data, w, h, w * c, QImage.Format_RGB888)
                    pixmap = QPixmap.fromImage(qimg)

                    # Mostra l'anteprima
                    preview_label = QLabel()
                    preview_label.setAlignment(Qt.AlignCenter)
                    preview_label.setPixmap(pixmap)
                    self.results_content_layout.addWidget(preview_label)
            except Exception as e:
                logger.error(f"Errore nella generazione dell'anteprima: {e}")

        # Aggiungi spaziatura
        self.results_content_layout.addStretch(1)

    def set_scanner_controller(self, scanner_controller):
        """Imposta il controller dello scanner."""
        self.scanner_controller = scanner_controller

        # Abilita il pulsante di avvio scansione se c'è uno scanner selezionato
        self.start_scan_button.setEnabled(
            self.scanner_controller and
            self.scanner_controller.selected_scanner and
            self.scanner_controller.is_connected(self.scanner_controller.selected_scanner.device_id)
        )

    def update_selected_scanner(self, scanner):
        """Aggiorna lo scanner selezionato."""
        self.selected_scanner = scanner

        # Verifica se lo scanner è connesso
        is_connected = (scanner is not None and
                        self.scanner_controller and
                        self.scanner_controller.is_connected(scanner.device_id))

        # Abilita/disabilita il pulsante di avvio scansione
        self.start_scan_button.setEnabled(is_connected)

        # Aggiorna l'etichetta di stato
        if is_connected:
            self.status_label.setText(f"Connesso a {scanner.name}")
        else:
            self.status_label.setText("Scanner non connesso")