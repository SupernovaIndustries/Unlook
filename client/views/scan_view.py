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
import glob
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from client.models.scanner_model import Scanner, ScannerStatus

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFileDialog,
    QGroupBox, QFormLayout, QComboBox, QSlider, QCheckBox, QMessageBox,
    QSpinBox, QDoubleSpinBox, QFrame, QSplitter, QTabWidget, QRadioButton,
    QButtonGroup, QLineEdit, QProgressBar, QToolButton, QDialog, QScrollArea,
    QTextEdit, QApplication, QStyle, QStyleOption, QStyleFactory, QProgressDialog
)
from PySide6.QtCore import Qt, Signal, Slot, QTimer, QSize, QSettings, QThread, QObject
from PySide6.QtGui import QIcon, QFont, QColor, QPixmap, QImage


# Definizione della classe ScanFrameProcessor come fallback globale
# in caso di fallimento dell'importazione
class ScanFrameProcessor:
    """Classe fallback per ScanFrameProcessor quando non è disponibile il modulo originale."""

    def __init__(self, output_dir=None):
        self.output_dir = output_dir
        self._progress_callback = None
        self._frame_callback = None
        logger = logging.getLogger(__name__)
        logger.warning("Utilizzando versione fallback di ScanFrameProcessor")

    def set_callbacks(self, progress_callback=None, frame_callback=None):
        self._progress_callback = progress_callback
        self._frame_callback = frame_callback

    def start_scan(self, scan_id=None, num_patterns=24, pattern_type="PROGRESSIVE"):
        if scan_id is None:
            scan_id = f"Scan_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        return scan_id

    def process_frame(self, camera_index, frame, frame_info):
        return True

    def stop_scan(self):
        return {"success": True, "message": "Scan stopped (mock implementation)"}

    def get_scan_progress(self):
        return {"state": "IDLE", "progress": 0.0}


# Importa il modulo di triangolazione
try:
    from client.processing.triangulation import ScanProcessor, PatternType
except ImportError:
    logger = logging.getLogger(__name__)
    logger.error("Impossibile importare il modulo di triangolazione. La visualizzazione 3D sarà disabilitata.")


    # Definizione di PatternType come fallback
    class PatternType:
        PROGRESSIVE = "PROGRESSIVE"
        GRAY_CODE = "GRAY_CODE"
        BINARY_CODE = "BINARY_CODE"
        PHASE_SHIFT = "PHASE_SHIFT"


    # Definizione di ScanProcessor come fallback
    class ScanProcessor:
        def __init__(self, *args, **kwargs):
            pass

        def set_callbacks(self, *args, **kwargs):
            pass

        def load_local_scan(self, *args, **kwargs):
            return False

        def process_scan(self, *args, **kwargs):
            return False

# Ora tentiamo di importare la versione reale di ScanFrameProcessor
try:
    from client.processing.scan_frame_processor import ScanFrameProcessor

    logger = logging.getLogger(__name__)
    logger.info("ScanFrameProcessor importato con successo")
except ImportError:
    logger = logging.getLogger(__name__)
    logger.error("Impossibile importare ScanFrameProcessor, utilizzo versione fallback")
    # Nota: Non è necessario ridefinire ScanFrameProcessor qui perché
    # l'abbiamo già definito a livello globale prima del blocco try

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

try:
    from PyQt5.QtWebEngineWidgets import QWebEngineView
    WEBENGINE_AVAILABLE = True
except ImportError:
    try:
        from PySide6.QtWebEngineWidgets import QWebEngineView
        WEBENGINE_AVAILABLE = True
    except ImportError:
        WEBENGINE_AVAILABLE = False
        logger.warning("QtWebEngine non disponibile. Sarà usata una visualizzazione 3D semplificata.")

# Configura logging
logger = logging.getLogger(__name__)


class RealtimeViewer3D(QWidget):
    """Widget per la visualizzazione in tempo reale della nuvola di punti 3D."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pointcloud = None
        self.last_update_time = 0
        self._setup_ui()

    def _setup_ui(self):
        """Configura l'interfaccia utente del visualizzatore."""
        layout = QVBoxLayout(self)

        # Usa WebEngine se disponibile per una visualizzazione 3D interattiva
        if WEBENGINE_AVAILABLE:
            self.web_view = QWebEngineView()
            self.web_view.setMinimumHeight(300)
            layout.addWidget(self.web_view)

            # Carica una pagina HTML con Three.js per la visualizzazione
            self._load_threejs_viewer()
        else:
            # Fallback a un semplice widget di visualizzazione
            self.view_label = QLabel("Visualizzazione nuvola di punti")
            self.view_label.setAlignment(Qt.AlignCenter)
            self.view_label.setMinimumHeight(300)
            self.view_label.setStyleSheet("background-color: #f0f0f0; border: 1px solid #ccc;")
            layout.addWidget(self.view_label)

        # Aggiunge informazioni sulla nuvola di punti
        self.info_label = QLabel("Nessuna nuvola di punti disponibile")
        self.info_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.info_label)

        # Aggiungi controlli per la visualizzazione
        controls_layout = QHBoxLayout()

        self.center_button = QPushButton("Centra Vista")
        self.center_button.clicked.connect(self._center_view)

        self.reset_button = QPushButton("Reset")
        self.reset_button.clicked.connect(self._reset_view)

        controls_layout.addWidget(self.center_button)
        controls_layout.addWidget(self.reset_button)

        layout.addLayout(controls_layout)

    def _load_threejs_viewer(self):
        """Carica il visualizzatore Three.js."""
        if not hasattr(self, 'web_view'):
            return

        # HTML base per il visualizzatore
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>UnLook 3D Viewer</title>
            <style>
                body { margin: 0; overflow: hidden; }
                canvas { width: 100%; height: 100%; display: block; }
            </style>
            <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
            <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.min.js"></script>
        </head>
        <body>
            <script>
                // Variabili globali
                let scene, camera, renderer, controls;
                let pointcloud;

                // Inizializza la scena
                function init() {
                    // Crea scena
                    scene = new THREE.Scene();
                    scene.background = new THREE.Color(0xf0f0f0);

                    // Crea camera
                    camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000);
                    camera.position.z = 200;

                    // Crea renderer
                    renderer = new THREE.WebGLRenderer({ antialias: true });
                    renderer.setSize(window.innerWidth, window.innerHeight);
                    document.body.appendChild(renderer.domElement);

                    // Aggiungi controlli
                    controls = new THREE.OrbitControls(camera, renderer.domElement);
                    controls.enableDamping = true;
                    controls.dampingFactor = 0.25;

                    // Aggiungi luci
                    const ambientLight = new THREE.AmbientLight(0xcccccc, 0.5);
                    scene.add(ambientLight);

                    const directionalLight = new THREE.DirectionalLight(0xffffff, 0.8);
                    directionalLight.position.set(1, 1, 1).normalize();
                    scene.add(directionalLight);

                    // Aggiungi griglia e assi
                    const gridHelper = new THREE.GridHelper(200, 20);
                    scene.add(gridHelper);

                    const axesHelper = new THREE.AxesHelper(100);
                    scene.add(axesHelper);

                    // Gestisci resize
                    window.addEventListener('resize', onWindowResize, false);

                    // Avvia animazione
                    animate();
                }

                // Aggiorna dimensioni al resize
                function onWindowResize() {
                    camera.aspect = window.innerWidth / window.innerHeight;
                    camera.updateProjectionMatrix();
                    renderer.setSize(window.innerWidth, window.innerHeight);
                }

                // Loop di animazione
                function animate() {
                    requestAnimationFrame(animate);
                    controls.update();
                    renderer.render(scene, camera);
                }

                // Funzione per aggiornare la nuvola di punti
                function updatePointCloud(points) {
                    // Rimuovi nuvola esistente
                    if (pointcloud) {
                        scene.remove(pointcloud);
                    }

                    if (!points || points.length === 0) {
                        return;
                    }

                    // Crea geometria
                    const geometry = new THREE.BufferGeometry();
                    const vertices = new Float32Array(points.length * 3);

                    for (let i = 0; i < points.length; i++) {
                        vertices[i*3] = points[i][0];
                        vertices[i*3+1] = points[i][1];
                        vertices[i*3+2] = points[i][2];
                    }

                    geometry.setAttribute('position', new THREE.BufferAttribute(vertices, 3));

                    // Crea materiale
                    const material = new THREE.PointsMaterial({
                        size: 1.5,
                        color: 0x0088ff,
                        sizeAttenuation: true
                    });

                    // Crea nuvola di punti
                    pointcloud = new THREE.Points(geometry, material);
                    scene.add(pointcloud);

                    // Centra camera sulla nuvola
                    geometry.computeBoundingSphere();
                    const center = geometry.boundingSphere.center;
                    const radius = geometry.boundingSphere.radius;

                    camera.position.set(center.x, center.y, center.z + radius * 2);
                    controls.target.set(center.x, center.y, center.z);
                    camera.updateProjectionMatrix();
                    controls.update();
                }

                // Funzione per centrare la vista
                function centerView() {
                    if (pointcloud) {
                        const geometry = pointcloud.geometry;
                        geometry.computeBoundingSphere();
                        const center = geometry.boundingSphere.center;
                        const radius = geometry.boundingSphere.radius;

                        controls.target.set(center.x, center.y, center.z);
                        camera.position.set(center.x, center.y, center.z + radius * 2);
                        camera.updateProjectionMatrix();
                        controls.update();
                    }
                }

                // Funzione per resettare la vista
                function resetView() {
                    camera.position.set(0, 0, 200);
                    controls.target.set(0, 0, 0);
                    camera.updateProjectionMatrix();
                    controls.update();
                }

                // Inizializza
                document.addEventListener('DOMContentLoaded', init);
            </script>
        </body>
        </html>
        """

        # Carica l'HTML nel widget
        self.web_view.setHtml(html)

    def update_pointcloud(self, pointcloud):
        """
        Aggiorna la nuvola di punti visualizzata.

        Args:
            pointcloud: Nuvola di punti come array NumPy
        """
        # Limita aggiornamenti troppo frequenti (max uno ogni 0.5 secondi)
        current_time = time.time()
        if current_time - self.last_update_time < 0.5:
            return

        self.last_update_time = current_time
        self.pointcloud = pointcloud

        if pointcloud is None or len(pointcloud) == 0:
            self.info_label.setText("Nessuna nuvola di punti disponibile")
            return

        # Aggiorna informazioni
        self.info_label.setText(f"Nuvola di punti: {len(pointcloud)} punti")

        # Se stiamo usando WebEngine, aggiorna la nuvola nel visualizzatore 3D
        if WEBENGINE_AVAILABLE and hasattr(self, 'web_view'):
            # Converti la nuvola in formato JSON per JavaScript
            import json
            points_list = pointcloud.tolist()

            # Limita a max 20,000 punti per performance
            if len(points_list) > 20000:
                import random
                points_list = random.sample(points_list, 20000)

            points_json = json.dumps(points_list)

            # Chiama la funzione JavaScript per aggiornare la nuvola
            js_code = f"updatePointCloud({points_json});"
            self.web_view.page().runJavaScript(js_code)
        else:
            # Se WebEngine non è disponibile, genera un'immagine statica
            self._update_static_image(pointcloud)

    def _update_static_image(self, pointcloud):
        """Genera un'immagine statica della nuvola di punti."""
        if not hasattr(self, 'view_label'):
            return

        if not OPEN3D_AVAILABLE or pointcloud is None or len(pointcloud) == 0:
            self.view_label.setText("Visualizzazione 3D non disponibile")
            return

        try:
            import tempfile

            # Crea nuvola Open3D
            pcd = o3d.geometry.PointCloud()
            pcd.points = o3d.utility.Vector3dVector(pointcloud)

            # Aggiungi un sistema di coordinate per riferimento
            coord_frame = o3d.geometry.TriangleMesh.create_coordinate_frame(size=20)

            # Crea visualizzatore
            vis = o3d.visualization.Visualizer()
            vis.create_window(visible=False, width=800, height=600)
            vis.add_geometry(pcd)
            vis.add_geometry(coord_frame)

            # Configura vista
            vis.get_render_option().point_size = 2.0
            vis.get_render_option().background_color = np.array([0.9, 0.9, 0.9])
            vis.poll_events()
            vis.update_renderer()

            # Cattura immagine
            temp_img = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
            vis.capture_screen_image(temp_img.name)
            vis.destroy_window()

            # Mostra immagine
            pixmap = QPixmap(temp_img.name)
            self.view_label.setPixmap(pixmap.scaled(
                self.view_label.width(), self.view_label.height(),
                Qt.KeepAspectRatio, Qt.SmoothTransformation
            ))

            # Elimina file temporaneo
            try:
                os.unlink(temp_img.name)
            except:
                pass

        except Exception as e:
            logger.error(f"Errore nella generazione dell'immagine statica: {e}")
            self.view_label.setText(f"Errore nella visualizzazione: {str(e)}")

    def _center_view(self):
        """Centra la vista sulla nuvola di punti."""
        if WEBENGINE_AVAILABLE and hasattr(self, 'web_view'):
            self.web_view.page().runJavaScript("centerView();")

    def _reset_view(self):
        """Ripristina la vista predefinita."""
        if WEBENGINE_AVAILABLE and hasattr(self, 'web_view'):
            self.web_view.page().runJavaScript("resetView();")

class TestCapabilityWorker(QObject):
    """Worker per eseguire il test delle capacità di scansione in un thread separato."""
    progress = Signal(int, str)  # progress, message
    finished = Signal(dict)  # response
    error = Signal(str)  # error message

    def __init__(self, scanner_controller, device_id):
        super().__init__()
        self.scanner_controller = scanner_controller
        self.device_id = device_id

    def run(self):
        try:
            self.progress.emit(20, "Invio comando di test...")

            command_success = self.scanner_controller.send_command(
                self.device_id,
                "CHECK_SCAN_CAPABILITY"
            )

            if not command_success:
                self.error.emit("Impossibile inviare il comando di test al server.")
                return

            self.progress.emit(40, "Attesa risposta dal server...")

            # Attendi la risposta con timeout aumentato (60 secondi)
            response = self.scanner_controller.wait_for_response(
                self.device_id,
                "CHECK_SCAN_CAPABILITY",
                timeout=60.0
            )

            if not response:
                self.error.emit("Nessuna risposta dal server entro il timeout.")
                return

            self.progress.emit(100, "Test completato.")
            self.finished.emit(response)
        except Exception as e:
            self.error.emit(f"Errore durante il test: {str(e)}")


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
        logger.info("Inizializzazione ScanView")

        # Stato della scansione
        self.is_scanning = False
        self.selected_scanner = None
        self.current_scan_id = None
        self.scan_log = ""
        self.progress_dialog = None
        self.test_thread = None
        self.test_worker = None

        # Directory di output per le scansioni e nuvole di punti
        # IMPORTANTE: inizializzare output_dir PRIMA di usarlo per ScanFrameProcessor
        self.output_dir = self._get_default_output_dir()

        # Registra il gestore di frame
        self._register_frame_handler()
        logger.info("Gestore frame registrato")

        # Processore per i frame di scansione in tempo reale
        self.scan_frame_processor = ScanFrameProcessor(output_dir=self.output_dir)

        # Imposta callback per aggiornare l'interfaccia utente
        def progress_callback(progress_info):
            self.progress_bar.setValue(int(progress_info["progress"]))
            self.status_label.setText(
                f"Stato: {progress_info['state']}, frame ricevuti: {progress_info['frames_total']}")

        def frame_callback(camera_index, pattern_index, frame):
            # Aggiorna l'anteprima
            self._update_preview_image()

        self.scan_frame_processor.set_callbacks(progress_callback, frame_callback)

        # Processor per la triangolazione
        self.scan_processor = ScanProcessor()

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
        """
        Controlla periodicamente lo stato della connessione.
        Versione migliorata per non fermare la scansione se lo streaming è attivo.
        """
        if self.scanner_controller and self.selected_scanner:
            # Verifica se lo scanner è in streaming (stato più affidabile)
            streaming_active = self.selected_scanner.status == ScannerStatus.STREAMING

            # Verifica la connessione con priorità allo streaming
            is_connected = streaming_active or self.scanner_controller.is_connected(self.selected_scanner.device_id)

            # Aggiorna l'interfaccia solo se lo stato è cambiato
            if self.start_scan_button.isEnabled() != is_connected:
                self.start_scan_button.setEnabled(is_connected)

                if is_connected:
                    if streaming_active:
                        self.status_label.setText(f"Connesso a {self.selected_scanner.name} (Streaming attivo)")
                    else:
                        self.status_label.setText(f"Connesso a {self.selected_scanner.name}")
                else:
                    self.status_label.setText("Scanner non connesso")

                    # Non fermare la scansione se lo streaming è ancora attivo
                    if self.is_scanning and not streaming_active:
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

        self.test_scan_button = QPushButton("Test Capacità 3D")
        self.test_scan_button.clicked.connect(self._test_scan_capability)
        self.test_scan_button.setEnabled(False)  # Disabilitato finché non è selezionato uno scanner

        action_layout.addWidget(self.start_scan_button)
        action_layout.addWidget(self.stop_scan_button)
        action_layout.addWidget(self.test_scan_button)  # Aggiungi il bottone al layout

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

        # Widget per la visualizzazione 3D in tempo reale
        self.realtime_viewer = RealtimeViewer3D()
        results_layout.addWidget(self.realtime_viewer)

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

    def _test_scan_capability(self):
        """Testa la capacità di scansione 3D del server con gestione errori migliorata."""
        if not self.scanner_controller or not self.selected_scanner:
            QMessageBox.warning(
                self,
                "Errore",
                "Nessuno scanner selezionato. Seleziona uno scanner prima di eseguire il test."
            )
            return

        # Aggiorna lo scanner selezionato
        self.selected_scanner = self.scanner_controller.selected_scanner

        # Verifica che lo scanner sia connesso
        if not self.scanner_controller.is_connected(self.selected_scanner.device_id):
            QMessageBox.warning(
                self,
                "Errore",
                "Lo scanner selezionato non è connesso. Connettiti prima di eseguire il test."
            )
            return

        # Aggiorna l'interfaccia
        self.status_label.setText("Test delle capacità 3D in corso...")
        self.progress_bar.setValue(10)

        # Crea un dialog di progresso per evitare il blocco dell'UI
        progress_dialog = QProgressDialog("Verifica delle capacità di scansione 3D...", "Annulla", 0, 100, self)
        progress_dialog.setWindowTitle("Test in corso")
        progress_dialog.setWindowModality(Qt.WindowModal)
        progress_dialog.setValue(10)
        progress_dialog.show()

        # Processa eventi per aggiornare l'UI
        QApplication.processEvents()

        # Invia il comando di test capacità con timeout aumentato
        try:
            logger.info("Esecuzione test capacità 3D")
            progress_dialog.setValue(20)
            QApplication.processEvents()

            command_success = self.scanner_controller.send_command(
                self.selected_scanner.device_id,
                "CHECK_SCAN_CAPABILITY"
            )

            if not command_success:
                progress_dialog.close()
                self.status_label.setText("Errore nell'invio del comando di test")
                QMessageBox.critical(
                    self,
                    "Errore",
                    "Impossibile inviare il comando di test al server."
                )
                return

            # Aggiorna la barra di progresso
            progress_dialog.setValue(40)
            progress_dialog.setLabelText("Attendo risposta dal server...")
            QApplication.processEvents()

            # Thread di monitoraggio per evitare blocchi nella UI
            class ResponseThread(QThread):
                response_received = Signal(dict)
                timeout_occurred = Signal()

                def __init__(self, scanner_controller, device_id, command_type, timeout):
                    super().__init__()
                    self.scanner_controller = scanner_controller
                    self.device_id = device_id
                    self.command_type = command_type
                    self.timeout = timeout

                def run(self):
                    response = self.scanner_controller.wait_for_response(
                        self.device_id,
                        self.command_type,
                        timeout=self.timeout
                    )

                    if response:
                        self.response_received.emit(response)
                    else:
                        self.timeout_occurred.emit()

            # Avvia thread di monitoraggio
            response_thread = ResponseThread(
                self.scanner_controller,
                self.selected_scanner.device_id,
                "CHECK_SCAN_CAPABILITY",
                timeout=30.0  # 30 secondi di timeout
            )

            # Connetti i segnali
            response_thread.response_received.connect(
                lambda response: self._handle_capability_response(response, progress_dialog)
            )

            response_thread.timeout_occurred.connect(
                lambda: self._handle_capability_timeout(progress_dialog)
            )

            response_thread.start()

            # Loop di aggiornamento della UI durante l'attesa
            while response_thread.isRunning():
                QApplication.processEvents()
                time.sleep(0.1)  # Piccola pausa per non sovraccaricare la CPU

                # Verifica se l'utente ha annullato la dialog
                if progress_dialog.wasCanceled():
                    response_thread.quit()
                    response_thread.wait(1000)  # Attendi fino a 1 secondo
                    progress_dialog.close()
                    self.status_label.setText("Test annullato dall'utente")
                    return

            # Il thread è terminato, assicurati che la dialog sia chiusa
            if progress_dialog.isVisible():
                progress_dialog.close()

        except Exception as e:
            if progress_dialog.isVisible():
                progress_dialog.close()

            logger.error(f"Errore nell'esecuzione del test: {e}")
            self.status_label.setText(f"Errore: {str(e)}")
            QMessageBox.critical(
                self,
                "Errore",
                f"Si è verificato un errore durante il test:\n{str(e)}\n\n"
                "Verifica la connessione di rete e che il server sia in esecuzione."
            )

    def _handle_capability_response(self, response, progress_dialog):
        """Gestisce la risposta al test delle capacità."""
        # Chiudi la dialog se è ancora aperta
        if progress_dialog.isVisible():
            progress_dialog.setValue(100)
            progress_dialog.close()

        # Verifica lo stato della risposta
        capability_available = response.get("scan_capability", False)
        capability_details = response.get("scan_capability_details", {})

        # Salva il risultato del test per uso futuro
        self._scan_capabilities_verified = capability_available

        # Costruisci un messaggio dettagliato
        if capability_available:
            msg = "Il sistema dispone delle capacità di scansione 3D!\n\nDettagli:\n"

            for key, value in capability_details.items():
                msg += f"- {key}: {value}\n"

            self.status_label.setText("Capacità di scansione 3D disponibili")
            QMessageBox.information(
                self,
                "Test Completato",
                msg
            )

            # Abilita il pulsante di avvio scansione
            self.start_scan_button.setEnabled(True)
            self.test_scan_button.setEnabled(True)
        else:
            error_msg = "Il sistema NON dispone delle capacità di scansione 3D.\n\nDettagli:\n"

            for key, value in capability_details.items():
                error_msg += f"- {key}: {value}\n"

            # Aggiungi consigli per la risoluzione
            error_msg += "\nSuggerimenti per la risoluzione:\n"
            error_msg += "1. Verifica che il proiettore DLP sia collegato e acceso\n"
            error_msg += "2. Controlla che l'I2C sia abilitato sul Raspberry Pi (sudo raspi-config)\n"
            error_msg += "3. Verifica che l'indirizzo I2C e il bus siano corretti\n"
            error_msg += "4. Riavvia il server UnLook per reinizializzare i componenti"

            self.status_label.setText("Capacità di scansione 3D NON disponibili")
            QMessageBox.warning(
                self,
                "Test Fallito",
                error_msg
            )

    def _handle_capability_timeout(self, progress_dialog):
        """Gestisce il timeout nella risposta al test delle capacità."""
        # Chiudi la dialog se è ancora aperta
        if progress_dialog.isVisible():
            progress_dialog.close()

        self.status_label.setText("Verifica dello stato del proiettore DLP...")

        # Prova a verificare se il server è ancora connesso
        ping_success = self.scanner_controller.send_command(
            self.selected_scanner.device_id,
            "PING",
            {"timestamp": time.time()}
        )

        if ping_success:
            # Il server è raggiungibile, ma potrebbe esserci un problema col proiettore
            QMessageBox.warning(
                self,
                "Avviso",
                "Il server è attivo ma non ha risposto alla verifica delle capacità 3D.\n\n"
                "Potrebbe esserci un problema con il proiettore DLP. Verifica:\n"
                "1. Che il proiettore sia collegato correttamente e acceso\n"
                "2. Che l'I2C sia abilitato sul Raspberry Pi\n"
                "3. Che l'indirizzo I2C sia configurato correttamente"
            )
        else:
            self.status_label.setText("Server non raggiungibile")
            QMessageBox.critical(
                self,
                "Errore",
                "Il server non ha risposto ai tentativi di verifica."
            )

    def _update_test_progress(self, progress, message):
        """Aggiorna il progresso del test delle capacità di scansione."""
        if hasattr(self, 'progress_dialog') and self.progress_dialog:
            self.progress_dialog.setValue(progress)
            self.progress_dialog.setLabelText(message)
        self.progress_bar.setValue(progress)
        self.status_label.setText(message)

    def _on_test_capability_finished(self, response):
        """Gestisce il completamento del test delle capacità di scansione."""
        # Chiudi il dialog di progresso
        if hasattr(self, 'progress_dialog') and self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None

        # Ferma il thread
        if hasattr(self, 'test_thread') and self.test_thread:
            self.test_thread.quit()
            self.test_thread.wait()
            self.test_thread = None
            self.test_worker = None

        # Verifica lo stato della risposta
        capability_available = response.get("scan_capability", False)
        capability_details = response.get("scan_capability_details", {})

        # Salva il risultato del test
        self._scan_capabilities_verified = capability_available

        # Costruisci un messaggio dettagliato
        if capability_available:
            msg = "Il sistema dispone delle capacità di scansione 3D!\n\nDettagli:\n"

            for key, value in capability_details.items():
                msg += f"- {key}: {value}\n"

            self.status_label.setText("Capacità di scansione 3D disponibili")
            QMessageBox.information(
                self,
                "Test Completato",
                msg
            )

            # Abilita il pulsante di avvio scansione
            self.start_scan_button.setEnabled(True)
        else:
            error_msg = "Il sistema NON dispone delle capacità di scansione 3D.\n\nDettagli:\n"

            for key, value in capability_details.items():
                error_msg += f"- {key}: {value}\n"

            # Aggiungi consigli per la risoluzione
            error_msg += "\nSuggerimenti per la risoluzione:\n"
            error_msg += "1. Verifica che il proiettore DLP sia collegato e acceso\n"
            error_msg += "2. Controlla che l'I2C sia abilitato sul Raspberry Pi (sudo raspi-config)\n"
            error_msg += "3. Verifica che l'indirizzo I2C e il bus siano corretti\n"
            error_msg += "4. Riavvia il server UnLook per reinizializzare i componenti"

            self.status_label.setText("Capacità di scansione 3D NON disponibili")
            QMessageBox.warning(
                self,
                "Test Fallito",
                error_msg
            )

    def _on_test_capability_error(self, error_message):
        """Gestisce un errore durante il test delle capacità di scansione."""
        # Chiudi il dialog di progresso
        if hasattr(self, 'progress_dialog') and self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None

        # Ferma il thread
        if hasattr(self, 'test_thread') and self.test_thread:
            self.test_thread.quit()
            self.test_thread.wait()
            self.test_thread = None
            self.test_worker = None

        # Aggiorna l'interfaccia
        self.status_label.setText(f"Errore: {error_message}")
        self.progress_bar.setValue(0)

        # Mostra un messaggio di errore
        QMessageBox.critical(
            self,
            "Errore",
            f"Si è verificato un errore durante il test:\n{error_message}\n\n"
            "Verifica la connessione di rete e che il server sia in esecuzione."
        )

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

            # Ogni 3 aggiornamenti di stato, richiedi un'anteprima
            if not hasattr(self, '_preview_counter'):
                self._preview_counter = 0
            self._preview_counter += 1

            if self._preview_counter % 3 == 0 and state == "SCANNING":
                # Richiedi un'anteprima della scansione
                self._request_scan_preview()

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
        Versione migliorata per dare priorità allo streaming attivo.
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
                    logger.debug(f"Errore nell'invio del ping di refresh: {e}")

            # Verifica se lo scanner è in streaming (stato più affidabile)
            streaming_active = self.selected_scanner.status == ScannerStatus.STREAMING

            # Usa la connessione effettiva o lo stato di streaming
            connected = streaming_active or self.scanner_controller.is_connected(self.selected_scanner.device_id)

            # Aggiorna la UI in base allo stato più affidabile
            self.start_scan_button.setEnabled(connected)
            self.test_scan_button.setEnabled(connected)  # Abilita/disabilita anche il pulsante di test

            # Aggiorna l'etichetta di stato
            if connected:
                if streaming_active:
                    self.status_label.setText(f"Connesso a {self.selected_scanner.name} (Streaming attivo)")
                else:
                    self.status_label.setText(f"Connesso a {self.selected_scanner.name}")
            else:
                self.status_label.setText("Scanner non connesso")

    def _start_scan(self):
        """
        Avvia una nuova scansione con gestione della connessione migliorata.
        Versione con ping attivo e timeout estesi per mantenere la connessione durante tutta la scansione.
        """
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

        # MIGLIORAMENTO: Prima dell'avvio della scansione, invia un ping con timeout esteso
        # per assicurarsi che la connessione sia solida
        try:
            import socket
            # Ottieni l'IP locale
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()

            # Invia un ping con informazioni estese
            ping_success = self.scanner_controller.send_command(
                self.selected_scanner.device_id,
                "PING",
                {
                    "timestamp": time.time(),
                    "client_ip": local_ip,
                    "keep_connection": True,  # Flag per mantenere la connessione attiva
                    "client_session_id": str(time.time())  # ID sessione unico
                }
            )

            logger.info(f"Ping pre-scansione inviato con successo: {ping_success}")

            # Attesa breve per assicurarsi che il ping venga elaborato
            time.sleep(0.2)
        except Exception as e:
            logger.debug(f"Errore nell'invio del ping pre-scansione: {e}")

        # Prima di avviare la scansione, ferma lo streaming se attivo
        streaming_active = False
        try:
            # Ottieni un riferimento alla finestra principale
            main_window = self.window()
            if hasattr(main_window, 'streaming_widget') and main_window.streaming_widget:
                streaming_widget = main_window.streaming_widget
                if hasattr(streaming_widget, 'is_streaming') and streaming_widget.is_streaming():
                    logger.info("Arresto dello streaming prima di avviare la scansione")
                    streaming_active = True
                    streaming_widget.stop_streaming()
                    # Breve pausa per assicurarsi che lo streaming sia fermato
                    time.sleep(0.5)
                    # Invia anche un comando esplicito di stop al server
                    self.scanner_controller.send_command(
                        self.selected_scanner.device_id,
                        "STOP_STREAM"
                    )
                    time.sleep(0.2)  # Altra piccola pausa
        except Exception as e:
            logger.warning(f"Errore nell'arresto dello streaming prima della scansione: {e}")

        # Prepara il percorso della scansione
        scan_name = self.scan_name_edit.text()
        if not scan_name:
            scan_name = f"Scan_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # Genera un ID unico per la scansione
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.current_scan_id = f"{scan_name}_{timestamp}"

        # Avvia il processore di frame
        self.scan_frame_processor.start_scan(
            scan_id=self.current_scan_id,
            num_patterns=self.scan_config.get("num_patterns", 12),
            pattern_type=self.scan_config.get("pattern_type", "PROGRESSIVE")
        )

        # Prepara la configurazione
        scan_config = self.scan_config.copy()

        # MIGLIORAMENTO: Aggiungi informazioni del client alla configurazione
        try:
            import socket
            scan_config["client_info"] = {
                "ip": socket.gethostbyname(socket.gethostname()),
                "hostname": socket.gethostname(),
                "timestamp": time.time(),
                "session_id": str(time.time())
            }
        except:
            pass

        # Aggiorna l'interfaccia
        self.progress_bar.setValue(0)
        self.status_label.setText("Inizializzazione scansione...")
        self.start_scan_button.setEnabled(False)
        self.stop_scan_button.setEnabled(True)
        self.options_button.setEnabled(False)
        self.browse_button.setEnabled(False)
        self.scan_name_edit.setEnabled(False)

        # Memorizza che lo streaming era attivo prima della scansione
        self._streaming_was_active = streaming_active

        # Reset del log
        self.scan_log = f"[{datetime.now().strftime('%H:%M:%S')}] Avvio scansione: {self.current_scan_id}\n"
        self.scan_log += f"[{datetime.now().strftime('%H:%M:%S')}] Tipo di pattern: {scan_config['pattern_type']}\n"
        self.scan_log += f"[{datetime.now().strftime('%H:%M:%S')}] Numero di pattern: {scan_config['num_patterns']}\n"
        self.scan_log += f"[{datetime.now().strftime('%H:%M:%S')}] Tempo di esposizione: {scan_config['exposure_time']} sec\n"
        self.scan_log += f"[{datetime.now().strftime('%H:%M:%S')}] Qualità: {scan_config['quality']}\n"

        # MODIFICA: Bypassa la verifica delle capacità 3D
        # Assumi che il dispositivo abbia le capacità 3D
        self._scan_capabilities_verified = True
        self.scan_log += f"[{datetime.now().strftime('%H:%M:%S')}] Verifica capacità 3D bypassata per prototipo\n"

        # Invia il comando di avvio scansione al server
        try:
            logger.info(f"Avvio scansione: {self.current_scan_id}")

            # Invia un ping prima del comando per verificare la connessione
            ping_success = self.scanner_controller.send_command(
                self.selected_scanner.device_id,
                "PING",
                {"timestamp": time.time()}
            )

            if not ping_success:
                logger.warning("Il server non risponde al ping")
                self.scan_log += f"[{datetime.now().strftime('%H:%M:%S')}] Attenzione: il server non risponde al ping\n"

            # Invia il comando di avvio scansione
            command_success = self.scanner_controller.send_command(
                self.selected_scanner.device_id,
                "START_SCAN",
                {"scan_config": scan_config}
            )

            if not command_success:
                self._handle_scan_error("Impossibile inviare il comando di avvio scansione")
                # Se lo streaming era attivo, ripristinalo
                if streaming_active:
                    try:
                        main_window = self.window()
                        if hasattr(main_window, 'streaming_widget') and main_window.streaming_widget:
                            logger.info("Ripristino dello streaming dopo errore di avvio scansione")
                            time.sleep(0.5)  # Piccola pausa
                            main_window.streaming_widget.start_streaming(self.selected_scanner)
                    except Exception as e:
                        logger.error(f"Errore nel ripristino dello streaming: {e}")
                return

            # Imposta la scansione come attiva immediatamente
            self.is_scanning = True
            self.view_log_button.setEnabled(True)

            # Aggiorna il log
            self.scan_log += f"[{datetime.now().strftime('%H:%M:%S')}] Comando di avvio scansione inviato, in attesa di conferma...\n"

            # MIGLIORAMENTO: Aggiungi un timer per l'invio di ping durante la scansione
            self._scan_keepalive_timer = QTimer(self)
            self._scan_keepalive_timer.timeout.connect(self._send_scan_keepalive)
            self._scan_keepalive_timer.start(2000)  # Invia un ping ogni 2 secondi

            # Log dell'avvio del timer keepalive
            logger.info("Timer keepalive scansione avviato")
            self.scan_log += f"[{datetime.now().strftime('%H:%M:%S')}] Timer keepalive scansione avviato\n"

            # Avvia un timer per il polling dello stato invece di aspettare sincronamente
            self._start_status_polling_timer()

            # Emetti il segnale di scansione avviata
            self.scan_started.emit(scan_config)

        except Exception as e:
            logger.error(f"Errore nell'avvio della scansione: {e}")
            self._handle_scan_error(str(e))

            # Se lo streaming era attivo, ripristinalo
            if streaming_active:
                try:
                    main_window = self.window()
                    if hasattr(main_window, 'streaming_widget') and main_window.streaming_widget:
                        logger.info("Ripristino dello streaming dopo errore di avvio scansione")
                        time.sleep(0.5)  # Piccola pausa
                        main_window.streaming_widget.start_streaming(self.selected_scanner)
                except Exception as e:
                    logger.error(f"Errore nel ripristino dello streaming: {e}")

    def _handle_capability_check_response(self, response, progress_dialog):
        """Gestisce la risposta alla verifica delle capacità durante l'avvio della scansione."""
        # Aggiorna il dialog
        progress_dialog.setValue(60)
        QApplication.processEvents()

        # Verifica il risultato
        capability_available = response.get("scan_capability", False)
        capability_details = response.get("scan_capability_details", {})

        if not capability_available:
            progress_dialog.close()

            error_details = "Unknown error"
            if capability_details:
                if isinstance(capability_details, dict):
                    error_details = json.dumps(capability_details, indent=2)
                else:
                    error_details = str(capability_details)

            error_msg = f"Lo scanner non supporta la scansione 3D: {error_details}\n\n"
            error_msg += "Verifica che:\n"
            error_msg += "1. Il proiettore DLP sia collegato e acceso\n"
            error_msg += "2. L'I2C sia abilitato sul Raspberry Pi\n"
            error_msg += "3. L'indirizzo I2C sia configurato correttamente\n"
            error_msg += "4. Il server sia stato avviato con i permessi appropriati"

            self._handle_scan_error(error_msg)
            return

        # Segna che il test delle capacità è stato completato con successo
        self._scan_capabilities_verified = True

        # Continua il dialog - non lo chiudiamo qui perché il metodo chiamante proseguirà con l'avvio scansione

    def _handle_capability_check_timeout(self, progress_dialog):
        """Gestisce il timeout nella verifica delle capacità durante l'avvio della scansione."""
        progress_dialog.close()
        self.status_label.setText("Server non ha risposto alla verifica delle capacità")

        # Prova a verificare se il server è ancora connesso
        ping_success = self.scanner_controller.send_command(
            self.selected_scanner.device_id,
            "PING",
            {"timestamp": time.time()}
        )

        if ping_success:
            # Il server è raggiungibile, ma potrebbe esserci un problema col proiettore
            QMessageBox.warning(
                self,
                "Avviso",
                "Il server è attivo ma non ha risposto alla verifica delle capacità 3D.\n\n"
                "Potrebbe esserci un problema con il proiettore DLP. Verifica:\n"
                "1. Che il proiettore sia collegato correttamente e acceso\n"
                "2. Che l'I2C sia abilitato sul Raspberry Pi\n"
                "3. Che l'indirizzo I2C sia configurato correttamente"
            )
        else:
            QMessageBox.critical(
                self,
                "Errore",
                "Il server non ha risposto ai tentativi di verifica."
            )

        self._reset_ui_after_scan()

    def _handle_capability_check_failed(self, progress_dialog):
        """Gestisce l'errore nell'invio del comando per la verifica delle capacità."""
        progress_dialog.close()
        self.status_label.setText("Errore nell'invio del comando di verifica")

        QMessageBox.critical(
            self,
            "Errore",
            "Impossibile inviare il comando di verifica capacità al server."
        )

        self._reset_ui_after_scan()

    def _start_status_polling_timer(self):
        """Avvia un timer per il polling dello stato della scansione con migliore gestione degli errori."""
        # Se esiste già un timer di polling, fermalo
        if hasattr(self, '_polling_timer') and self._polling_timer:
            try:
                self._polling_timer.stop()
                self._polling_timer.deleteLater()
            except Exception as e:
                logger.debug(f"Errore nella pulizia del timer precedente: {e}")

        # Crea un nuovo timer
        self._polling_timer = QTimer(self)
        self._polling_timer.timeout.connect(self._poll_scan_status)
        # Polling frequente all'inizio (ogni 1 secondo)
        self._polling_timer.start(1000)

        # Contatore per tenere traccia dei tentativi di polling
        self._polling_attempts = 0

        # Contatore per errori consecutivi
        self._polling_errors = 0

        # Imposta un timeout di sicurezza per la scansione (5 minuti)
        self._scan_safety_timeout = QTimer(self)
        self._scan_safety_timeout.setSingleShot(True)
        self._scan_safety_timeout.timeout.connect(self._scan_safety_timeout_handler)
        self._scan_safety_timeout.start(300000)  # 5 minuti

        logger.info("Timer di polling dello stato della scansione avviato")

    def _scan_safety_timeout_handler(self):
        """Gestore per il timeout di sicurezza della scansione."""
        if self.is_scanning:
            logger.warning("Timeout di sicurezza della scansione raggiunto (5 minuti)")
            self.scan_log += f"[{datetime.now().strftime('%H:%M:%S')}] Timeout di sicurezza della scansione raggiunto (5 minuti)\n"

            # Chiedi all'utente se vuole continuare a attendere
            reply = QMessageBox.question(
                self,
                "Scansione in corso da molto tempo",
                "La scansione è in corso da 5 minuti senza completamento.\n"
                "Vuoi continuare ad attendere o interrompere la scansione?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )

            if reply == QMessageBox.No:
                self._stop_scan()
            else:
                # Reset del timeout per altri 5 minuti
                self._scan_safety_timeout.start(300000)

    def _poll_scan_status(self):
        """Esegue il polling dello stato della scansione in modo più robusto."""
        if not self.is_scanning or not self.selected_scanner:
            # Se la scansione è stata fermata o lo scanner non è più disponibile, ferma il polling
            if hasattr(self, '_polling_timer') and self._polling_timer:
                self._polling_timer.stop()
            return

        self._polling_attempts += 1
        logger.debug(f"Polling dello stato scansione (tentativo {self._polling_attempts})")

        # Gestione del backoff per ridurre la frequenza di polling nel tempo
        if self._polling_attempts > 10 and self._polling_attempts <= 30:
            # Dopo 10 tentativi, rallenta a 2 secondi
            if self._polling_timer.interval() != 2000:
                self._polling_timer.setInterval(2000)
                logger.info("Polling rallentato a 2 secondi")
        elif self._polling_attempts > 30 and self._polling_attempts <= 60:
            # Dopo 30 tentativi, rallenta a 5 secondi
            if self._polling_timer.interval() != 5000:
                self._polling_timer.setInterval(5000)
                logger.info("Polling rallentato a 5 secondi")
        elif self._polling_attempts > 60:
            # Dopo 60 tentativi, rallenta a 10 secondi
            if self._polling_timer.interval() != 10000:
                self._polling_timer.setInterval(10000)
                logger.info("Polling rallentato a 10 secondi")

        try:
            # Invia il comando di stato scansione senza bloccare
            command_success = self.scanner_controller.send_command(
                self.selected_scanner.device_id,
                "GET_SCAN_STATUS"
            )

            if not command_success:
                logger.warning("Impossibile inviare il comando GET_SCAN_STATUS")
                self._polling_errors += 1
                return

            # Reset del contatore di errori se il comando è stato inviato con successo
            self._polling_errors = 0

            # Attesa non bloccante della risposta - usa timeout breve di 1 secondo
            response = self.scanner_controller.wait_for_response(
                self.selected_scanner.device_id,
                "GET_SCAN_STATUS",
                timeout=1.0
            )

            if not response:
                # Se non abbiamo ricevuto risposta, non incrementare errori, riproveremo al prossimo ciclo
                return

            # Elabora la risposta ricevuta
            self._handle_status_response(response)

        except Exception as e:
            logger.error(f"Errore nel polling dello stato: {str(e)}")
            self.scan_log += f"[{datetime.now().strftime('%H:%M:%S')}] Errore nel polling: {str(e)}\n"
            self._polling_errors += 1

    def _handle_status_response(self, response):
        """Gestisce la risposta allo stato della scansione."""
        try:
            # Estrai lo stato della scansione
            scan_status = response.get("scan_status", {})
            state = scan_status.get("state", "UNKNOWN")
            progress = scan_status.get("progress", 0.0)
            error_message = scan_status.get("error_message", "")

            # Aggiorna l'interfaccia
            self.status_label.setText(f"Stato: {state}")
            self.progress_bar.setValue(int(progress))

            # Aggiungi al log ogni 5 polling o quando lo stato cambia
            if self._polling_attempts % 5 == 0 or state != "SCANNING":
                log_entry = f"[{datetime.now().strftime('%H:%M:%S')}] Stato: {state}, Progresso: {progress:.1f}%"
                if error_message:
                    log_entry += f", Errore: {error_message}"
                self.scan_log += log_entry + "\n"

            # Aggiorna le anteprime delle immagini ogni 3 polling
            if state == "SCANNING" and self._polling_attempts % 3 == 0:
                self._update_preview_image()

            # Controlla se la scansione è completata o in errore
            if state == "COMPLETED":
                self._handle_scan_completed()
                if hasattr(self, '_polling_timer') and self._polling_timer:
                    self._polling_timer.stop()
            elif state == "ERROR":
                self._handle_scan_error(error_message)
                if hasattr(self, '_polling_timer') and self._polling_timer:
                    self._polling_timer.stop()
            elif state == "IDLE" and self._polling_attempts > 10:
                # Se dopo diversi tentativi lo stato è ancora IDLE, potrebbe esserci un problema
                self._handle_scan_error("Lo scanner non ha avviato la scansione")
                if hasattr(self, '_polling_timer') and self._polling_timer:
                    self._polling_timer.stop()

            # Reset del contatore di errori se abbiamo ricevuto una risposta valida
            self._polling_errors = 0

        except Exception as e:
            logger.error(f"Errore nell'elaborazione della risposta di stato: {e}")
            self._polling_errors += 1

    def _send_scan_keepalive(self):
        """
        Invia un segnale keepalive durante la scansione per mantenere la connessione attiva.
        Questa funzione viene chiamata periodicamente dal timer durante la scansione.
        """
        if not self.is_scanning or not self.scanner_controller or not self.selected_scanner:
            # Se la scansione è terminata, ferma il timer
            if hasattr(self, '_scan_keepalive_timer') and self._scan_keepalive_timer.isActive():
                self._scan_keepalive_timer.stop()
                logger.info("Timer keepalive scansione fermato")
            return

        try:
            import socket
            # Ottieni l'IP locale
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()

            # Invia un ping keepalive
            self.scanner_controller.send_command(
                self.selected_scanner.device_id,
                "PING",
                {
                    "timestamp": time.time(),
                    "client_ip": local_ip,
                    "keep_connection": True,
                    "is_scanning": True,
                    "scan_id": self.current_scan_id
                }
            )
            logger.debug("Keepalive scansione inviato")
        except Exception as e:
            logger.debug(f"Errore nell'invio del keepalive scansione: {e}")
    def _handle_status_timeout(self):
        """Gestisce il timeout nella risposta allo stato della scansione."""
        logger.warning("Timeout nella richiesta dello stato della scansione")

        # Incrementa il contatore di errori
        self._polling_errors += 1

        # Se ci sono troppi errori consecutivi, chiedi all'utente
        if self._polling_errors >= 5:
            reply = QMessageBox.question(
                self,
                "Problemi di comunicazione",
                "Il server non risponde alle richieste di stato.\n"
                "Vuoi continuare la scansione?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )

            if reply == QMessageBox.No:
                self._handle_scan_error("Troppi timeout consecutivi")
                if hasattr(self, '_polling_timer') and self._polling_timer:
                    self._polling_timer.stop()
            else:
                # Reset del contatore di errori
                self._polling_errors = 0
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

        # CORREZIONE: Arresta i timer di sicurezza
        if hasattr(self, '_scan_safety_timeout') and self._scan_safety_timeout.isActive():
            self._scan_safety_timeout.stop()

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

        # Salva il log della scansione
        self._save_scan_log(scan_path)

        # Ripristina lo streaming se era attivo prima della scansione
        self._restore_streaming_if_needed()

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

    def _request_scan_preview(self):
        """Richiede un'anteprima della scansione in corso al server."""
        if not self.is_scanning or not self.scanner_controller or not self.selected_scanner:
            logger.debug("Impossibile richiedere anteprima: scansione non attiva o scanner non selezionato")
            return False

        try:
            # Invia la richiesta di anteprima
            command_success = self.scanner_controller.send_command(
                self.selected_scanner.device_id,
                "GET_SCAN_PREVIEW",
                {"scan_id": self.current_scan_id}
            )

            if not command_success:
                logger.debug("Impossibile inviare il comando GET_SCAN_PREVIEW")
                return False

            # Attendi la risposta con un timeout breve (non bloccare l'UI)
            response = self.scanner_controller.wait_for_response(
                self.selected_scanner.device_id,
                "GET_SCAN_PREVIEW",
                timeout=1.0  # Timeout breve per non bloccare l'UI
            )

            if not response:
                logger.debug("Nessuna risposta alla richiesta GET_SCAN_PREVIEW")
                return False

            # Elabora la risposta
            if response.get("status") == "ok":
                # Ottieni i dati delle immagini
                preview_data = response.get("preview_data", {})
                left_data = preview_data.get("left")
                right_data = preview_data.get("right")

                if left_data or right_data:
                    # Visualizza le anteprime
                    self._process_preview_images(response)
                    return True

            return False
        except Exception as e:
            logger.error(f"Errore nella richiesta di anteprima: {e}")
            return False

    def _save_scan_log(self, scan_path):
        """Salva il log della scansione su file."""
        try:
            # Assicurati che la directory esista
            os.makedirs(scan_path, exist_ok=True)

            log_file = os.path.join(scan_path, "scan_log.txt")
            with open(log_file, 'w') as f:
                f.write(self.scan_log)
            logger.info(f"Log della scansione salvato su {log_file}")
        except Exception as e:
            logger.error(f"Errore nel salvataggio del log della scansione: {e}")

    def _restore_streaming_if_needed(self):
        """Ripristina lo streaming se era attivo prima della scansione."""
        if hasattr(self, '_streaming_was_active') and self._streaming_was_active:
            try:
                # Ottieni un riferimento alla finestra principale
                main_window = self.window()
                if hasattr(main_window, 'streaming_widget') and main_window.streaming_widget:
                    streaming_widget = main_window.streaming_widget
                    logger.info("Ripristino dello streaming dopo la scansione")

                    # Piccola pausa per assicurarsi che il server sia pronto
                    time.sleep(0.5)

                    # Prima invia un ping per verificare che il server sia reattivo
                    if self.scanner_controller and self.selected_scanner:
                        self.scanner_controller.send_command(
                            self.selected_scanner.device_id,
                            "PING",
                            {"timestamp": time.time()}
                        )

                        # Piccola pausa
                        time.sleep(0.2)

                        # Avvia lo streaming
                        streaming_widget.start_streaming(self.selected_scanner)

                        self.scan_log += f"[{datetime.now().strftime('%H:%M:%S')}] Streaming ripristinato\n"
                        logger.info("Streaming ripristinato dopo la scansione")
            except Exception as e:
                logger.error(f"Errore nel ripristino dello streaming: {e}")

    def _handle_scan_error(self, error_message):
        """Gestisce un errore durante la scansione."""
        # Aggiorna il log
        self.scan_log += f"[{datetime.now().strftime('%H:%M:%S')}] Errore nella scansione: {error_message}\n"

        # Aggiorna lo stato
        self.is_scanning = False

        # CORREZIONE: Arresta i timer di sicurezza
        if hasattr(self, '_scan_safety_timeout') and self._scan_safety_timeout.isActive():
            self._scan_safety_timeout.stop()

        # CORREZIONE: Arresta il timer di polling se attivo
        if hasattr(self, '_polling_timer') and self._polling_timer.isActive():
            self._polling_timer.stop()

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

    def _update_preview_image(self, scan_dir=None):
        """
        Aggiorna l'anteprima delle immagini durante la scansione in modo più efficiente.
        Migliora la visualizzazione in tempo reale delle immagini catturate e della nuvola di punti.

        Args:
            scan_dir: Directory della scansione (opzionale, usa la corrente se None)
        """
        if scan_dir is None and self.current_scan_id:
            scan_dir = os.path.join(str(self.output_dir), self.current_scan_id)

        # OTTIMIZZAZIONE: Prima cerca di ottenere dati in memoria per maggiore reattività
        if hasattr(self, 'scan_frame_processor') and self.scan_frame_processor:
            pattern_frames = getattr(self.scan_frame_processor, 'pattern_frames', {})
            if pattern_frames:
                # Trova l'ultimo pattern ricevuto per visualizzazione più reattiva
                pattern_indices = sorted(pattern_frames.keys())
                if pattern_indices:
                    latest_idx = pattern_indices[-1]
                    frames = pattern_frames[latest_idx]

                    # Controlla se abbiamo entrambi i frame
                    if 0 in frames and 1 in frames:
                        left_frame = frames[0]
                        right_frame = frames[1]

                        # Visualizza i frame
                        self._display_preview_frames(left_frame, right_frame)

                        # NOVITÀ: Tenta di visualizzare anche la nuvola di punti in tempo reale
                        if hasattr(self.scan_frame_processor, '_realtime_pointcloud') and \
                                self.scan_frame_processor._realtime_pointcloud is not None and \
                                hasattr(self.scan_frame_processor, '_pointcloud_lock'):

                            with self.scan_frame_processor._pointcloud_lock:
                                pointcloud = self.scan_frame_processor._realtime_pointcloud

                            if pointcloud is not None and len(pointcloud) > 100:
                                # Visualizza la nuvola di punti (limitata a 30K punti per prestazioni)
                                if len(pointcloud) > 30000:
                                    # Campionamento causale per visualizzazione rapida
                                    indices = np.random.choice(len(pointcloud), 30000, replace=False)
                                    display_cloud = pointcloud[indices]
                                else:
                                    display_cloud = pointcloud

                                self._display_realtime_pointcloud(display_cloud)

                        return

        # Se non abbiamo dati in memoria, tentiamo di richiederli dal server
        # con timeout breve per non bloccare l'interfaccia
        if self.selected_scanner and self.scanner_controller and self.is_scanning:
            try:
                # Invia un comando per ottenere l'anteprima
                preview_success = self.scanner_controller.send_command(
                    self.selected_scanner.device_id,
                    "GET_SCAN_PREVIEW",
                    {"scan_id": self.current_scan_id if self.current_scan_id else "current"}
                )

                if preview_success:
                    # Attendi la risposta con un timeout breve (200ms max)
                    preview_response = self.scanner_controller.wait_for_response(
                        self.selected_scanner.device_id,
                        "GET_SCAN_PREVIEW",
                        timeout=0.2
                    )

                    if preview_response and preview_response.get("status") == "ok":
                        # Elabora le immagini di anteprima ricevute
                        self._process_preview_images(preview_response)
                        return
            except Exception as e:
                # Non blocchiamo l'interfaccia in caso di errore
                logger.debug(f"Errore nel tentativo di ottenere anteprime: {e}")

        # Fallback: cerca immagini su disco se non abbiamo dati in memoria
        if not scan_dir or not os.path.isdir(scan_dir):
            return

        # Cerca le immagini più recenti (usa glob con sorting ottimizzato)
        left_dir = os.path.join(scan_dir, "left")
        right_dir = os.path.join(scan_dir, "right")

        if not os.path.isdir(left_dir) or not os.path.isdir(right_dir):
            return

        # OTTIMIZZAZIONE: Usa sorting by mtime per trovare rapidamente le più recenti
        try:
            left_images = glob.glob(os.path.join(left_dir, "*.png"))
            right_images = glob.glob(os.path.join(right_dir, "*.png"))

            if not left_images or not right_images:
                return

            # Ordina per data di modifica senza ordinare l'intero array
            latest_left = max(left_images, key=os.path.getmtime)
            latest_right = max(right_images, key=os.path.getmtime)

            # Carica e visualizza le immagini
            if OPENCV_AVAILABLE:
                left_img = cv2.imread(latest_left)
                right_img = cv2.imread(latest_right)

                if left_img is not None and right_img is not None:
                    self._display_preview_frames(left_img, right_img)

        except Exception as e:
            logger.error(f"Errore nell'aggiornamento delle anteprime: {e}")

    def _display_preview_frames(self, left_img, right_img):
        """
        Visualizza i frame di anteprima nell'interfaccia utente in modo efficiente.

        Args:
            left_img: Frame della camera sinistra
            right_img: Frame della camera destra
        """
        try:
            # Crea o aggiorna il widget per l'anteprima
            if not hasattr(self, 'preview_widget') or not self.preview_widget:
                # Crea un nuovo widget
                self.preview_widget = QWidget()
                preview_layout = QHBoxLayout(self.preview_widget)

                self.left_preview = QLabel("Camera sinistra")
                self.left_preview.setAlignment(Qt.AlignCenter)
                self.left_preview.setMinimumSize(320, 240)

                self.right_preview = QLabel("Camera destra")
                self.right_preview.setAlignment(Qt.AlignCenter)
                self.right_preview.setMinimumSize(320, 240)

                preview_layout.addWidget(self.left_preview)
                preview_layout.addWidget(self.right_preview)

                # Aggiungi il widget all'interfaccia
                self.results_content_layout.insertWidget(0, self.preview_widget)

            # OTTIMIZZAZIONE: Ridimensiona una sola volta se le dimensioni sono uguali
            # Questo evita calcoli ripetuti di scaling quando non necessario
            if left_img.shape[:2] == right_img.shape[:2]:
                # Ridimensiona per la visualizzazione
                scale = min(320 / left_img.shape[1], 240 / left_img.shape[0])
                width = int(left_img.shape[1] * scale)
                height = int(left_img.shape[0] * scale)

                # Ridimensiona le immagini
                left_img_resized = cv2.resize(left_img, (width, height), interpolation=cv2.INTER_AREA)
                right_img_resized = cv2.resize(right_img, (width, height), interpolation=cv2.INTER_AREA)

                # Converti in formato Qt
                left_img_rgb = cv2.cvtColor(left_img_resized, cv2.COLOR_BGR2RGB)
                right_img_rgb = cv2.cvtColor(right_img_resized, cv2.COLOR_BGR2RGB)

                # Crea QImage e QPixmap
                h, w, c = left_img_rgb.shape
                left_qimg = QImage(left_img_rgb.data, w, h, w * c, QImage.Format_RGB888)
                left_pixmap = QPixmap.fromImage(left_qimg)

                h, w, c = right_img_rgb.shape
                right_qimg = QImage(right_img_rgb.data, w, h, w * c, QImage.Format_RGB888)
                right_pixmap = QPixmap.fromImage(right_qimg)
            else:
                # Ridimensiona separatamente
                # Camera sinistra
                scale_left = min(320 / left_img.shape[1], 240 / left_img.shape[0])
                width_left = int(left_img.shape[1] * scale_left)
                height_left = int(left_img.shape[0] * scale_left)
                left_img_resized = cv2.resize(left_img, (width_left, height_left), interpolation=cv2.INTER_AREA)
                left_img_rgb = cv2.cvtColor(left_img_resized, cv2.COLOR_BGR2RGB)
                h, w, c = left_img_rgb.shape
                left_qimg = QImage(left_img_rgb.data, w, h, w * c, QImage.Format_RGB888)
                left_pixmap = QPixmap.fromImage(left_qimg)

                # Camera destra
                scale_right = min(320 / right_img.shape[1], 240 / right_img.shape[0])
                width_right = int(right_img.shape[1] * scale_right)
                height_right = int(right_img.shape[0] * scale_right)
                right_img_resized = cv2.resize(right_img, (width_right, height_right), interpolation=cv2.INTER_AREA)
                right_img_rgb = cv2.cvtColor(right_img_resized, cv2.COLOR_BGR2RGB)
                h, w, c = right_img_rgb.shape
                right_qimg = QImage(right_img_rgb.data, w, h, w * c, QImage.Format_RGB888)
                right_pixmap = QPixmap.fromImage(right_qimg)

            # Mostra le immagini
            self.left_preview.setPixmap(left_pixmap)
            self.left_preview.setText("")

            self.right_preview.setPixmap(right_pixmap)
            self.right_preview.setText("")

            # Mostra il widget di anteprima
            self.preview_widget.setVisible(True)

            # Aggiorna la schermata
            QApplication.processEvents()

        except Exception as e:
            logger.error(f"Errore nella visualizzazione dei frame di anteprima: {e}")

    def _display_realtime_pointcloud(self, pointcloud):
        """
        Visualizza la nuvola di punti in tempo reale.

        Args:
            pointcloud: Nuvola di punti come array numpy
        """
        if not OPEN3D_AVAILABLE or pointcloud is None or len(pointcloud) == 0:
            return

        try:
            # Crea o aggiorna il widget per la visualizzazione 3D
            if not hasattr(self, 'pointcloud_preview') or not self.pointcloud_preview:
                # Crea un nuovo widget
                self.pointcloud_preview = QLabel("Nuvola di punti in tempo reale")
                self.pointcloud_preview.setAlignment(Qt.AlignCenter)
                self.pointcloud_preview.setMinimumSize(640, 480)

                # Aggiungi il widget all'interfaccia sotto le anteprime
                if hasattr(self, 'preview_widget') and self.preview_widget:
                    idx = self.results_content_layout.indexOf(self.preview_widget)
                    self.results_content_layout.insertWidget(idx + 1, self.pointcloud_preview)
                else:
                    self.results_content_layout.insertWidget(0, self.pointcloud_preview)

            # Genera un'immagine della nuvola di punti
            import tempfile

            # Crea una directory temporanea se non esiste
            if not hasattr(self, '_temp_dir') or not os.path.isdir(self._temp_dir):
                self._temp_dir = tempfile.mkdtemp(prefix="unlook_preview_")

            # Percorso per lo screenshot
            screenshot_path = os.path.join(self._temp_dir, "pointcloud_preview.png")

            # Crea un visualizzatore Open3D
            pcd = o3d.geometry.PointCloud()
            pcd.points = o3d.utility.Vector3dVector(pointcloud)

            # Opzionale: applica un filtro per rimuovere outlier
            if len(pointcloud) > 100:
                try:
                    pcd, _ = pcd.remove_statistical_outlier(nb_neighbors=20, std_ratio=2.0)
                except Exception as e:
                    logger.debug(f"Errore nell'applicazione del filtro outlier: {e}")

            # Aggiungi un sistema di coordinate per riferimento
            coord_frame = o3d.geometry.TriangleMesh.create_coordinate_frame(size=20)

            # Crea una finestra di visualizzazione nascosta
            vis = o3d.visualization.Visualizer()
            vis.create_window(visible=False, width=640, height=480)
            vis.add_geometry(pcd)
            vis.add_geometry(coord_frame)

            # Ottimizza la vista
            vis.get_render_option().point_size = 2.0
            vis.get_render_option().background_color = np.array([0.9, 0.9, 0.9])
            vis.get_view_control().set_zoom(0.8)
            vis.poll_events()
            vis.update_renderer()

            # Cattura lo screenshot
            vis.capture_screen_image(screenshot_path)
            vis.destroy_window()

            # Mostra lo screenshot
            pixmap = QPixmap(screenshot_path)
            self.pointcloud_preview.setPixmap(pixmap)
            self.pointcloud_preview.setText("")

            # Aggiorna l'interfaccia
            QApplication.processEvents()

        except Exception as e:
            logger.error(f"Errore nella visualizzazione della nuvola di punti in tempo reale: {e}")

    def _process_preview_images(self, preview_response):
        """
        Elabora le immagini di anteprima ricevute dal server.

        Args:
            preview_response: Risposta del server con le immagini di anteprima
        """
        try:
            # Estrai le immagini di anteprima
            preview_data = preview_response.get("preview_data", {})
            left_data = preview_data.get("left")
            right_data = preview_data.get("right")

            if not left_data or not right_data:
                return

            # Il server potrebbe inviare i dati in formato base64
            import base64
            import numpy as np

            # Crea o aggiorna il widget per l'anteprima
            if not hasattr(self, 'preview_widget') or not self.preview_widget:
                # Crea un nuovo widget
                self.preview_widget = QWidget()
                preview_layout = QHBoxLayout(self.preview_widget)

                self.left_preview = QLabel("Camera sinistra")
                self.left_preview.setAlignment(Qt.AlignCenter)
                self.left_preview.setMinimumSize(320, 240)

                self.right_preview = QLabel("Camera destra")
                self.right_preview.setAlignment(Qt.AlignCenter)
                self.right_preview.setMinimumSize(320, 240)

                preview_layout.addWidget(self.left_preview)
                preview_layout.addWidget(self.right_preview)

                # Aggiungi il widget all'interfaccia
                self.results_content_layout.insertWidget(0, self.preview_widget)

            # Elabora l'immagine sinistra
            if left_data and OPENCV_AVAILABLE:
                try:
                    # Decodifica l'immagine
                    if isinstance(left_data, str):
                        # Immagine in formato base64
                        left_bytes = base64.b64decode(left_data)
                        left_array = np.frombuffer(left_bytes, dtype=np.uint8)
                        left_img = cv2.imdecode(left_array, cv2.IMREAD_COLOR)
                    else:
                        # Immagine in formato binario
                        left_array = np.frombuffer(left_data, dtype=np.uint8)
                        left_img = cv2.imdecode(left_array, cv2.IMREAD_COLOR)

                    if left_img is not None:
                        # Ridimensiona per la visualizzazione
                        scale = min(320 / left_img.shape[1], 240 / left_img.shape[0])
                        width = int(left_img.shape[1] * scale)
                        height = int(left_img.shape[0] * scale)
                        left_img_resized = cv2.resize(left_img, (width, height), interpolation=cv2.INTER_AREA)

                        # Converti in formato Qt
                        left_img_rgb = cv2.cvtColor(left_img_resized, cv2.COLOR_BGR2RGB)
                        h, w, c = left_img_rgb.shape
                        left_qimg = QImage(left_img_rgb.data, w, h, w * c, QImage.Format_RGB888)
                        left_pixmap = QPixmap.fromImage(left_qimg)

                        # Mostra l'immagine
                        self.left_preview.setPixmap(left_pixmap)
                        self.left_preview.setText("")
                except Exception as e:
                    logger.debug(f"Errore elaborazione anteprima sinistra: {e}")

            # Elabora l'immagine destra
            if right_data and OPENCV_AVAILABLE:
                try:
                    # Decodifica l'immagine
                    if isinstance(right_data, str):
                        # Immagine in formato base64
                        right_bytes = base64.b64decode(right_data)
                        right_array = np.frombuffer(right_bytes, dtype=np.uint8)
                        right_img = cv2.imdecode(right_array, cv2.IMREAD_COLOR)
                    else:
                        # Immagine in formato binario
                        right_array = np.frombuffer(right_data, dtype=np.uint8)
                        right_img = cv2.imdecode(right_array, cv2.IMREAD_COLOR)

                    if right_img is not None:
                        # Ridimensiona per la visualizzazione
                        scale = min(320 / right_img.shape[1], 240 / right_img.shape[0])
                        width = int(right_img.shape[1] * scale)
                        height = int(right_img.shape[0] * scale)
                        right_img_resized = cv2.resize(right_img, (width, height), interpolation=cv2.INTER_AREA)

                        # Converti in formato Qt
                        right_img_rgb = cv2.cvtColor(right_img_resized, cv2.COLOR_BGR2RGB)
                        h, w, c = right_img_rgb.shape
                        right_qimg = QImage(right_img_rgb.data, w, h, w * c, QImage.Format_RGB888)
                        right_pixmap = QPixmap.fromImage(right_qimg)

                        # Mostra l'immagine
                        self.right_preview.setPixmap(right_pixmap)
                        self.right_preview.setText("")
                except Exception as e:
                    logger.debug(f"Errore elaborazione anteprima destra: {e}")

            # Mostra il widget di anteprima
            self.preview_widget.setVisible(True)

            # Aggiorna la schermata
            QApplication.processEvents()

        except Exception as e:
            logger.error(f"Errore nell'elaborazione delle anteprime: {e}")

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

    # In client/views/scan_view.py, metodo _register_frame_handler()

    def _register_frame_handler(self):
        """
        Registra un gestore per ricevere i frame della scansione in tempo reale.
        Usa il ScanFrameProcessor per elaborare i frame ricevuti.
        """
        if self.scanner_controller and hasattr(self.scanner_controller, '_connection_manager'):
            try:
                # Cerca nel main window uno streaming_widget
                main_window = self.window()
                if hasattr(main_window, 'streaming_widget') and main_window.streaming_widget:
                    streaming_widget = main_window.streaming_widget

                    # Se lo streaming widget ha un receiver, colleghiamo la nostra funzione
                    if hasattr(streaming_widget, 'stream_receiver') and streaming_widget.stream_receiver:
                        # Ottieni il riferimento allo stream_receiver
                        stream_receiver = streaming_widget.stream_receiver
                        logger.info(f"StreamReceiver trovato, collegamento segnale scan_frame_received...")

                        # IMPORTANTE: Assicuriamoci di disconnettere eventuali connessioni precedenti
                        # Correzione: Utilizziamo try/except per bloccare solo eccezioni specifiche di disconnessione
                        try:
                            stream_receiver.scan_frame_received.disconnect(self._handle_scan_frame)
                        except (TypeError, RuntimeError):
                            # È normale se non c'erano connessioni precedenti o se il segnale era collegato a un metodo diverso
                            logger.debug(
                                "Nessuna connessione precedente da disconnettere o errore nella disconnessione")
                            pass

                        # Ricollega direttamente alla funzione di gestione (non usando lambda che può causare problemi)
                        stream_receiver.scan_frame_received.connect(self._handle_scan_frame)
                        logger.info("Segnale scan_frame_received collegato con successo")

                        # Test di connessione inviando un segnale di prova
                        try:
                            import numpy as np
                            # Creiamo un frame di test
                            test_frame = np.zeros((10, 10, 3), dtype=np.uint8)
                            test_info = {"is_scan_frame": True, "pattern_index": -1, "pattern_name": "test"}
                            logger.info("Invio frame di test per verificare connessione segnale...")
                            # Non emettere realmente il segnale che causerebbe errori
                            # stream_receiver.scan_frame_received.emit(0, test_frame, test_info)
                        except Exception as e:
                            logger.error(f"Errore nel test di connessione del segnale: {e}")
                    else:
                        logger.warning("StreamReceiver non trovato nello streaming_widget")
                else:
                    logger.warning("streaming_widget non trovato nella finestra principale")

            except Exception as e:
                logger.error(f"Errore nella registrazione del gestore di frame: {e}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")
        else:
            logger.error("Scanner controller o connection manager non disponibile")

    def _handle_scan_frame(self, camera_index, frame, frame_info):
        """
        Gestore centralizzato per i frame di scansione.
        Versione migliorata con salvataggio di sicurezza e diagnostica approfondita.

        Args:
            camera_index: Indice della camera (0=sinistra, 1=destra)
            frame: Frame come array NumPy
            frame_info: Informazioni sul frame (pattern_index, pattern_name, ecc.)
        """
        # Gestione speciale per aggiornamenti della nuvola di punti
        if frame_info.get("type") == "pointcloud_update" and hasattr(self, 'realtime_viewer'):
            try:
                # Estrai la nuvola di punti e aggiorna il visualizzatore
                pointcloud = frame_info.get("pointcloud")
                if pointcloud is not None and len(pointcloud) > 0:
                    self.realtime_viewer.update_pointcloud(pointcloud)
                    logger.info(f"Aggiornata visualizzazione con nuvola di {len(pointcloud)} punti")

                    # Abilita pulsanti di interazione durante la scansione
                    self.view_3d_button.setEnabled(True)

                    # Salva la nuvola corrente per uso futuro
                    self._current_pointcloud = pointcloud
                return
            except Exception as e:
                logger.error(f"Errore nell'aggiornamento della visualizzazione 3D: {e}")

        # Log dettagliato per ogni frame ricevuto
        pattern_index = frame_info.get("pattern_index", -1)
        pattern_name = frame_info.get("pattern_name", "unknown")
        scan_id = frame_info.get("scan_id", self.current_scan_id)

        logger.info(f"FRAME RICEVUTO: Camera {camera_index} - Pattern {pattern_index} ({pattern_name})")

        # Verifica che sia un frame di scansione
        if not frame_info.get("is_scan_frame", False):
            logger.warning(f"Frame non marcato come frame di scansione: {frame_info}")
            return

        # Verifica se c'è una scansione attiva - se non c'è, salviamo comunque ma con warning
        if not self.is_scanning:
            logger.warning(f"Ricevuto frame {pattern_index} ma nessuna scansione è attiva. Salvando comunque.")
            # Prova ad attivare automaticamente lo stato di scansione se non attivo
            if self.current_scan_id is None:
                timestamp = int(time.time())
                self.current_scan_id = f"EmergencyScan_{timestamp}"
                logger.warning(f"Creato scan_id di emergenza: {self.current_scan_id}")
                self.is_scanning = True

        # Verifica l'ID della scansione
        if not scan_id and self.current_scan_id:
            scan_id = self.current_scan_id
            logger.info(f"Nessun scan_id nel frame, usando quello corrente: {scan_id}")
        elif not scan_id:
            timestamp = int(time.time())
            scan_id = f"Scan_{timestamp}"
            self.current_scan_id = scan_id
            logger.warning(f"Nessun scan_id disponibile, creato nuovo ID: {scan_id}")

        # Verifica il frame ricevuto
        if frame is None or frame.size == 0:
            logger.error(f"Frame {pattern_index} nullo o vuoto")
            return

        logger.info(f"Frame valido: shape={frame.shape}, dtype={frame.dtype}, min={frame.min()}, max={frame.max()}")

        # Salvataggio di emergenza diretto (bypass ScanFrameProcessor per sicurezza)
        try:
            # Crea directory di scan
            scan_dir = Path(self.output_dir) / scan_id
            scan_dir.mkdir(parents=True, exist_ok=True)

            # Crea directory per camera
            camera_dir = scan_dir / ("left" if camera_index == 0 else "right")
            camera_dir.mkdir(parents=True, exist_ok=True)

            # Componi nome file e percorso
            if pattern_index < 0:
                # Caso speciale per frames di test o non numerati
                filename = f"test_{int(time.time() * 1000)}.png"
            else:
                filename = f"{pattern_index:04d}_{pattern_name}.png"

            file_path = camera_dir / filename

            # Salva direttamente con OpenCV
            success = cv2.imwrite(str(file_path), frame)
            if success:
                logger.info(f"SALVATAGGIO DIRETTO: Frame salvato in {file_path}")
                # Verifica file esistente
                if os.path.exists(str(file_path)):
                    file_size = os.path.getsize(str(file_path))
                    logger.info(f"Verifica file: {file_path} - dimensione: {file_size} bytes")
                else:
                    logger.error(f"ERRORE CRITICO: File {file_path} non esiste dopo il salvataggio!")
            else:
                logger.error(f"ERRORE CRITICO: cv2.imwrite ha fallito per {file_path}")

                # Tentativo alternativo con PIL
                try:
                    from PIL import Image
                    img = Image.fromarray(frame)
                    img.save(str(file_path))
                    logger.info(f"Salvataggio alternativo con PIL successo: {file_path}")
                except Exception as e:
                    logger.error(f"Anche salvataggio PIL fallito: {e}")

                    # Salvataggio binario come ultima risorsa
                    try:
                        np.save(str(file_path).replace('.png', '.npy'), frame)
                        logger.info(f"Salvataggio binario numpy successo: {file_path}.npy")
                    except Exception as e2:
                        logger.error(f"Tutti i metodi di salvataggio hanno fallito: {e2}")

        except Exception as e:
            logger.error(f"Errore nel salvataggio diretto del frame: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")

        # Passaggio al ScanFrameProcessor (dopo il salvataggio diretto di sicurezza)
        try:
            # Verifica processor
            if not hasattr(self, 'scan_frame_processor') or self.scan_frame_processor is None:
                logger.error("ScanFrameProcessor non disponibile!")
                self.scan_frame_processor = ScanFrameProcessor(output_dir=self.output_dir)
                logger.info("Creato nuovo ScanFrameProcessor di emergenza")

            # Assicurati che il processor abbia lo scan_id corretto
            if not self.scan_frame_processor.is_scanning:
                self.scan_frame_processor.start_scan(scan_id=scan_id)
                logger.info(f"Avviato scan_id nel processor: {scan_id}")

            # Elabora il frame (anche se abbiamo già fatto un salvataggio di emergenza)
            success = self.scan_frame_processor.process_frame(camera_index, frame, frame_info)

            if success:
                logger.info(f"ScanFrameProcessor: elaborazione frame {pattern_index} riuscita")
                # Aggiorna l'anteprima dell'interfaccia
                if camera_index == 1:  # Solo dopo il frame della camera destra
                    self._update_preview_image()
            else:
                logger.error(f"ScanFrameProcessor: errore nell'elaborazione del frame {pattern_index}")

        except Exception as e:
            logger.error(f"Errore generale nel passaggio a ScanFrameProcessor: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
    def _setup_frame_receiver(self):
        """
        Configura un ricevitore dedicato per i frame di scansione.
        Versione migliorata con maggiore robustezza e gestione errori.
        """
        try:
            import zmq
            import threading

            def frame_receiver_thread():
                """Thread dedicato a ricevere i frame di scansione"""
                logger.info("Avvio thread ricevitore frame di scansione")

                try:
                    # Crea un contesto ZMQ
                    context = zmq.Context()

                    # Crea un socket PULL per ricevere i frame (pattern PUSH-PULL più affidabile)
                    socket = context.socket(zmq.PULL)

                    # Configura socket per maggiore affidabilità
                    socket.setsockopt(zmq.RCVTIMEO, 5000)  # 5 secondi timeout
                    socket.setsockopt(zmq.LINGER, 0)  # Non attendere alla chiusura

                    # Ottieni porta e indirizzo del server
                    if self.selected_scanner:
                        server_ip = self.selected_scanner.ip_address
                        # La porta per i frame è la porta di comando + 2
                        frame_port = self.selected_scanner.port + 2

                        # Connetti al server
                        endpoint = f"tcp://{server_ip}:{frame_port}"
                        logger.info(f"Connessione a {endpoint} per ricevere frame")
                        socket.connect(endpoint)

                        # Invia un segnale di ready al server
                        ready_sent = False

                        # Loop di ricezione con maggiore robustezza
                        while True:
                            try:
                                # Ricezione con timeout
                                message = socket.recv_json()

                                if message and message.get("type") == "SCAN_FRAME":
                                    # Aggiorna il timestamp dell'ultima attività
                                    self._last_client_activity = time.time()
                                    # Processa il frame ricevuto
                                    self._on_scan_frame_received(self.selected_scanner.device_id, message)
                                    # Log meno frequente
                                    if message.get("frame_info", {}).get("pattern_index", 0) % 5 == 0:
                                        logger.info(
                                            f"Frame {message.get('frame_info', {}).get('pattern_index')} ricevuto")

                            except zmq.Again:
                                # Timeout nella ricezione, invia un segnale di 'still alive'
                                if self.selected_scanner and self.scanner_controller:
                                    try:
                                        # Ogni 3 secondi invia un ping per mantenere viva la connessione
                                        if not ready_sent or time.time() % 3 < 0.1:
                                            self.scanner_controller.send_command(
                                                self.selected_scanner.device_id,
                                                "PING",
                                                {
                                                    "timestamp": time.time(),
                                                    "receiving_frames": True,
                                                    "scan_id": self.current_scan_id
                                                }
                                            )
                                            ready_sent = True
                                    except:
                                        pass
                                continue
                            except Exception as e:
                                logger.error(f"Errore nella ricezione frame: {e}")
                                time.sleep(1)  # Pausa per evitare loop di errore

                    # Pulizia
                    socket.close()
                    context.term()

                except Exception as e:
                    logger.error(f"Errore nel thread ricevitore frame: {e}")
                    import traceback
                    logger.error(f"Traceback: {traceback.format_exc()}")

            # Avvia il thread
            self._frame_receiver_thread = threading.Thread(target=frame_receiver_thread)
            self._frame_receiver_thread.daemon = True
            self._frame_receiver_thread.start()
            logger.info("Thread ricevitore frame avviato con successo")

        except Exception as e:
            logger.error(f"Errore nella configurazione del ricevitore frame: {e}")

    def _on_scan_frame_received(self, device_id: str, message: Dict[str, Any]):
        """
        Gestisce la ricezione di un frame di scansione in tempo reale con gestione errori migliorata.
        Versione migliorata con maggiore robustezza nel salvataggio delle immagini.
        """
        try:
            # Verifica minima del messaggio
            if not message:
                logger.warning("Messaggio di frame vuoto")
                return

            # Estrai informazioni dal messaggio con robustezza
            frame_info = message.get("frame_info", {})
            if not frame_info:
                logger.warning("Informazioni frame mancanti nel messaggio")
                return

            pattern_index = frame_info.get("pattern_index", 0)
            pattern_name = frame_info.get("pattern_name", "unknown")
            scan_id = message.get("scan_id", self.current_scan_id)

            # Log ridotto per evitare spam
            if pattern_index % 5 == 0 or pattern_index < 5:
                logger.info(f"Ricevuto frame {pattern_index} ({pattern_name}) da {device_id}")

            # Se non c'è un ID di scansione, usa quello corrente o crea un nuovo ID
            if not scan_id:
                if self.current_scan_id:
                    scan_id = self.current_scan_id
                else:
                    # Crea un nuovo ID come fallback
                    scan_id = f"Scan_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                    self.current_scan_id = scan_id
                    logger.info(f"Creato nuovo scan_id: {scan_id}")

            # Prepara la directory per salvare i frame, con gestione robusta dei percorsi
            scan_dir = Path(os.path.join(str(self.output_dir), scan_id))
            left_dir = scan_dir / "left"
            right_dir = scan_dir / "right"

            # Crea le directory con gestione robusta
            try:
                scan_dir.mkdir(parents=True, exist_ok=True)
                left_dir.mkdir(exist_ok=True)
                right_dir.mkdir(exist_ok=True)
            except Exception as e:
                logger.error(f"Errore nella creazione delle directory: {e}")
                # Tenta di utilizzare una directory temporanea come fallback
                import tempfile
                temp_dir = Path(tempfile.mkdtemp(prefix="unlook_scan_"))
                scan_dir = temp_dir
                left_dir = scan_dir / "left"
                right_dir = scan_dir / "right"
                left_dir.mkdir(exist_ok=True)
                right_dir.mkdir(exist_ok=True)
                logger.warning(f"Usando directory temporanea: {scan_dir}")

            # Verifica i dati dei frame con gestione robusta
            left_frame_data = message.get("left_frame")
            right_frame_data = message.get("right_frame")

            if not left_frame_data or not right_frame_data:
                logger.warning(f"Dati frame mancanti per pattern {pattern_index}")
                return

            # Decodifica i dati dei frame - AGGIUNGI QUESTO FIX
            import base64
            try:
                # Verifica se i dati sono già in formato binario o necessitano decodifica base64
                if isinstance(left_frame_data, str):
                    left_frame_data = base64.b64decode(left_frame_data)
                if isinstance(right_frame_data, str):
                    right_frame_data = base64.b64decode(right_frame_data)
            except Exception as e:
                logger.error(f"Errore nella decodifica base64: {e}")
                return

            # Definisci nomi file con estensione corretta e percorsi assoluti
            left_file = os.path.join(left_dir, f"{pattern_index:04d}_{pattern_name}.png")
            right_file = os.path.join(right_dir, f"{pattern_index:04d}_{pattern_name}.png")

            # Salvataggio diretto dei dati binari con controllo errori migliorato
            try:
                # Metodo 1: Salvataggio binario diretto
                with open(left_file, "wb") as f:
                    f.write(left_frame_data)
                logger.debug(f"File sinistro salvato: {left_file}")

                with open(right_file, "wb") as f:
                    f.write(right_frame_data)
                logger.debug(f"File destro salvato: {right_file}")

                # Verifica che i file esistano e hanno dimensione > 0
                if not os.path.exists(left_file) or os.path.getsize(left_file) == 0:
                    logger.error(f"File sinistro non creato o vuoto: {left_file}")

                if not os.path.exists(right_file) or os.path.getsize(right_file) == 0:
                    logger.error(f"File destro non creato o vuoto: {right_file}")

                # Log informativo
                logger.info(f"Frame {pattern_index} salvato con successo")

            except Exception as e:
                logger.error(f"Errore nel salvataggio diretto: {e}")

                # Metodo alternativo: decodifica e salva tramite OpenCV
                try:
                    import numpy as np
                    import cv2

                    # Decodifica il frame sinistro
                    left_np = np.frombuffer(left_frame_data, np.uint8)
                    left_img = cv2.imdecode(left_np, cv2.IMREAD_UNCHANGED)

                    # Decodifica il frame destro
                    right_np = np.frombuffer(right_frame_data, np.uint8)
                    right_img = cv2.imdecode(right_np, cv2.IMREAD_UNCHANGED)

                    # Salva solo se la decodifica è riuscita
                    if left_img is not None and left_img.size > 0:
                        cv2.imwrite(left_file, left_img)
                        logger.info(f"Frame sinistro salvato via OpenCV: {left_file}")

                    if right_img is not None and right_img.size > 0:
                        cv2.imwrite(right_file, right_img)
                        logger.info(f"Frame destro salvato via OpenCV: {right_file}")
                except Exception as e2:
                    logger.error(f"Anche il salvataggio alternativo è fallito: {e2}")

                    # Tentativo di fallback con nomi file alternativi
                    try:
                        alt_left_file = os.path.join(left_dir, f"{pattern_index:04d}_{pattern_name}.jpg")
                        alt_right_file = os.path.join(right_dir, f"{pattern_index:04d}_{pattern_name}.jpg")

                        with open(alt_left_file, "wb") as f:
                            f.write(left_frame_data)

                        with open(alt_right_file, "wb") as f:
                            f.write(right_frame_data)

                        logger.info(f"Frame {pattern_index} salvato con estensione alternativa")
                    except Exception as e3:
                        logger.error(f"Tutti i tentativi di salvataggio falliti: {e3}")

            # Aggiorna l'anteprima delle immagini
            self._update_preview_image()

        except Exception as e:
            logger.error(f"Errore generale nella gestione del frame ricevuto: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")

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

        # Abilita/disabilita i pulsanti
        self.start_scan_button.setEnabled(is_connected)
        self.test_scan_button.setEnabled(is_connected)  # Abilita/disabilita anche il pulsante di test

        # Aggiorna l'etichetta di stato
        if is_connected:
            self.status_label.setText(f"Connesso a {scanner.name}")
        else:
            self.status_label.setText("Scanner non connesso")

    def closeEvent(self, event):
        """Gestisce l'evento di chiusura della finestra."""
        # Ferma eventuali thread in esecuzione
        if hasattr(self, 'test_thread') and self.test_thread:
            self.test_thread.quit()
            self.test_thread.wait()
            self.test_thread = None
            self.test_worker = None

        # Chiudi eventuali dialog aperti
        if hasattr(self, 'progress_dialog') and self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None

        # Ferma eventuali timer
        if hasattr(self, 'status_timer'):
            self.status_timer.stop()

        if hasattr(self, '_polling_timer') and self._polling_timer and self._polling_timer.isActive():
            self._polling_timer.stop()

        if hasattr(self, '_scan_safety_timeout') and self._scan_safety_timeout and self._scan_safety_timeout.isActive():
            self._scan_safety_timeout.stop()

        # Continua con l'evento di chiusura
        super().closeEvent(event)