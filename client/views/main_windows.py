#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Finestra principale dell'applicazione UnLook Client.
"""

import logging
from enum import Enum
from typing import Optional, List

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QStatusBar, QAction, QToolBar,
    QDockWidget, QSplitter, QFrame, QTabWidget, QMessageBox,
    QMenu
)
from PySide6.QtCore import Qt, Slot, QSettings, QSize, QPoint
from PySide6.QtGui import QIcon, QPixmap, QFont

from controllers.scanner_controller import ScannerController
from models.scanner_model import Scanner, ScannerStatus
from views.scanner_view import ScannerDiscoveryWidget
from views.streaming_view import DualStreamView
from views.config_view import ConfigurationWidget

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """
    Finestra principale dell'applicazione UnLook Client.
    Fornisce un'interfaccia integrata per il controllo dello scanner e la visualizzazione
    degli stream video.
    """

    class TabIndex(Enum):
        """Indici delle schede nella finestra principale."""
        SCANNER = 0
        STREAMING = 1
        CONFIG = 2

    def __init__(self, scanner_controller: ScannerController):
        super().__init__()
        self.scanner_controller = scanner_controller

        # Configurazione della finestra
        self.setWindowTitle("UnLook Scanner - Client")
        self.setMinimumSize(1024, 768)

        # Carica le impostazioni
        self._load_settings()

        # Inizializza l'interfaccia utente
        self._setup_ui()

        # Collega i segnali
        self._connect_signals()

        # Avvia la scoperta degli scanner
        self.scanner_controller.start_discovery()

        logger.info("Interfaccia utente principale inizializzata")

    def _setup_ui(self):
        """Configura l'interfaccia utente principale."""
        # Widget centrale con layout a tab
        self.central_tabs = QTabWidget()
        self.setCentralWidget(self.central_tabs)

        # Crea i widget delle schede
        self.scanner_widget = ScannerDiscoveryWidget(self.scanner_controller)
        self.streaming_widget = DualStreamView()
        self.config_widget = ConfigurationWidget()

        # Aggiungi le schede
        self.central_tabs.addTab(self.scanner_widget, "Scanner")
        self.central_tabs.addTab(self.streaming_widget, "Streaming")
        self.central_tabs.addTab(self.config_widget, "Configurazione")

        # Disabilita le schede che richiedono una connessione attiva
        self.central_tabs.setTabEnabled(self.TabIndex.STREAMING.value, False)
        self.central_tabs.setTabEnabled(self.TabIndex.CONFIG.value, False)

        # Configura la barra di stato
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        # Label per lo stato della connessione
        self.connection_status_label = QLabel("Non connesso")
        self.status_bar.addPermanentWidget(self.connection_status_label)

        # Barra degli strumenti
        self._setup_toolbar()

        # Menu
        self._setup_menu()

    def _setup_toolbar(self):
        """Configura la barra degli strumenti."""
        self.toolbar = QToolBar("Strumenti principali")
        self.toolbar.setMovable(False)
        self.addToolBar(Qt.TopToolBarArea, self.toolbar)

        # Pulsante per avviare/fermare la scoperta
        self.action_toggle_discovery = QAction("Ferma ricerca", self)
        self.action_toggle_discovery.triggered.connect(self._toggle_discovery)
        self.toolbar.addAction(self.action_toggle_discovery)

        self.toolbar.addSeparator()

        # Menu a tendina per gli scanner disponibili
        self.scanner_selector = QComboBox()
        self.scanner_selector.setMinimumWidth(200)
        self.scanner_selector.setEnabled(False)
        self.toolbar.addWidget(QLabel("Scanner: "))
        self.toolbar.addWidget(self.scanner_selector)

        # Pulsante per connettersi/disconnettersi
        self.action_toggle_connection = QAction("Connetti", self)
        self.action_toggle_connection.setEnabled(False)
        self.action_toggle_connection.triggered.connect(self._toggle_connection)
        self.toolbar.addAction(self.action_toggle_connection)

        self.toolbar.addSeparator()

        # Pulsante per avviare/fermare lo streaming
        self.action_toggle_streaming = QAction("Avvia streaming", self)
        self.action_toggle_streaming.setEnabled(False)
        self.action_toggle_streaming.triggered.connect(self._toggle_streaming)
        self.toolbar.addAction(self.action_toggle_streaming)

        # Pulsante per acquisire un'immagine
        self.action_capture = QAction("Acquisizione", self)
        self.action_capture.setEnabled(False)
        self.action_capture.triggered.connect(self._capture_frame)
        self.toolbar.addAction(self.action_capture)

    def _setup_menu(self):
        """Configura il menu dell'applicazione."""
        # Menu File
        file_menu = self.menuBar().addMenu("&File")

        # Azione Esci
        exit_action = QAction("E&sci", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # Menu Scanner
        scanner_menu = self.menuBar().addMenu("&Scanner")

        # Azione Ricerca scanner
        discovery_action = QAction("&Ricerca scanner", self)
        discovery_action.triggered.connect(self.scanner_controller.start_discovery)
        scanner_menu.addAction(discovery_action)

        # Azione Disconnetti tutti
        disconnect_all_action = QAction("&Disconnetti tutti", self)
        disconnect_all_action.triggered.connect(self._disconnect_all)
        scanner_menu.addAction(disconnect_all_action)

        # Menu Visualizza
        view_menu = self.menuBar().addMenu("&Visualizza")

        # Azione mostra barra degli strumenti
        toggle_toolbar_action = QAction("Barra degli &strumenti", self)
        toggle_toolbar_action.setCheckable(True)
        toggle_toolbar_action.setChecked(True)
        toggle_toolbar_action.triggered.connect(
            lambda checked: self.toolbar.setVisible(checked)
        )
        view_menu.addAction(toggle_toolbar_action)

        # Azione mostra barra di stato
        toggle_statusbar_action = QAction("Barra di &stato", self)
        toggle_statusbar_action.setCheckable(True)
        toggle_statusbar_action.setChecked(True)
        toggle_statusbar_action.triggered.connect(
            lambda checked: self.status_bar.setVisible(checked)
        )
        view_menu.addAction(toggle_statusbar_action)

        # Menu Aiuto
        help_menu = self.menuBar().addMenu("&Aiuto")

        # Azione Info
        about_action = QAction("&Informazioni su UnLook", self)
        about_action.triggered.connect(self._show_about_dialog)
        help_menu.addAction(about_action)

    def _connect_signals(self):
        """Collega i segnali dell'applicazione."""
        # Segnali del controller degli scanner
        self.scanner_controller.scanners_changed.connect(self._update_scanner_list)
        self.scanner_controller.scanner_connected.connect(self._on_scanner_connected)
        self.scanner_controller.scanner_disconnected.connect(self._on_scanner_disconnected)
        self.scanner_controller.connection_error.connect(self._on_connection_error)

        # Segnali dell'interfaccia
        self.scanner_selector.currentIndexChanged.connect(self._on_scanner_selected)
        self.central_tabs.currentChanged.connect(self._on_tab_changed)

    def _load_settings(self):
        """Carica le impostazioni dell'applicazione."""
        settings = QSettings()

        # Carica la geometria della finestra
        geometry = settings.value("mainwindow/geometry")
        if geometry:
            self.restoreGeometry(geometry)
        else:
            # Imposta la dimensione predefinita
            self.resize(1280, 800)

        # Carica lo stato della finestra
        state = settings.value("mainwindow/state")
        if state:
            self.restoreState(state)

    def _save_settings(self):
        """Salva le impostazioni dell'applicazione."""
        settings = QSettings()

        # Salva la geometria della finestra
        settings.setValue("mainwindow/geometry", self.saveGeometry())

        # Salva lo stato della finestra
        settings.setValue("mainwindow/state", self.saveState())

    def closeEvent(self, event):
        """Gestisce l'evento di chiusura della finestra."""
        # Salva le impostazioni
        self._save_settings()

        # Ferma la scoperta degli scanner
        self.scanner_controller.stop_discovery()

        # Disconnetti tutti gli scanner
        self._disconnect_all()

        # Accetta l'evento di chiusura
        event.accept()

    @Slot()
    def _update_scanner_list(self):
        """Aggiorna la lista degli scanner disponibili."""
        # Memorizza lo scanner selezionato corrente
        current_device_id = None
        if self.scanner_selector.currentIndex() >= 0:
            current_device_id = self.scanner_selector.currentData()

        # Blocca i segnali per evitare attivazioni durante l'aggiornamento
        self.scanner_selector.blockSignals(True)

        # Svuota la lista
        self.scanner_selector.clear()

        # Aggiungi gli scanner disponibili
        scanners = self.scanner_controller.scanners
        if scanners:
            for scanner in scanners:
                # Ottieni lo stato della connessione
                is_connected = scanner.status in (ScannerStatus.CONNECTED, ScannerStatus.STREAMING)

                # Aggiungi lo scanner al menu a tendina
                status_text = " (Connesso)" if is_connected else ""
                self.scanner_selector.addItem(f"{scanner.name}{status_text}", scanner.device_id)

            # Riseleziona lo scanner precedente se ancora disponibile
            if current_device_id:
                index = self.scanner_selector.findData(current_device_id)
                if index >= 0:
                    self.scanner_selector.setCurrentIndex(index)

            # Abilita il selettore
            self.scanner_selector.setEnabled(True)

            # Abilita il pulsante di connessione se c'è uno scanner selezionato
            self.action_toggle_connection.setEnabled(True)
        else:
            # Nessuno scanner disponibile
            self.scanner_selector.addItem("Nessuno scanner disponibile", None)
            self.scanner_selector.setEnabled(False)
            self.action_toggle_connection.setEnabled(False)

        # Ripristina i segnali
        self.scanner_selector.blockSignals(False)

        # Aggiorna l'interfaccia in base allo scanner selezionato
        self._update_ui_for_selected_scanner()

    @Slot(Scanner)
    def _on_scanner_connected(self, scanner: Scanner):
        """Gestisce l'evento di connessione a uno scanner."""
        # Aggiorna la lista degli scanner
        self._update_scanner_list()

        # Aggiorna lo stato della connessione
        self.connection_status_label.setText(f"Connesso a {scanner.name}")

        # Abilita le schede che richiedono una connessione
        self.central_tabs.setTabEnabled(self.TabIndex.STREAMING.value, True)
        self.central_tabs.setTabEnabled(self.TabIndex.CONFIG.value, True)

        # Cambia il testo del pulsante di connessione
        self.action_toggle_connection.setText("Disconnetti")

        # Abilita il pulsante di streaming
        self.action_toggle_streaming.setEnabled(True)

        # Passa alla scheda di streaming
        self.central_tabs.setCurrentIndex(self.TabIndex.STREAMING.value)

    @Slot(Scanner)
    def _on_scanner_disconnected(self, scanner: Scanner):
        """Gestisce l'evento di disconnessione da uno scanner."""
        # Aggiorna la lista degli scanner
        self._update_scanner_list()

        # Aggiorna lo stato della connessione
        self.connection_status_label.setText("Non connesso")

        # Disabilita le schede che richiedono una connessione
        self.central_tabs.setTabEnabled(self.TabIndex.STREAMING.value, False)
        self.central_tabs.setTabEnabled(self.TabIndex.CONFIG.value, False)

        # Cambia il testo del pulsante di connessione
        self.action_toggle_connection.setText("Connetti")

        # Disabilita il pulsante di streaming e acquisizione
        self.action_toggle_streaming.setEnabled(False)
        self.action_capture.setEnabled(False)

        # Ferma lo streaming se attivo
        self.streaming_widget.stop_streaming()

        # Passa alla scheda degli scanner
        self.central_tabs.setCurrentIndex(self.TabIndex.SCANNER.value)

    @Slot(str, str)
    def _on_connection_error(self, device_id: str, error: str):
        """Gestisce l'evento di errore di connessione."""
        # Cerca il nome dello scanner
        scanner_name = device_id
        for scanner in self.scanner_controller.scanners:
            if scanner.device_id == device_id:
                scanner_name = scanner.name
                break

        # Mostra un messaggio di errore
        QMessageBox.critical(
            self,
            "Errore di connessione",
            f"Impossibile connettersi a {scanner_name}:\n{error}"
        )

        # Aggiorna l'interfaccia
        self._update_scanner_list()

    @Slot(int)
    def _on_scanner_selected(self, index: int):
        """Gestisce la selezione di uno scanner."""
        # Verifica se c'è uno scanner valido selezionato
        if index < 0:
            return

        # Ottieni l'ID dello scanner selezionato
        device_id = self.scanner_selector.currentData()
        if not device_id:
            return

        # Seleziona lo scanner nel controller
        self.scanner_controller.select_scanner(device_id)

        # Aggiorna l'interfaccia in base allo scanner selezionato
        self._update_ui_for_selected_scanner()

    @Slot(int)
    def _on_tab_changed(self, index: int):
        """Gestisce il cambio di scheda."""
        # Aggiorna l'interfaccia in base alla scheda selezionata
        if index == self.TabIndex.STREAMING.value:
            # Scheda di streaming
            pass
        elif index == self.TabIndex.CONFIG.value:
            # Scheda di configurazione
            pass

    @Slot()
    def _toggle_discovery(self):
        """Attiva/disattiva la scoperta degli scanner."""
        if self.action_toggle_discovery.text() == "Ferma ricerca":
            # Ferma la scoperta
            self.scanner_controller.stop_discovery()
            self.action_toggle_discovery.setText("Avvia ricerca")
            self.status_bar.showMessage("Ricerca scanner fermata", 3000)
        else:
            # Avvia la scoperta
            self.scanner_controller.start_discovery()
            self.action_toggle_discovery.setText("Ferma ricerca")
            self.status_bar.showMessage("Ricerca scanner avviata", 3000)

    @Slot()
    def _toggle_connection(self):
        """Connette/disconnette lo scanner selezionato."""
        # Verifica se c'è uno scanner selezionato
        if self.scanner_selector.currentIndex() < 0:
            return

        # Ottieni l'ID dello scanner selezionato
        device_id = self.scanner_selector.currentData()
        if not device_id:
            return

        # Verifica lo stato corrente
        if self.action_toggle_connection.text() == "Connetti":
            # Connettiti allo scanner
            self.scanner_controller.connect_to_scanner(device_id)
            self.status_bar.showMessage(f"Connessione in corso...", 3000)
        else:
            # Disconnettiti dallo scanner
            self.scanner_controller.disconnect_from_scanner(device_id)
            self.status_bar.showMessage(f"Disconnessione in corso...", 3000)

    @Slot()
    def _toggle_streaming(self):
        """Avvia/ferma lo streaming video."""
        # Verifica se c'è uno scanner connesso
        selected_scanner = self.scanner_controller.selected_scanner
        if not selected_scanner or not self.scanner_controller.is_connected(selected_scanner.device_id):
            return

        # Avvia/ferma lo streaming
        if self.action_toggle_streaming.text() == "Avvia streaming":
            # Avvia lo streaming
            success = self.streaming_widget.start_streaming(selected_scanner)
            if success:
                self.action_toggle_streaming.setText("Ferma streaming")
                self.action_capture.setEnabled(True)
                self.status_bar.showMessage("Streaming avviato", 3000)
        else:
            # Ferma lo streaming
            self.streaming_widget.stop_streaming()
            self.action_toggle_streaming.setText("Avvia streaming")
            self.action_capture.setEnabled(False)
            self.status_bar.showMessage("Streaming fermato", 3000)

    @Slot()
    def _capture_frame(self):
        """Acquisisce un frame dallo streaming."""
        # Verifica se lo streaming è attivo
        if not self.streaming_widget.is_streaming():
            return

        # Acquisisce il frame
        success = self.streaming_widget.capture_frame()
        if success:
            self.status_bar.showMessage("Frame acquisito", 3000)

    def _disconnect_all(self):
        """Disconnette tutti gli scanner connessi."""
        for scanner in self.scanner_controller.scanners:
            if self.scanner_controller.is_connected(scanner.device_id):
                self.scanner_controller.disconnect_from_scanner(scanner.device_id)

    def _update_ui_for_selected_scanner(self):
        """Aggiorna l'interfaccia in base allo scanner selezionato."""
        # Ottieni lo scanner selezionato
        selected_scanner = self.scanner_controller.selected_scanner

        # Se non c'è uno scanner selezionato o il menu a tendina è vuoto, esci
        if not selected_scanner or self.scanner_selector.count() == 0:
            self.action_toggle_connection.setText("Connetti")
            self.action_toggle_connection.setEnabled(False)
            return

        # Aggiorna il pulsante di connessione
        is_connected = selected_scanner.status in (ScannerStatus.CONNECTED, ScannerStatus.STREAMING)
        self.action_toggle_connection.setText("Disconnetti" if is_connected else "Connetti")
        self.action_toggle_connection.setEnabled(True)

        # Aggiorna i pulsanti di streaming e acquisizione
        is_streaming = selected_scanner.status == ScannerStatus.STREAMING
        self.action_toggle_streaming.setText("Ferma streaming" if is_streaming else "Avvia streaming")
        self.action_toggle_streaming.setEnabled(is_connected)
        self.action_capture.setEnabled(is_streaming)

    def _show_about_dialog(self):
        """Mostra la finestra di dialogo Informazioni su."""
        QMessageBox.about(
            self,
            "Informazioni su UnLook",
            "UnLook Scanner Client\n"
            "Versione 1.0.0\n\n"
            "© 2025 SupernovaIndustries\n"
            "Un sistema di scansione 3D open source e modulare\n"
            "Licenza MIT"
        )