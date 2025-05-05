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
import socket
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
        Connette il widget agli stream delle camere con approccio più robusto.
        Rispetta il pattern di assegnazione delle responsabilità.
        """
        # Se già connesso e non è passato troppo tempo dall'ultimo frame, non fare nulla
        if self._stream_connected and hasattr(self, '_last_frame_time') and \
                time.time() - self._last_frame_time < 2.0:
            return True

        try:
            # Cerca lo stream receiver in vari possibili percorsi
            receiver = self._get_existing_stream_receiver()

            if receiver:
                logger.info(f"Stream receiver trovato: {receiver}")

                # Blocca i segnali durante la riconfigurazione per evitare race condition
                receiver.blockSignals(True)
                try:
                    # Disconnetti eventuali vecchie connessioni per evitare doppie chiamate
                    if hasattr(receiver, 'frame_received'):
                        self._safe_disconnect_signal(receiver.frame_received, self._on_frame_received)

                    if hasattr(receiver, 'scan_frame_received'):
                        self._safe_disconnect_signal(receiver.scan_frame_received, self._on_scan_frame_received)

                    # Connetti i segnali con Qt.QueuedConnection per thread safety
                    if hasattr(receiver, 'frame_received'):
                        receiver.frame_received.connect(self._on_frame_received, Qt.QueuedConnection)
                        logger.info("Segnale frame_received collegato con successo")

                    if hasattr(receiver, 'scan_frame_received'):
                        receiver.scan_frame_received.connect(self._on_scan_frame_received, Qt.QueuedConnection)
                        logger.info("Segnale scan_frame_received collegato con successo")
                finally:
                    # Sempre sblocca i segnali alla fine
                    receiver.blockSignals(False)

                # Imposta il processore di frame
                if hasattr(receiver, 'set_frame_processor') and hasattr(self, 'scan_processor'):
                    receiver.set_frame_processor(self.scan_processor)
                    logger.info("Frame processor collegato direttamente")

                # Configura ottimizzazioni
                if hasattr(receiver, 'enable_direct_routing'):
                    receiver.enable_direct_routing(True)
                    logger.info("Routing diretto abilitato")

                if hasattr(receiver, 'set_low_latency_mode'):
                    receiver.set_low_latency_mode(True)
                    logger.info("Modalità bassa latenza attivata")

                # Inizializza monitoraggio attività
                self._last_frame_time = time.time()
                self._stream_connected = True

                return True

            # Se arriviamo qui, nessun receiver esistente è stato trovato
            if self.selected_scanner:
                logger.info("Nessun receiver esistente trovato, creazione nuovo receiver")
                return self._setup_stream_receiver(self.selected_scanner)
            else:
                logger.warning("Nessuno scanner selezionato, impossibile creare stream receiver")
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
        """
        Gestione ottimizzata dei frame ricevuti con tracciamento attività stream.
        Cruciale per il monitoraggio dello stato dello streaming.
        """
        try:
            # Aggiorna timestamp ultimo frame (fondamentale per monitoraggio attività)
            self._last_frame_time = time.time()

            # Incrementa contatore frame per questa camera
            if hasattr(self, '_frames_received'):
                self._frames_received[camera_index] = self._frames_received.get(camera_index, 0) + 1

            # Calcola latenza (utile per diagnostica)
            latency_ms = (time.time() - timestamp) * 1000 if timestamp > 0 else 0

            # Log ottimizzato per eventi significativi
            if not hasattr(self, '_first_frame_received'):
                # Primo frame - inizializza tracking
                self._first_frame_received = {0: False, 1: False}
                logger.info(f"Inizializzato tracking frame")

            # Log primo frame per camera
            if self._first_frame_received is not None and not self._first_frame_received.get(camera_index, False):
                self._first_frame_received[camera_index] = True
                logger.info(f"Primo frame camera {camera_index}: {frame.shape}, latenza={latency_ms:.1f}ms")

            # Fast path per aggiornamento preview
            if camera_index == 0:
                self.left_preview.update_frame(frame, timestamp)
            elif camera_index == 1:
                self.right_preview.update_frame(frame, timestamp)

        except Exception as e:
            logger.error(f"Errore in _on_frame_received: {e}")

    def _setup_stream_receiver(self, scanner):
        """
        Configura il receiver di stream per uno scanner connesso con gestione robusta degli errori.
        """
        try:
            # Prima ferma eventuali receiver esistenti
            if hasattr(self, 'stream_receiver') and self.stream_receiver:
                try:
                    logger.info("Arresto del precedente stream receiver...")
                    self.stream_receiver.stop()
                    time.sleep(0.5)  # Attendi il completamento
                except Exception as e:
                    logger.warning(f"Errore nell'arresto del receiver esistente: {e}")

            # Invia comando per fermare qualsiasi streaming esistente
            # PRIMA di inizializzare il nuovo receiver - questo è critico per rispettare REQ/REP
            if self.scanner_controller and self.selected_scanner:
                try:
                    # Verifica che la connessione sia attiva prima di inviare comandi
                    is_connected = self.scanner_controller.is_connected(self.selected_scanner.device_id)
                    if is_connected:
                        logger.info("Invio comando STOP_STREAM per pulire lo stato...")
                        # Invia comando STOP_STREAM con timeout ragionevole
                        stop_sent = self.scanner_controller.send_command(
                            self.selected_scanner.device_id,
                            "STOP_STREAM",
                            timeout=2.0
                        )

                        # Importante: attendi esplicitamente la risposta per completare il ciclo REQ/REP
                        if stop_sent:
                            response = self.scanner_controller.receive_response(self.selected_scanner.device_id,
                                                                                timeout=2.0)
                            logger.info(f"Risposta STOP_STREAM: {response}")

                        # Attendi che lo streaming si fermi completamente sul server
                        time.sleep(0.5)
                except Exception as e:
                    logger.warning(f"Errore nell'invio del comando STOP_STREAM: {e}")
                    # Continua comunque con il setup

            # Importa qui per evitare importazioni circolari
            from client.network.stream_receiver import StreamReceiver

            # Informazioni di connessione
            host = scanner.ip_address
            port = scanner.port + 1  # La porta di streaming è quella di comando + 1

            logger.info(f"Inizializzazione stream receiver da {host}:{port}")

            # Crea il receiver
            self.stream_receiver = StreamReceiver(host, port)

            # Configura il processor di frame
            if hasattr(self, 'scan_processor') and self.scan_processor:
                self.stream_receiver.set_frame_processor(self.scan_processor)
                logger.info("Processore di frame configurato nel stream receiver")

            # Configura altre opzioni
            if hasattr(self.stream_receiver, 'enable_direct_routing'):
                self.stream_receiver.enable_direct_routing(True)
                logger.info("Routing diretto abilitato")

            if hasattr(self.stream_receiver, 'request_dual_camera'):
                self.stream_receiver.request_dual_camera(True)
                logger.info("Dual camera richiesto")

            # Avvia il receiver prima di inviare START_STREAM
            self.stream_receiver.start()
            time.sleep(0.3)  # Breve pausa per permettere l'inizializzazione completa

            # Invia il comando START_STREAM per avviare lo streaming
            # Questo è importante: il receiver deve essere pronto ad accettare
            # i frame prima che il server inizi a inviarli
            self._start_streaming()

            # Inizializza statistiche per monitoraggio
            self._frames_received = {0: 0, 1: 0}
            self._last_frame_time = time.time()
            self._stream_connected = True

            # Configura il monitoraggio attività per rilevare problemi
            self._start_activity_monitor()

            # Propaga il receiver al resto del sistema
            main_window = self.window()
            if main_window and hasattr(main_window, 'stream_receiver'):
                main_window.stream_receiver = self.stream_receiver
                main_window._stream_initialized = True

            return True

        except Exception as e:
            logger.error(f"Errore nell'inizializzazione dello stream receiver: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False

    def _start_streaming(self):
        """
        Avvia lo streaming video in modo robusto con verifica della risposta e gestione
        del pattern REQ/REP.
        """
        if not self.selected_scanner or not self.scanner_controller:
            logger.error("Impossibile avviare streaming: scanner non selezionato/connesso")
            return False

        device_id = self.selected_scanner.device_id
        logger.info(f"Avvio streaming per scanner {device_id}")

        # Configurazione streaming ottimizzata con parametri espliciti
        streaming_config = {
            "dual_camera": True,  # Richiedi entrambe le camere
            "quality": 90,  # Alta qualità per scansione
            "target_fps": 30,  # Frame rate target ottimale
            "low_latency": True,  # Priorità alla latenza
            "timestamp": time.time(),  # Timestamp per sincronizzazione
            "client_ip": self._get_local_ip()  # Importante per NAT traversal
        }

        # Implementazione con tentativi multipli e attesa per completamento ciclo REQ/REP
        max_attempts = 3
        success = False

        for attempt in range(max_attempts):
            try:
                if attempt > 0:
                    logger.info(f"Tentativo {attempt + 1}/{max_attempts} di avvio streaming...")
                    time.sleep(1.0)  # Pausa tra tentativi

                # 1. Prima invia un STOP_STREAM per assicurarsi che il pattern REQ/REP sia pulito
                if attempt > 0:
                    try:
                        # Interrompi eventuale streaming precedente
                        stop_cmd = self.scanner_controller.send_command(
                            device_id,
                            "STOP_STREAM",
                            timeout=1.0
                        )

                        # Importante: attendi la risposta STOP_STREAM
                        response = self.scanner_controller.receive_response(device_id, timeout=1.0)
                        logger.info(f"Pulizia con STOP_STREAM: {response}")

                        # Piccola pausa per stabilizzazione
                        time.sleep(0.5)
                    except Exception as e:
                        logger.warning(f"Errore nella pulizia: {e}, continuo comunque")

                # 2. Invia comando START_STREAM
                cmd_sent = self.scanner_controller.send_command(
                    device_id,
                    "START_STREAM",
                    streaming_config,
                    timeout=5.0  # Timeout maggiore per il primo comando
                )

                if not cmd_sent:
                    logger.warning(f"Errore nell'invio del comando START_STREAM (tentativo {attempt + 1})")

                    # Se il socket è in uno stato invalido, resettalo
                    if hasattr(self.scanner_controller, 'connection_manager'):
                        try:
                            self.scanner_controller.connection_manager._reset_socket_state(device_id)
                            logger.info("Socket di comunicazione resettato prima del prossimo tentativo")
                        except:
                            pass

                    continue

                # 3. FONDAMENTALE: Attendi ESPLICITAMENTE la risposta per completare il ciclo REQ/REP
                response = self.scanner_controller.receive_response(device_id, timeout=5.0)

                if response and response.get("status") == "ok":
                    logger.info(f"Streaming avviato con successo: {response}")
                    success = True

                    # Aggiorna UI e stato
                    self.status_label.setText("Streaming attivo")

                    # Imposta timer per verificare lo stato dello streaming
                    self._start_streaming_monitor()

                    break
                else:
                    logger.warning(f"Risposta non valida a START_STREAM: {response}")

                    # Reset socket di comunicazione prima del prossimo tentativo
                    if hasattr(self.scanner_controller, 'connection_manager'):
                        try:
                            self.scanner_controller.connection_manager._reset_socket_state(device_id)
                            logger.info("Socket di comunicazione resettato prima del prossimo tentativo")
                        except:
                            pass

            except Exception as e:
                logger.error(f"Errore nell'avvio dello streaming (tentativo {attempt + 1}): {e}")

        if not success:
            logger.error(f"Impossibile avviare lo streaming dopo {max_attempts} tentativi")
            self.status_label.setText("Errore nell'avvio dello streaming")

        return success

    def _get_local_ip(self):
        """Ottiene l'indirizzo IP locale per connessioni NAT."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            return local_ip
        except:
            return None

    def _start_streaming_monitor(self):
        """
        Avvia un timer per monitorare lo stato dello streaming.
        Essenziale per rilevare interruzioni e riavviare se necessario.
        """
        if hasattr(self, '_streaming_monitor') and self._streaming_monitor.isActive():
            self._streaming_monitor.stop()

        # Crea e configura timer
        self._streaming_monitor = QTimer(self)
        self._streaming_monitor.timeout.connect(self._check_streaming_status)

        # Inizializza contatore frame
        self._frames_received = {0: 0, 1: 0}
        self._last_frame_time = time.time()
        self._last_check_time = time.time()

        # Avvia timer - controlla ogni 3 secondi
        self._streaming_monitor.start(3000)
        logger.info("Monitor dello streaming avviato")

    def _check_streaming_status(self):
        """
        Verifica se lo streaming è attivo e funzionante.
        Tenta di riavviare lo streaming se inattivo.
        """
        current_time = time.time()
        time_since_last_frame = current_time - self._last_frame_time

        # Se non riceviamo frame da più di 5 secondi, consideriamo lo streaming non attivo
        if time_since_last_frame > 5.0:
            logger.warning(f"Streaming inattivo da {time_since_last_frame:.1f}s")

            # Aggiorna UI
            self.status_label.setText(f"Streaming inattivo da {int(time_since_last_frame)}s. Riconnessione...")

            # Tenta riconnessione solo se non è stato tentato negli ultimi 10 secondi
            if current_time - getattr(self, '_last_reconnect_attempt', 0) > 10.0:
                self._last_reconnect_attempt = current_time

                # Tenta di riavviare lo streaming
                logger.info("Tentativo di riavvio dello streaming...")
                self._restart_streaming()
        else:
            # Streaming funzionante, calcola statistiche
            frames_since_last_check = sum(self._frames_received.values())
            if hasattr(self, '_last_frames_count'):
                new_frames = frames_since_last_check - self._last_frames_count
                fps = new_frames / (current_time - self._last_check_time)

                # Aggiorna UI solo se ci sono nuovi frame
                if new_frames > 0:
                    self.status_label.setText(f"Streaming attivo: {fps:.1f} FPS")

            # Aggiorna contatori
            self._last_frames_count = frames_since_last_check
            self._last_check_time = current_time

    def _restart_streaming(self):
        """
        Tenta di riavviare lo streaming quando si rileva inattività.
        Implementa una sequenza di riavvio più robusta.
        """
        if not self.selected_scanner or not self.scanner_controller:
            return

        try:
            device_id = self.selected_scanner.device_id

            # 1. Prima ferma esplicitamente lo streaming attuale
            logger.info("Invio comando esplicito STOP_STREAM...")
            self.scanner_controller.send_command(device_id, "STOP_STREAM")

            # Importante: ricevi la risposta per completare il ciclo REQ/REP
            response = self.scanner_controller.receive_response(device_id)
            logger.debug(f"Risposta STOP_STREAM: {response}")

            # 2. Breve pausa
            time.sleep(0.5)

            # 3. Controlla lo stato della connessione
            is_connected = self.scanner_controller.is_connected(device_id)
            if not is_connected:
                logger.warning("Scanner disconnesso, tentativo di riconnessione...")
                reconnect_success = self.scanner_controller.attempt_reconnection(device_id)
                if not reconnect_success:
                    logger.error("Riconnessione fallita, impossibile riavviare streaming")
                    return

                # Attendi un momento dopo la riconnessione
                time.sleep(1.0)

            # 4. Ferma e ricrea lo stream receiver
            if hasattr(self, '_stream_receiver') and self._stream_receiver:
                try:
                    self._stream_receiver.stop()
                    time.sleep(0.5)
                except Exception as e:
                    logger.warning(f"Errore nell'arresto dello stream receiver: {e}")

            # 5. Ricrea il receiver e riavvia lo streaming
            self._setup_stream_receiver(self.selected_scanner)

        except Exception as e:
            logger.error(f"Errore nel riavvio dello streaming: {e}")

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
        """
        Connette il widget agli stream delle camere con approccio più robusto.
        Rispetta il pattern di assegnazione delle responsabilità.
        """
        # Se già connesso e non è passato troppo tempo dall'ultimo frame, non fare nulla
        if self._stream_connected and hasattr(self, '_last_frame_time') and \
                time.time() - self._last_frame_time < 2.0:
            return True

        try:
            # Cerca lo stream receiver in vari possibili percorsi
            receiver = self._get_existing_stream_receiver()

            if receiver:
                logger.info(f"Stream receiver trovato: {receiver}")

                # Disconnetti eventuali vecchie connessioni per evitare doppie chiamate
                self._safe_disconnect_signal(receiver.frame_received, self._on_frame_received)
                self._safe_disconnect_signal(receiver.scan_frame_received, self._on_scan_frame_received)

                # Connetti i segnali con Qt.QueuedConnection per thread safety
                receiver.frame_received.connect(self._on_frame_received, Qt.QueuedConnection)

                if hasattr(receiver, 'scan_frame_received'):
                    receiver.scan_frame_received.connect(self._on_scan_frame_received, Qt.QueuedConnection)

                # Imposta il processore di frame
                if hasattr(receiver, 'set_frame_processor') and hasattr(self, 'scan_processor'):
                    receiver.set_frame_processor(self.scan_processor)
                    logger.info("Frame processor collegato direttamente")

                # Configura ottimizzazioni
                if hasattr(receiver, 'enable_direct_routing'):
                    receiver.enable_direct_routing(True)

                if hasattr(receiver, 'set_low_latency_mode'):
                    receiver.set_low_latency_mode(True)
                    logger.info("Modalità bassa latenza attivata")

                # Inizializza monitoraggio attività
                self._last_frame_time = time.time()
                self._stream_connected = True

                return True

            # Se arriviamo qui, nessun receiver esistente è stato trovato
            if self.selected_scanner:
                logger.info("Nessun receiver esistente trovato, creazione nuovo receiver")
                return self._setup_stream_receiver(self.selected_scanner)
            else:
                logger.warning("Nessuno scanner selezionato, impossibile creare stream receiver")
                return False

        except Exception as e:
            logger.error(f"Errore nella connessione agli stream: {e}")
            import traceback
            logger.error(f"Traceback completo: {traceback.format_exc()}")
            return False

    def _get_existing_stream_receiver(self):
        """
        Cerca lo stream receiver in tutte le possibili locazioni.
        """
        # 1. Cerca in MainWindow
        main_window = self.window()
        if hasattr(main_window, 'stream_receiver') and main_window.stream_receiver:
            return main_window.stream_receiver

        # 2. Cerca tramite scanner_controller
        if self.scanner_controller and hasattr(self.scanner_controller, 'get_stream_receiver'):
            receiver = self.scanner_controller.get_stream_receiver()
            if receiver:
                return receiver

        # 3. Controlla se abbiamo già un'istanza locale
        if hasattr(self, '_stream_receiver') and self._stream_receiver:
            return self._stream_receiver

        return None

    def _start_activity_monitor(self):
        """
        Avvia monitor attività stream frame per rilevare problemi.
        """
        if hasattr(self, '_activity_check_timer') and self._activity_check_timer.is_alive():
            return  # Già attivo

        def _check_activity():
            try:
                # Verifica tempo dall'ultimo frame
                current_time = time.time()
                last_frame = getattr(self, '_last_frame_time', 0)
                inactivity = current_time - last_frame

                # Se inattivo per più di 2 secondi, considera streaming perso
                if inactivity > 2.0 and self._stream_connected:
                    logger.warning(f"Inattività stream rilevata: {inactivity:.1f}s senza frame")

                    # Prova riconnessione automatica
                    if inactivity > 5.0:
                        logger.error("Stream inattivo per 5s, tentativo riconnessione")
                        # Reset flag connessione
                        self._stream_connected = False
                        # Forza riconnessione
                        QTimer.singleShot(0, self._connect_to_stream)

                # Pianifica prossimo check
                self._activity_check_timer = threading.Timer(1.0, _check_activity)
                self._activity_check_timer.daemon = True
                self._activity_check_timer.start()

            except Exception as e:
                logger.error(f"Errore nel monitoraggio attività: {e}")

        # Avvia primo check
        self._activity_check_timer = threading.Timer(1.0, _check_activity)
        self._activity_check_timer.daemon = True
        self._activity_check_timer.start()

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

    def _sync_pattern_projection_optimized(self, pattern_index):
        """
        Sincronizzazione pattern ottimizzata con timing predittivo.
        Riduce latenza anticipando tempi di comunicazione.
        """
        if not self.selected_scanner or not self.scanner_controller:
            return None

        try:
            # Timeout adattivo: più breve per pattern iniziali
            timeout = 0.2 if pattern_index < 5 else 0.3

            # Ottimizzazione: prefetch next command
            request_time = time.time()

            # Comando con predizione di tempo
            command_success = self.scanner_controller.send_command(
                self.selected_scanner.device_id,
                "SYNC_PATTERN",
                {
                    "pattern_index": pattern_index,
                    "timestamp": request_time,
                    "priority": "high",  # Alta priorità
                    "adaptive_timing": True,  # Abilita timing adattivo
                    "prefetch_next": True  # Suggerisce prefetch pattern successivo
                },
                timeout=timeout
            )

            if not command_success:
                logger.error(f"Errore invio comando SYNC_PATTERN {pattern_index}")
                return None

            # Attendi risposta con timeout adattivo
            response = self.scanner_controller.wait_for_response(
                self.selected_scanner.device_id,
                "SYNC_PATTERN",
                timeout=timeout
            )

            if not response:
                logger.error(f"Timeout risposta SYNC_PATTERN {pattern_index}")
                return None

            # Timestamp risposta
            response_time = time.time()

            # Calcola RTT e offset clock
            rtt = response_time - request_time

            server_timestamp = response.get("timestamp", 0)
            if server_timestamp > 0:
                # Calcola offset di clock per sincronizzazione più precisa
                clock_offset = server_timestamp - (request_time + rtt / 2)

                # Salva per calibrazione futura
                if not hasattr(self, '_clock_offsets'):
                    self._clock_offsets = []
                self._clock_offsets.append(clock_offset)

                # Log solo se offset significativo
                if abs(clock_offset) > 0.01:  # 10ms
                    logger.debug(f"Clock offset: {clock_offset * 1000:.1f}ms, RTT: {rtt * 1000:.1f}ms")

                # Aggiorna risposta
                response["clock_offset"] = clock_offset
                response["rtt"] = rtt
                response["client_response_time"] = response_time

            return response

        except Exception as e:
            logger.error(f"Errore in _sync_pattern_projection_optimized: {e}")
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
        Avvia scansione sincronizzata ottimizzata per bassa latenza.
        Usa double-buffering e prefetch pattern per minimizzare jitter.
        """
        if self.is_scanning:
            return

        # Verifica connessione
        if not self.selected_scanner or not self.scanner_controller:
            QMessageBox.warning(self, "Scanner non connesso",
                                "Seleziona e connetti uno scanner prima di avviare la scansione.")
            return

        # Assicura connessione stream attiva
        if not self._connect_to_stream():
            QMessageBox.warning(self, "Stream non disponibile",
                                "Impossibile connettersi allo stream. Riprova tra qualche istante.")
            return

        # Genera ID scansione con timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.scan_id = f"Scan_{timestamp}"

        # Configura scan processor con modalità bassa latenza
        self.scan_processor.start_scan(
            scan_id=self.scan_id,
            num_patterns=24,
            pattern_type="PROGRESSIVE"
        )

        # Imposta stato
        self.is_scanning = True

        # Aggiorna UI
        self.status_label.setText("Inizializzazione scansione...")
        self.progress_bar.setValue(0)
        self.start_scan_button.setEnabled(False)
        self.stop_scan_button.setEnabled(True)

        # Ottimizzazione 1: Prefetch pattern
        success = self.scanner_controller.send_command(
            self.selected_scanner.device_id,
            "PREFETCH_PATTERNS",
            {"count": 24}  # Prefetch tutti i pattern
        )

        if success:
            logger.info("Pattern prefetch richiesto per ridurre latenza")

        # Ottimizzazione 2: Requisiti real-time
        self.scanner_controller.send_command(
            self.selected_scanner.device_id,
            "SET_SCAN_MODE",
            {"mode": "REALTIME", "priority": "high"}
        )

        # Avvia thread sincronizzazione
        scan_thread = threading.Thread(target=self._synchronized_scan_loop_optimized)
        scan_thread.daemon = True
        scan_thread.start()

        logger.info(f"Scansione avviata: {self.scan_id}")

    def _synchronized_scan_loop_optimized(self):
        """Loop di scansione sincronizzata ottimizzato con proiezione predittiva."""
        try:
            # Parametri
            num_patterns = 24  # Inclusi white/black
            pattern_wait_base = 0.1  # Tempo attesa base

            # Buffer stati pattern
            pattern_states = {}

            # Calibrazione iniziale timing system
            self._calibrate_sync_timing()

            # Aggiorna UI
            self._update_ui_status("Scansione sincronizzata in corso...")

            # Prefetch dei primi pattern
            prefetch_count = min(4, num_patterns)
            for p_idx in range(prefetch_count):
                # Richiedi prefetch pattern (non-bloccante)
                self._request_pattern_prefetch(p_idx)

            # Loop principale pattern
            for pattern_index in range(num_patterns):
                # Controllo interruzione
                if not self.is_scanning:
                    logger.info("Scansione interrotta dall'utente")
                    break

                # Calcola progresso
                progress = (pattern_index / num_patterns) * 100
                self._update_ui_progress(int(progress))

                # Nome pattern per UI
                pattern_name = f"Pattern {pattern_index}"
                if pattern_index == 0:
                    pattern_name = "White"
                elif pattern_index == 1:
                    pattern_name = "Black"

                self._update_ui_status(f"Acquisizione {pattern_name} ({pattern_index + 1}/{num_patterns})...")

                # Prefetch di pattern futuri (pipeline adelante)
                next_pattern = pattern_index + prefetch_count
                if next_pattern < num_patterns:
                    self._request_pattern_prefetch(next_pattern)

                # Sincronizzazione pattern con timing adattivo
                sync_result = self._sync_pattern_projection_optimized(pattern_index)

                if not sync_result:
                    logger.error(f"Errore sincronizzazione pattern {pattern_index}")
                    # Riprova una volta
                    sync_result = self._sync_pattern_projection_optimized(pattern_index)
                    if not sync_result:
                        continue

                # Estrai informazioni di timing
                server_timestamp = sync_result.get('timestamp', 0)
                projection_time_ms = sync_result.get('projection_time_ms', 0)

                # Attesa adattiva in base ai tempi misurati
                stabilization_time = pattern_wait_base
                if projection_time_ms > 0:
                    # Riduci attesa se la proiezione è stata lenta
                    stabilization_time = max(0.05, pattern_wait_base - (projection_time_ms / 1000.0))

                # Attendi stabilizzazione pattern
                time.sleep(stabilization_time)

                # Memorizza stato pattern
                pattern_states[pattern_index] = {
                    'server_timestamp': server_timestamp,
                    'projection_time_ms': projection_time_ms,
                    'stabilization_time': stabilization_time
                }

            # Attendi ulteriori frame in arrivo
            if self.is_scanning:
                time.sleep(0.5)  # Breve attesa per gli ultimi frame

                # Aggiorna UI
                self._update_ui_progress(100)
                self._update_ui_status("Scansione completata")

                # Ferma scansione
                self._stop_scan()

        except Exception as e:
            logger.error(f"Errore nel loop scan ottimizzato: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")

            # Cleanup
            if self.is_scanning:
                self._stop_scan()

                # Notifica errore in UI thread
                QTimer.singleShot(0, lambda: QMessageBox.critical(
                    self, "Errore", f"Errore durante la scansione: {str(e)}")
                                  )

    def _calibrate_sync_timing(self):
        """
        Calibra i tempi di sincronizzazione per ottimizzare latenza.
        Misura RTT di base e pianifica sync pattern di conseguenza.
        """
        if not self.selected_scanner or not self.scanner_controller:
            return

        try:
            # Misura RTT baseline
            rtt_sum = 0
            rtt_count = 0

            # Esegui 3 ping per misurare RTT medio
            for _ in range(3):
                ping_start = time.time()
                success = self.scanner_controller.send_command(
                    self.selected_scanner.device_id,
                    "PING",
                    {"timestamp": ping_start}
                )

                if success:
                    response = self.scanner_controller.wait_for_response(
                        self.selected_scanner.device_id,
                        "PING",
                        timeout=0.5
                    )

                    if response:
                        ping_end = time.time()
                        rtt = ping_end - ping_start
                        rtt_sum += rtt
                        rtt_count += 1

                # Breve attesa tra ping
                time.sleep(0.05)

            # Calcola RTT medio
            avg_rtt = rtt_sum / rtt_count if rtt_count > 0 else 0.05

            # Memorizza per uso successivo
            self._baseline_rtt = avg_rtt
            logger.info(f"RTT base calibrato: {avg_rtt * 1000:.1f}ms")

            # Ottimizzazione tempi di attesa pattern in base a RTT
            pattern_wait_base = max(0.05, min(0.15, avg_rtt * 2))
            logger.info(f"Tempo attesa pattern base: {pattern_wait_base * 1000:.1f}ms")

            # Comunica al server offset di clock e RTT base
            self.scanner_controller.send_command(
                self.selected_scanner.device_id,
                "SYNC_CONFIG",
                {
                    "baseline_rtt_ms": avg_rtt * 1000,
                    "client_timestamp": time.time()
                }
            )

        except Exception as e:
            logger.error(f"Errore nella calibrazione timing: {e}")

    def _request_pattern_prefetch(self, pattern_index):
        """
        Richiede prefetch asincrono di un pattern per ridurre latenza.
        Non attende risposta per non bloccare il thread.
        """
        if not self.selected_scanner or not self.scanner_controller:
            return False

        try:
            # Comando non bloccante
            self.scanner_controller.send_command(
                self.selected_scanner.device_id,
                "PREFETCH_PATTERN",
                {
                    "pattern_index": pattern_index,
                    "priority": "medium",  # Priorità media per non interferire con sync
                    "async": True  # Non attende risposta
                },
                timeout=0.1  # Timeout breve
            )
            return True
        except:
            # Ignora errori - prefetch è solo ottimizzazione
            return False

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
            # Inizializza contatori frame se necessario
            if not hasattr(self, '_frame_count_by_camera'):
                self._frame_count_by_camera = {0: 0, 1: 0}

            # Verifica quali camere non ricevono frame
            missing_cameras = []
            for idx in [0, 1]:
                # Una camera è considerata missing se non ha ricevuto frame o ha ricevuto meno di 3 frame
                if idx not in self._frame_count_by_camera or self._frame_count_by_camera.get(idx, 0) < 3:
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
            logger.warning(f"Camera {camera_str} non riceve frame. Tentativo di recovery...")

            # Monitora il tempo di inattività
            if not hasattr(self, '_camera_inactive_since'):
                self._camera_inactive_since = time.time()

            inactivity_time = time.time() - self._camera_inactive_since

            if inactivity_time > 10.0:  # Solo dopo 10 secondi di inattività
                logger.warning(
                    f"Le camere {camera_str} sono inattive da {inactivity_time:.1f}s, tentativo di recovery aggressivo")

                # STRATEGIA 1: Reset completo dello streaming
                if self.selected_scanner and self.scanner_controller:
                    try:
                        # 1. Ferma lo streaming attuale
                        logger.info("Fermata streaming per recovery...")
                        self.scanner_controller.send_command(
                            self.selected_scanner.device_id,
                            "STOP_STREAM"
                        )
                        # Attendi risposta per completare REQ/REP
                        self.scanner_controller.receive_response(self.selected_scanner.device_id)

                        # 2. Reset socket di comunicazione
                        if hasattr(self.scanner_controller, 'connection_manager'):
                            try:
                                cm = self.scanner_controller.connection_manager
                                cm._reset_socket_state(self.selected_scanner.device_id)
                                logger.info("Socket di comunicazione resettato")
                            except Exception as e:
                                logger.warning(f"Errore nel reset socket: {e}")

                        # 3. Piccola pausa per stabilizzazione
                        time.sleep(1.0)

                        # 4. Ricrea completamente lo stream receiver
                        logger.info("Ricreazione stream receiver...")
                        self._setup_stream_receiver(self.selected_scanner)

                        # Reset del timer di inattività
                        self._camera_inactive_since = time.time()

                    except Exception as e:
                        logger.error(f"Errore nel recovery streaming: {e}")

            # Sempre: pianifica prossima verifica
            check_interval = 2.0 if missing_cameras else 5.0
            if not hasattr(self, '_camera_check_timer') or not self._camera_check_timer.is_alive():
                self._camera_check_timer = threading.Timer(check_interval, self._verify_camera_streams)
                self._camera_check_timer.daemon = True
                self._camera_check_timer.start()

        except Exception as e:
            logger.error(f"Errore nella verifica delle camere: {e}")
            # Assicurati che il timer venga comunque riavviato
            if not hasattr(self, '_camera_check_timer') or not self._camera_check_timer.is_alive():
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
        if not signal or not slot:
            return True  # Nulla da fare se il segnale o lo slot non sono validi

        try:
            # Prova semplicemente a disconnettere e cattura l'errore specifico se non è connesso
            try:
                signal.disconnect(slot)
                logger.debug(f"Segnale disconnesso con successo")
                return True
            except TypeError:
                # TypeError può verificarsi se il segnale non supporta la disconnessione esplicita
                # o se lo slot non è del tipo corretto
                logger.debug(f"Errore di tipo nella disconnessione del segnale")
                return True
        except RuntimeError as e:
            # In PySide/PyQt RuntimeError è sollevato quando si tenta di disconnettere un segnale non connesso
            if "not connected" in str(e).lower() or "failed to disconnect" in str(e).lower():
                logger.debug(f"Segnale già disconnesso")
                return True
            else:
                logger.warning(f"Errore nella disconnessione del segnale: {e}")
                return False
        except Exception as e:
            logger.warning(f"Errore imprevisto nella disconnessione del segnale: {e}")
            return False