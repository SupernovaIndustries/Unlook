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
            if current_tab == self.TabIndex.STREAMING.value and hasattr(self, 'streaming_widget'):
                # Se siamo nella scheda streaming, verifica che lo streaming sia attivo se lo scanner è connesso
                selected_scanner = self.scanner_controller.selected_scanner
                if selected_scanner and selected_scanner.status == ScannerStatus.CONNECTED:
                    if hasattr(self.streaming_widget, 'is_streaming') and not self.streaming_widget.is_streaming():
                        logger.debug("Scheda streaming attiva con scanner connesso ma streaming inattivo")

            elif current_tab == self.TabIndex.SCANNING.value and hasattr(self, 'scanning_widget'):
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
        """
        Gestisce l'evento di disconnessione da uno scanner.
        Versione migliorata che garantisce coerenza tra tutti i componenti
        e ferma esplicitamente lo streaming.
        """
        logger.info(f"Disconnessione rilevata da {scanner.name}")

        # Aggiorna la lista degli scanner
        self._update_scanner_list()

        # Aggiorna lo stato della connessione
        self.connection_status_label.setText("Non connesso")

        # Ferma esplicitamente lo streaming se attivo
        streaming_was_active = False
        if hasattr(self, 'streaming_widget') and self.streaming_widget:
            try:
                if hasattr(self.streaming_widget, 'is_streaming') and self.streaming_widget.is_streaming():
                    logger.info("Arresto dello streaming in seguito a disconnessione")
                    streaming_was_active = True
                    self.streaming_widget.stop_streaming()
            except Exception as e:
                logger.error(f"Errore nell'arresto dello streaming: {e}")

        # Disabilita le schede che richiedono una connessione attiva
        self.central_tabs.setTabEnabled(self.TabIndex.STREAMING.value, False)
        self.central_tabs.setTabEnabled(self.TabIndex.SCANNING.value, False)

        # Cambia il testo del pulsante di connessione
        self.action_toggle_connection.setText("Connetti")

        # Passa alla scheda degli scanner
        if self.central_tabs.currentIndex() in [self.TabIndex.STREAMING.value, self.TabIndex.SCANNING.value]:
            logger.info("Passaggio alla scheda scanner dopo disconnessione")
            self.central_tabs.setCurrentIndex(self.TabIndex.SCANNER.value)

        # Se lo streaming era attivo e c'è stato un problema di comunicazione,
        # mostra un messaggio informativo
        if streaming_was_active and scanner.status == ScannerStatus.ERROR:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(
                self,
                "Connessione persa",
                f"La connessione con {scanner.name} è stata persa durante lo streaming.\n"
                "Lo streaming è stato interrotto automaticamente."
            )
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