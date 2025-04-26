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
    QTabWidget, QMessageBox, QMenu, QFileDialog, QDialog, QApplication
)
from PySide6.QtCore import Qt, Slot, QSettings, QSize, QPoint, QTimer, QEvent, QCoreApplication
from PySide6.QtGui import QIcon, QPixmap, QFont, QAction, QCloseEvent

from client.controllers.scanner_controller import ScannerController
from client.models.scanner_model import Scanner, ScannerStatus
from client.views.scanner_view import ScannerDiscoveryWidget
from client.views.streaming_view import DualStreamView
from client.views.scan_view import ScanView

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
        STREAMING = 1
        SCANNING = 2

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

        logger.info("Interfaccia utente principale inizializzata")
        self._global_keepalive_timer = QTimer(self)
        self._global_keepalive_timer.timeout.connect(self._send_global_keepalive)
        self._global_keepalive_timer.start(2000)  # Invia un keepalive ogni 2 secondi

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

        # Crea i widget delle schede
        self.scanner_widget = ScannerDiscoveryWidget(self.scanner_controller)
        self.streaming_widget = DualStreamView()
        self.scanning_widget = ScanView(self.scanner_controller)

        # Aggiungi le schede
        self.central_tabs.addTab(self.scanner_widget, "Scanner")
        self.central_tabs.addTab(self.streaming_widget, "Streaming")
        self.central_tabs.addTab(self.scanning_widget, "Scansione 3D")  # Nuova scheda

        # Disabilita le schede che richiedono una connessione attiva
        self.central_tabs.setTabEnabled(self.TabIndex.STREAMING.value, False)
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
        Versione migliorata con gestione completa del rilascio delle risorse.
        """
        logger.info("Chiusura dell'applicazione in corso...")

        # Mostra un dialog di progresso durante la chiusura per evitare che l'applicazione sembri bloccata
        from PySide6.QtWidgets import QProgressDialog, QApplication
        progress = QProgressDialog("Chiusura in corso...", "Attendi", 0, 100, self)
        progress.setWindowTitle("Chiusura applicazione")
        progress.setWindowModality(Qt.WindowModal)
        progress.setAutoClose(True)
        progress.setMinimumDuration(500)  # Mostra solo se la chiusura richiede più di 500ms
        progress.setValue(10)

        try:
            # Salva le impostazioni
            self._save_settings()
            progress.setValue(20)

            # Ferma la scoperta degli scanner
            self.scanner_controller.stop_discovery()
            progress.setValue(30)

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
                        time.sleep(0.5)
                except Exception as e:
                    logger.error(f"Errore nell'arresto della scansione: {e}")

            progress.setValue(40)

            # Invia un comando di arresto streaming esplicito se connesso
            selected_scanner = self.scanner_controller.selected_scanner
            if selected_scanner and self.scanner_controller.is_connected(selected_scanner.device_id):
                logger.info(f"Scanner connesso trovato: {selected_scanner.name}")
                progress.setLabelText(f"Disconnessione dallo scanner {selected_scanner.name}...")

                # Importa qui per evitare problemi di importazione circolare
                from client.network.connection_manager import ConnectionManager
                connection_manager = ConnectionManager()

                try:
                    # Ferma lo streaming se attivo
                    if hasattr(self, 'streaming_widget') and self.streaming_widget:
                        logger.info("Arresto dello streaming...")
                        progress.setLabelText("Arresto dello streaming in corso...")
                        self.streaming_widget.stop_streaming()
                        # Piccola pausa per consentire il completamento dell'operazione
                        QApplication.processEvents()
                        time.sleep(0.3)

                    # Invia esplicitamente il comando STOP_STREAM
                    logger.info(f"Invio comando STOP_STREAM a {selected_scanner.name}...")
                    connection_manager.send_message(selected_scanner.device_id, "STOP_STREAM")
                    # Breve pausa per assicurarsi che il comando venga processato
                    QApplication.processEvents()
                    time.sleep(0.3)
                except Exception as e:
                    logger.error(f"Errore nell'invio del comando STOP_STREAM: {e}")

            progress.setValue(60)

            # Disconnetti tutti gli scanner in modo sicuro
            logger.info("Disconnessione da tutti gli scanner...")
            progress.setLabelText("Disconnessione da tutti gli scanner...")
            self._disconnect_all()

            # Arresta eventuali timer attivi
            try:
                if hasattr(self, "connection_timer") and self.connection_timer.isActive():
                    self.connection_timer.stop()

                # Ferma il timer di keepalive se presente in scanner_controller
                if hasattr(self.scanner_controller,
                           "_keepalive_timer") and self.scanner_controller._keepalive_timer.isActive():
                    self.scanner_controller._keepalive_timer.stop()
            except Exception as e:
                logger.error(f"Errore nell'arresto dei timer: {e}")

            progress.setValue(80)

            # Rilascia esplicitamente alcune risorse critiche
            try:
                # Chiudi eventuali socket ZMQ aperti
                from client.network.connection_manager import ConnectionManager
                connection_manager = ConnectionManager()
                # Esegui la disconnessione di tutti i device
                for device_id in list(connection_manager._connections.keys()):
                    connection_manager.disconnect(device_id)
            except Exception as e:
                logger.error(f"Errore nel rilascio delle risorse di rete: {e}")

            # Attendi un momento per permettere alle disconnessioni di completarsi
            progress.setLabelText("Finalizzazione chiusura...")
            QApplication.processEvents()
            time.sleep(0.8)

            progress.setValue(100)
        except Exception as e:
            logger.error(f"Errore durante la chiusura dell'applicazione: {e}")
        finally:
            # Nasconde la dialog di progresso
            progress.close()

        # Forza il rilascio di alcune risorse critiche
        import gc
        gc.collect()

        # Accetta l'evento di chiusura
        logger.info("Applicazione chiusa con successo")
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
        self.central_tabs.setTabEnabled(self.TabIndex.SCANNING.value, True)  # Abilita la scheda di scansione

        # Cambia il testo del pulsante di connessione
        self.action_toggle_connection.setText("Disconnetti")

        # Passa alla scheda di streaming
        self.central_tabs.setCurrentIndex(self.TabIndex.STREAMING.value)

        # Aggiorna lo scanner selezionato nella vista di scansione
        self.scanning_widget.update_selected_scanner(scanner)

    @Slot(Scanner)
    def _on_scanner_disconnected(self, scanner: Scanner):
        """Gestisce l'evento di disconnessione da uno scanner."""
        # Aggiorna la lista degli scanner
        self._update_scanner_list()

        # Aggiorna lo stato della connessione
        self.connection_status_label.setText("Non connesso")

        # Disabilita le schede che richiedono una connessione
        self.central_tabs.setTabEnabled(self.TabIndex.STREAMING.value, False)
        self.central_tabs.setTabEnabled(self.TabIndex.SCANNING.value, False)

        # Cambia il testo del pulsante di connessione
        self.action_toggle_connection.setText("Connetti")

        # Ferma lo streaming se attivo
        if hasattr(self, 'streaming_widget') and self.streaming_widget:
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
            # Verifica se lo streaming è attivo
            selected_scanner = self.scanner_controller.selected_scanner
            if selected_scanner and selected_scanner.status == ScannerStatus.CONNECTED:
                # Se il dispositivo è connesso ma lo streaming non è attivo, avvia lo streaming automaticamente
                if hasattr(self,
                           'streaming_widget') and self.streaming_widget and not self.streaming_widget.is_streaming():
                    self.streaming_widget.start_streaming(selected_scanner)
        elif index == self.TabIndex.SCANNING.value:
            # Aggiorna lo stato dello scanner nella tab di scansione
            if hasattr(self, 'scanning_widget') and self.scanning_widget:
                self.scanning_widget.refresh_scanner_state()

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