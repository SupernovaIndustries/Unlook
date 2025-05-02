#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Widget per la configurazione delle camere degli scanner UnLook.
Versione ottimizzata e focalizzata esclusivamente sulla configurazione,
senza funzionalità di visualizzazione stream ora integrate in ScanView.
"""

import logging
import time
import json
from pathlib import Path
from typing import Optional, Dict, List, Any

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QFormLayout, QComboBox, QSlider, QCheckBox,
    QTabWidget, QRadioButton, QButtonGroup, QMessageBox,
    QProgressDialog, QApplication, QFileDialog, QLineEdit
)
from PySide6.QtCore import Qt, Signal, Slot, QTimer, QMutex, QMutexLocker
from PySide6.QtGui import QFont

from client.models.scanner_model import Scanner, ScannerStatus

logger = logging.getLogger(__name__)


class CameraConfigView(QWidget):
    """
    Widget per la configurazione avanzata delle camere degli scanner UnLook.
    Fornisce interfaccia dedicata per impostare e salvare parametri come esposizione,
    guadagno, modalità, contrasto, ecc.
    """

    # Segnali
    settings_applied = Signal(dict)  # Configurazione applicata con successo
    settings_failed = Signal(str)  # Errore nell'applicazione delle impostazioni
    profile_saved = Signal(str)  # Nome profilo salvato
    profile_loaded = Signal(str)  # Nome profilo caricato

    def __init__(self, scanner_controller=None, parent=None):
        super().__init__(parent)
        self.scanner_controller = scanner_controller
        self.selected_scanner = None
        self._profiles_dir = Path.home() / "UnLook" / "config" / "profiles"
        self._profiles_dir.mkdir(parents=True, exist_ok=True)
        self._lock = QMutex()  # Mutex per proteggere accesso concorrente

        # Configura l'interfaccia
        self._setup_ui()

        # Timer di stato
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._update_ui_state)
        self._status_timer.start(1000)  # Aggiorna ogni secondo

    def _setup_ui(self):
        """Configura l'interfaccia utente."""
        # Layout principale
        main_layout = QVBoxLayout(self)

        # Titolo e informazioni
        title_layout = QHBoxLayout()
        title_label = QLabel("Configurazione Avanzata Camere")
        title_label.setFont(QFont("Arial", 14, QFont.Bold))
        title_label.setAlignment(Qt.AlignLeft)

        self.scanner_info_label = QLabel("Scanner: non selezionato")
        self.scanner_info_label.setAlignment(Qt.AlignRight)

        title_layout.addWidget(title_label)
        title_layout.addStretch(1)
        title_layout.addWidget(self.scanner_info_label)

        main_layout.addLayout(title_layout)

        # Sezione profili
        profiles_group = QGroupBox("Profili di configurazione")
        profiles_layout = QHBoxLayout(profiles_group)

        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(200)
        self.profile_name_edit = QLineEdit()
        self.profile_name_edit.setPlaceholderText("Nome profilo...")

        self.save_profile_button = QPushButton("Salva Profilo")
        self.load_profile_button = QPushButton("Carica Profilo")
        self.delete_profile_button = QPushButton("Elimina")

        self.save_profile_button.clicked.connect(self._save_camera_profile)
        self.load_profile_button.clicked.connect(self._load_camera_profile)
        self.delete_profile_button.clicked.connect(self._delete_camera_profile)

        profiles_layout.addWidget(QLabel("Profilo:"))
        profiles_layout.addWidget(self.profile_combo)
        profiles_layout.addWidget(self.profile_name_edit)
        profiles_layout.addWidget(self.save_profile_button)
        profiles_layout.addWidget(self.load_profile_button)
        profiles_layout.addWidget(self.delete_profile_button)

        main_layout.addWidget(profiles_group)

        # Tab per i controlli delle camere
        self.camera_tabs = QTabWidget()

        # Crea le tab per i controlli delle camere
        left_cam_tab, right_cam_tab = self._setup_camera_controls()

        # Aggiungi le tab al widget
        self.camera_tabs.addTab(left_cam_tab, "Camera Sinistra")
        self.camera_tabs.addTab(right_cam_tab, "Camera Destra")

        main_layout.addWidget(self.camera_tabs)

        # Checkbox per sincronizzazione automatica
        sync_layout = QHBoxLayout()
        self.sync_cameras_checkbox = QCheckBox("Sincronizza automaticamente le impostazioni tra le camere")
        self.sync_cameras_checkbox.setChecked(True)
        self.sync_cameras_checkbox.toggled.connect(self._toggle_camera_sync)
        sync_layout.addWidget(self.sync_cameras_checkbox)
        sync_layout.addStretch(1)

        main_layout.addLayout(sync_layout)

        # Pulsanti azioni
        buttons_layout = QHBoxLayout()

        self.refresh_button = QPushButton("Ricarica Impostazioni Attuali")
        self.refresh_button.clicked.connect(self._refresh_camera_settings)

        self.apply_settings_button = QPushButton("Applica Impostazioni")
        self.apply_settings_button.clicked.connect(self._apply_camera_settings)
        self.apply_settings_button.setStyleSheet("font-weight: bold;")

        self.reset_default_button = QPushButton("Ripristina Predefiniti")
        self.reset_default_button.clicked.connect(self._reset_default_settings)

        buttons_layout.addWidget(self.refresh_button)
        buttons_layout.addStretch(1)
        buttons_layout.addWidget(self.reset_default_button)
        buttons_layout.addWidget(self.apply_settings_button)

        main_layout.addLayout(buttons_layout)

        # Etichetta di stato
        self.status_label = QLabel("Connetti uno scanner per configurare le camere")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("font-style: italic; color: #666;")
        main_layout.addWidget(self.status_label)

        # Inizializza lo stato iniziale dell'interfaccia
        self._update_ui_enabled_state(False)
        self._load_profiles_list()

    def _setup_camera_controls(self):
        """
        Configura i controlli avanzati della camera.
        """
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
        self.left_exposure_slider.valueChanged.connect(
            lambda v: self._sync_slider_if_needed(self.left_exposure_slider, self.right_exposure_slider))

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
        self.left_gain_slider.valueChanged.connect(
            lambda v: self._sync_slider_if_needed(self.left_gain_slider, self.right_gain_slider))

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
        self.left_brightness_slider.valueChanged.connect(
            lambda v: self._sync_slider_if_needed(self.left_brightness_slider, self.right_brightness_slider))
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
        self.left_contrast_slider.valueChanged.connect(
            lambda v: self._sync_slider_if_needed(self.left_contrast_slider, self.right_contrast_slider))
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
        self.left_sharpness_slider.valueChanged.connect(
            lambda v: self._sync_slider_if_needed(self.left_sharpness_slider, self.right_sharpness_slider))
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
        self.left_saturation_slider.valueChanged.connect(
            lambda v: self._sync_slider_if_needed(self.left_saturation_slider, self.right_saturation_slider))
        left_saturation_layout.addWidget(self.left_saturation_slider)
        left_saturation_layout.addWidget(self.left_saturation_value)
        left_advanced_layout.addRow("Saturazione:", left_saturation_layout)

        # Aggiungi il gruppo avanzato
        left_cam_layout.addRow(left_advanced_group)

        # Salva i riferimenti alle righe di saturazione per poter controllare la visibilità
        self.left_saturation_row = (
            left_advanced_layout.itemAt(left_advanced_layout.rowCount() - 1, QFormLayout.LabelRole).widget(),
            left_advanced_layout.itemAt(left_advanced_layout.rowCount() - 1, QFormLayout.FieldRole).widget()
        )

        # Collegamento tra modalità e saturazione per camera sinistra
        self.left_mode_color.toggled.connect(lambda checked: self._update_saturation_visibility(checked, True))
        self.left_mode_grayscale.toggled.connect(lambda checked: self._update_saturation_visibility(not checked, True))

        # Collegamento per sincronizzazione modalità
        self.left_mode_color.toggled.connect(
            lambda checked: self._sync_mode_if_needed(self.left_mode_color, self.right_mode_color))
        self.left_mode_grayscale.toggled.connect(
            lambda checked: self._sync_mode_if_needed(self.left_mode_grayscale, self.right_mode_grayscale))

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
        self.right_exposure_slider.valueChanged.connect(
            lambda v: self._sync_slider_if_needed(self.right_exposure_slider, self.left_exposure_slider))

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
        self.right_gain_slider.valueChanged.connect(
            lambda v: self._sync_slider_if_needed(self.right_gain_slider, self.left_gain_slider))

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
        self.right_brightness_slider.valueChanged.connect(
            lambda v: self._sync_slider_if_needed(self.right_brightness_slider, self.left_brightness_slider))
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
        self.right_contrast_slider.valueChanged.connect(
            lambda v: self._sync_slider_if_needed(self.right_contrast_slider, self.left_contrast_slider))
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
        self.right_sharpness_slider.valueChanged.connect(
            lambda v: self._sync_slider_if_needed(self.right_sharpness_slider, self.left_sharpness_slider))
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
        self.right_saturation_slider.valueChanged.connect(
            lambda v: self._sync_slider_if_needed(self.right_saturation_slider, self.left_saturation_slider))
        right_saturation_layout.addWidget(self.right_saturation_slider)
        right_saturation_layout.addWidget(self.right_saturation_value)
        right_advanced_layout.addRow("Saturazione:", right_saturation_layout)

        # Aggiungi il gruppo avanzato
        right_cam_layout.addRow(right_advanced_group)

        # Salva i riferimenti alle righe di saturazione per poter controllare la visibilità
        self.right_saturation_row = (
            right_advanced_layout.itemAt(right_advanced_layout.rowCount() - 1, QFormLayout.LabelRole).widget(),
            right_advanced_layout.itemAt(right_advanced_layout.rowCount() - 1, QFormLayout.FieldRole).widget()
        )

        # Collegamento tra modalità e saturazione per camera destra
        self.right_mode_color.toggled.connect(lambda checked: self._update_saturation_visibility(checked, False))
        self.right_mode_grayscale.toggled.connect(
            lambda checked: self._update_saturation_visibility(not checked, False))

        # Collegamento per sincronizzazione modalità
        self.right_mode_color.toggled.connect(
            lambda checked: self._sync_mode_if_needed(self.right_mode_color, self.left_mode_color))
        self.right_mode_grayscale.toggled.connect(
            lambda checked: self._sync_mode_if_needed(self.right_mode_grayscale, self.left_mode_grayscale))

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

    def _sync_slider_if_needed(self, source_slider, target_slider):
        """
        Sincronizza il valore di uno slider con l'altro, se la sincronizzazione è attiva.

        Args:
            source_slider: Slider di origine del valore
            target_slider: Slider di destinazione da sincronizzare
        """
        if self.sync_cameras_checkbox.isChecked():
            target_slider.blockSignals(True)
            target_slider.setValue(source_slider.value())
            target_slider.blockSignals(False)

    def _sync_mode_if_needed(self, source_radio, target_radio):
        """
        Sincronizza la modalità colore/grayscale tra le camere, se la sincronizzazione è attiva.

        Args:
            source_radio: RadioButton di origine
            target_radio: RadioButton di destinazione da sincronizzare
        """
        if self.sync_cameras_checkbox.isChecked() and source_radio.isChecked():
            target_radio.setChecked(True)

    def _toggle_camera_sync(self, checked):
        """
        Attiva/disattiva la sincronizzazione automatica tra le camere.

        Args:
            checked: True se la sincronizzazione è attiva, False altrimenti
        """
        if checked:
            # Se la sincronizzazione viene attivata, sincronizza subito con i valori della camera sinistra
            self._sync_all_settings_from_left()

    def _sync_all_settings_from_left(self):
        """Sincronizza tutte le impostazioni dalla camera sinistra alla destra."""
        # Modalità
        if self.left_mode_color.isChecked():
            self.right_mode_color.setChecked(True)
        else:
            self.right_mode_grayscale.setChecked(True)

        # Sliders
        sliders_pairs = [
            (self.left_exposure_slider, self.right_exposure_slider),
            (self.left_gain_slider, self.right_gain_slider),
            (self.left_brightness_slider, self.right_brightness_slider),
            (self.left_contrast_slider, self.right_contrast_slider),
            (self.left_sharpness_slider, self.right_sharpness_slider),
            (self.left_saturation_slider, self.right_saturation_slider)
        ]

        for left, right in sliders_pairs:
            right.blockSignals(True)
            right.setValue(left.value())
            right.blockSignals(False)

        # Aggiorna i label dei valori
        self.right_exposure_value.setText(self.left_exposure_value.text())
        self.right_gain_value.setText(self.left_gain_value.text())
        self.right_brightness_value.setText(self.left_brightness_value.text())
        self.right_contrast_value.setText(self.left_contrast_value.text())
        self.right_sharpness_value.setText(self.left_sharpness_value.text())
        self.right_saturation_value.setText(self.left_saturation_value.text())

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
        streaming_was_active = False
        main_window = self.window()
        if hasattr(main_window, 'streaming_widget'):
            streaming_widget = main_window.streaming_widget
            if hasattr(streaming_widget, 'is_streaming'):
                streaming_was_active = streaming_widget.is_streaming()

        # Se lo streaming è attivo, fermalo prima di applicare le modifiche
        if streaming_was_active and hasattr(main_window.streaming_widget, 'stop_streaming'):
            main_window.streaming_widget.stop_streaming()
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

                    # Emetti il segnale di configurazione applicata
                    self.settings_applied.emit(config)
                    self.status_label.setText("Impostazioni applicate con successo")
                else:
                    QMessageBox.warning(
                        self,
                        "Avviso",
                        "La configurazione è stata inviata, ma non è stato possibile confermare l'applicazione."
                    )

                    self.settings_failed.emit("Impossibile confermare l'applicazione delle impostazioni")
                    self.status_label.setText("Avviso: impossibile confermare l'applicazione")
            else:
                QMessageBox.warning(
                    self,
                    "Errore",
                    "Impossibile inviare la configurazione al server."
                )

                self.settings_failed.emit("Impossibile inviare la configurazione al server")
                self.status_label.setText("Errore: impossibile inviare configurazione")

        except Exception as e:
            logger.error(f"Errore nell'applicazione delle impostazioni: {e}")
            QMessageBox.critical(
                self,
                "Errore",
                f"Si è verificato un errore durante l'applicazione delle impostazioni:\n{str(e)}"
            )

            self.settings_failed.emit(str(e))
            self.status_label.setText(f"Errore: {str(e)}")

        finally:
            # Chiudi il dialog
            dialog.close()

            # Riavvia lo streaming se era attivo
            if streaming_was_active and hasattr(main_window.streaming_widget, 'start_streaming'):
                time.sleep(1.0)  # Attendi un po' prima di riavviare lo streaming
                main_window.streaming_widget.start_streaming(self.selected_scanner)

    def _save_camera_profile(self):
        """
        Salva il profilo di configurazione corrente delle camere.
        """
        # Ottieni nome dal campo di testo o chiedi all'utente
        profile_name = self.profile_name_edit.text().strip()

        if not profile_name:
            # Se il campo è vuoto ma c'è un profilo selezionato, usa quel nome
            if self.profile_combo.currentText():
                profile_name = self.profile_combo.currentText()
            else:
                # Altrimenti genera un nome basato sulla data e ora
                from datetime import datetime
                profile_name = f"Profilo_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # Normalizza il nome del file
        safe_name = ''.join(c if c.isalnum() or c in '._- ' else '_' for c in profile_name)

        # Percorso file
        file_path = self._profiles_dir / f"{safe_name}.json"

        # Chiedi conferma se il file esiste già
        if file_path.exists():
            response = QMessageBox.question(
                self,
                "Sovrascrivere profilo",
                f"Il profilo '{profile_name}' esiste già. Sovrascrivere?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )

            if response != QMessageBox.Yes:
                return

        # Ottieni configurazione corrente
        config = self.get_camera_settings()

        # Aggiungi metadati
        config["metadata"] = {
            "name": profile_name,
            "created": datetime.now().isoformat(),
            "scanner_id": self.selected_scanner.device_id if self.selected_scanner else "unknown"
        }

        # Salva su file
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2)

            # Aggiorna lista profili
            self._load_profiles_list()

            # Seleziona il profilo appena salvato
            index = self.profile_combo.findText(profile_name)
            if index >= 0:
                self.profile_combo.setCurrentIndex(index)

            # Pulisci campo nome
            self.profile_name_edit.clear()

            # Aggiorna status
            self.status_label.setText(f"Profilo '{profile_name}' salvato con successo")

            # Emetti segnale
            self.profile_saved.emit(profile_name)

            logger.info(f"Profilo camera salvato: {file_path}")

        except Exception as e:
            logger.error(f"Errore nel salvataggio del profilo: {e}")
            QMessageBox.critical(
                self,
                "Errore",
                f"Impossibile salvare il profilo:\n{str(e)}"
            )

    def _load_camera_profile(self):
        """
        Carica un profilo di configurazione delle camere.
        """
        # Ottieni nome profilo selezionato
        profile_name = self.profile_combo.currentText()

        if not profile_name:
            QMessageBox.warning(
                self,
                "Nessun profilo",
                "Nessun profilo selezionato da caricare."
            )
            return

        # Percorso file
        file_path = self._profiles_dir / f"{profile_name}.json"

        if not file_path.exists():
            QMessageBox.warning(
                self,
                "File non trovato",
                f"Il file del profilo '{profile_name}' non è stato trovato."
            )
            return

        # Carica configurazione
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                config = json.load(f)

            # Applica configurazione all'interfaccia
            self.load_camera_settings(config)

            # Aggiorna status
            self.status_label.setText(f"Profilo '{profile_name}' caricato con successo")

            # Chiedi se applicare subito
            response = QMessageBox.question(
                self,
                "Applicare impostazioni",
                f"Profilo '{profile_name}' caricato.\n\nVuoi applicare le impostazioni al dispositivo ora?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )

            if response == QMessageBox.Yes:
                self._apply_camera_settings()

            # Emetti segnale
            self.profile_loaded.emit(profile_name)

            logger.info(f"Profilo camera caricato: {file_path}")

        except Exception as e:
            logger.error(f"Errore nel caricamento del profilo: {e}")
            QMessageBox.critical(
                self,
                "Errore",
                f"Impossibile caricare il profilo:\n{str(e)}"
            )

    def _delete_camera_profile(self):
        """
        Elimina un profilo di configurazione delle camere.
        """
        # Ottieni nome profilo selezionato
        profile_name = self.profile_combo.currentText()

        if not profile_name:
            QMessageBox.warning(
                self,
                "Nessun profilo",
                "Nessun profilo selezionato da eliminare."
            )
            return

        # Chiedi conferma
        response = QMessageBox.question(
            self,
            "Eliminare profilo",
            f"Sei sicuro di voler eliminare il profilo '{profile_name}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if response != QMessageBox.Yes:
            return

        # Percorso file
        file_path = self._profiles_dir / f"{profile_name}.json"

        # Elimina file
        try:
            if file_path.exists():
                file_path.unlink()

                # Aggiorna lista profili
                self._load_profiles_list()

                # Aggiorna status
                self.status_label.setText(f"Profilo '{profile_name}' eliminato")

                logger.info(f"Profilo camera eliminato: {file_path}")
            else:
                QMessageBox.warning(
                    self,
                    "File non trovato",
                    f"Il file del profilo '{profile_name}' non è stato trovato."
                )
        except Exception as e:
            logger.error(f"Errore nell'eliminazione del profilo: {e}")
            QMessageBox.critical(
                self,
                "Errore",
                f"Impossibile eliminare il profilo:\n{str(e)}"
            )

    def _load_profiles_list(self):
        """
        Carica la lista dei profili disponibili.
        """
        try:
            # Salva selezione corrente
            current_profile = self.profile_combo.currentText()

            # Blocca segnali
            self.profile_combo.blockSignals(True)

            # Svuota la lista
            self.profile_combo.clear()

            # Aggiungi profili trovati
            profiles = []
            for file_path in self._profiles_dir.glob("*.json"):
                profile_name = file_path.stem
                profiles.append(profile_name)

            # Ordina alfabeticamente
            profiles.sort()

            # Aggiungi alla combo box
            for profile in profiles:
                self.profile_combo.addItem(profile)

            # Ripristina selezione precedente se possibile
            if current_profile:
                index = self.profile_combo.findText(current_profile)
                if index >= 0:
                    self.profile_combo.setCurrentIndex(index)

            # Sblocca segnali
            self.profile_combo.blockSignals(False)

            logger.debug(f"Caricati {len(profiles)} profili")

        except Exception as e:
            logger.error(f"Errore nel caricamento della lista profili: {e}")

    def _refresh_camera_settings(self):
        """
        Ricarica le impostazioni attuali delle camere dal dispositivo.
        """
        if not self.selected_scanner or not self.scanner_controller or not self.scanner_controller.is_connected(
                self.selected_scanner.device_id):
            QMessageBox.warning(
                self,
                "Errore",
                "Per ricaricare le impostazioni è necessario essere connessi a uno scanner."
            )
            return

        # Mostra dialog di attesa
        dialog = QProgressDialog("Ricaricamento configurazione in corso...", None, 0, 100, self)
        dialog.setWindowTitle("Attendere")
        dialog.setMinimumDuration(300)
        dialog.setValue(20)
        dialog.setCancelButton(None)
        dialog.setWindowModality(Qt.WindowModal)
        dialog.show()

        try:
            # Richiedi configurazione al server
            command_success = self.scanner_controller.send_command(
                self.selected_scanner.device_id,
                "GET_CONFIG"
            )

            dialog.setValue(50)
            QApplication.processEvents()

            if command_success:
                # Attendi la risposta
                response = self.scanner_controller.wait_for_response(
                    self.selected_scanner.device_id,
                    "GET_CONFIG",
                    timeout=5.0
                )

                dialog.setValue(80)
                QApplication.processEvents()

                if response and response.get("status") == "ok":
                    # Estrai configurazione
                    config = response.get("config", {})

                    # Applica all'interfaccia
                    if self.load_camera_settings(config):
                        dialog.setValue(100)
                        self.status_label.setText("Configurazione attuale caricata con successo")
                    else:
                        self.status_label.setText("Configurazione parziale o non valida")
                else:
                    self.status_label.setText("Impossibile ottenere la configurazione attuale")
            else:
                self.status_label.setText("Impossibile inviare richiesta di configurazione")

        except Exception as e:
            logger.error(f"Errore nel ricaricamento delle impostazioni: {e}")
            self.status_label.setText(f"Errore: {str(e)}")

        finally:
            dialog.close()

    def _reset_default_settings(self):
        """
        Ripristina le impostazioni predefinite per entrambe le camere.
        """
        # Chiedi conferma
        response = QMessageBox.question(
            self,
            "Ripristina predefiniti",
            "Ripristinare i valori predefiniti per tutte le impostazioni delle camere?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if response != QMessageBox.Yes:
            return

        # Impostazioni predefinite per slider
        default_value = 50

        # Blocca temporaneamente la sincronizzazione
        sync_was_enabled = self.sync_cameras_checkbox.isChecked()
        self.sync_cameras_checkbox.setChecked(False)

        # Modalità colore come default
        self.left_mode_color.setChecked(True)
        self.right_mode_color.setChecked(True)

        # Reset slider camera sinistra
        self.left_exposure_slider.setValue(default_value)
        self.left_gain_slider.setValue(default_value)
        self.left_brightness_slider.setValue(default_value)
        self.left_contrast_slider.setValue(default_value)
        self.left_sharpness_slider.setValue(default_value)
        self.left_saturation_slider.setValue(default_value)

        # Reset slider camera destra
        self.right_exposure_slider.setValue(default_value)
        self.right_gain_slider.setValue(default_value)
        self.right_brightness_slider.setValue(default_value)
        self.right_contrast_slider.setValue(default_value)
        self.right_sharpness_slider.setValue(default_value)
        self.right_saturation_slider.setValue(default_value)

        # Ripristina sincronizzazione se era attiva
        self.sync_cameras_checkbox.setChecked(sync_was_enabled)

        # Aggiorna status
        self.status_label.setText("Impostazioni predefinite ripristinate")

    def _update_ui_state(self):
        """Aggiorna lo stato dell'interfaccia utente in base allo scanner selezionato."""
        if self.selected_scanner and self.scanner_controller:
            is_connected = self.scanner_controller.is_connected(self.selected_scanner.device_id)
            self._update_ui_enabled_state(is_connected)

            # Aggiorna info scanner
            if is_connected:
                self.scanner_info_label.setText(f"Scanner: {self.selected_scanner.name} (connesso)")
                self.scanner_info_label.setStyleSheet("color: green; font-weight: bold;")

                # Aggiorna status se necessario
                if self.status_label.text() == "Connetti uno scanner per configurare le camere":
                    self.status_label.setText("Scanner connesso. Pronto per configurare le camere.")
            else:
                self.scanner_info_label.setText(f"Scanner: {self.selected_scanner.name} (non connesso)")
                self.scanner_info_label.setStyleSheet("color: red;")
                self.status_label.setText("Scanner non connesso. Connetti lo scanner per configurare le camere.")
        else:
            self._update_ui_enabled_state(False)
            self.scanner_info_label.setText("Scanner: non selezionato")
            self.scanner_info_label.setStyleSheet("")
            self.status_label.setText("Connetti uno scanner per configurare le camere")

    def _update_ui_enabled_state(self, enabled: bool):
        """
        Abilita/disabilita i controlli dell'interfaccia in base allo stato di connessione.

        Args:
            enabled: True se i controlli devono essere abilitati, False altrimenti
        """
        # Elementi da abilitare/disabilitare
        self.camera_tabs.setEnabled(enabled)
        self.apply_settings_button.setEnabled(enabled)
        self.refresh_button.setEnabled(enabled)
        self.save_profile_button.setEnabled(enabled)

        # Profili sempre abilitati, ma load/delete solo se ci sono profili
        has_profiles = self.profile_combo.count() > 0
        self.load_profile_button.setEnabled(has_profiles)
        self.delete_profile_button.setEnabled(has_profiles)

    def update_selected_scanner(self, scanner):
        """
        Aggiorna lo scanner selezionato e lo stato dell'interfaccia.

        Args:
            scanner: Oggetto Scanner selezionato
        """
        self.selected_scanner = scanner
        self._update_ui_state()

    def load_camera_settings(self, settings: Dict):
        """
        Carica le impostazioni delle camere nell'interfaccia.

        Args:
            settings: Dizionario con le impostazioni delle camere

        Returns:
            bool: True se le impostazioni sono state caricate con successo, False altrimenti
        """
        try:
            if not settings or "camera" not in settings:
                return False

            camera_settings = settings["camera"]

            # Carica impostazioni camera sinistra
            if "left" in camera_settings:
                left = camera_settings["left"]

                # Modalità
                if "mode" in left:
                    if left["mode"] == "color":
                        self.left_mode_color.setChecked(True)
                    else:
                        self.left_mode_grayscale.setChecked(True)

                # Altre impostazioni
                if "exposure" in left:
                    self.left_exposure_slider.setValue(left["exposure"])
                if "gain" in left:
                    self.left_gain_slider.setValue(left["gain"])
                if "brightness" in left:
                    self.left_brightness_slider.setValue(left["brightness"])
                if "contrast" in left:
                    self.left_contrast_slider.setValue(left["contrast"])
                if "sharpness" in left:
                    self.left_sharpness_slider.setValue(left["sharpness"])
                if "saturation" in left:
                    self.left_saturation_slider.setValue(left["saturation"])

            # Carica impostazioni camera destra
            if "right" in camera_settings:
                right = camera_settings["right"]

                # Modalità
                if "mode" in right:
                    if right["mode"] == "color":
                        self.right_mode_color.setChecked(True)
                    else:
                        self.right_mode_grayscale.setChecked(True)

                # Altre impostazioni
                if "exposure" in right:
                    self.right_exposure_slider.setValue(right["exposure"])
                if "gain" in right:
                    self.right_gain_slider.setValue(right["gain"])
                if "brightness" in right:
                    self.right_brightness_slider.setValue(right["brightness"])
                if "contrast" in right:
                    self.right_contrast_slider.setValue(right["contrast"])
                if "sharpness" in right:
                    self.right_sharpness_slider.setValue(right["sharpness"])
                if "saturation" in right:
                    self.right_saturation_slider.setValue(right["saturation"])

            return True

        except Exception as e:
            logger.error(f"Errore nel caricamento delle impostazioni delle camere: {e}")
            return False

    def get_camera_settings(self) -> Dict:
        """
        Ottiene le impostazioni correnti delle camere dall'interfaccia.

        Returns:
            Dizionario con le impostazioni delle camere
        """
        left_mode = "color" if self.left_mode_color.isChecked() else "grayscale"
        right_mode = "color" if self.right_mode_color.isChecked() else "grayscale"

        return {
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