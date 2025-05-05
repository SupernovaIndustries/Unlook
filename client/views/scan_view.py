#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Widget per la scansione 3D in tempo reale con UnLook.
Versione completamente riprogettata per operare esclusivamente in real-time
con preview integrata delle camere e visualizzazione 3D in tempo reale.
"""

import logging
import time
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import numpy as np
import cv2
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSplitter,
    QGroupBox, QFormLayout, QComboBox, QSlider, QProgressBar, QMessageBox,
    QApplication, QFileDialog, QProgressDialog
)
from PySide6.QtCore import Qt, Signal, Slot, QTimer, QMetaObject, Q_ARG
from PySide6.QtGui import QImage, QPixmap, QStatusTipEvent

from client.models.scanner_model import Scanner, ScannerStatus
from client.processing.scan_frame_processor import ScanFrameProcessor

# Verifica la disponibilità di Open3D per la visualizzazione 3D
try:
    import open3d as o3d

    OPEN3D_AVAILABLE = True
except ImportError:
    OPEN3D_AVAILABLE = False
    logging.warning("Open3D non disponibile. Funzionalità di visualizzazione 3D limitate.")

# Configura logging
logger = logging.getLogger(__name__)


class CameraPreviewWidget(QWidget):
    """Widget per visualizzare il preview di una singola camera con lag meter."""

    def __init__(self, camera_index: int, parent=None):
        super().__init__(parent)
        self.camera_index = camera_index
        self._frame = None
        self._last_update_time = time.time()
        self._fps = 0
        self._frame_count = 0
        self._lag_ms = 0
        self._last_lag_ms = 0  # Aggiungi questa inizializzazione
        self._max_lag_warning = 200  # ms, soglia per avviso lag

        # Setup UI
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Display per l'immagine
        self.display_label = QLabel()
        self.display_label.setAlignment(Qt.AlignCenter)
        self.display_label.setMinimumSize(320, 240)
        self.display_label.setStyleSheet("background-color: black; color: white;")
        self.display_label.setText("Camera non attiva\nIn attesa dei frame...")

        # Layout info con FPS e lag
        info_layout = QHBoxLayout()

        # Etichetta informativa
        self.info_label = QLabel("Camera non attiva")
        self.info_label.setAlignment(Qt.AlignLeft)

        # Etichetta lag
        self.lag_label = QLabel("Lag: N/A")
        self.lag_label.setAlignment(Qt.AlignRight)
        self.lag_label.setStyleSheet("color: green;")

        info_layout.addWidget(self.info_label)
        info_layout.addStretch(1)
        info_layout.addWidget(self.lag_label)

        layout.addWidget(self.display_label)
        layout.addLayout(info_layout)

    def update_frame(self, frame: np.ndarray, timestamp: float = None):
        """Aggiorna il frame visualizzato con diagnostica migliorata."""
        try:
            if frame is None or not isinstance(frame, np.ndarray) or frame.size == 0:
                logger.warning(f"CameraPreviewWidget: frame non valido ricevuto per camera {self.camera_index}")
                return

            # Memorizza il frame
            self._frame = frame.copy()
            self._frame_count += 1

            # Traccia il primo frame per diagnostica
            if self._frame_count == 1:
                logger.info(f"CameraPreviewWidget: primo frame visualizzato per camera {self.camera_index}: "
                            f"shape={frame.shape}, dtype={frame.dtype}")

                # Verifica che l'immagine abbia valori validi
                min_val = np.min(frame)
                max_val = np.max(frame)
                logger.info(f"Range valori: min={min_val}, max={max_val}")

            # Conversione a QImage con gestione robusta
            try:
                height, width = frame.shape[:2]
                bytes_per_line = frame.strides[0]

                if len(frame.shape) == 3 and frame.shape[2] == 3:
                    # RGB/BGR - verifica se è nel range corretto
                    if frame.dtype == np.uint8:
                        qt_image = QImage(frame.data, width, height, bytes_per_line, QImage.Format_BGR888)
                        format_str = "BGR"
                    else:
                        # Converte se necessario
                        frame_8bit = (frame * 255).astype(np.uint8) if frame.dtype == np.float32 else frame.astype(
                            np.uint8)
                        qt_image = QImage(frame_8bit.data, width, height, frame_8bit.strides[0], QImage.Format_BGR888)
                        format_str = f"BGR (convertito da {frame.dtype})"
                elif len(frame.shape) == 3 and frame.shape[2] == 4:
                    # RGBA/BGRA
                    qt_image = QImage(frame.data, width, height, bytes_per_line, QImage.Format_ARGB32)
                    format_str = "BGRA"
                elif len(frame.shape) == 2:
                    # Grayscale
                    qt_image = QImage(frame.data, width, height, bytes_per_line, QImage.Format_Grayscale8)
                    format_str = "Grayscale"
                else:
                    logger.warning(f"Formato frame non supportato: {frame.shape}")
                    return

                # Log dettagliato periodico
                if self._frame_count == 1 or self._frame_count % 100 == 0:
                    logger.debug(f"CameraPreviewWidget: frame {self._frame_count} per camera {self.camera_index}: "
                                 f"formato={format_str}, dimensione={width}x{height}")

                # Aggiorna display
                pixmap = QPixmap.fromImage(qt_image)
                self.display_label.setPixmap(pixmap)

                # Traccia frame visualizzati
                if hasattr(self.parent(), '_frames_displayed') and isinstance(self.parent()._frames_displayed, dict):
                    self.parent()._frames_displayed[self.camera_index] = self.parent()._frames_displayed.get(
                        self.camera_index, 0) + 1

                # Aggiorna etichetta info
                if time.time() - self._last_update_time > 3.0:
                    self._last_update_time = time.time()
                    camera_name = "Sinistra" if self.camera_index == 0 else "Destra"
                    self.info_label.setText(f"Camera {camera_name} | {width}x{height} | Attiva")

            except Exception as e:
                logger.error(f"CameraPreviewWidget: errore nella conversione del frame: {e}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")
                return

            # Calcola lag se timestamp fornito
            if timestamp is not None:
                self._lag_ms = int((time.time() - timestamp) * 1000)
                self._update_lag_label()

        except Exception as e:
            logger.error(f"CameraPreviewWidget: errore generale in update_frame: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")

    def _update_lag_label(self):
        """Aggiorna l'etichetta del lag e imposta il colore appropriato."""
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


class PointCloudViewerWidget(QWidget):
    """Widget per visualizzare la nuvola di punti 3D in tempo reale."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pointcloud = None
        self._last_update_time = time.time()
        self._fps = 0
        self._frame_count = 0

        # Setup UI
        layout = QVBoxLayout(self)

        # Etichetta per visualizzazione
        self.display_label = QLabel("Nuvola di punti non disponibile")
        self.display_label.setAlignment(Qt.AlignCenter)
        self.display_label.setMinimumSize(400, 300)
        self.display_label.setStyleSheet("background-color: #f0f0f0; border: 1px solid #ccc;")

        # Etichetta informativa
        self.info_label = QLabel("In attesa della nuvola di punti...")
        self.info_label.setAlignment(Qt.AlignCenter)

        # Pulsanti di controllo
        controls_layout = QHBoxLayout()

        self.export_button = QPushButton("Esporta PLY...")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self._export_pointcloud)

        controls_layout.addWidget(self.export_button)
        controls_layout.addStretch(1)

        # Assembla il layout
        layout.addWidget(self.display_label)
        layout.addWidget(self.info_label)
        layout.addLayout(controls_layout)

    def update_pointcloud(self, pointcloud):
        """Aggiorna la nuvola di punti visualizzata."""
        if pointcloud is None or len(pointcloud) == 0:
            return

        # Memorizza la nuvola per l'esportazione
        self.pointcloud = pointcloud.copy()
        self._frame_count += 1

        # Abilita il pulsante di esportazione
        self.export_button.setEnabled(True)

        # Aggiorna etichetta informativa
        self.info_label.setText(f"Nuvola di punti: {len(pointcloud):,} punti")

        # Genera e visualizza immagine della nuvola
        self._update_pointcloud_image()

        # Calcola FPS
        current_time = time.time()
        if self._last_update_time > 0:
            time_diff = current_time - self._last_update_time
            if time_diff > 0:
                fps = 1.0 / time_diff
                # Media mobile per stabilizzare
                alpha = 0.1
                self._fps = (1.0 - alpha) * self._fps + alpha * fps

        self._last_update_time = current_time

    def _update_pointcloud_image(self):
        """Genera e visualizza un'immagine della nuvola di punti."""
        if not OPEN3D_AVAILABLE or self.pointcloud is None:
            self.display_label.setText("Visualizzazione 3D non disponibile")
            return

        try:
            import tempfile

            # Crea nuvola Open3D
            pcd = o3d.geometry.PointCloud()
            pcd.points = o3d.utility.Vector3dVector(self.pointcloud)

            # Crea sistema di coordinate
            coord_frame = o3d.geometry.TriangleMesh.create_coordinate_frame(size=20)

            # Visualizzazione
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
            self.display_label.setPixmap(pixmap.scaled(
                self.display_label.width(), self.display_label.height(),
                Qt.KeepAspectRatio, Qt.SmoothTransformation
            ))
            self.display_label.setText("")

            # Elimina file temporaneo
            try:
                os.unlink(temp_img.name)
            except:
                pass

        except Exception as e:
            logger.error(f"Errore nella visualizzazione della nuvola: {e}")
            self.display_label.setText(f"Errore nella visualizzazione 3D: {str(e)}")

    def _export_pointcloud(self):
        """Esporta la nuvola di punti su file PLY."""
        if self.pointcloud is None or len(self.pointcloud) == 0:
            QMessageBox.warning(
                self,
                "Nessuna nuvola di punti",
                "Non ci sono dati da esportare."
            )
            return

        try:
            # Chiedi dove salvare il file
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "Esporta Nuvola di Punti",
                os.path.join(str(Path.home()), "pointcloud.ply"),
                "PLY Files (*.ply);;All Files (*)"
            )

            if not file_path:
                return

            # Assicura che l'estensione sia .ply
            if not file_path.lower().endswith('.ply'):
                file_path += '.ply'

            # Crea directory se necessario
            os.makedirs(os.path.dirname(file_path), exist_ok=True)

            # Salva la nuvola
            if OPEN3D_AVAILABLE:
                # Usa Open3D
                pcd = o3d.geometry.PointCloud()
                pcd.points = o3d.utility.Vector3dVector(self.pointcloud)
                o3d.io.write_point_cloud(file_path, pcd)
            else:
                # Fallback a salvataggio manuale
                with open(file_path, 'w') as f:
                    # Scrivi header
                    f.write("ply\n")
                    f.write("format ascii 1.0\n")
                    f.write(f"element vertex {len(self.pointcloud)}\n")
                    f.write("property float x\n")
                    f.write("property float y\n")
                    f.write("property float z\n")
                    f.write("end_header\n")

                    # Scrivi vertici
                    for point in self.pointcloud:
                        f.write(f"{point[0]} {point[1]} {point[2]}\n")

            QMessageBox.information(
                self,
                "Esportazione Completata",
                f"La nuvola di punti con {len(self.pointcloud):,} punti è stata esportata con successo in:\n{file_path}"
            )

        except Exception as e:
            logger.error(f"Errore nell'esportazione della nuvola: {e}")
            QMessageBox.critical(
                self,
                "Errore",
                f"Si è verificato un errore durante l'esportazione:\n{str(e)}"
            )


class ScanView(QWidget):
    """
    Widget per la scansione 3D in tempo reale.
    Integra direttamente lo streaming delle camere e la visualizzazione 3D.
    """

    # Segnali
    scan_started = Signal(dict)  # Configurazione scansione
    scan_completed = Signal(str)  # Percorso di output
    scan_failed = Signal(str)  # Messaggio errore
    frame_processed = Signal(int, int, np.ndarray)  # camera_index, pattern_index, frame

    def __init__(self, scanner_controller=None, parent=None):
        super().__init__(parent)
        self.scanner_controller = scanner_controller
        self.selected_scanner = None

        # Stato della scansione
        self.is_scanning = False
        self.scan_id = None
        self.output_dir = self._get_default_output_dir()

        # Frame processor
        self.scan_processor = ScanFrameProcessor(output_dir=self.output_dir)

        # Setup UI
        self._setup_ui()

        # Timer di stato
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self._update_status)
        self.status_timer.start(500)  # Aggiorna ogni 500ms

        # Connessione agli stream
        self._stream_connected = False
        self._frame_receiver_registered = False

        logger.info("ScanView inizializzato")

    def _get_default_output_dir(self):
        """Restituisce la directory di output predefinita."""
        return Path.home() / "UnLook" / "scans"

    def _setup_ui(self):
        """Configura l'interfaccia utente."""
        main_layout = QVBoxLayout(self)

        # Sezione superiore: controlli e anteprima camere
        top_section = QWidget()
        top_layout = QVBoxLayout(top_section)
        top_layout.setContentsMargins(0, 0, 0, 0)

        # Controlli principali
        controls_layout = QHBoxLayout()

        self.start_scan_button = QPushButton("▶ Avvia Scansione")
        self.start_scan_button.setMinimumWidth(150)
        self.start_scan_button.clicked.connect(self._start_scan)
        self.start_scan_button.setEnabled(False)

        self.stop_scan_button = QPushButton("⏹ Ferma Scansione")
        self.stop_scan_button.setMinimumWidth(150)
        self.stop_scan_button.clicked.connect(self._stop_scan)
        self.stop_scan_button.setEnabled(False)

        self.diagnostics_button = QPushButton("🔍 Diagnostica")
        self.diagnostics_button.setMinimumWidth(100)
        self.diagnostics_button.clicked.connect(self._run_sync_diagnostics)
        self.diagnostics_button.setEnabled(False)

        self.export_button = QPushButton("💾 Esporta")
        self.export_button.setMinimumWidth(100)
        self.export_button.clicked.connect(self._export_scan)
        self.export_button.setEnabled(False)

        # Barra di stato e progresso
        status_layout = QHBoxLayout()

        self.status_label = QLabel("Non connesso")
        self.status_label.setStyleSheet("font-weight: bold;")

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setMinimumWidth(200)

        # Assembla i controlli
        controls_layout.addWidget(self.start_scan_button)
        controls_layout.addWidget(self.stop_scan_button)
        controls_layout.addStretch(1)
        controls_layout.addWidget(self.export_button)

        status_layout.addWidget(self.status_label)
        status_layout.addStretch(1)
        status_layout.addWidget(self.progress_bar)

        top_layout.addLayout(controls_layout)
        top_layout.addLayout(status_layout)

        # Preview delle camere
        preview_layout = QHBoxLayout()

        self.left_preview = CameraPreviewWidget(0)
        self.right_preview = CameraPreviewWidget(1)

        preview_layout.addWidget(self.left_preview)
        preview_layout.addWidget(self.right_preview)

        top_layout.addLayout(preview_layout)

        # Sezione inferiore: visualizzazione 3D
        self.pointcloud_viewer = PointCloudViewerWidget()

        # Splitter per regolare le dimensioni relative
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(top_section)
        splitter.addWidget(self.pointcloud_viewer)
        splitter.setSizes([int(self.height() * 0.6), int(self.height() * 0.4)])

        main_layout.addWidget(splitter)

        # Configura callback per il processore di scansione
        self.scan_processor.set_callbacks(
            progress_callback=self._on_scan_progress,
            frame_callback=self._on_frame_processed
        )

    def _connect_to_stream(self):
        """
        Versione completamente riprogettata per connettere il widget agli stream.
        Implementa una logica chiara e robusta con diagnostica estesa.
        """
        # --- FASE 1: Verifica dello stato attuale ---
        if self._stream_connected:
            logger.debug("Stream già connesso, verifico stato delle camere")
            # Verifica ricezione frame per ogni camera
            if hasattr(self, '_frame_count_by_camera'):
                camera_issues = []
                for cam_idx in [0, 1]:
                    if cam_idx not in self._frame_count_by_camera or self._frame_count_by_camera.get(cam_idx, 0) == 0:
                        camera_issues.append(f"Camera {cam_idx} non riceve frame")

                if camera_issues:
                    logger.warning(f"Problemi rilevati: {', '.join(camera_issues)}")
                    # Non forzare la riconnessione qui, ma segnalare il problema
                    # La riconnessione è gestita dal timer di verifica
                else:
                    return True
            else:
                # Inizializza contatori alla prima verifica
                self._frame_count_by_camera = {0: 0, 1: 0}
                self._last_frame_log_time = time.time()
                return True

        # --- FASE 2: Cerca MainWindow e stream_receiver ---
        main_window = self.window()
        logger.info(f"MainWindow trovata: {main_window is not None}")

        if main_window is None:
            logger.error("Impossibile ottenere riferimento alla MainWindow")
            return False

        has_stream_receiver = hasattr(main_window, 'stream_receiver')
        logger.info(f"MainWindow ha stream_receiver: {has_stream_receiver}")

        if has_stream_receiver and main_window.stream_receiver:
            receiver = main_window.stream_receiver
            logger.info("Stream receiver trovato in MainWindow")

            # CORREZIONE: Usa _safe_disconnect_signal invece di try-except
            if hasattr(receiver, 'frame_received'):
                self._safe_disconnect_signal(receiver.frame_received, self._on_frame_received)

            # Connetti il segnale e configura
            try:
                receiver.frame_received.connect(self._on_frame_received)
                logger.info("Segnale frame_received collegato con successo")
            except Exception as e:
                logger.error(f"Errore nella connessione del segnale: {e}")
                return False

            if hasattr(receiver, 'set_frame_processor'):
                try:
                    receiver.set_frame_processor(self.scan_processor)
                    logger.info("Processore di frame impostato con successo")
                except Exception as e:
                    logger.error(f"Errore nell'impostazione del processore di frame: {e}")

            if hasattr(receiver, 'enable_direct_routing'):
                try:
                    receiver.enable_direct_routing(True)
                    logger.info("Direct routing abilitato con successo")
                except Exception as e:
                    logger.error(f"Errore nell'abilitazione del direct routing: {e}")

            # IMPORTANTE: configura il timer di verifica
            if not hasattr(self, '_camera_check_timer') or not self._camera_check_timer.is_alive():
                self._camera_check_timer = threading.Timer(3.0, self._verify_camera_streams)
                self._camera_check_timer.daemon = True
                self._camera_check_timer.start()
                logger.info("Timer di verifica camere avviato")

            self._stream_connected = True
            return True

        # --- FASE 3: Diagnostica dettagliata della struttura MainWindow ---
        logger.debug(f"Tipo di main_window: {type(main_window).__name__}")

        # Elenca attributi rilevanti per diagnostica
        important_attrs = ['stream_receiver', 'streaming_widget', 'scanner_controller']
        found_attrs = []
        for attr in important_attrs:
            if hasattr(main_window, attr):
                found_attrs.append(attr)
        logger.debug(f"Attributi rilevanti trovati: {found_attrs}")

        # --- FASE 4: Tentativo di connessione tramite stream_receiver diretto ---
        if hasattr(main_window, 'stream_receiver') and main_window.stream_receiver:
            logger.info("Stream receiver trovato in MainWindow")
            receiver = main_window.stream_receiver

            # Verifica funzionalità fondamentali
            if not hasattr(receiver, 'frame_received'):
                logger.error("Stream receiver non ha il segnale frame_received, impossibile connettersi")
                return False

            # Reinizializza statistiche
            self._frame_count_by_camera = {0: 0, 1: 0}
            self._last_frame_log_time = time.time()

            # Verifica stato del receiver
            if hasattr(receiver, 'is_active'):
                is_active = receiver.is_active()
                logger.info(f"Stream receiver is_active: {is_active}")
                if not is_active and hasattr(receiver, 'start'):
                    logger.info("Avvio automatico stream_receiver")
                    receiver.start()
                    # Breve pausa per consentire l'inizializzazione completa
                    time.sleep(0.5)

            # CORREZIONE: Usa _safe_disconnect_signal invece di try-except
            if hasattr(receiver, 'frame_received'):
                self._safe_disconnect_signal(receiver.frame_received, self._on_frame_received)

            # Connetti segnali
            receiver.frame_received.connect(self._on_frame_received)
            logger.info("Segnale frame_received collegato con successo")

            # Configura il processore di frame
            if hasattr(receiver, 'set_frame_processor'):
                receiver.set_frame_processor(self.scan_processor)
                logger.info("Processore di frame impostato con successo")

            # Richiedi esplicitamente dual camera se disponibile
            if hasattr(receiver, 'request_dual_camera'):
                logger.info("Richiesta esplicita dual camera")
                receiver.request_dual_camera(True)
            elif hasattr(receiver, 'set_dual_camera'):
                logger.info("Impostazione esplicita dual camera")
                receiver.set_dual_camera(True)

            # Abilita routing diretto per efficienza
            if hasattr(receiver, 'enable_direct_routing'):
                receiver.enable_direct_routing(True)
                logger.info("Routing diretto abilitato per efficienza")

            # Verifica e diagnosi ulteriori connessioni
            if hasattr(receiver, '_connections'):
                conn_count = len(receiver._connections)
                logger.info(f"Stream receiver ha {conn_count} connessioni attive")

                if conn_count == 0:
                    logger.warning("Nessuna connessione attiva nel receiver!")
                    # Prova a inviare un comando di riavvio streaming al server
                    if self.selected_scanner and self.scanner_controller:
                        try:
                            logger.info("Riavvio stream dal server...")
                            # Prima ferma lo streaming eventuale
                            self.scanner_controller.send_command(
                                self.selected_scanner.device_id,
                                "STOP_STREAM"
                            )
                            time.sleep(0.3)
                            # Riavvia con dual_camera=True esplicito
                            self.scanner_controller.send_command(
                                self.selected_scanner.device_id,
                                "START_STREAM",
                                {"dual_camera": True}
                            )
                        except Exception as e:
                            logger.error(f"Errore nel riavvio dello stream: {e}")

            # Configura timer di verifica camere mancanti
            if not hasattr(self, '_camera_check_timer') or not self._camera_check_timer.is_alive():
                self._camera_check_timer = threading.Timer(3.0, self._verify_camera_streams)
                self._camera_check_timer.daemon = True
                self._camera_check_timer.start()
                logger.info("Timer di verifica camere avviato")

            self._stream_connected = True
            return True

        # --- FASE 5: Fallback tramite streaming_widget ---
        elif hasattr(main_window, 'streaming_widget') and main_window.streaming_widget:
            logger.info("Tentativo tramite streaming_widget")
            streaming_widget = main_window.streaming_widget

            # Cerca stream_receiver nel widget
            if hasattr(streaming_widget, 'stream_receiver') and streaming_widget.stream_receiver:
                logger.info("Stream receiver trovato in streaming_widget")
                receiver = streaming_widget.stream_receiver

                # CORREZIONE: Usa _safe_disconnect_signal invece di try-except
                if hasattr(receiver, 'frame_received'):
                    self._safe_disconnect_signal(receiver.frame_received, self._on_frame_received)

                # Connetti segnali e configura
                receiver.frame_received.connect(self._on_frame_received)

                if hasattr(receiver, 'set_frame_processor'):
                    receiver.set_frame_processor(self.scan_processor)

                if hasattr(receiver, 'enable_direct_routing'):
                    receiver.enable_direct_routing(True)

                if hasattr(receiver, 'request_dual_camera'):
                    receiver.request_dual_camera(True)

                self._stream_connected = True
                logger.info("Connessione tramite streaming_widget riuscita")
                return True

        # --- FASE 6: Tentativo tramite scanner_controller ---
        if hasattr(self, 'scanner_controller') and self.scanner_controller:
            logger.info("Tentativo tramite scanner_controller")

            # Ottieni stream_receiver dal controller
            if hasattr(self.scanner_controller, 'get_stream_receiver'):
                receiver = self.scanner_controller.get_stream_receiver()
                if receiver:
                    logger.info("Stream receiver ottenuto da scanner_controller")

                    # CORREZIONE: Usa _safe_disconnect_signal invece di try-except
                    if hasattr(receiver, 'frame_received'):
                        self._safe_disconnect_signal(receiver.frame_received, self._on_frame_received)

                    # Connetti segnali e configura
                    receiver.frame_received.connect(self._on_frame_received)

                    if hasattr(receiver, 'set_frame_processor'):
                        receiver.set_frame_processor(self.scan_processor)

                    if hasattr(receiver, 'enable_direct_routing'):
                        receiver.enable_direct_routing(True)

                    if hasattr(receiver, 'request_dual_camera'):
                        receiver.request_dual_camera(True)

                    self._stream_connected = True
                    logger.info("Connessione tramite scanner_controller riuscita")
                    return True

            # Verifica riferimento diretto a stream_receiver nel controller
            elif hasattr(self.scanner_controller, 'stream_receiver'):
                receiver = self.scanner_controller.stream_receiver
                if receiver:
                    logger.info("Usando scanner_controller.stream_receiver")

                    # CORREZIONE: Usa _safe_disconnect_signal invece di try-except
                    if hasattr(receiver, 'frame_received'):
                        self._safe_disconnect_signal(receiver.frame_received, self._on_frame_received)

                    receiver.frame_received.connect(self._on_frame_received)

                    if hasattr(receiver, 'set_frame_processor'):
                        receiver.set_frame_processor(self.scan_processor)

                    if hasattr(receiver, 'enable_direct_routing'):
                        receiver.enable_direct_routing(True)

                    if hasattr(receiver, 'request_dual_camera'):
                        receiver.request_dual_camera(True)

                    self._stream_connected = True
                    return True

        # --- FASE 7: Tentativo di creazione nuovo receiver ---
        logger.info("Tentativo di creazione nuovo receiver")
        try:
            if self.selected_scanner:
                # Ottieni parametri connessione
                host = self.selected_scanner.ip_address
                port = self.selected_scanner.port + 1  # Porta stream = porta comandi + 1

                # Importa dinamicamente StreamReceiver
                try:
                    from client.network.stream_receiver import StreamReceiver
                    logger.info(f"Creazione nuovo StreamReceiver su {host}:{port}")

                    # Crea istanza
                    receiver = StreamReceiver(host, port)

                    # Configura
                    receiver.frame_received.connect(self._on_frame_received)

                    if hasattr(receiver, 'set_frame_processor'):
                        receiver.set_frame_processor(self.scan_processor)

                    if hasattr(receiver, 'enable_direct_routing'):
                        receiver.enable_direct_routing(True)

                    # Avvia il receiver
                    receiver.start()

                    # Mantieni riferimento
                    self._local_stream_receiver = receiver

                    # Forza avvio streaming se abbiamo il controller
                    if self.scanner_controller:
                        logger.info("Invio comando avvio streaming al server...")
                        self.scanner_controller.send_command(
                            self.selected_scanner.device_id,
                            "START_STREAM",
                            {
                                "dual_camera": True,
                                "quality": 90,
                                "target_fps": 30
                            }
                        )

                    self._stream_connected = True
                    logger.info("Nuovo StreamReceiver creato e avviato")
                    return True
                except ImportError:
                    logger.error("Impossibile importare StreamReceiver")
                except Exception as e:
                    logger.error(f"Errore nella creazione StreamReceiver: {e}")
            else:
                logger.warning("Nessuno scanner selezionato, impossibile creare StreamReceiver")
        except Exception as e:
            logger.error(f"Errore nel tentativo finale: {e}")

        # --- FASE 8: Fallimento finale ---
        logger.error("Impossibile connettersi agli stream delle camere dopo tutti i tentativi")
        return False

    def _register_frame_handler(self):
        """Registra il gestore dei frame per la scansione."""
        if self._frame_receiver_registered:
            return True

        try:
            # Cerca il main window
            main_window = self.window()

            # Cerca il widget di streaming
            if hasattr(main_window, 'streaming_widget') and main_window.streaming_widget:
                streaming_widget = main_window.streaming_widget

                # Accedi al ricevitore di stream
                if hasattr(streaming_widget, 'stream_receiver') and streaming_widget.stream_receiver:
                    receiver = streaming_widget.stream_receiver

                    # Collega i segnali se disponibili
                    if hasattr(receiver, 'scan_frame_received'):
                        try:
                            receiver.scan_frame_received.disconnect(self._on_scan_frame_received)
                        except:
                            pass

                        receiver.scan_frame_received.connect(self._on_scan_frame_received)

                    # Imposta il processore di frame
                    if hasattr(receiver, 'set_frame_processor'):
                        receiver.set_frame_processor(self.scan_processor)

                    # Abilita il routing diretto
                    if hasattr(receiver, 'enable_direct_routing'):
                        receiver.enable_direct_routing(True)

                    self._frame_receiver_registered = True
                    logger.info("Frame handler registrato con successo")
                    return True
        except Exception as e:
            logger.error(f"Errore nella registrazione del frame handler: {e}")

        return False

    def _on_frame_received(self, camera_index: int, frame: np.ndarray, timestamp: float):
        """Gestisce la ricezione di un frame dallo stream con diagnostica migliorata e sincronizzazione."""
        try:
            # Log migliorato per tracciamento frame
            if not hasattr(self, '_frame_count_by_camera'):
                self._frame_count_by_camera = {0: 0, 1: 0}
                self._last_frame_log_time = time.time()
                self._frames_displayed = {0: 0, 1: 0}  # Nuova metrica: frame effettivamente visualizzati
                logger.info("Inizializzazione contatori di frame")

            # Incrementa contatore per questa camera
            self._frame_count_by_camera[camera_index] = self._frame_count_by_camera.get(camera_index, 0) + 1

            # Traccia primo frame ricevuto per ogni camera
            if not hasattr(self, f'_first_frame_{camera_index}'):
                logger.info(f"ScanView: primo frame ricevuto per fotocamera {camera_index}: dimensione={frame.shape}")
                setattr(self, f'_first_frame_{camera_index}', True)

            # Log periodico (ogni 5 secondi) per verificare ricezione frame per camera
            now = time.time()
            if now - getattr(self, '_last_frame_log_time', 0) > 5.0:
                self._last_frame_log_time = now
                total_frames = sum(self._frame_count_by_camera.values())
                fps_calc = total_frames / 5.0  # FPS negli ultimi 5 secondi

                logger.info(f"ScanView: statistiche frame ricevuti negli ultimi 5s: " +
                            f"totale={total_frames}, FPS={fps_calc:.1f}, " +
                            ", ".join([f"camera{idx}={count}" for idx, count in self._frame_count_by_camera.items()]))

                # Statistiche display (se disponibili)
                if hasattr(self, '_frames_displayed'):
                    total_displayed = sum(self._frames_displayed.values())
                    logger.info(f"ScanView: frame visualizzati: totale={total_displayed}, " +
                                ", ".join([f"camera{idx}={count}" for idx, count in self._frames_displayed.items()]))
                    self._frames_displayed = {0: 0, 1: 0}  # Reset contatori display

                self._frame_count_by_camera = {0: 0, 1: 0}  # Reset contatori ricezione

            # Verifica validità frame
            if frame is None or not isinstance(frame, np.ndarray) or frame.size == 0:
                logger.warning(f"ScanView: frame non valido ricevuto per camera {camera_index}")
                return

            # Sincronizza i frame se possibile
            if self._synchronize_camera_frames(camera_index, frame, timestamp):
                # Frame già gestito dalla sincronizzazione
                return

            # Se non è stato sincronizzato, aggiorna comunque il preview corrispondente
            if camera_index == 0:
                self.left_preview.update_frame(frame, timestamp)
                if hasattr(self, '_frames_displayed'):
                    self._frames_displayed[0] += 1
            elif camera_index == 1:
                self.right_preview.update_frame(frame, timestamp)
                if hasattr(self, '_frames_displayed'):
                    self._frames_displayed[1] += 1
            else:
                logger.warning(f"ScanView: indice camera non riconosciuto: {camera_index}")

        except Exception as e:
            # Log esplicito degli errori per debug
            logger.error(f"ScanView: errore in _on_frame_received per camera {camera_index}: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")

    def _on_scan_frame_received(self, camera_index: int, frame: np.ndarray, frame_info: Dict):
        """Gestisce la ricezione di un frame di scansione."""
        if not self.is_scanning:
            return

        try:
            # Aggiorna i preview
            if camera_index == 0:
                self.left_preview.update_frame(frame, frame_info.get('timestamp'))
            elif camera_index == 1:
                self.right_preview.update_frame(frame, frame_info.get('timestamp'))

            # Processa il frame se la scansione è attiva
            pattern_index = frame_info.get('pattern_index', 0)

            # Emetti il segnale di frame processato
            self.frame_processed.emit(camera_index, pattern_index, frame)

        except Exception as e:
            logger.error(f"Errore nell'elaborazione del frame di scansione: {e}")

    def _on_scan_progress(self, progress):
        """Callback per l'avanzamento della scansione."""
        try:
            # Estrai informazioni dal progresso
            if isinstance(progress, dict):
                percent = progress.get('progress', 0)
                message = progress.get('message', '')
                state = progress.get('state', 'SCANNING')
            else:
                # Formato semplice
                percent = progress
                message = ''
                state = 'SCANNING'

            # Aggiorna UI
            self.progress_bar.setValue(int(percent))

            if message:
                self.status_label.setText(message)
        except Exception as e:
            logger.error(f"Errore nell'aggiornamento del progresso: {e}")

    def _on_frame_processed(self, camera_index, pattern_index, frame_info):
        """Callback per frame processati con monitoraggio sincronizzazione."""
        try:
            # Verifica se è un aggiornamento della nuvola di punti
            if frame_info and frame_info.get('type') == 'pointcloud_update':
                # Aggiorna la visualizzazione 3D
                pointcloud = frame_info.get('pointcloud')
                if pointcloud is not None and len(pointcloud) > 0:
                    self.pointcloud_viewer.update_pointcloud(pointcloud)
                    # Abilita esportazione
                    self.export_button.setEnabled(True)

            # Monitoraggio del frame acquisito se è un frame di scansione
            elif frame_info and frame_info.get('pattern_index') is not None:
                pattern_idx = frame_info.get('pattern_index')
                timestamp = frame_info.get('timestamp')
                server_timestamp = frame_info.get('server_timestamp')

                # Se abbiamo sia il timestamp del server che quello del frame
                if server_timestamp and timestamp:
                    self._monitor_synchronization_timing(pattern_idx, server_timestamp, timestamp)

                    # Calcola latenza di acquisizione
                    acq_delay = timestamp - server_timestamp
                    if acq_delay > 0.2:  # 200ms
                        logger.warning(
                            f"Latenza acquisizione elevata per pattern {pattern_idx}: {acq_delay * 1000:.1f}ms")

        except Exception as e:
            logger.error(f"Errore nel callback frame_processed: {e}")

    def _start_scan(self):
        """Avvia una nuova scansione con sincronizzazione proiettore-scanner."""
        if self.is_scanning:
            logger.info("Scansione già in corso, nessuna azione necessaria")
            return

        # Verifica connessione scanner
        if not self.selected_scanner or not self.scanner_controller:
            logger.warning("Scanner non selezionato o controller non disponibile")
            QMessageBox.warning(
                self,
                "Scanner non selezionato",
                "Seleziona uno scanner prima di avviare la scansione."
            )
            return

        # Verifica preliminare stato streaming
        streaming_status = self._verify_streaming_status()
        logger.info(f"Stato streaming verificato: {streaming_status}")

        # Verifica connessione stream
        connection_status = self._connect_to_stream()
        logger.info(f"Connessione allo stream: {connection_status}")

        if not connection_status:
            # Mostra errore dettagliato
            QMessageBox.warning(
                self,
                "Stream non disponibile",
                "Lo stream delle camere non è disponibile.\n"
                "Avvia lo streaming prima di iniziare la scansione."
            )
            return

        # Avvia la scansione sincronizzata
        self._start_synchronized_scan()

    def _stop_scan(self):
        """Ferma la scansione in corso."""
        if not self.is_scanning:
            return

        try:
            # Invia comando di stop al server
            if self.selected_scanner and self.scanner_controller:
                self.scanner_controller.send_command(
                    self.selected_scanner.device_id,
                    "STOP_SCAN"
                )

            # Ferma il processore
            stats = self.scan_processor.stop_scan()

            # Aggiorna stato
            self.is_scanning = False

            # Aggiorna UI
            self.status_label.setText("Scansione completata")
            self.progress_bar.setValue(100)
            self.start_scan_button.setEnabled(True)
            self.stop_scan_button.setEnabled(False)

            # Abilita esportazione se abbiamo una nuvola
            if self.pointcloud_viewer.pointcloud is not None:
                self.export_button.setEnabled(True)

            logger.info(f"Scansione fermata: {self.scan_id}")

        except Exception as e:
            logger.error(f"Errore nell'arresto della scansione: {e}")
            QMessageBox.critical(
                self,
                "Errore",
                f"Si è verificato un errore nell'arresto della scansione:\n{str(e)}"
            )

            # Ripristina stato UI
            self.is_scanning = False
            self.start_scan_button.setEnabled(True)
            self.stop_scan_button.setEnabled(False)

    def _export_scan(self):
        """Esporta i risultati della scansione."""
        # Semplicemente delega all'export del visualizzatore
        self.pointcloud_viewer._export_pointcloud()

    def _update_status(self):
        """Aggiorna lo stato periodicamente."""
        # Verifica connessione scanner
        if self.scanner_controller and self.selected_scanner:
            is_connected = self.scanner_controller.is_connected(self.selected_scanner.device_id)

            # Abilita/disabilita pulsante avvio
            self.start_scan_button.setEnabled(is_connected and not self.is_scanning)

            # Aggiorna stato se non in scansione
            if not self.is_scanning:
                if is_connected:
                    self.status_label.setText(f"Connesso a {self.selected_scanner.name}")
                else:
                    self.status_label.setText("Scanner non connesso")
        else:
            self.status_label.setText("Scanner non selezionato")
            self.start_scan_button.setEnabled(False)

        # Se in scansione, aggiorna info da scan_processor
        if self.is_scanning:
            progress = self.scan_processor.get_scan_progress()
            self.progress_bar.setValue(int(progress.get('progress', 0)))

            # Aggiorna stato solo ogni 10 chiamate per non sovrascrivere i messaggi importanti
            if not hasattr(self, '_status_update_counter'):
                self._status_update_counter = 0

            self._status_update_counter += 1

            if self._status_update_counter % 10 == 0:
                patterns = progress.get('patterns_received', 0)
                frames = progress.get('frames_total', 0)
                self.status_label.setText(f"Scansione in corso: {patterns} pattern, {frames} frame totali")

    def set_scanner_controller(self, controller):
        """Imposta il controller dello scanner."""
        self.scanner_controller = controller
        self._update_status()

    def update_selected_scanner(self, scanner):
        """Aggiorna lo scanner selezionato."""
        self.selected_scanner = scanner
        self._update_status()

        # Prova a connettersi agli stream
        self._connect_to_stream()

        # Abilita il pulsante diagnostica se c'è uno scanner selezionato
        if self.selected_scanner and hasattr(self, 'diagnostics_button'):
            self.diagnostics_button.setEnabled(True)

    def refresh_scanner_state(self):
        """Aggiorna lo stato dello scanner (richiamato quando la tab diventa attiva)."""
        self._update_status()
        self._connect_to_stream()

    # Metodi aggiuntivi per compatibilità con l'implementazione originale
    def get_realtime_pointcloud(self):
        """Restituisce l'ultima nuvola di punti generata."""
        return self.pointcloud_viewer.pointcloud

    def _connect_to_stream(self):
        """Collega il widget agli stream delle camere con gestione più robusta degli errori."""
        if self._stream_connected:
            logger.debug("Stream già connesso, nessuna azione necessaria")
            return True

        try:
            # Cerca il main window
            main_window = self.window()
            logger.info(f"MainWindow trovata: {main_window is not None}")

            # Verifica se stream_receiver è presente direttamente in MainWindow
            if hasattr(main_window, 'stream_receiver') and main_window.stream_receiver:
                receiver = main_window.stream_receiver

                # CORREZIONE: Gestione più robusta della disconnessione dei segnali
                try:
                    # Verifica se il segnale ha già ricevitori prima di disconnettere
                    if hasattr(receiver.frame_received, 'receivers'):
                        connections = receiver.frame_received.receivers()
                        logger.info(f"Connessioni esistenti: {connections}")

                        # Verifica se il nostro metodo è già connesso
                        try:
                            # Prova a disconnettere solo se sicuri che sia connesso
                            receiver.frame_received.disconnect(self._on_frame_received)
                            logger.info("Segnale frame_received disconnesso con successo")
                        except (TypeError, RuntimeError) as e:
                            # Ignora l'errore se il segnale non era connesso
                            logger.info(f"Nessun segnale da disconnettere: {e}")
                    else:
                        # Fallback meno elegante ma comunque funzionale
                        try:
                            receiver.frame_received.disconnect(self._on_frame_received)
                        except Exception:
                            pass  # Ignora qualsiasi errore di disconnessione
                except Exception as e:
                    logger.warning(f"Errore gestito nella disconnessione: {e}")
                    # Continua comunque con la connessione

                # Collega il segnale
                receiver.frame_received.connect(self._on_frame_received)
                logger.info("Segnale frame_received collegato con successo")

                # Imposta il processore di scan frame
                if hasattr(receiver, 'set_frame_processor'):
                    receiver.set_frame_processor(self.scan_processor)
                    logger.info("Processore di frame impostato con successo")

                # Abilita routing diretto
                if hasattr(receiver, 'enable_direct_routing'):
                    receiver.enable_direct_routing(True)
                    logger.info("Routing diretto abilitato con successo")

                self._stream_connected = True
                return True

            # ... il resto del codice esistente ...

        except Exception as e:
            logger.error(f"Errore nella connessione agli stream: {e}")
            import traceback
            logger.error(f"Traceback completo: {traceback.format_exc()}")

        return False

    def _verify_streaming_status(self):
        """Verifica lo stato effettivo dello streaming."""
        try:
            main_window = self.window()

            # Controlla direttamente se stream_receiver è presente e attivo
            if hasattr(main_window, 'stream_receiver') and main_window.stream_receiver:
                logger.info("Stream receiver trovato in MainWindow")
                receiver = main_window.stream_receiver

                # Verifica se il receiver è attivo
                if hasattr(receiver, 'is_running') and receiver.is_running():
                    logger.info("Stream receiver is running")
                    return True

                # Controlla se ci sono connessioni attive
                if hasattr(receiver, '_connections') and len(receiver._connections) > 0:
                    logger.info(f"Stream receiver ha {len(receiver._connections)} connessioni attive")
                    return True

            # Se arriviamo qui, verifica se è disponibile tramite scanner_controller
            if hasattr(self, 'scanner_controller') and self.scanner_controller:
                if hasattr(self.scanner_controller, 'get_stream_receiver'):
                    receiver = self.scanner_controller.get_stream_receiver()
                    if receiver and (hasattr(receiver, 'is_running') and receiver.is_running()):
                        logger.info("Stream receiver trovato tramite controller e attivo")
                        return True

            logger.warning("Non è stato possibile confermare che lo streaming è attivo")
            return False

        except Exception as e:
            logger.error(f"Errore nella verifica dello stato dello streaming: {e}")
            return False

    def _sync_pattern_projection(self, pattern_index):
        """
        Sincronizza la proiezione di un pattern specifico con il server.
        Versione ottimizzata per bassa latenza e alta precisione.
        """
        if not self.selected_scanner or not self.scanner_controller:
            return None

        try:
            # Timestamp preciso pre-richiesta (alta risoluzione)
            request_time = time.time()

            # Invia comando con timestamp preciso e priorità alta
            command_success = self.scanner_controller.send_command(
                self.selected_scanner.device_id,
                "SYNC_PATTERN",
                {
                    "pattern_index": pattern_index,
                    "timestamp": request_time,
                    "priority": "high"  # Comunica al server priorità alta
                },
                timeout=0.2  # Timeout breve
            )

            if not command_success:
                logger.error(f"Errore nell'invio del comando SYNC_PATTERN per pattern {pattern_index}")
                return None

            # Attendi risposta con timeout breve
            response = self.scanner_controller.wait_for_response(
                self.selected_scanner.device_id,
                "SYNC_PATTERN",
                timeout=0.3  # Solo 300ms di attesa max
            )

            if not response:
                logger.error("Nessuna risposta ricevuta per SYNC_PATTERN")
                return None

            # Timestamp di risposta ad alta precisione
            response_time = time.time()

            # Calcola RTT (Round Trip Time)
            rtt = response_time - request_time

            # Aggiungi informazioni di sincronizzazione
            response["client_request_time"] = request_time
            response["client_response_time"] = response_time
            response["rtt"] = rtt

            # Calcola offset di clock stimato
            server_timestamp = response.get("timestamp", 0)
            if server_timestamp > 0:
                # Stima offset clock = timestamp server - (tempo client + RTT/2)
                clock_offset = server_timestamp - (request_time + rtt / 2)
                response["clock_offset"] = clock_offset

                if abs(clock_offset) > 0.5:  # Offset >500ms
                    logger.warning(f"Offset di clock elevato: {clock_offset * 1000:.1f}ms")

            # Log latenza comando per debug
            logger.info(f"Pattern {pattern_index} sincronizzato: RTT={rtt * 1000:.1f}ms")

            return response

        except Exception as e:
            logger.error(f"Errore nella sincronizzazione del pattern {pattern_index}: {e}")
            return None

    def _monitor_synchronization_timing(self, pattern_index, server_timestamp, capture_timestamp=None):
        """
        Monitora i tempi di sincronizzazione per identificare problemi.

        Args:
            pattern_index: Indice del pattern
            server_timestamp: Timestamp del server quando il pattern è stato proiettato
            capture_timestamp: Timestamp locale quando il frame è stato acquisito
        """
        now = time.time()

        # Calcola i ritardi
        server_time_diff = now - server_timestamp

        # Aggiorna statistiche
        if not hasattr(self, '_sync_stats'):
            self._sync_stats = {
                'patterns': 0,
                'total_server_delay': 0,
                'max_server_delay': 0,
                'capture_delays': []
            }

        self._sync_stats['patterns'] += 1
        self._sync_stats['total_server_delay'] += server_time_diff
        self._sync_stats['max_server_delay'] = max(self._sync_stats['max_server_delay'], server_time_diff)

        if capture_timestamp:
            capture_delay = capture_timestamp - server_timestamp
            self._sync_stats['capture_delays'].append(capture_delay)

        # Alert su ritardi significativi
        if server_time_diff > 0.5:  # Ritardo superiore a 500ms
            logger.warning(
                f"Ritardo di sincronizzazione elevato per pattern {pattern_index}: {server_time_diff * 1000:.1f}ms")

            # Suggerimenti automatici per problemi
            if server_time_diff > 1.0:
                logger.error("Ritardo critico. Possibili cause: rete congestionata, CPU server sovraccarica")

        # Ogni 10 pattern, stampa statistiche di sincronizzazione
        if self._sync_stats['patterns'] % 10 == 0:
            avg_delay = self._sync_stats['total_server_delay'] / self._sync_stats['patterns']
            logger.info(
                f"Statistiche sincronizzazione: media={avg_delay * 1000:.1f}ms, max={self._sync_stats['max_server_delay'] * 1000:.1f}ms")

    def _start_synchronized_scan(self):
        """
        Avvia una scansione completamente sincronizzata con il proiettore.
        Versione robusta con riconnessione automatica e gestione avanzata degli errori.
        """
        if self.is_scanning:
            logger.info("Scansione già in corso, nessuna azione necessaria")
            return

        # Verifica preliminare scanner
        if not self.selected_scanner or not self.scanner_controller:
            logger.warning("Scanner non selezionato o controller non disponibile")
            QMessageBox.warning(
                self,
                "Scanner non selezionato",
                "Seleziona uno scanner prima di avviare la scansione."
            )
            return

        # Verifica connessione al server con retry
        attempt = 0
        max_attempts = 3
        while attempt < max_attempts:
            if self.scanner_controller.is_connected(self.selected_scanner.device_id):
                break

            attempt += 1
            logger.info(f"Tentativo di riconnessione {attempt}/{max_attempts}...")

            success = self.scanner_controller.connect_to_scanner(self.selected_scanner.device_id)
            if success:
                logger.info("Riconnessione riuscita")
                break

            if attempt < max_attempts:
                # Attesa progressiva tra tentativi
                wait_time = attempt * 0.5  # 0.5s, 1.0s, 1.5s...
                time.sleep(wait_time)

        if attempt == max_attempts and not self.scanner_controller.is_connected(self.selected_scanner.device_id):
            QMessageBox.warning(
                self,
                "Errore di connessione",
                f"Impossibile connettersi a {self.selected_scanner.name} dopo {max_attempts} tentativi."
            )
            return

        # Verifica connessione stream
        connection_status = self._connect_to_stream()
        logger.info(f"Connessione allo stream: {connection_status}")

        if not connection_status:
            # Tentativo di inizializzazione del receiver tramite MainWindow
            logger.info("Tentativo di inizializzazione stream_receiver tramite MainWindow...")

            main_window = self.window()
            if hasattr(main_window, '_setup_stream_receiver'):
                # Chiamata diretta al metodo di inizializzazione
                try:
                    init_success = main_window._setup_stream_receiver(self.selected_scanner)
                    if init_success:
                        logger.info("Inizializzazione stream_receiver riuscita")
                        # Riprova connessione
                        connection_status = self._connect_to_stream()
                except Exception as e:
                    logger.error(f"Errore nell'inizializzazione dello stream: {e}")

            if not connection_status:
                QMessageBox.warning(
                    self,
                    "Stream non disponibile",
                    "Lo stream delle camere non è disponibile.\n"
                    "Avvia lo streaming prima di iniziare la scansione."
                )
                return

        # Ottieni e verifica capacità di scansione del server
        try:
            capability_result = self.scanner_controller.send_command(
                self.selected_scanner.device_id,
                "CHECK_SCAN_CAPABILITY"
            )

            if not capability_result:
                QMessageBox.warning(
                    self,
                    "Errore verifica capacità",
                    "Impossibile verificare le capacità di scansione 3D del server."
                )
                return

            # Attendi risposta con timeout
            capability_response = self.scanner_controller.wait_for_response(
                self.selected_scanner.device_id,
                "CHECK_SCAN_CAPABILITY",
                timeout=5.0
            )

            if not capability_response or capability_response.get("status") != "ok":
                error_msg = "Errore risposta server" if not capability_response else capability_response.get("message",
                                                                                                             "Errore sconosciuto")
                QMessageBox.warning(
                    self,
                    "Errore verifica capacità",
                    f"Errore dal server: {error_msg}"
                )
                return

            # Verifica se la scansione 3D è supportata
            scan_capability = capability_response.get("scan_capability", False)
            if not scan_capability:
                # Estrai dettagli per messaggio informativo
                details = capability_response.get("scan_capability_details", {})
                error_message = details.get("error", "Scanner non supporta la scansione 3D")

                QMessageBox.warning(
                    self,
                    "Scansione 3D non supportata",
                    f"{error_message}\n\nVerifica che il proiettore sia collegato e funzionante."
                )
                return
        except Exception as e:
            logger.error(f"Errore nella verifica delle capacità: {e}")
            QMessageBox.warning(
                self,
                "Errore",
                f"Errore nella verifica delle capacità di scansione:\n{str(e)}"
            )
            return

        # Genera ID scansione
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.scan_id = f"SyncScan_{timestamp}"

        # Prepara il processore
        self.scan_processor.start_scan(
            scan_id=self.scan_id,
            num_patterns=24,  # Numero standard di pattern
            pattern_type="PROGRESSIVE"  # Tipo di pattern standard
        )

        # Imposta stato
        self.is_scanning = True

        # Aggiorna UI
        self.status_label.setText("Inizializzazione scansione sincronizzata...")
        self.progress_bar.setValue(0)
        self.start_scan_button.setEnabled(False)
        self.stop_scan_button.setEnabled(True)

        # Avvia thread di scansione
        scan_thread = threading.Thread(target=self._synchronized_scan_loop)
        scan_thread.daemon = True
        scan_thread.start()

        logger.info(f"Scansione sincronizzata avviata: {self.scan_id}")

    def _synchronized_scan_loop(self):
        """Loop principale per la scansione sincronizzata."""
        try:
            # Parametri scansione
            num_patterns = 24  # Inclusi white/black
            pattern_wait_time = 0.1  # 100ms di attesa dopo la conferma di proiezione

            # Evita di usare classi non definite - usa Signals per comunicare con l'UI thread
            self._update_ui_status("Scansione sincronizzata in corso...")

            # Loop principale pattern
            for pattern_index in range(num_patterns):
                # Verifica se la scansione è stata interrotta
                if not self.is_scanning:
                    logger.info("Scansione sincronizzata interrotta")
                    break

                # Calcola progresso
                progress = (pattern_index / num_patterns) * 100

                # Aggiorna UI da thread principale usando il metodo sicuro
                self._update_ui_progress(int(progress))

                pattern_name = f"Pattern {pattern_index}"
                if pattern_index == 0:
                    pattern_name = "White"
                elif pattern_index == 1:
                    pattern_name = "Black"

                self._update_ui_status(f"Acquisizione {pattern_name} ({pattern_index + 1}/{num_patterns})...")

                # Sincronizza proiezione
                sync_result = self._sync_pattern_projection(pattern_index)

                if not sync_result:
                    logger.error(f"Errore nella sincronizzazione del pattern {pattern_index}")
                    continue

                # Attesa per stabilizzazione pattern
                time.sleep(pattern_wait_time)

                # Acquisizione frame (i frame arriveranno automaticamente via callback)
                logger.info(f"Attesa acquisizione frame per pattern {pattern_index}")

                # Breve attesa per assicurarsi che i frame siano ricevuti
                time.sleep(0.2)

            # Scansione completata
            if self.is_scanning:
                # Aggiorna UI
                self._update_ui_progress(100)
                self._update_ui_status("Scansione sincronizzata completata")

                # Ferma scansione
                self._stop_scan()

        except Exception as e:
            logger.error(f"Errore nel loop di scansione sincronizzata: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")

            # Ferma scansione in caso di errore
            if self.is_scanning:
                self._stop_scan()

                # Mostra errore usando metodo thread-safe
                self._show_error_message("Errore",
                                         f"Si è verificato un errore durante la scansione sincronizzata:\n{str(e)}")

    def _update_ui_progress(self, value):
        """Aggiorna la barra di progresso in modo thread-safe."""
        if not self.progress_bar:
            return

        # Aggiorna l'UI nel thread principale
        QMetaObject.invokeMethod(
            self.progress_bar,
            "setValue",
            Qt.QueuedConnection,
            Q_ARG(int, value)
        )

    def _update_ui_status(self, message):
        """Aggiorna l'etichetta di stato in modo thread-safe."""
        if not self.status_label:
            return

        # Aggiorna l'UI nel thread principale
        QMetaObject.invokeMethod(
            self.status_label,
            "setText",
            Qt.QueuedConnection,
            Q_ARG(str, message)
        )

    def _show_error_message(self, title, message):
        """Mostra un messaggio di errore in modo thread-safe."""
        # Usa QTimer.singleShot per eseguire nel thread UI
        QTimer.singleShot(0, lambda: QMessageBox.critical(self, title, message))
    def _run_sync_diagnostics(self):
        """
        Esegue una diagnostica del ciclo di sincronizzazione per identificare problemi
        di timing e latenza.
        """
        if not self.selected_scanner or not self.scanner_controller:
            logger.error("Scanner non selezionato o controller non disponibile")
            QMessageBox.warning(
                self,
                "Diagnostica impossibile",
                "Seleziona e connetti uno scanner prima di eseguire la diagnostica."
            )
            return

        # Mostra dialogo di progresso
        progress = QProgressDialog("Diagnostica del ciclo di sincronizzazione in corso...", "Annulla", 0, 10, self)
        progress.setWindowTitle("Diagnostica")
        progress.setWindowModality(Qt.WindowModal)
        progress.show()
        QApplication.processEvents()

        try:
            # Assicurati che lo streaming sia attivo
            if not self._connect_to_stream():
                progress.close()
                QMessageBox.warning(
                    self,
                    "Errore stream",
                    "Impossibile connettersi allo stream. Avvia lo streaming prima di eseguire la diagnostica."
                )
                return

            # Misura latenza di proiezione-acquisizione
            results = []

            # Testa diversi pattern
            test_patterns = [0, 1, 2, 5, 10]  # White, black, pattern iniziali, pattern avanzati

            for i, pattern_idx in enumerate(test_patterns):
                progress.setValue(i)
                progress.setLabelText(f"Test pattern {pattern_idx}...")
                QApplication.processEvents()

                if progress.wasCanceled():
                    break

                # Azzera contatori di ricezione
                frame_received = {0: False, 1: False}
                capture_timestamps = {0: 0, 1: 0}

                # Callback temporanea per catturare i frame di questo pattern
                def sync_frame_callback(camera_idx, pattern_idx_received, frame):
                    if pattern_idx_received == pattern_idx:
                        frame_received[camera_idx] = True
                        capture_timestamps[camera_idx] = time.time()

                # Collega callback temporanea
                old_callback = self._frame_callback
                self._frame_callback = sync_frame_callback

                # Avvia sincronizzazione e misura tempo
                start_time = time.time()
                sync_response = self._sync_pattern_projection(pattern_idx)

                if not sync_response or sync_response.get('status') != 'success':
                    results.append({
                        'pattern': pattern_idx,
                        'success': False,
                        'error': sync_response.get('message', 'Errore sconosciuto nella sincronizzazione')
                    })
                    continue

                # Attendi ricezione frame (max 500ms)
                wait_start = time.time()
                timeout = 0.5  # 500ms

                while (not frame_received[0] or not frame_received[1]) and time.time() - wait_start < timeout:
                    QApplication.processEvents()
                    time.sleep(0.01)

                # Ripristina callback originale
                self._frame_callback = old_callback

                # Calcola le metriche
                server_projection_time = sync_response.get('projection_time_ms', 0)
                server_stabilization_time = sync_response.get('stabilization_time_ms', 0)
                server_timestamp = sync_response.get('timestamp', 0)

                left_latency = (capture_timestamps[0] - server_timestamp) * 1000 if frame_received[0] else None
                right_latency = (capture_timestamps[1] - server_timestamp) * 1000 if frame_received[1] else None

                # Salva risultati
                results.append({
                    'pattern': pattern_idx,
                    'pattern_name': sync_response.get('pattern_name', f'Pattern {pattern_idx}'),
                    'success': frame_received[0] and frame_received[1],
                    'left_captured': frame_received[0],
                    'right_captured': frame_received[1],
                    'left_latency_ms': left_latency,
                    'right_latency_ms': right_latency,
                    'server_projection_ms': server_projection_time,
                    'server_stabilization_ms': server_stabilization_time,
                    'total_sync_time_ms': int((time.time() - start_time) * 1000)
                })

            progress.setValue(len(test_patterns))
            progress.setLabelText("Analisi dei risultati...")
            QApplication.processEvents()
            time.sleep(0.5)  # Breve pausa per visualizzare il 100%
            progress.close()

            # Mostra risultati
            if not results:
                QMessageBox.warning(
                    self,
                    "Diagnostica annullata",
                    "La diagnostica è stata annullata prima di raccogliere risultati."
                )
                return

            # Crea report
            report = "DIAGNOSTICA CICLO DI SINCRONIZZAZIONE\n"
            report += "=" * 50 + "\n\n"

            for r in results:
                report += f"Pattern: {r['pattern']} ({r['pattern_name']})\n"
                report += f"Successo: {'✓' if r['success'] else '✗'}\n"

                if r['left_captured']:
                    report += f"Camera sinistra: ✓ (latenza: {r['left_latency_ms']:.1f}ms)\n"
                else:
                    report += f"Camera sinistra: ✗ (frame non ricevuto)\n"

                if r['right_captured']:
                    report += f"Camera destra: ✓ (latenza: {r['right_latency_ms']:.1f}ms)\n"
                else:
                    report += f"Camera destra: ✗ (frame non ricevuto)\n"

                report += f"Tempi server: proiezione={r['server_projection_ms']}ms, stabilizzazione={r['server_stabilization_ms']}ms\n"
                report += f"Tempo totale ciclo: {r['total_sync_time_ms']}ms\n\n"

            # Calcola metriche riassuntive
            success_rate = sum(1 for r in results if r['success']) / len(results) * 100
            avg_latency_left = sum(r['left_latency_ms'] for r in results if r['left_latency_ms'] is not None) / sum(
                1 for r in results if r['left_latency_ms'] is not None)
            avg_latency_right = sum(r['right_latency_ms'] for r in results if r['right_latency_ms'] is not None) / sum(
                1 for r in results if r['right_latency_ms'] is not None)

            report += "RIEPILOGO\n"
            report += "-" * 50 + "\n"
            report += f"Tasso di successo: {success_rate:.1f}%\n"
            report += f"Latenza media (sinistra): {avg_latency_left:.1f}ms\n"
            report += f"Latenza media (destra): {avg_latency_right:.1f}ms\n"

            # Mostra il report
            from PySide6.QtWidgets import QTextEdit, QVBoxLayout, QDialog, QPushButton

            dialog = QDialog(self)
            dialog.setWindowTitle("Report diagnostica sincronizzazione")
            dialog.resize(600, 500)

            layout = QVBoxLayout(dialog)

            text_edit = QTextEdit()
            text_edit.setReadOnly(True)
            text_edit.setFontFamily("Monospace")
            text_edit.setText(report)

            layout.addWidget(text_edit)

            button = QPushButton("Chiudi")
            button.clicked.connect(dialog.accept)
            layout.addWidget(button)

            dialog.exec()

        except Exception as e:
            progress.close()
            logger.error(f"Errore durante la diagnostica: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")

            QMessageBox.critical(
                self,
                "Errore diagnostica",
                f"Si è verificato un errore durante la diagnostica:\n{str(e)}"
            )

    def _synchronized_scan_loop_robust(self):
        """
        Loop principale per la scansione sincronizzata con gestione errori robusta.
        """
        try:
            # Parametri scansione
            num_patterns = 24  # Inclusi white/black
            pattern_wait_time = 0.1  # Tempo base di attesa tra pattern

            # Evita di usare classi non definite - usa Signals per comunicare con l'UI thread
            self._update_ui_status("Scansione sincronizzata in corso...")

            # Loop principale pattern
            for pattern_index in range(num_patterns):
                # Verifica se la scansione è stata interrotta
                if not self.is_scanning:
                    logger.info("Scansione sincronizzata interrotta")
                    break

                # Calcola progresso
                progress = (pattern_index / num_patterns) * 100

                # Aggiorna UI da thread principale usando il metodo sicuro
                self._update_ui_progress(int(progress))

                pattern_name = f"Pattern {pattern_index}"
                if pattern_index == 0:
                    pattern_name = "White"
                elif pattern_index == 1:
                    pattern_name = "Black"

                self._update_ui_status(f"Acquisizione {pattern_name} ({pattern_index + 1}/{num_patterns})...")

                # Sincronizza proiezione
                sync_result = self._sync_pattern_projection(pattern_index)

                if not sync_result:
                    logger.error(f"Errore nella sincronizzazione del pattern {pattern_index}")
                    continue

                # Attesa per stabilizzazione pattern e acquisizione
                time.sleep(pattern_wait_time)

                # Breve attesa aggiuntiva per frame successivi
                time.sleep(0.2)

            # Scansione completata
            if self.is_scanning:
                # Aggiorna UI
                self._update_ui_progress(100)
                self._update_ui_status("Scansione sincronizzata completata")

                # Ferma scansione
                self._stop_scan()

        except Exception as e:
            logger.error(f"Errore nel loop di scansione sincronizzata: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")

            # Ferma scansione in caso di errore
            if self.is_scanning:
                self._stop_scan()

                # Mostra errore usando metodo thread-safe
                self._show_error_message("Errore",
                                         f"Si è verificato un errore durante la scansione sincronizzata:\n{str(e)}")

    def _verify_camera_streams(self):
        """
        Verifica che entrambe le camere stiano ricevendo frame e tenta di recuperare
        quelle mancanti in modo più aggressivo.
        """
        try:
            if not hasattr(self, '_frame_count_by_camera'):
                self._frame_count_by_camera = {0: 0, 1: 0}

            # Verifica quali camere non ricevono frame
            missing_cameras = []
            for idx in [0, 1]:
                if idx not in self._frame_count_by_camera or self._frame_count_by_camera.get(idx, 0) == 0:
                    missing_cameras.append(idx)

            # Se entrambe le camere funzionano, nessuna azione necessaria
            if not missing_cameras:
                # Resetta contatori per prossima verifica
                self._frame_count_by_camera = {0: 0, 1: 0}

                # Pianifica prossima verifica
                if not hasattr(self, '_camera_check_timer') or not self._camera_check_timer.is_alive():
                    self._camera_check_timer = threading.Timer(5.0, self._verify_camera_streams)
                    self._camera_check_timer.daemon = True
                    self._camera_check_timer.start()
                return

            # Altrimenti, abbiamo camere mancanti da recuperare
            camera_names = ["sinistra" if idx == 0 else "destra" for idx in missing_cameras]
            camera_str = " e ".join(camera_names)
            logger.warning(f"Camera {camera_str} non riceve frame. Tentativo di recupero più aggressivo...")

            # Monitora il tempo di inattività
            if not hasattr(self, '_camera_inactive_since'):
                self._camera_inactive_since = time.time()

            inactivity_time = time.time() - self._camera_inactive_since
            logger.info(f"Le camere {camera_str} sono inattive da {inactivity_time:.1f}s")

            # STRATEGIA 1: Riavvia lo streaming lato server più aggressivamente
            if self.selected_scanner and self.scanner_controller:
                try:
                    # Prima verifica la connessione con un PING
                    ping_success = self.scanner_controller.send_command(
                        self.selected_scanner.device_id,
                        "PING",
                        {"timestamp": time.time()}
                    )

                    if not ping_success:
                        logger.warning("Ping fallito, tentativo di riconnessione...")
                        reconnect_success = self.scanner_controller.connect_to_scanner(self.selected_scanner.device_id)
                        if reconnect_success:
                            logger.info("Riconnessione al server riuscita")
                        else:
                            logger.error("Riconnessione al server fallita")

                    # Prima ferma lo streaming - più tentativi con attese più brevi
                    for attempt in range(2):
                        logger.info(f"Tentativo {attempt + 1} di fermata temporanea dello streaming...")
                        stop_success = self.scanner_controller.send_command(
                            self.selected_scanner.device_id,
                            "STOP_STREAM"
                        )
                        if stop_success:
                            logger.info("Streaming fermato con successo")
                            break
                        time.sleep(0.2)  # Attesa breve tra tentativi

                    # Attesa più breve
                    time.sleep(0.3)  # Attendi che si fermi completamente

                    # Riavvia con richiesta esplicita dual camera - più tentativi
                    for attempt in range(3):
                        logger.info(f"Tentativo {attempt + 1} di riavvio streaming con dual_camera=True...")
                        start_success = self.scanner_controller.send_command(
                            self.selected_scanner.device_id,
                            "START_STREAM",
                            {
                                "dual_camera": True,
                                "quality": 90,
                                "target_fps": 30
                            }
                        )
                        if start_success:
                            logger.info("Streaming riavviato con successo")
                            break
                        time.sleep(0.3)  # Attesa breve tra tentativi

                    # Reset contatori per prossima verifica
                    self._frame_count_by_camera = {0: 0, 1: 0}
                    # Reset del timer di inattività se abbiamo eseguito un'azione
                    self._camera_inactive_since = time.time()
                except Exception as e:
                    logger.error(f"Errore nel riavvio dello streaming: {e}")

            # STRATEGIA 2: Se l'inattività persiste, riconnessione accelerata
            if inactivity_time > 15.0:  # Più aggressivo: solo 15 secondi invece di 30
                logger.warning("Inattività prolungata, tentativo di riconnessione completa accelerata...")

                try:
                    # Disconnetti completamente
                    if self.selected_scanner and self.scanner_controller:
                        logger.info("Disconnessione forzata...")
                        self.scanner_controller.disconnect_from_scanner(self.selected_scanner.device_id)
                        time.sleep(0.5)  # Attesa ridotta

                        # Riconnetti
                        logger.info("Tentativo di riconnessione accelerata...")
                        reconnect_success = self.scanner_controller.connect_to_scanner(self.selected_scanner.device_id)
                        if reconnect_success:
                            logger.info("Riconnessione completata con successo")
                            # Reset del timer
                            self._camera_inactive_since = time.time()

                            # Forza anche l'aggiornamento dello streaming
                            logger.info("Forza aggiornamento del stream receiver...")
                            if hasattr(self, '_connect_to_stream'):
                                self._connect_to_stream()
                        else:
                            logger.error("Riconnessione fallita")
                except Exception as e:
                    logger.error(f"Errore nella riconnessione completa: {e}")

            # Pianifica prossima verifica con intervallo più breve se ci sono problemi
            check_interval = 2.0 if missing_cameras else 5.0  # Più aggressivo: 2 secondi invece di 3
            if not hasattr(self, '_camera_check_timer') or not self._camera_check_timer.is_alive():
                self._camera_check_timer = threading.Timer(check_interval, self._verify_camera_streams)
                self._camera_check_timer.daemon = True
                self._camera_check_timer.start()

        except Exception as e:
            logger.error(f"Errore nella verifica delle camere: {e}")
            # Assicurati che il timer venga comunque riavviato
            self._camera_check_timer = threading.Timer(5.0, self._verify_camera_streams)
            self._camera_check_timer.daemon = True
            self._camera_check_timer.start()

    def _synchronize_camera_frames(self, camera_index, frame, timestamp):
        """
        Sincronizza i frame delle diverse camere in base ai timestamp.

        Args:
            camera_index: Indice della camera
            frame: Frame ricevuto
            timestamp: Timestamp del frame

        Returns:
            True se il frame è stato sincronizzato, False altrimenti
        """
        # Inizializza buffer e timestamp se necessario
        if not hasattr(self, '_frame_buffer'):
            self._frame_buffer = {0: None, 1: None}
            self._frame_timestamps = {0: 0, 1: 0}
            self._last_sync_time = time.time()

        # Memorizza il frame e il timestamp
        self._frame_buffer[camera_index] = frame.copy()
        self._frame_timestamps[camera_index] = timestamp

        # Controlla se abbiamo entrambi i frame
        current_time = time.time()

        # Sincronizzazione time-based: cerca di corrispondere frame in una finestra di 100ms
        all_frames_available = all(ts > 0 for ts in self._frame_timestamps.values())
        timestamp_difference = abs(self._frame_timestamps.get(0, 0) - self._frame_timestamps.get(1, 0))
        time_since_last_sync = current_time - self._last_sync_time

        # Frame matching se non c'è stata sincronizzazione da almeno 30ms e abbiamo frame da entrambe le camere
        should_sync = (all_frames_available and time_since_last_sync > 0.03 and
                       (timestamp_difference < 0.1))  # 100ms max differenza

        # Forza sincronizzazione dopo 200ms anche se non abbiamo frame perfettamente sincronizzati
        force_sync = time_since_last_sync > 0.2 and all(f is not None for f in self._frame_buffer.values())

        if should_sync or force_sync:
            # Aggiorna i preview
            left_frame = self._frame_buffer.get(0)
            right_frame = self._frame_buffer.get(1)

            if left_frame is not None:
                self.left_preview.update_frame(left_frame, self._frame_timestamps.get(0, 0))

            if right_frame is not None:
                self.right_preview.update_frame(right_frame, self._frame_timestamps.get(1, 0))

            # Reset
            self._last_sync_time = current_time

            # Log periodico per debug
            if not hasattr(self, '_sync_count'):
                self._sync_count = 0

            self._sync_count += 1
            if self._sync_count % 30 == 0:  # Log ogni 30 sincronizzazioni
                logger.debug(f"Sincronizzazione frame: diff={timestamp_difference * 1000:.1f}ms, "
                             f"force={force_sync}")

            return True

        return False

    def _safe_disconnect_signal(self, signal, slot):
        """
        Disconnette un segnale da uno slot in modo sicuro, gestendo gli errori.

        Args:
            signal: Il segnale da disconnettere
            slot: Lo slot da disconnettere

        Returns:
            True se la disconnessione è riuscita o non era necessaria, False in caso di errore
        """
        try:
            # Verifica se il segnale è connesso allo slot
            try:
                is_connected = signal.isConnected(slot)
            except (AttributeError, TypeError):
                # Alcuni segnali non hanno il metodo isConnected o non possiamo verificare
                is_connected = True  # Assumiamo sia connesso per sicurezza

            # Disconnetti solo se era connesso
            if is_connected:
                signal.disconnect(slot)
                logger.debug(f"Segnale disconnesso con successo: {signal} da {slot.__name__}")
            else:
                logger.debug(f"Segnale non era connesso: {signal} a {slot.__name__}")

            return True
        except (RuntimeError, TypeError) as e:
            # Ignora errori specifici che indicano disconnessione già avvenuta
            if "not connected" in str(e).lower() or "failed to disconnect" in str(e).lower():
                logger.debug(f"Segnale già disconnesso: {e}")
                return True
            else:
                logger.warning(f"Errore non previsto nella disconnessione del segnale: {e}")
                return False
        except Exception as e:
            logger.warning(f"Errore imprevisto nella disconnessione del segnale: {e}")
            return False