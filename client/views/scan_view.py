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
    QApplication, QFileDialog
)
from PySide6.QtCore import Qt, Signal, Slot, QTimer
from PySide6.QtGui import QImage, QPixmap

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

    @Slot(np.ndarray, float)
    def update_frame(self, frame: np.ndarray, timestamp: float = None):
        """Aggiorna il frame visualizzato con calcolo lag."""
        if frame is None or not isinstance(frame, np.ndarray) or frame.size == 0:
            return

        # Memorizza e analizza il frame
        self._frame = frame.copy()
        self._frame_count += 1

        # Converti il frame in QImage per visualizzazione
        height, width = frame.shape[:2]
        bytes_per_line = frame.strides[0]

        if len(frame.shape) == 3 and frame.shape[2] == 3:
            # Frame a colori BGR -> RGB
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            qt_image = QImage(rgb_frame.data, width, height, bytes_per_line, QImage.Format_RGB888)
        else:
            # Frame in scala di grigi
            qt_image = QImage(frame.data, width, height, bytes_per_line, QImage.Format_Grayscale8)

        # Visualizza il frame
        pixmap = QPixmap.fromImage(qt_image)
        self.display_label.setPixmap(pixmap.scaled(
            self.display_label.width(), self.display_label.height(),
            Qt.KeepAspectRatio, Qt.SmoothTransformation
        ))
        self.display_label.setStyleSheet("")  # Rimuovi stile sfondo nero

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

        # Calcola lag se è stato fornito un timestamp
        if timestamp is not None:
            self._lag_ms = int((time.time() - timestamp) * 1000)
            self._update_lag_label()
        else:
            self.lag_label.setText("Lag: N/A")
            self.lag_label.setStyleSheet("color: gray;")

        # Aggiorna etichetta informativa
        camera_name = "Sinistra" if self.camera_index == 0 else "Destra"
        fps_text = f"{self._fps:.1f} FPS" if self._fps > 0 else ""
        self.info_label.setText(f"Camera {camera_name} | {width}x{height} | {fps_text}")

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
        """Collega il widget agli stream delle camere."""
        if self._stream_connected:
            logger.debug("Stream già connesso, nessuna azione necessaria")
            return True

        try:
            # Cerca il main window
            main_window = self.window()

            # Verifica se lo stream_receiver è presente in main_window
            if hasattr(main_window, 'stream_receiver') and main_window.stream_receiver is not None:
                receiver = main_window.stream_receiver

                # Tenta di accedere al segnale frame_received
                if hasattr(receiver, 'frame_received'):
                    # Disconnetti eventuali connessioni esistenti
                    try:
                        receiver.frame_received.disconnect(self._on_frame_received)
                    except:
                        pass

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

            # Tentativo alternativo di trovare il receiver dal controller
            if hasattr(self, 'scanner_controller') and self.scanner_controller:
                if hasattr(self.scanner_controller, 'get_stream_receiver'):
                    receiver = self.scanner_controller.get_stream_receiver()
                    if receiver:
                        # Collega il segnale e configura come sopra...
                        # (stesso codice di collegamento del segnale di prima)

                        self._stream_connected = True
                        return True

            logger.error("Stream receiver non trovato in MainWindow o nel controller")
            return False

        except Exception as e:
            logger.error(f"Errore nella connessione agli stream: {e}")
            import traceback
            logger.error(f"Traceback completo: {traceback.format_exc()}")

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
        """Gestisce la ricezione di un frame dallo stream."""
        # Aggiorna il preview corrispondente
        if camera_index == 0:
            self.left_preview.update_frame(frame, timestamp)
        elif camera_index == 1:
            self.right_preview.update_frame(frame, timestamp)

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
        """Callback per frame processati."""
        try:
            # Verifica se è un aggiornamento della nuvola di punti
            if frame_info and frame_info.get('type') == 'pointcloud_update':
                # Aggiorna la visualizzazione 3D
                pointcloud = frame_info.get('pointcloud')
                if pointcloud is not None and len(pointcloud) > 0:
                    self.pointcloud_viewer.update_pointcloud(pointcloud)

                    # Abilita esportazione
                    self.export_button.setEnabled(True)
        except Exception as e:
            logger.error(f"Errore nel callback frame_processed: {e}")

    def _start_scan(self):
        """Avvia una nuova scansione con diagnostica avanzata."""
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
            # Se entrambe le verifiche falliscono, mostra errore dettagliato
            error_info = ""
            main_window = self.window()
            if hasattr(main_window, 'streaming_widget'):
                error_info += "StreamingWidget è presente nel main_window.\n"
                if hasattr(main_window.streaming_widget, 'stream_receiver'):
                    error_info += "StreamReceiver è presente nello StreamingWidget.\n"
                    if main_window.streaming_widget.stream_receiver:
                        error_info += "StreamReceiver è inizializzato.\n"
                    else:
                        error_info += "StreamReceiver è NULL.\n"
                else:
                    error_info += "StreamReceiver non è presente nello StreamingWidget.\n"

                # Verifica metodo is_streaming
                if hasattr(main_window.streaming_widget, 'is_streaming'):
                    is_streaming = main_window.streaming_widget.is_streaming()
                    error_info += f"Stato streaming (is_streaming): {is_streaming}\n"
            else:
                error_info += "StreamingWidget non è presente nel main_window.\n"

            logger.error(f"Dettagli diagnostici: {error_info}")

            QMessageBox.warning(
                self,
                "Stream non disponibile",
                f"Lo stream delle camere non è disponibile.\n"
                f"Avvia lo streaming prima di iniziare la scansione.\n\n"
                f"Dettagli tecnici:\n{error_info}"
            )
            return

        # Registra il gestore dei frame
        frame_handler_status = self._register_frame_handler()
        logger.info(f"Registrazione frame handler: {frame_handler_status}")

        # Genera ID scansione
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.scan_id = f"Scan_{timestamp}"

        # Avvia la scansione
        try:
            # Prepara il processore
            self.scan_processor.start_scan(
                scan_id=self.scan_id,
                num_patterns=24,  # Numero standard di pattern
                pattern_type="PROGRESSIVE"  # Tipo di pattern standard
            )

            # Invia comando al server per avviare la proiezione dei pattern
            success = self.scanner_controller.send_command(
                self.selected_scanner.device_id,
                "START_SCAN",
                {
                    "scan_id": self.scan_id,
                    "pattern_type": "PROGRESSIVE",
                    "num_patterns": 24,
                    "quality": 3
                }
            )

            logger.info(f"Comando START_SCAN inviato: {success}")

            if not success:
                QMessageBox.critical(
                    self,
                    "Errore",
                    "Impossibile inviare il comando di avvio al server."
                )
                self.scan_processor.stop_scan()
                return

            # Imposta stato
            self.is_scanning = True

            # Aggiorna UI
            self.status_label.setText("Scansione in corso...")
            self.progress_bar.setValue(0)
            self.start_scan_button.setEnabled(False)
            self.stop_scan_button.setEnabled(True)

            # Emetti segnale
            self.scan_started.emit({
                "scan_id": self.scan_id,
                "timestamp": timestamp
            })

            logger.info(f"Scansione avviata: {self.scan_id}")

        except Exception as e:
            logger.error(f"Errore nell'avvio della scansione: {e}")
            import traceback
            logger.error(f"Traceback completo: {traceback.format_exc()}")
            QMessageBox.critical(
                self,
                "Errore",
                f"Si è verificato un errore nell'avvio della scansione:\n{str(e)}"
            )

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

    def refresh_scanner_state(self):
        """Aggiorna lo stato dello scanner (richiamato quando la tab diventa attiva)."""
        self._update_status()
        self._connect_to_stream()

    # Metodi aggiuntivi per compatibilità con l'implementazione originale
    def get_realtime_pointcloud(self):
        """Restituisce l'ultima nuvola di punti generata."""
        return self.pointcloud_viewer.pointcloud

    def _connect_to_stream(self):
        """Collega il widget agli stream delle camere con diagnostica avanzata."""
        if self._stream_connected:
            logger.debug("Stream già connesso, nessuna azione necessaria")
            return True

        try:
            # Cerca il main window
            main_window = self.window()
            logger.info(f"MainWindow trovata: {main_window is not None}")

            # Verifica streaming_widget
            has_streaming_widget = hasattr(main_window, 'streaming_widget')
            logger.info(f"MainWindow ha streaming_widget: {has_streaming_widget}")

            if has_streaming_widget and main_window.streaming_widget:
                streaming_widget = main_window.streaming_widget

                # Verifica stream_receiver
                has_receiver = hasattr(streaming_widget, 'stream_receiver')
                logger.info(f"StreamingWidget ha stream_receiver: {has_receiver}")

                if has_receiver and streaming_widget.stream_receiver:
                    receiver = streaming_widget.stream_receiver

                    # Verifica se il receiver ha i metodi necessari
                    logger.info(f"Metodi disponibili nel receiver: "
                                f"frame_received={hasattr(receiver, 'frame_received')}, "
                                f"set_frame_processor={hasattr(receiver, 'set_frame_processor')}, "
                                f"enable_direct_routing={hasattr(receiver, 'enable_direct_routing')}")

                    # Tenta di accedere al segnale frame_received
                    if hasattr(receiver, 'frame_received'):
                        # Disconnetti eventuali connessioni esistenti
                        try:
                            receiver.frame_received.disconnect(self._on_frame_received)
                        except:
                            pass

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
                    else:
                        logger.error("Segnale frame_received non trovato nel receiver")
                else:
                    logger.error("StreamReceiver non trovato o non inizializzato in StreamingWidget")
            else:
                logger.error("StreamingWidget non trovato in MainWindow")
        except Exception as e:
            logger.error(f"Errore nella connessione agli stream: {e}")
            import traceback
            logger.error(f"Traceback completo: {traceback.format_exc()}")

        return False

    def _verify_streaming_status(self):
        """Verifica lo stato effettivo dello streaming."""
        try:
            main_window = self.window()
            if hasattr(main_window, 'streaming_widget') and main_window.streaming_widget:
                streaming_widget = main_window.streaming_widget

                # Metodo 1: controllo attributo _streaming_active
                if hasattr(streaming_widget, '_streaming_active'):
                    logger.info(f"Stato streaming (_streaming_active): {streaming_widget._streaming_active}")
                    if streaming_widget._streaming_active:
                        return True

                # Metodo 2: controllo attributo stream_receiver
                if hasattr(streaming_widget, 'stream_receiver') and streaming_widget.stream_receiver:
                    logger.info("Stream receiver presente")
                    receiver = streaming_widget.stream_receiver

                    # Verifica se il receiver ha metodi di stato
                    if hasattr(receiver, 'is_running') and receiver.is_running():
                        logger.info("Stream receiver is running")
                        return True

                    # Controlla se ci sono connessioni attive
                    if hasattr(receiver, '_connections') and len(receiver._connections) > 0:
                        logger.info(f"Stream receiver ha {len(receiver._connections)} connessioni attive")
                        return True

                # Se arriviamo qui, significa che non abbiamo potuto confermare che lo streaming è attivo
                logger.warning("Non è stato possibile confermare che lo streaming è attivo")
                return False

            else:
                logger.error("StreamingWidget non trovato in MainWindow")
                return False
        except Exception as e:
            logger.error(f"Errore nella verifica dello stato dello streaming: {e}")
            return False