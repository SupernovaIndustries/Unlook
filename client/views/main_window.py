#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Finestra principale dell'applicazione UnLook Client.
Versione migliorata con supporto configurazione integrato,
correzione del bug di disconnessione e autopair.
"""

import logging
import time  # Aggiunto l'import mancante
from enum import Enum
from typing import Optional, List
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QStatusBar, QToolBar, QDockWidget, QSplitter, QFrame,
    QTabWidget, QMessageBox, QMenu, QFileDialog, QDialog, QApplication, QProgressDialog,
)
from PySide6.QtCore import *
from PySide6.QtGui import *

from client.controllers.scanner_controller import ScannerController
from client.models.scanner_model import Scanner, ScannerStatus
from client.views.scanner_view import ScannerDiscoveryWidget

logger = logging.getLogger(__name__)


class AppSettingsDialog(QDialog):
    """
    Dialog per le impostazioni dell'applicazione.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Impostazioni Applicazione")
        self.setMinimumWidth(500)

        layout = QVBoxLayout(self)

        # Timer per keepalive globale
        self._global_keepalive_timer = QTimer(self)
        self._global_keepalive_timer.timeout.connect(self._send_global_keepalive)
        self._global_keepalive_timer.start(2000)  # Invia un keepalive ogni 2 secondi

        # Creiamo un'istanza del widget di configurazione dell'applicazione
        from client.models.config_model import ConfigManager
        from client.controllers.config_controller import ConfigController

        config_manager = ConfigManager()
        config_controller = ConfigController(config_manager)

        # Importa qui per evitare importazioni circolari
        from client.views.config_view import ApplicationConfigWidget
        self.app_config_widget = ApplicationConfigWidget(config_controller)
        layout.addWidget(self.app_config_widget)

        # Pulsanti di chiusura
        button_layout = QHBoxLayout()
        ok_button = QPushButton("OK")
        ok_button.clicked.connect(self.accept)
        button_layout.addStretch(1)
        button_layout.addWidget(ok_button)

        layout.addLayout(button_layout)


class MainWindow(QMainWindow):
    """
    Finestra principale dell'applicazione UnLook Client.
    Fornisce un'interfaccia integrata per il controllo dello scanner e la visualizzazione
    degli stream video.
    """

    class TabIndex(Enum):
        """Indici delle schede nella finestra principale."""
        SCANNER = 0
        SCANNING = 1
        CAMERA_CONFIG = 2


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

        # Configura il timer per l'autopair ritardato
        # (dopo che la scoperta ha avuto tempo di trovare gli scanner)
        self._autopair_timer = QTimer(self)
        self._autopair_timer.setSingleShot(True)
        self._autopair_timer.timeout.connect(self._attempt_autopair)
        self._autopair_timer.start(2000)  # 2 secondi dopo l'avvio

        # Timer per la sincronizzazione periodica degli stati
        self._sync_state_timer = QTimer(self)
        self._sync_state_timer.timeout.connect(self._periodic_state_sync)
        self._sync_state_timer.start(5000)  # Sincronizza ogni 5 secondi

        logger.info("Interfaccia utente principale inizializzata")
        self._global_keepalive_timer = QTimer(self)
        self._global_keepalive_timer.timeout.connect(self._send_global_keepalive)
        self._global_keepalive_timer.start(2000)  # Invia un keepalive ogni 2 secondi

    def _periodic_state_sync(self):
        """
        Esegue la sincronizzazione periodica degli stati degli scanner.
        Questa funzione viene chiamata periodicamente per mantenere coerenza
        tra i diversi componenti dell'applicazione.
        """
        try:
            self.scanner_controller.synchronize_scanner_states()

            # Aggiorna anche lo stato nelle varie schede
            current_tab = self.central_tabs.currentIndex()

            # Aggiorna la scheda corrente in modo specifico
            if current_tab == self.TabIndex.SCANNING.value and hasattr(self, 'scanning_widget'):
                # Se siamo nella scheda scansione, aggiorna lo stato dello scanner
                if hasattr(self.scanning_widget, 'refresh_scanner_state'):
                    self.scanning_widget.refresh_scanner_state()

        except Exception as e:
            logger.error(f"Errore nella sincronizzazione periodica degli stati: {e}")

    def _send_global_keepalive(self):
        """
        Invia un ping globale al server se c'è uno scanner connesso.
        Questo mantiene viva la connessione indipendentemente dalla tab attiva.
        """
        if self.scanner_controller and self.scanner_controller.selected_scanner:
            scanner = self.scanner_controller.selected_scanner
            try:
                # Verifica lo stato di connessione prima di inviare
                is_connected = self.scanner_controller.is_connected(scanner.device_id)

                if is_connected:
                    import socket
                    # Ottieni l'IP locale
                    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    s.connect(("8.8.8.8", 80))
                    local_ip = s.getsockname()[0]
                    s.close()

                    # Invia il ping con l'IP del client
                    self.scanner_controller.send_command(
                        scanner.device_id,
                        "PING",
                        {
                            "timestamp": time.time(),
                            "client_ip": local_ip
                        }
                    )
                    logger.debug(f"Global keepalive inviato a {scanner.name}")
            except Exception as e:
                logger.error(f"Errore nell'invio del keepalive globale: {e}")
    def _attempt_autopair(self):
        """
        Tenta di connettersi automaticamente all'ultimo scanner utilizzato.
        """
        try:
            # Controlla se ci sono scanner disponibili prima di tentare l'autopair
            if not self.scanner_controller.scanners:
                logger.info("Nessuno scanner disponibile per l'autopair, continuo a cercare...")
                # Continua a cercare scanner e riprova più tardi
                self._autopair_timer.start(3000)  # Riprova tra 3 secondi
                return

            logger.info("Tentativo di autoconnessione all'ultimo scanner...")
            success = self.scanner_controller.try_autoconnect_last_scanner()

            if success:
                self.status_bar.showMessage("Connessione all'ultimo scanner utilizzato...", 3000)
            else:
                logger.info("Autoconnessione fallita o non possibile, nessun problema")

        except Exception as e:
            logger.error(f"Errore durante l'autoconnessione: {str(e)}")

    def _setup_ui(self):
        """Configura l'interfaccia utente principale."""
        # Widget centrale con layout a tab
        self.central_tabs = QTabWidget()
        self.setCentralWidget(self.central_tabs)

        # Aggiorna la classe TabIndex per riflettere la nuova struttura delle schede
        class TabIndex(Enum):
            """Indici delle schede nella finestra principale."""
            SCANNER = 0
            CAMERA_CONFIG = 1
            SCANNING = 2  # Scansione 3D ora è la terza scheda

        # Sostituisce l'enum originale con quello aggiornato
        self.TabIndex = TabIndex

        # Crea i widget delle schede
        self.scanner_widget = ScannerDiscoveryWidget(self.scanner_controller)

        # Import la classe CameraConfigView
        from client.views.camera_config_view import CameraConfigView
        self.camera_config_widget = CameraConfigView(self.scanner_controller)

        # Widget di scansione
        from client.views.scan_view import ScanView
        self.scanning_widget = ScanView(self.scanner_controller)

        # Inizializza il receiver di stream (precedentemente gestito da StreamingView)
        self._initialize_stream_receiver()

        # Aggiungi le schede
        self.central_tabs.addTab(self.scanner_widget, "Scanner")
        self.central_tabs.addTab(self.camera_config_widget, "Configurazione Camere")
        self.central_tabs.addTab(self.scanning_widget, "Scansione 3D")

        # Disabilita le schede che richiedono una connessione attiva
        self.central_tabs.setTabEnabled(self.TabIndex.CAMERA_CONFIG.value, False)
        self.central_tabs.setTabEnabled(self.TabIndex.SCANNING.value, False)

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

    def _setup_menu(self):
        """Configura il menu dell'applicazione."""
        # Menu File
        file_menu = self.menuBar().addMenu("&File")

        # Azione Impostazioni Applicazione
        settings_action = QAction("&Impostazioni applicazione", self)
        settings_action.triggered.connect(self._show_app_settings)
        settings_action.setShortcut("Ctrl+,")
        file_menu.addAction(settings_action)

        # Azione Imposta directory output
        set_output_dir_action = QAction("&Imposta directory output", self)
        set_output_dir_action.triggered.connect(self._set_output_directory)
        file_menu.addAction(set_output_dir_action)

        file_menu.addSeparator()

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

    def closeEvent(self, event: QCloseEvent):
        """
        Gestisce l'evento di chiusura della finestra.
        Versione completamente rivista per garantire una chiusura pulita e prevenire crash.
        """
        logger.info("Chiusura dell'applicazione in corso...")

        # Mostra un dialog di progresso per evitare che l'applicazione sembri bloccata
        progress = QProgressDialog("Chiusura in corso...", None, 0, 100, self)
        progress.setWindowTitle("Chiusura applicazione")
        progress.setWindowModality(Qt.WindowModal)
        progress.setAutoClose(True)
        progress.setMinimumDuration(300)  # Mostra solo se la chiusura richiede più di 300ms
        progress.setCancelButton(None)  # Rimuove il pulsante di annullamento
        progress.setValue(5)
        progress.show()

        try:
            # Processa eventi per mostrare la dialog
            QApplication.processEvents()

            # Salva le impostazioni
            self._save_settings()
            progress.setValue(10)
            QApplication.processEvents()

            # Ferma esplicitamente lo streaming se attivo
            if hasattr(self, 'streaming_widget') and self.streaming_widget:
                try:
                    if hasattr(self.streaming_widget, 'is_streaming') and self.streaming_widget.is_streaming():
                        progress.setLabelText("Arresto dello streaming in corso...")
                        logger.info("Arresto dello streaming...")
                        self.streaming_widget.stop_streaming()
                        # Pausa per permettere allo streaming di fermarsi
                        QApplication.processEvents()
                        time.sleep(0.3)
                except Exception as e:
                    logger.error(f"Errore nell'arresto dello streaming: {e}")

            progress.setValue(30)
            QApplication.processEvents()

            # Ferma la scoperta degli scanner
            progress.setLabelText("Arresto della scoperta scanner...")
            self.scanner_controller.stop_discovery()
            progress.setValue(40)
            QApplication.processEvents()

            # Controlla se c'è una scansione in corso e fermala
            if hasattr(self, 'scanning_widget') and self.scanning_widget:
                try:
                    # Ferma la scansione se attiva
                    if hasattr(self.scanning_widget, 'is_scanning') and self.scanning_widget.is_scanning:
                        logger.info("Arresto della scansione in corso...")
                        progress.setLabelText("Arresto della scansione in corso...")
                        self.scanning_widget._stop_scan()
                        # Attendi un po' per consentire l'arresto della scansione
                        QApplication.processEvents()
                        time.sleep(0.3)
                except Exception as e:
                    logger.error(f"Errore nell'arresto della scansione: {e}")

            progress.setValue(50)
            QApplication.processEvents()

            # Invia un comando di arresto streaming esplicito se connesso
            selected_scanner = self.scanner_controller.selected_scanner
            if selected_scanner:
                try:
                    logger.info(f"Invio comando STOP_STREAM a {selected_scanner.name}...")
                    progress.setLabelText(f"Invio comandi di arresto a {selected_scanner.name}...")

                    # Invia un PING prima come verifica della connettività
                    ping_result = self.scanner_controller.send_command(
                        selected_scanner.device_id,
                        "PING",
                        {"timestamp": time.time()}
                    )

                    if ping_result:
                        # Invia esplicitamente il comando STOP_STREAM
                        self.scanner_controller.send_command(
                            selected_scanner.device_id,
                            "STOP_STREAM"
                        )
                        # Breve pausa per assicurarsi che il comando venga processato
                        QApplication.processEvents()
                        time.sleep(0.2)
                except Exception as e:
                    logger.error(f"Errore nell'invio del comando STOP_STREAM: {e}")

            progress.setValue(70)
            QApplication.processEvents()

            # Disconnetti tutti gli scanner in modo sicuro
            logger.info("Disconnessione da tutti gli scanner...")
            progress.setLabelText("Disconnessione da tutti gli scanner...")
            self._disconnect_all_safely()

            progress.setValue(80)
            QApplication.processEvents()

            # Arresta eventuali timer attivi
            try:
                for attr_name in dir(self):
                    attr = getattr(self, attr_name)
                    if isinstance(attr, QTimer) and attr.isActive():
                        attr.stop()
            except Exception as e:
                logger.error(f"Errore nell'arresto dei timer: {e}")

            progress.setValue(90)
            QApplication.processEvents()

            # Rilascia esplicitamente le risorse di rete
            try:
                # Chiudi eventuali socket ZMQ aperti
                from client.network.connection_manager import ConnectionManager
                connection_manager = ConnectionManager()

                # Ottieni un elenco di device_id prima della modifica del dizionario
                device_ids = list(connection_manager._connections.keys())

                # Esegui la disconnessione di tutti i device
                for device_id in device_ids:
                    try:
                        connection_manager.disconnect(device_id)
                    except Exception as e:
                        logger.error(f"Errore nella disconnessione di {device_id}: {e}")
            except Exception as e:
                logger.error(f"Errore nel rilascio delle risorse di rete: {e}")

            # Attendi un momento per permettere alle disconnessioni di completarsi
            progress.setLabelText("Finalizzazione chiusura...")
            QApplication.processEvents()
            time.sleep(0.5)

            progress.setValue(100)
            QApplication.processEvents()

        except Exception as e:
            logger.error(f"Errore durante la chiusura dell'applicazione: {e}")
        finally:
            # Nasconde e distrugge la dialog di progresso
            progress.close()
            progress.deleteLater()

        # Forza il rilascio di alcune risorse critiche
        import gc
        gc.collect()

        # Accetta l'evento di chiusura
        logger.info("Applicazione chiusa con successo")
        event.accept()

    def _disconnect_all_safely(self):
        """
        Disconnette tutti gli scanner connessi in modo sicuro e robusto.
        Versione migliorata per gestire ogni scanner individualmente e tollerare errori.
        """
        try:
            # Ottieni una copia della lista degli scanner per evitare problemi
            # se la lista viene modificata durante l'iterazione
            scanners = list(self.scanner_controller.scanners)

            for scanner in scanners:
                try:
                    # Prima verifica che lo scanner sia effettivamente connesso
                    if self.scanner_controller.is_connected(scanner.device_id):
                        logger.info(f"Disconnessione da {scanner.name} in corso...")

                        # Prima invia un comando di ping per verificare la connettività
                        ping_result = self.scanner_controller.send_command(
                            scanner.device_id,
                            "PING",
                            {"timestamp": time.time()}
                        )

                        # Se il ping ha successo, procedi con la disconnessione esplicita
                        if ping_result:
                            self.scanner_controller.disconnect_from_scanner(scanner.device_id)
                            # Piccola pausa tra disconnessioni consecutive
                            time.sleep(0.2)
                        else:
                            logger.warning(f"Scanner {scanner.name} non risponde, forzando lo stato disconnesso")
                            # Forza lo stato a disconnesso
                            scanner.status = ScannerStatus.DISCONNECTED

                except Exception as e:
                    # Cattura le eccezioni per singolo scanner, così se uno fallisce
                    # possiamo comunque provare con gli altri
                    logger.error(f"Errore durante la disconnessione da {scanner.name}: {e}")
                    # Forza comunque lo stato a disconnesso
                    scanner.status = ScannerStatus.DISCONNECTED

        except Exception as e:
            logger.error(f"Errore nella disconnessione da tutti gli scanner: {e}")

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

        # Inizializza il receiver di stream se necessario
        if not self._stream_initialized:
            self._setup_stream_receiver(scanner)

        # Abilita le schede che richiedono una connessione
        self.central_tabs.setTabEnabled(self.TabIndex.CAMERA_CONFIG.value, True)
        self.central_tabs.setTabEnabled(self.TabIndex.SCANNING.value, True)

        # Cambia il testo del pulsante di connessione
        self.action_toggle_connection.setText("Disconnetti")

        # Passa alla scheda di scansione
        self.central_tabs.setCurrentIndex(self.TabIndex.SCANNING.value)

        # Aggiorna lo scanner selezionato nelle viste
        self.scanning_widget.update_selected_scanner(scanner)
        self.camera_config_widget.update_selected_scanner(scanner)

    def _setup_stream_receiver(self, scanner):
        """
        Configura il receiver di stream per uno scanner connesso con gestione robusta degli errori.
        """
        try:
            # Prima ferma eventuali receiver esistenti
            if hasattr(self, 'stream_receiver') and self.stream_receiver:
                try:
                    self.stream_receiver.stop()
                    time.sleep(0.5)  # Attendi che si fermi completamente
                    logger.info("Stream receiver esistente fermato")
                except Exception as e:
                    logger.warning(f"Errore nell'arresto del receiver esistente: {e}")

            from client.network.stream_receiver import StreamReceiver

            # Informazioni di connessione
            host = scanner.ip_address
            port = scanner.port + 1  # La porta di streaming è quella di comando + 1

            logger.info(f"Inizializzazione stream receiver da {host}:{port}")

            # Invia comando per fermare qualsiasi streaming esistente
            # PRIMA di inizializzare il nuovo receiver
            try:
                self.scanner_controller.send_command(
                    scanner.device_id,
                    "STOP_STREAM"
                )
                # Attendi la risposta esplicitamente per rispettare REQ/REP
                self.scanner_controller.receive_response(scanner.device_id)
                time.sleep(0.5)  # Attendi che lo streaming si fermi
            except Exception as e:
                logger.warning(f"Errore nell'arresto dello streaming esistente: {e}")

            # Crea il receiver
            self.stream_receiver = StreamReceiver(host, port)

            # Ottieni il processore da scanning_widget invece che dall'oggetto MainWindow
            frame_processor = None
            if hasattr(self, 'scanning_widget') and self.scanning_widget:
                if hasattr(self.scanning_widget, 'scan_processor'):
                    frame_processor = self.scanning_widget.scan_processor
                    logger.info("Usando scan_processor da scanning_widget")

            # Configura il receiver con il processore di frame corretto
            if frame_processor and hasattr(self.stream_receiver, 'set_frame_processor'):
                self.stream_receiver.set_frame_processor(frame_processor)
                logger.info("Frame processor configurato nel stream receiver")

            # Avvia il receiver
            self.stream_receiver.start()
            self._stream_initialized = True

            # Invia comando START_STREAM per avviare lo streaming
            self._start_streaming(scanner.device_id)

            # Aggiorna il riferimento nel ScanView
            if hasattr(self, 'scanning_widget') and self.scanning_widget:
                self.scanning_widget._connect_to_stream()

            return True

        except Exception as e:
            logger.error(f"Errore nell'inizializzazione dello stream receiver: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False

    def _start_streaming(self, device_id):
        """
        Avvia lo streaming video con gestione robusta degli errori e retry.

        Args:
            device_id: ID dello scanner

        Returns:
            bool: True se lo streaming è stato avviato, False altrimenti
        """
        logger.info(f"Avvio streaming per scanner {device_id}")

        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                # Attendi un po' tra i tentativi (tranne il primo)
                if attempt > 0:
                    time.sleep(1.0)
                    logger.info(f"Tentativo {attempt + 1}/{max_attempts} di avvio streaming...")

                # Invia comando per avviare lo streaming con configurazione completa
                command_success = self.scanner_controller.send_command(
                    device_id,
                    "START_STREAM",
                    {
                        "dual_camera": True,  # Richiedi entrambe le camere
                        "quality": 90,  # Buona qualità immagine
                        "target_fps": 30,  # Frame rate target
                        "low_latency": True  # Priorità alla latenza
                    },
                    timeout=5.0  # Timeout ragionevole
                )

                if not command_success:
                    logger.warning(f"Errore nell'invio del comando START_STREAM (tentativo {attempt + 1})")
                    continue

                # Attendi la risposta per completare il ciclo REQ/REP
                response = self.scanner_controller.receive_response(device_id, 5.0)

                # Verifica la risposta
                if response and response.get("status") == "ok":
                    logger.info(f"Streaming avviato con successo: {response}")
                    return True
                else:
                    logger.warning(f"Risposta non valida al comando START_STREAM: {response}")

            except Exception as e:
                logger.error(f"Errore nell'avvio dello streaming (tentativo {attempt + 1}): {e}")

        logger.error(f"Impossibile avviare lo streaming dopo {max_attempts} tentativi")
        return False

    def _send_global_keepalive(self):
        """
        Invia un ping globale al server se c'è uno scanner connesso.
        Questo mantiene viva la connessione indipendentemente dalla tab attiva.
        """
        if self.scanner_controller and self.scanner_controller.selected_scanner:
            scanner = self.scanner_controller.selected_scanner
            try:
                # Verifica lo stato di connessione prima di inviare
                is_connected = self.scanner_controller.is_connected(scanner.device_id)

                if is_connected:
                    import socket
                    # Ottieni l'IP locale
                    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    s.connect(("8.8.8.8", 80))
                    local_ip = s.getsockname()[0]
                    s.close()

                    # Invia il ping con l'IP del client
                    self.scanner_controller.send_command(
                        scanner.device_id,
                        "PING",
                        {
                            "timestamp": time.time(),
                            "client_ip": local_ip
                        }
                    )
                    logger.debug(f"Global keepalive inviato a {scanner.name}")
            except Exception as e:
                logger.error(f"Errore nell'invio del keepalive globale: {e}")
    def _connect_to_stream(self):
        """Collega il widget agli stream delle camere."""
        if self._stream_connected:
            logger.debug("Stream già connesso, nessuna azione necessaria")
            return True

        try:
            # Cerca il main window
            main_window = self.window()
            logger.info(f"MainWindow trovata: {main_window is not None}")

            # Verifica se stream_receiver è presente direttamente in MainWindow
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
                else:
                    logger.error("Segnale frame_received non trovato nel receiver")
            else:
                logger.warning("Stream receiver non trovato in MainWindow")

                # Tentativo alternativo di trovare il receiver dal controller
                if hasattr(self, 'scanner_controller') and self.scanner_controller:
                    if hasattr(self.scanner_controller, 'get_stream_receiver'):
                        receiver = self.scanner_controller.get_stream_receiver()
                        if receiver:
                            logger.info("Receiver trovato direttamente dal controller")

                            # Collega il segnale e configura come sopra...
                            try:
                                receiver.frame_received.disconnect(self._on_frame_received)
                            except:
                                pass

                            receiver.frame_received.connect(self._on_frame_received)

                            if hasattr(receiver, 'set_frame_processor'):
                                receiver.set_frame_processor(self.scan_processor)

                            if hasattr(receiver, 'enable_direct_routing'):
                                receiver.enable_direct_routing(True)

                            self._stream_connected = True
                            return True

                logger.error("Non è stato possibile trovare un stream receiver valido")
                return False

        except Exception as e:
            logger.error(f"Errore nella connessione agli stream: {e}")
            import traceback
            logger.error(f"Traceback completo: {traceback.format_exc()}")

        return False
    @Slot(Scanner)
    def _on_scanner_disconnected(self, scanner: Scanner):
        """
        Gestisce l'evento di disconnessione da uno scanner.
        """
        logger.info(f"Disconnessione rilevata da {scanner.name}")

        # Aggiorna la lista degli scanner
        self._update_scanner_list()

        # Aggiorna lo stato della connessione
        self.connection_status_label.setText("Non connesso")

        # Ferma lo stream receiver se è inizializzato
        if self._stream_initialized and self.stream_receiver:
            try:
                # Invia comando di stop
                self.scanner_controller.send_command(
                    scanner.device_id,
                    "STOP_STREAM"
                )

                # Ferma il receiver
                self.stream_receiver.stop()
                logger.info("Stream receiver fermato")
            except Exception as e:
                logger.error(f"Errore nell'arresto dello stream receiver: {e}")

        # Reset dello stato
        self._stream_initialized = False

        # Disabilita le schede che richiedono una connessione attiva
        self.central_tabs.setTabEnabled(self.TabIndex.CAMERA_CONFIG.value, False)
        self.central_tabs.setTabEnabled(self.TabIndex.SCANNING.value, False)

        # Cambia il testo del pulsante di connessione
        self.action_toggle_connection.setText("Connetti")

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
        """
        Gestisce la selezione di uno scanner.
        Versione migliorata con verifica di selezione valida e aggiornamento
        di tutti i componenti interessati.
        """
        # Verifica se c'è uno scanner valido selezionato
        if index < 0:
            logger.debug("Nessuno scanner selezionato")
            return

        # Ottieni l'ID dello scanner selezionato
        device_id = self.scanner_selector.currentData()
        if not device_id:
            logger.debug("ID scanner nullo")
            return

        # Seleziona lo scanner nel controller
        selection_success = self.scanner_controller.select_scanner(device_id)

        if not selection_success:
            logger.warning(f"Impossibile selezionare lo scanner con ID {device_id}")
            return

        # Ottieni il riferimento allo scanner selezionato
        selected_scanner = self.scanner_controller.selected_scanner

        if not selected_scanner:
            logger.warning("selected_scanner è None dopo la selezione")
            return

        # Aggiorna lo scanner selezionato in tutte le viste attive
        if hasattr(self, 'scanning_widget') and self.scanning_widget:
            self.scanning_widget.update_selected_scanner(selected_scanner)

        if hasattr(self, 'streaming_widget') and self.streaming_widget:
            # Assicurati che il parametro scanner_controller sia sempre impostato
            self.streaming_widget.scanner_controller = self.scanner_controller
            self.streaming_widget.selected_scanner = selected_scanner

        # Aggiorna l'interfaccia in base allo scanner selezionato
        self._update_ui_for_selected_scanner()

        # Aggiorna lo stato della connessione visualizzato
        is_connected = self.scanner_controller.is_connected(device_id)
        status_text = f"Connesso a {selected_scanner.name}" if is_connected else "Non connesso"
        self.connection_status_label.setText(status_text)

        logger.info(f"Scanner selezionato: {selected_scanner.name}, connesso: {is_connected}")

    @Slot(int)
    def _on_tab_changed(self, index: int):
        """Gestisce il cambio di scheda."""
        # Ottieni il riferimento dello scanner selezionato
        selected_scanner = self.scanner_controller.selected_scanner

        # Se non c'è uno scanner connesso, non fare nulla di speciale
        if not selected_scanner or selected_scanner.status not in (ScannerStatus.CONNECTED, ScannerStatus.STREAMING):
            return

        # Gestisci il cambio alla scheda di scansione
        if index == self.TabIndex.SCANNING.value:
            # Aggiorna lo stato dello scanner nella tab di scansione
            if hasattr(self, 'scanning_widget') and self.scanning_widget:
                self.scanning_widget.update_selected_scanner(selected_scanner)
                self.scanning_widget.refresh_scanner_state()

        # Gestisci il cambio alla scheda di configurazione camera
        elif index == self.TabIndex.CAMERA_CONFIG.value:
            # Aggiorna lo scanner selezionato nella configurazione camera
            if hasattr(self, 'camera_config_widget') and self.camera_config_widget:
                if hasattr(self.camera_config_widget, 'update_selected_scanner'):
                    self.camera_config_widget.update_selected_scanner(selected_scanner)

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
        """Connette/disconnette lo scanner selezionato con gestione robusta degli errori."""
        # Verifica se c'è uno scanner selezionato
        if self.scanner_selector.currentIndex() < 0:
            return

        # Ottieni l'ID dello scanner selezionato
        device_id = self.scanner_selector.currentData()
        if not device_id:
            return

        try:
            # Verifica lo stato corrente
            if self.action_toggle_connection.text() == "Connetti":
                # Connettiti allo scanner
                self.scanner_controller.connect_to_scanner(device_id)
                self.status_bar.showMessage(f"Connessione in corso...", 3000)
            else:
                # Disabilita temporaneamente il pulsante per evitare clic multipli
                self.action_toggle_connection.setEnabled(False)

                # Disabilita anche il selettore scanner durante la disconnessione
                self.scanner_selector.setEnabled(False)

                # Mostra messaggio e aggiorna status bar
                self.status_bar.showMessage(f"Disconnessione in corso...", 3000)

                # Piccola pausa per aggiornare l'UI prima di operazioni potenzialmente bloccanti
                QApplication.processEvents()

                # Disconnettiti dallo scanner
                success = self.scanner_controller.disconnect_from_scanner(device_id)

                # Riattiva il pulsante e il selettore
                self.action_toggle_connection.setEnabled(True)
                self.scanner_selector.setEnabled(True)

                # Mostra un messaggio appropriato
                if success:
                    self.status_bar.showMessage(f"Disconnessione completata", 3000)
                else:
                    self.status_bar.showMessage(f"Errore nella disconnessione", 3000)

                # Aggiorna la lista degli scanner
                self._update_scanner_list()
        except Exception as e:
            logger.error(f"Errore durante la connessione/disconnessione: {e}")
            self.status_bar.showMessage(f"Errore: {str(e)}", 5000)

            # Assicurati di riattivare i controlli
            self.action_toggle_connection.setEnabled(True)
            self.scanner_selector.setEnabled(True)

    def _disconnect_all(self):
        """
        Disconnette tutti gli scanner connessi in modo sicuro.
        Versione migliorata con gestione errori.
        """
        try:
            for scanner in self.scanner_controller.scanners:
                if self.scanner_controller.is_connected(scanner.device_id):
                    try:
                        logger.info(f"Disconnessione da {scanner.name} in corso...")
                        self.scanner_controller.disconnect_from_scanner(scanner.device_id)
                    except Exception as e:
                        # Catturo le eccezioni per singolo scanner, così se uno fallisce
                        # possiamo comunque provare con gli altri
                        logger.error(f"Errore durante la disconnessione da {scanner.name}: {e}")
        except Exception as e:
            logger.error(f"Errore nella disconnessione da tutti gli scanner: {e}")

    def _initialize_stream_receiver(self):
        """
        Inizializza la variabile stream_receiver ma delega la gestione effettiva a ScanView.
        Implementa la separazione di responsabilità tra MainWindow e ScanView.
        """
        # Memorizza solo il riferimento, non inizializzare
        self.stream_receiver = None
        self._stream_initialized = False

        logger.info("Stream receiver sarà inizializzato da ScanView alla connessione con uno scanner")
    def _update_ui_for_selected_scanner(self):
        """Aggiorna l'interfaccia in base allo scanner selezionato."""
        # Ottieni lo scanner selezionato
        selected_scanner = self.scanner_controller.selected_scanner

        # Se non c'è uno scanner selezionato o il menu a tendina è vuoto, esci
        if not selected_scanner or self.scanner_selector.count() == 0:
            self.action_toggle_connection.setText("Connetti")
            self.action_toggle_connection.setEnabled(False)
            return

        # Aggiorna lo scanner selezionato nella vista di scansione
        if selected_scanner:
            self.scanning_widget.update_selected_scanner(selected_scanner)

        # Aggiorna il pulsante di connessione
        is_connected = selected_scanner.status in (ScannerStatus.CONNECTED, ScannerStatus.STREAMING)
        self.action_toggle_connection.setText("Disconnetti" if is_connected else "Connetti")
        self.action_toggle_connection.setEnabled(True)

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

    def _show_app_settings(self):
        """Mostra la finestra delle impostazioni dell'applicazione."""
        # Apre il dialog delle impostazioni
        dialog = AppSettingsDialog(self)
        dialog.exec()

    def _set_output_directory(self):
        """Imposta la directory di output per i file salvati."""
        # Apri un selettore di directory
        directory = QFileDialog.getExistingDirectory(
            self,
            "Seleziona directory di output",
            str(Path.home()),
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks
        )

        if directory:
            # Qui implementiamo il salvataggio della configurazione
            try:
                from client.models.config_model import ConfigManager
                config_manager = ConfigManager()
                app_config = config_manager.get_app_config()
                app_config.save_path = directory
                config_manager.update_app_config(app_config)
                config_manager.save_config()

                QMessageBox.information(
                    self,
                    "Directory Impostata",
                    f"Directory di output impostata a:\n{directory}"
                )
            except Exception as e:
                QMessageBox.warning(
                    self,
                    "Errore",
                    f"Errore nell'impostazione della directory:\n{str(e)}"
                )