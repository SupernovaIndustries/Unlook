#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Widget per la configurazione del sistema UnLook.
"""

import logging
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QFormLayout, QComboBox, QSlider, QCheckBox,
    QSpinBox, QDoubleSpinBox, QTabWidget, QScrollArea,
    QFileDialog, QMessageBox, QFrame, QSplitter, QLineEdit,
    QRadioButton, QButtonGroup
)
from PySide6.QtCore import Qt, Signal, Slot, QSettings
from PySide6.QtGui import QFont

from controllers.config_controller import ConfigController
from models.config_model import (
    CameraConfig, DLPConfig, ToFConfig, ScanConfig, NetworkConfig,
    ApplicationConfig, StreamResolution, CameraMode
)

logger = logging.getLogger(__name__)


class CameraConfigWidget(QWidget):
    """
    Widget per la configurazione di una singola camera.
    """

    config_changed = Signal(int, CameraConfig)  # camera_index, config

    def __init__(self, camera_index: int, config_controller: ConfigController, parent=None):
        super().__init__(parent)
        self.camera_index = camera_index
        self.config_controller = config_controller

        # Carica la configurazione iniziale
        self._config = self.config_controller.get_camera_config(camera_index)

        # Nome della camera
        self.camera_name = "Sinistra" if camera_index == 0 else "Destra"

        # Configura l'interfaccia utente
        self._setup_ui()

        # Aggiorna l'interfaccia con i valori della configurazione
        self._update_ui_from_config()

    def _setup_ui(self):
        """Configura l'interfaccia utente."""
        # Layout principale
        layout = QVBoxLayout(self)

        # Gruppo principale
        camera_group = QGroupBox(f"Camera {self.camera_name}")
        camera_layout = QFormLayout(camera_group)

        # Checkbox per abilitare la camera
        self.enabled_checkbox = QCheckBox("Abilitata")
        self.enabled_checkbox.toggled.connect(self._on_config_changed)
        camera_layout.addRow("", self.enabled_checkbox)

        # Selezione della risoluzione
        resolution_layout = QHBoxLayout()

        self.resolution_combo = QComboBox()
        for name, _ in self.config_controller.get_available_resolutions():
            self.resolution_combo.addItem(name)

        self.resolution_combo.currentIndexChanged.connect(self._on_resolution_changed)
        resolution_layout.addWidget(self.resolution_combo)

        # Widget per la risoluzione personalizzata
        self.custom_resolution_widget = QWidget()
        custom_resolution_layout = QHBoxLayout(self.custom_resolution_widget)
        custom_resolution_layout.setContentsMargins(0, 0, 0, 0)

        self.width_spinbox = QSpinBox()
        self.width_spinbox.setRange(320, 3840)
        self.width_spinbox.setSingleStep(16)
        self.width_spinbox.valueChanged.connect(self._on_config_changed)

        self.height_spinbox = QSpinBox()
        self.height_spinbox.setRange(240, 2160)
        self.height_spinbox.setSingleStep(16)
        self.height_spinbox.valueChanged.connect(self._on_config_changed)

        custom_resolution_layout.addWidget(self.width_spinbox)
        custom_resolution_layout.addWidget(QLabel("x"))
        custom_resolution_layout.addWidget(self.height_spinbox)

        resolution_layout.addWidget(self.custom_resolution_widget)

        camera_layout.addRow("Risoluzione:", resolution_layout)

        # FPS
        self.fps_spinbox = QSpinBox()
        self.fps_spinbox.setRange(1, 60)
        self.fps_spinbox.setSingleStep(1)
        self.fps_spinbox.valueChanged.connect(self._on_config_changed)
        camera_layout.addRow("FPS:", self.fps_spinbox)

        # Modalità camera
        self.mode_combo = QComboBox()
        for name, _ in self.config_controller.get_available_camera_modes():
            self.mode_combo.addItem(name)

        self.mode_combo.currentIndexChanged.connect(self._on_config_changed)
        camera_layout.addRow("Modalità:", self.mode_combo)

        # Gruppo per i parametri di esposizione
        exposure_group = QGroupBox("Parametri di esposizione")
        exposure_layout = QFormLayout(exposure_group)

        # Esposizione
        exposure_layout_h = QHBoxLayout()

        self.exposure_slider = QSlider(Qt.Horizontal)
        self.exposure_slider.setRange(0, 100)
        self.exposure_slider.setSingleStep(1)
        self.exposure_slider.valueChanged.connect(self._on_exposure_changed)

        self.exposure_spinbox = QSpinBox()
        self.exposure_spinbox.setRange(0, 100)
        self.exposure_spinbox.setSingleStep(1)
        self.exposure_spinbox.valueChanged.connect(self._on_exposure_spin_changed)

        exposure_layout_h.addWidget(self.exposure_slider)
        exposure_layout_h.addWidget(self.exposure_spinbox)

        exposure_layout.addRow("Esposizione:", exposure_layout_h)

        # Guadagno
        gain_layout_h = QHBoxLayout()

        self.gain_slider = QSlider(Qt.Horizontal)
        self.gain_slider.setRange(0, 100)
        self.gain_slider.setSingleStep(1)
        self.gain_slider.valueChanged.connect(self._on_gain_changed)

        self.gain_spinbox = QSpinBox()
        self.gain_spinbox.setRange(0, 100)
        self.gain_spinbox.setSingleStep(1)
        self.gain_spinbox.valueChanged.connect(self._on_gain_spin_changed)

        gain_layout_h.addWidget(self.gain_slider)
        gain_layout_h.addWidget(self.gain_spinbox)

        exposure_layout.addRow("Guadagno:", gain_layout_h)

        # Gruppo per i parametri avanzati
        advanced_group = QGroupBox("Parametri avanzati")
        advanced_layout = QFormLayout(advanced_group)

        # Luminosità
        brightness_layout_h = QHBoxLayout()

        self.brightness_slider = QSlider(Qt.Horizontal)
        self.brightness_slider.setRange(0, 100)
        self.brightness_slider.setSingleStep(1)
        self.brightness_slider.valueChanged.connect(self._on_brightness_changed)

        self.brightness_spinbox = QSpinBox()
        self.brightness_spinbox.setRange(0, 100)
        self.brightness_spinbox.setSingleStep(1)
        self.brightness_spinbox.valueChanged.connect(self._on_brightness_spin_changed)

        brightness_layout_h.addWidget(self.brightness_slider)
        brightness_layout_h.addWidget(self.brightness_spinbox)

        advanced_layout.addRow("Luminosità:", brightness_layout_h)

        # Contrasto
        contrast_layout_h = QHBoxLayout()

        self.contrast_slider = QSlider(Qt.Horizontal)
        self.contrast_slider.setRange(0, 100)
        self.contrast_slider.setSingleStep(1)
        self.contrast_slider.valueChanged.connect(self._on_contrast_changed)

        self.contrast_spinbox = QSpinBox()
        self.contrast_spinbox.setRange(0, 100)
        self.contrast_spinbox.setSingleStep(1)
        self.contrast_spinbox.valueChanged.connect(self._on_contrast_spin_changed)

        contrast_layout_h.addWidget(self.contrast_slider)
        contrast_layout_h.addWidget(self.contrast_spinbox)

        advanced_layout.addRow("Contrasto:", contrast_layout_h)

        # Saturazione (solo per modalità colore)
        saturation_layout_h = QHBoxLayout()

        self.saturation_slider = QSlider(Qt.Horizontal)
        self.saturation_slider.setRange(0, 100)
        self.saturation_slider.setSingleStep(1)
        self.saturation_slider.valueChanged.connect(self._on_saturation_changed)

        self.saturation_spinbox = QSpinBox()
        self.saturation_spinbox.setRange(0, 100)
        self.saturation_spinbox.setSingleStep(1)
        self.saturation_spinbox.valueChanged.connect(self._on_saturation_spin_changed)

        saturation_layout_h.addWidget(self.saturation_slider)
        saturation_layout_h.addWidget(self.saturation_spinbox)

        advanced_layout.addRow("Saturazione:", saturation_layout_h)

        # Nitidezza
        sharpness_layout_h = QHBoxLayout()

        self.sharpness_slider = QSlider(Qt.Horizontal)
        self.sharpness_slider.setRange(0, 100)
        self.sharpness_slider.setSingleStep(1)
        self.sharpness_slider.valueChanged.connect(self._on_sharpness_changed)

        self.sharpness_spinbox = QSpinBox()
        self.sharpness_spinbox.setRange(0, 100)
        self.sharpness_spinbox.setSingleStep(1)
        self.sharpness_spinbox.valueChanged.connect(self._on_sharpness_spin_changed)

        sharpness_layout_h.addWidget(self.sharpness_slider)
        sharpness_layout_h.addWidget(self.sharpness_spinbox)

        advanced_layout.addRow("Nitidezza:", sharpness_layout_h)

        # Pulsanti di azione
        action_layout = QHBoxLayout()

        self.reset_button = QPushButton("Ripristina predefiniti")
        self.reset_button.clicked.connect(self._on_reset_clicked)

        self.apply_button = QPushButton("Applica")
        self.apply_button.clicked.connect(self._on_apply_clicked)

        action_layout.addWidget(self.reset_button)
        action_layout.addStretch(1)
        action_layout.addWidget(self.apply_button)

        # Aggiungi i widget al layout principale
        layout.addWidget(camera_group)
        layout.addWidget(exposure_group)
        layout.addWidget(advanced_group)
        layout.addLayout(action_layout)
        layout.addStretch(1)

    def _update_ui_from_config(self):
        """Aggiorna l'interfaccia utente con i valori della configurazione."""
        # Blocca i segnali per evitare attivazioni durante l'aggiornamento
        self._block_signals(True)

        # Attiva/disattiva la camera
        self.enabled_checkbox.setChecked(self._config.enabled)

        # Imposta la risoluzione
        if self._config.resolution == StreamResolution.LOW:
            self.resolution_combo.setCurrentIndex(0)
        elif self._config.resolution == StreamResolution.MEDIUM:
            self.resolution_combo.setCurrentIndex(1)
        elif self._config.resolution == StreamResolution.HIGH:
            self.resolution_combo.setCurrentIndex(2)
        else:  # CUSTOM
            self.resolution_combo.setCurrentIndex(3)

        # Aggiorna la visibilità del widget di risoluzione personalizzata
        self.custom_resolution_widget.setVisible(
            self._config.resolution == StreamResolution.CUSTOM
        )

        # Imposta i valori della risoluzione personalizzata
        self.width_spinbox.setValue(self._config.custom_resolution[0])
        self.height_spinbox.setValue(self._config.custom_resolution[1])

        # Imposta gli FPS
        self.fps_spinbox.setValue(self._config.fps)

        # Imposta la modalità
        if self._config.mode == CameraMode.GRAYSCALE:
            self.mode_combo.setCurrentIndex(0)
        else:  # COLOR
            self.mode_combo.setCurrentIndex(1)

        # Aggiorna la visibilità del controllo saturazione in base alla modalità
        saturation_row = self.saturation_slider.parent().layout().labelForField(self.saturation_slider.parent())
        if saturation_row:
            saturation_row.setVisible(self._config.mode == CameraMode.COLOR)
            self.saturation_slider.parent().setVisible(self._config.mode == CameraMode.COLOR)

        # Imposta i parametri di esposizione
        self.exposure_slider.setValue(self._config.exposure)
        self.exposure_spinbox.setValue(self._config.exposure)

        self.gain_slider.setValue(self._config.gain)
        self.gain_spinbox.setValue(self._config.gain)

        # Imposta i parametri avanzati
        self.brightness_slider.setValue(self._config.brightness)
        self.brightness_spinbox.setValue(self._config.brightness)

        self.contrast_slider.setValue(self._config.contrast)
        self.contrast_spinbox.setValue(self._config.contrast)

        self.saturation_slider.setValue(self._config.saturation)
        self.saturation_spinbox.setValue(self._config.saturation)

        self.sharpness_slider.setValue(self._config.sharpness)
        self.sharpness_spinbox.setValue(self._config.sharpness)

        # Ripristina i segnali
        self._block_signals(False)

    def _block_signals(self, block: bool):
        """Blocca/sblocca i segnali di tutti i widget."""
        widgets = [
            self.enabled_checkbox,
            self.resolution_combo,
            self.width_spinbox,
            self.height_spinbox,
            self.fps_spinbox,
            self.mode_combo,
            self.exposure_slider,
            self.exposure_spinbox,
            self.gain_slider,
            self.gain_spinbox,
            self.brightness_slider,
            self.brightness_spinbox,
            self.contrast_slider,
            self.contrast_spinbox,
            self.saturation_slider,
            self.saturation_spinbox,
            self.sharpness_slider,
            self.sharpness_spinbox
        ]

        for widget in widgets:
            widget.blockSignals(block)

    def _update_config_from_ui(self):
        """Aggiorna la configurazione con i valori dell'interfaccia utente."""
        # Crea una nuova configurazione
        config = CameraConfig()

        # Attiva/disattiva la camera
        config.enabled = self.enabled_checkbox.isChecked()

        # Imposta la risoluzione
        resolution_index = self.resolution_combo.currentIndex()
        if resolution_index == 0:
            config.resolution = StreamResolution.LOW
        elif resolution_index == 1:
            config.resolution = StreamResolution.MEDIUM
        elif resolution_index == 2:
            config.resolution = StreamResolution.HIGH
        else:  # 3
            config.resolution = StreamResolution.CUSTOM

        # Imposta la risoluzione personalizzata
        config.custom_resolution = (
            self.width_spinbox.value(),
            self.height_spinbox.value()
        )

        # Imposta gli FPS
        config.fps = self.fps_spinbox.value()

        # Imposta la modalità
        config.mode = CameraMode.GRAYSCALE if self.mode_combo.currentIndex() == 0 else CameraMode.COLOR

        # Imposta i parametri di esposizione
        config.exposure = self.exposure_slider.value()
        config.gain = self.gain_slider.value()

        # Imposta i parametri avanzati
        config.brightness = self.brightness_slider.value()
        config.contrast = self.contrast_slider.value()
        config.saturation = self.saturation_slider.value()
        config.sharpness = self.sharpness_slider.value()

        # Aggiorna la configurazione
        self._config = config

        # Emetti il segnale di modifica
        self.config_changed.emit(self.camera_index, config)

    @Slot()
    def _on_config_changed(self):
        """Gestisce la modifica della configurazione."""
        # Aggiorna la visibilità del widget di risoluzione personalizzata
        self.custom_resolution_widget.setVisible(
            self.resolution_combo.currentIndex() == 3
        )

        # Aggiorna la visibilità del controllo saturazione in base alla modalità
        is_color = self.mode_combo.currentIndex() == 1
        saturation_row = self.saturation_slider.parent().layout().labelForField(self.saturation_slider.parent())
        if saturation_row:
            saturation_row.setVisible(is_color)
            self.saturation_slider.parent().setVisible(is_color)

        # Aggiorna la configurazione
        self._update_config_from_ui()

    @Slot(int)
    def _on_resolution_changed(self, index: int):
        """Gestisce il cambio di risoluzione."""
        # Aggiorna la visibilità del widget di risoluzione personalizzata
        self.custom_resolution_widget.setVisible(index == 3)

        # Aggiorna la configurazione
        self._update_config_from_ui()

    @Slot()
    def _on_reset_clicked(self):
        """Gestisce il clic sul pulsante Ripristina."""
        # Chiede conferma all'utente
        response = QMessageBox.question(
            self,
            "Ripristina configurazione",
            f"Sei sicuro di voler ripristinare la configurazione predefinita per la camera {self.camera_name}?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if response == QMessageBox.Yes:
            # Ripristina la configurazione predefinita
            self._config = CameraConfig()

            # Aggiorna l'interfaccia
            self._update_ui_from_config()

            # Emetti il segnale di modifica
            self.config_changed.emit(self.camera_index, self._config)

    @Slot()
    def _on_apply_clicked(self):
        """Gestisce il clic sul pulsante Applica."""
        # Aggiorna la configurazione
        self._update_config_from_ui()

        # Salva la configurazione
        self.config_controller.update_camera_config(self.camera_index, self._config)
        self.config_controller.save_config()

        # Mostra un messaggio di conferma
        QMessageBox.information(
            self,
            "Configurazione salvata",
            f"La configurazione della camera {self.camera_name} è stata salvata.",
            QMessageBox.Ok
        )

    @Slot(int)
    def _on_exposure_changed(self, value: int):
        """Gestisce il cambio di esposizione."""
        # Aggiorna lo spinbox
        self.exposure_spinbox.blockSignals(True)
        self.exposure_spinbox.setValue(value)
        self.exposure_spinbox.blockSignals(False)

        # Aggiorna la configurazione
        self._update_config_from_ui()

    @Slot(int)
    def _on_exposure_spin_changed(self, value: int):
        """Gestisce il cambio di esposizione dallo spinbox."""
        # Aggiorna lo slider
        self.exposure_slider.blockSignals(True)
        self.exposure_slider.setValue(value)
        self.exposure_slider.blockSignals(False)

        # Aggiorna la configurazione
        self._update_config_from_ui()

    @Slot(int)
    def _on_gain_changed(self, value: int):
        """Gestisce il cambio di guadagno."""
        # Aggiorna lo spinbox
        self.gain_spinbox.blockSignals(True)
        self.gain_spinbox.setValue(value)
        self.gain_spinbox.blockSignals(False)

        # Aggiorna la configurazione
        self._update_config_from_ui()

    @Slot(int)
    def _on_gain_spin_changed(self, value: int):
        """Gestisce il cambio di guadagno dallo spinbox."""
        # Aggiorna lo slider
        self.gain_slider.blockSignals(True)
        self.gain_slider.setValue(value)
        self.gain_slider.blockSignals(False)

        # Aggiorna la configurazione
        self._update_config_from_ui()

    @Slot(int)
    def _on_brightness_changed(self, value: int):
        """Gestisce il cambio di luminosità."""
        # Aggiorna lo spinbox
        self.brightness_spinbox.blockSignals(True)
        self.brightness_spinbox.setValue(value)
        self.brightness_spinbox.blockSignals(False)

        # Aggiorna la configurazione
        self._update_config_from_ui()

    @Slot(int)
    def _on_brightness_spin_changed(self, value: int):
        """Gestisce il cambio di luminosità dallo spinbox."""
        # Aggiorna lo slider
        self.brightness_slider.blockSignals(True)
        self.brightness_slider.setValue(value)
        self.brightness_slider.blockSignals(False)

        # Aggiorna la configurazione
        self._update_config_from_ui()

    @Slot(int)
    def _on_contrast_changed(self, value: int):
        """Gestisce il cambio di contrasto."""
        # Aggiorna lo spinbox
        self.contrast_spinbox.blockSignals(True)
        self.contrast_spinbox.setValue(value)
        self.contrast_spinbox.blockSignals(False)

        # Aggiorna la configurazione
        self._update_config_from_ui()

    @Slot(int)
    def _on_contrast_spin_changed(self, value: int):
        """Gestisce il cambio di contrasto dallo spinbox."""
        # Aggiorna lo slider
        self.contrast_slider.blockSignals(True)
        self.contrast_slider.setValue(value)
        self.contrast_slider.blockSignals(False)

        # Aggiorna la configurazione
        self._update_config_from_ui()

    @Slot(int)
    def _on_saturation_changed(self, value: int):
        """Gestisce il cambio di saturazione."""
        # Aggiorna lo spinbox
        self.saturation_spinbox.blockSignals(True)
        self.saturation_spinbox.setValue(value)
        self.saturation_spinbox.blockSignals(False)

        # Aggiorna la configurazione
        self._update_config_from_ui()

    @Slot(int)
    def _on_saturation_spin_changed(self, value: int):
        """Gestisce il cambio di saturazione dallo spinbox."""
        # Aggiorna lo slider
        self.saturation_slider.blockSignals(True)
        self.saturation_slider.setValue(value)
        self.saturation_slider.blockSignals(False)

        # Aggiorna la configurazione
        self._update_config_from_ui()

    @Slot(int)
    def _on_sharpness_changed(self, value: int):
        """Gestisce il cambio di nitidezza."""
        # Aggiorna lo spinbox
        self.sharpness_spinbox.blockSignals(True)
        self.sharpness_spinbox.setValue(value)
        self.sharpness_spinbox.blockSignals(False)

        # Aggiorna la configurazione
        self._update_config_from_ui()

    @Slot(int)
    def _on_sharpness_spin_changed(self, value: int):
        """Gestisce il cambio di nitidezza dallo spinbox."""
        # Aggiorna lo slider
        self.sharpness_slider.blockSignals(True)
        self.sharpness_slider.setValue(value)
        self.sharpness_slider.blockSignals(False)

        # Aggiorna la configurazione
        self._update_config_from_ui()


class ScanConfigWidget(QWidget):
    """
    Widget per la configurazione delle impostazioni di scansione.
    """

    config_changed = Signal(ScanConfig)

    def __init__(self, config_controller: ConfigController, parent=None):
        super().__init__(parent)
        self.config_controller = config_controller

        # Carica la configurazione iniziale
        self._config = self.config_controller.get_scan_config()

        # Configura l'interfaccia utente
        self._setup_ui()

        # Aggiorna l'interfaccia con i valori della configurazione
        self._update_ui_from_config()

    def _setup_ui(self):
        """Configura l'interfaccia utente."""
        # Layout principale
        layout = QVBoxLayout(self)

        # Gruppo dei parametri di scansione
        scan_group = QGroupBox("Parametri di scansione")
        scan_layout = QFormLayout(scan_group)

        # Nome della scansione
        self.name_edit = QLineEdit()
        self.name_edit.textChanged.connect(self._on_config_changed)
        scan_layout.addRow("Nome:", self.name_edit)

        # Risoluzione
        resolution_layout = QHBoxLayout()

        self.resolution_spinbox = QDoubleSpinBox()
        self.resolution_spinbox.setRange(0.1, 10.0)
        self.resolution_spinbox.setSingleStep(0.1)
        self.resolution_spinbox.setDecimals(1)
        self.resolution_spinbox.setSuffix(" mm")
        self.resolution_spinbox.valueChanged.connect(self._on_config_changed)

        resolution_layout.addWidget(self.resolution_spinbox)
        resolution_layout.addStretch(1)

        scan_layout.addRow("Risoluzione:", resolution_layout)

        # Qualità
        quality_layout = QHBoxLayout()

        self.quality_slider = QSlider(Qt.Horizontal)
        self.quality_slider.setRange(1, 5)
        self.quality_slider.setSingleStep(1)
        self.quality_slider.setTickPosition(QSlider.TicksBelow)
        self.quality_slider.setTickInterval(1)
        self.quality_slider.valueChanged.connect(self._on_quality_changed)

        self.quality_spinbox = QSpinBox()
        self.quality_spinbox.setRange(1, 5)
        self.quality_spinbox.setSingleStep(1)
        self.quality_spinbox.valueChanged.connect(self._on_quality_spin_changed)

        quality_layout.addWidget(self.quality_slider)
        quality_layout.addWidget(self.quality_spinbox)

        scan_layout.addRow("Qualità:", quality_layout)

        # Checkbox per l'acquisizione del colore
        self.color_checkbox = QCheckBox("Acquisizione colore")
        self.color_checkbox.toggled.connect(self._on_config_changed)
        scan_layout.addRow("", self.color_checkbox)

        # Modalità di scansione
        self.mode_group = QGroupBox("Modalità di scansione")
        mode_layout = QVBoxLayout(self.mode_group)

        self.mode_button_group = QButtonGroup(self)

        self.structured_light_radio = QRadioButton("Luce strutturata")
        self.tof_radio = QRadioButton("Time-of-Flight")

        self.mode_button_group.addButton(self.structured_light_radio, 0)
        self.mode_button_group.addButton(self.tof_radio, 1)

        self.mode_button_group.buttonClicked.connect(self._on_config_changed)

        mode_layout.addWidget(self.structured_light_radio)
        mode_layout.addWidget(self.tof_radio)

        # Area di scansione
        area_group = QGroupBox("Area di scansione")
        area_layout = QFormLayout(area_group)

        # Dimensioni X, Y, Z
        self.area_x_spinbox = QSpinBox()
        self.area_x_spinbox.setRange(10, 1000)
        self.area_x_spinbox.setSingleStep(10)
        self.area_x_spinbox.setSuffix(" mm")
        self.area_x_spinbox.valueChanged.connect(self._on_config_changed)
        area_layout.addRow("Larghezza (X):", self.area_x_spinbox)

        self.area_y_spinbox = QSpinBox()
        self.area_y_spinbox.setRange(10, 1000)
        self.area_y_spinbox.setSingleStep(10)
        self.area_y_spinbox.setSuffix(" mm")
        self.area_y_spinbox.valueChanged.connect(self._on_config_changed)
        area_layout.addRow("Altezza (Y):", self.area_y_spinbox)

        self.area_z_spinbox = QSpinBox()
        self.area_z_spinbox.setRange(10, 1000)
        self.area_z_spinbox.setSingleStep(10)
        self.area_z_spinbox.setSuffix(" mm")
        self.area_z_spinbox.valueChanged.connect(self._on_config_changed)
        area_layout.addRow("Profondità (Z):", self.area_z_spinbox)

        # Pulsanti di azione
        action_layout = QHBoxLayout()

        self.reset_button = QPushButton("Ripristina predefiniti")
        self.reset_button.clicked.connect(self._on_reset_clicked)

        self.apply_button = QPushButton("Applica")
        self.apply_button.clicked.connect(self._on_apply_clicked)

        action_layout.addWidget(self.reset_button)
        action_layout.addStretch(1)
        action_layout.addWidget(self.apply_button)

        # Aggiungi i widget al layout principale
        layout.addWidget(scan_group)
        layout.addWidget(self.mode_group)
        layout.addWidget(area_group)
        layout.addLayout(action_layout)
        layout.addStretch(1)

    def _update_ui_from_config(self):
        """Aggiorna l'interfaccia utente con i valori della configurazione."""
        # Blocca i segnali per evitare attivazioni durante l'aggiornamento
        self._block_signals(True)

        # Imposta il nome della scansione
        self.name_edit.setText(self._config.name)

        # Imposta la risoluzione
        self.resolution_spinbox.setValue(self._config.resolution)

        # Imposta la qualità
        self.quality_slider.setValue(self._config.quality)
        self.quality_spinbox.setValue(self._config.quality)

        # Imposta l'acquisizione colore
        self.color_checkbox.setChecked(self._config.color_capture)

        # Imposta la modalità di scansione
        if self._config.scan_mode == "structured_light":
            self.structured_light_radio.setChecked(True)
        else:  # tof
            self.tof_radio.setChecked(True)

        # Imposta l'area di scansione
        self.area_x_spinbox.setValue(self._config.scan_area[0])
        self.area_y_spinbox.setValue(self._config.scan_area[1])
        self.area_z_spinbox.setValue(self._config.scan_area[2])

        # Ripristina i segnali
        self._block_signals(False)

    def _block_signals(self, block: bool):
        """Blocca/sblocca i segnali di tutti i widget."""
        widgets = [
            self.name_edit,
            self.resolution_spinbox,
            self.quality_slider,
            self.quality_spinbox,
            self.color_checkbox,
            self.mode_button_group,
            self.area_x_spinbox,
            self.area_y_spinbox,
            self.area_z_spinbox
        ]

        for widget in widgets:
            widget.blockSignals(block)

    def _update_config_from_ui(self):
        """Aggiorna la configurazione con i valori dell'interfaccia utente."""
        # Crea una nuova configurazione
        config = ScanConfig()

        # Imposta il nome della scansione
        config.name = self.name_edit.text()

        # Imposta la risoluzione
        config.resolution = self.resolution_spinbox.value()

        # Imposta la qualità
        config.quality = self.quality_slider.value()

        # Imposta l'acquisizione colore
        config.color_capture = self.color_checkbox.isChecked()

        # Imposta la modalità di scansione
        config.scan_mode = "structured_light" if self.structured_light_radio.isChecked() else "tof"

        # Imposta l'area di scansione
        config.scan_area = (
            self.area_x_spinbox.value(),
            self.area_y_spinbox.value(),
            self.area_z_spinbox.value()
        )

        # Aggiorna la configurazione
        self._config = config

        # Emetti il segnale di modifica
        self.config_changed.emit(config)

    @Slot()
    def _on_config_changed(self):
        """Gestisce la modifica della configurazione."""
        # Aggiorna la configurazione
        self._update_config_from_ui()

    @Slot(int)
    def _on_quality_changed(self, value: int):
        """Gestisce il cambio di qualità."""
        # Aggiorna lo spinbox
        self.quality_spinbox.blockSignals(True)
        self.quality_spinbox.setValue(value)
        self.quality_spinbox.blockSignals(False)

        # Aggiorna la configurazione
        self._update_config_from_ui()

    @Slot(int)
    def _on_quality_spin_changed(self, value: int):
        """Gestisce il cambio di qualità dallo spinbox."""
        # Aggiorna lo slider
        self.quality_slider.blockSignals(True)
        self.quality_slider.setValue(value)
        self.quality_slider.blockSignals(False)

        # Aggiorna la configurazione
        self._update_config_from_ui()

    @Slot()
    def _on_reset_clicked(self):
        """Gestisce il clic sul pulsante Ripristina."""
        # Chiede conferma all'utente
        response = QMessageBox.question(
            self,
            "Ripristina configurazione",
            "Sei sicuro di voler ripristinare la configurazione predefinita per la scansione?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if response == QMessageBox.Yes:
            # Ripristina la configurazione predefinita
            self._config = ScanConfig()

            # Aggiorna l'interfaccia
            self._update_ui_from_config()

            # Emetti il segnale di modifica
            self.config_changed.emit(self._config)

    @Slot()
    def _on_apply_clicked(self):
        """Gestisce il clic sul pulsante Applica."""
        # Aggiorna la configurazione
        self._update_config_from_ui()

        # Salva la configurazione
        self.config_controller.update_scan_config(self._config)
        self.config_controller.save_config()

        # Mostra un messaggio di conferma
        QMessageBox.information(
            self,
            "Configurazione salvata",
            "La configurazione di scansione è stata salvata.",
            QMessageBox.Ok
        )


class ApplicationConfigWidget(QWidget):
    """
    Widget per la configurazione delle impostazioni dell'applicazione.
    """

    config_changed = Signal(ApplicationConfig)

    def __init__(self, config_controller: ConfigController, parent=None):
        super().__init__(parent)
        self.config_controller = config_controller

        # Carica la configurazione iniziale
        self._config = self.config_controller.get_app_config()

        # Configura l'interfaccia utente
        self._setup_ui()

        # Aggiorna l'interfaccia con i valori della configurazione
        self._update_ui_from_config()

    def _setup_ui(self):
        """Configura l'interfaccia utente."""
        # Layout principale
        layout = QVBoxLayout(self)

        # Gruppo delle impostazioni generali
        general_group = QGroupBox("Impostazioni generali")
        general_layout = QFormLayout(general_group)

        # Lingua
        self.language_combo = QComboBox()
        self.language_combo.addItem("Italiano", "it")
        self.language_combo.addItem("English", "en")
        self.language_combo.currentIndexChanged.connect(self._on_config_changed)
        general_layout.addRow("Lingua:", self.language_combo)

        # Tema
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("Chiaro", "light")
        self.theme_combo.addItem("Scuro", "dark")
        self.theme_combo.addItem("Sistema", "system")
        self.theme_combo.currentIndexChanged.connect(self._on_config_changed)
        general_layout.addRow("Tema:", self.theme_combo)

        # Percorso di salvataggio
        save_path_layout = QHBoxLayout()

        self.save_path_edit = QLineEdit()
        self.save_path_edit.setReadOnly(True)

        self.browse_button = QPushButton("Sfoglia...")
        self.browse_button.clicked.connect(self._on_browse_clicked)

        save_path_layout.addWidget(self.save_path_edit)
        save_path_layout.addWidget(self.browse_button)

        general_layout.addRow("Percorso di salvataggio:", save_path_layout)

        # Controllo aggiornamenti automatico
        self.update_checkbox = QCheckBox("Controlla aggiornamenti all'avvio")
        self.update_checkbox.toggled.connect(self._on_config_changed)
        general_layout.addRow("", self.update_checkbox)

        # Opzioni avanzate
        self.advanced_checkbox = QCheckBox("Mostra opzioni avanzate")
        self.advanced_checkbox.toggled.connect(self._on_config_changed)
        general_layout.addRow("", self.advanced_checkbox)

        # Pulsanti di azione
        action_layout = QHBoxLayout()

        self.reset_button = QPushButton("Ripristina predefiniti")
        self.reset_button.clicked.connect(self._on_reset_clicked)

        self.apply_button = QPushButton("Applica")
        self.apply_button.clicked.connect(self._on_apply_clicked)

        action_layout.addWidget(self.reset_button)
        action_layout.addStretch(1)
        action_layout.addWidget(self.apply_button)

        # Aggiungi i widget al layout principale
        layout.addWidget(general_group)
        layout.addLayout(action_layout)
        layout.addStretch(1)

    def _update_ui_from_config(self):
        """Aggiorna l'interfaccia utente con i valori della configurazione."""
        # Blocca i segnali per evitare attivazioni durante l'aggiornamento
        self._block_signals(True)

        # Imposta la lingua
        index = self.language_combo.findData(self._config.language)
        if index >= 0:
            self.language_combo.setCurrentIndex(index)

        # Imposta il tema
        index = self.theme_combo.findData(self._config.theme)
        if index >= 0:
            self.theme_combo.setCurrentIndex(index)

        # Imposta il percorso di salvataggio
        self.save_path_edit.setText(self._config.save_path)

        # Imposta il controllo aggiornamenti automatico
        self.update_checkbox.setChecked(self._config.auto_check_updates)

        # Imposta le opzioni avanzate
        self.advanced_checkbox.setChecked(self._config.show_advanced_options)

        # Ripristina i segnali
        self._block_signals(False)

    def _block_signals(self, block: bool):
        """Blocca/sblocca i segnali di tutti i widget."""
        widgets = [
            self.language_combo,
            self.theme_combo,
            self.update_checkbox,
            self.advanced_checkbox
        ]

        for widget in widgets:
            widget.blockSignals(block)

    def _update_config_from_ui(self):
        """Aggiorna la configurazione con i valori dell'interfaccia utente."""
        # Crea una nuova configurazione
        config = ApplicationConfig()

        # Imposta la lingua
        config.language = self.language_combo.currentData()

        # Imposta il tema
        config.theme = self.theme_combo.currentData()

        # Imposta il percorso di salvataggio
        config.save_path = self.save_path_edit.text()

        # Imposta il controllo aggiornamenti automatico
        config.auto_check_updates = self.update_checkbox.isChecked()

        # Imposta le opzioni avanzate
        config.show_advanced_options = self.advanced_checkbox.isChecked()

        # Aggiorna la configurazione
        self._config = config

        # Emetti il segnale di modifica
        self.config_changed.emit(config)

    @Slot()
    def _on_config_changed(self):
        """Gestisce la modifica della configurazione."""
        # Aggiorna la configurazione
        self._update_config_from_ui()

    @Slot()
    def _on_browse_clicked(self):
        """Gestisce il clic sul pulsante Sfoglia."""
        # Apre un selettore di directory
        directory = QFileDialog.getExistingDirectory(
            self,
            "Seleziona la directory di salvataggio",
            self.save_path_edit.text(),
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks
        )

        if directory:
            # Aggiorna il percorso di salvataggio
            self.save_path_edit.setText(directory)

            # Aggiorna la configurazione
            self._update_config_from_ui()

    @Slot()
    def _on_reset_clicked(self):
        """Gestisce il clic sul pulsante Ripristina."""
        # Chiede conferma all'utente
        response = QMessageBox.question(
            self,
            "Ripristina configurazione",
            "Sei sicuro di voler ripristinare la configurazione predefinita dell'applicazione?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if response == QMessageBox.Yes:
            # Ripristina la configurazione predefinita
            self._config = ApplicationConfig()

            # Aggiorna l'interfaccia
            self._update_ui_from_config()

            # Emetti il segnale di modifica
            self.config_changed.emit(self._config)

    @Slot()
    def _on_apply_clicked(self):
        """Gestisce il clic sul pulsante Applica."""
        # Aggiorna la configurazione
        self._update_config_from_ui()

        # Salva la configurazione
        self.config_controller.update_app_config(self._config)
        self.config_controller.save_config()

        # Mostra un messaggio di conferma
        QMessageBox.information(
            self,
            "Configurazione salvata",
            "La configurazione dell'applicazione è stata salvata.\nAlcune modifiche potrebbero richiedere il riavvio dell'applicazione.",
            QMessageBox.Ok
        )


class ConfigurationWidget(QWidget):
    """
    Widget principale per la configurazione del sistema UnLook.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        # Crea il gestore di configurazione
        from models.config_model import ConfigManager
        self._config_manager = ConfigManager()

        # Crea il controller di configurazione
        from controllers.config_controller import ConfigController
        self._config_controller = ConfigController(self._config_manager)

        # Configura l'interfaccia utente
        self._setup_ui()

    def _setup_ui(self):
        """Configura l'interfaccia utente."""
        # Layout principale
        layout = QVBoxLayout(self)

        # TabWidget per le diverse sezioni di configurazione
        self.tab_widget = QTabWidget()

        # Tab per la configurazione delle camere
        camera_tab = QWidget()
        camera_layout = QHBoxLayout(camera_tab)

        # Splitter per dividere le due camere
        camera_splitter = QSplitter(Qt.Horizontal)

        # Widget di configurazione per le camere
        self.left_camera_widget = CameraConfigWidget(0, self._config_controller)
        self.right_camera_widget = CameraConfigWidget(1, self._config_controller)

        camera_splitter.addWidget(self.left_camera_widget)
        camera_splitter.addWidget(self.right_camera_widget)

        # Imposta le dimensioni iniziali uguali
        camera_splitter.setSizes([self.width() // 2, self.width() // 2])

        camera_layout.addWidget(camera_splitter)

        # Tab per la configurazione della scansione
        scan_tab = QScrollArea()
        scan_tab.setWidgetResizable(True)
        scan_tab.setFrameShape(QFrame.NoFrame)

        self.scan_widget = ScanConfigWidget(self._config_controller)
        scan_tab.setWidget(self.scan_widget)

        # Tab per la configurazione dell'applicazione
        app_tab = QScrollArea()
        app_tab.setWidgetResizable(True)
        app_tab.setFrameShape(QFrame.NoFrame)

        self.app_widget = ApplicationConfigWidget(self._config_controller)
        app_tab.setWidget(self.app_widget)

        # Aggiungi i tab al TabWidget
        self.tab_widget.addTab(camera_tab, "Camere")
        self.tab_widget.addTab(scan_tab, "Scansione")
        self.tab_widget.addTab(app_tab, "Applicazione")

        # Aggiungi il TabWidget al layout principale
        layout.addWidget(self.tab_widget)