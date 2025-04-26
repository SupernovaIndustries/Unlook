#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Widget per la scoperta e la gestione degli scanner UnLook.
"""

import logging
import time
from typing import List, Dict, Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QGroupBox, QFormLayout,
    QFrame, QSplitter, QProgressBar, QCheckBox
)
from PySide6.QtCore import Qt, Slot, Signal, QTimer
from PySide6.QtGui import QIcon, QFont, QColor

from client.controllers.scanner_controller import ScannerController
from client.models.scanner_model import Scanner, ScannerStatus

logger = logging.getLogger(__name__)


class ScannerListItem(QListWidgetItem):
    """Item personalizzato per la lista degli scanner."""

    def __init__(self, scanner: Scanner):
        super().__init__()
        self.scanner = scanner
        self.update_display()

    def update_display(self):
        """Aggiorna la visualizzazione dell'item in base allo stato dello scanner."""
        # Imposta il testo dell'item
        self.setText(f"{self.scanner.name}")

        # Imposta l'icona in base allo stato
        if self.scanner.status == ScannerStatus.CONNECTED:
            self.setIcon(QIcon.fromTheme("network-wireless"))
            self.setForeground(QColor("#008800"))
        elif self.scanner.status == ScannerStatus.CONNECTING:
            self.setIcon(QIcon.fromTheme("network-transmit"))
            self.setForeground(QColor("#888800"))
        elif self.scanner.status == ScannerStatus.STREAMING:
            self.setIcon(QIcon.fromTheme("media-record"))
            self.setForeground(QColor("#0000AA"))
        elif self.scanner.status == ScannerStatus.ERROR:
            self.setIcon(QIcon.fromTheme("dialog-error"))
            self.setForeground(QColor("#AA0000"))
        else:
            self.setIcon(QIcon.fromTheme("network-offline"))
            self.setForeground(QColor("#000000"))

        # Imposta i dati dell'item
        self.setData(Qt.UserRole, self.scanner.device_id)

    def __lt__(self, other):
        # Ordina gli scanner: prima i connessi, poi per nome
        if not isinstance(other, ScannerListItem):
            return super().__lt__(other)

        # Priorità allo stato di connessione
        self_connected = self.scanner.status in (ScannerStatus.CONNECTED, ScannerStatus.STREAMING)
        other_connected = other.scanner.status in (ScannerStatus.CONNECTED, ScannerStatus.STREAMING)

        if self_connected and not other_connected:
            return True
        if not self_connected and other_connected:
            return False

        # Se hanno lo stesso stato, ordina per nome
        return self.scanner.name.lower() < other.scanner.name.lower()


class ScannerInfoWidget(QWidget):
    """Widget che mostra le informazioni dettagliate su uno scanner."""

    connect_requested = Signal(str)  # device_id
    disconnect_requested = Signal(str)  # device_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scanner: Optional[Scanner] = None
        self._setup_ui()

    def _setup_ui(self):
        """Configura l'interfaccia utente."""
        # Layout principale
        layout = QVBoxLayout(self)

        # Titolo
        self.title_label = QLabel("Seleziona uno scanner")
        self.title_label.setAlignment(Qt.AlignCenter)
        font = self.title_label.font()
        font.setPointSize(14)
        font.setBold(True)
        self.title_label.setFont(font)
        layout.addWidget(self.title_label)

        # Linea di separazione
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        layout.addWidget(separator)

        # Contenitore per le informazioni
        self.info_container = QWidget()
        self.info_layout = QFormLayout(self.info_container)

        # Campi informativi
        self.device_id_label = QLabel("")
        self.status_label = QLabel("")
        self.ip_address_label = QLabel("")
        self.capabilities_label = QLabel("")
        self.last_seen_label = QLabel("")

        # Aggiungi i campi al layout
        self.info_layout.addRow("ID Dispositivo:", self.device_id_label)
        self.info_layout.addRow("Stato:", self.status_label)
        self.info_layout.addRow("Indirizzo IP:", self.ip_address_label)
        self.info_layout.addRow("Capacità:", self.capabilities_label)
        self.info_layout.addRow("Ultimo contatto:", self.last_seen_label)

        # Aggiungi il contenitore al layout principale
        layout.addWidget(self.info_container)

        # Pulsanti di azione
        action_layout = QHBoxLayout()

        self.connect_button = QPushButton("Connetti")
        self.connect_button.setEnabled(False)
        self.connect_button.clicked.connect(self._on_connect_clicked)

        self.disconnect_button = QPushButton("Disconnetti")
        self.disconnect_button.setEnabled(False)
        self.disconnect_button.clicked.connect(self._on_disconnect_clicked)

        action_layout.addWidget(self.connect_button)
        action_layout.addWidget(self.disconnect_button)

        layout.addLayout(action_layout)

        # Aggiungi uno spazio elastico alla fine
        layout.addStretch(1)

        # Nasconde i dettagli fino a quando non viene selezionato uno scanner
        self.info_container.setVisible(False)

    def set_scanner(self, scanner: Optional[Scanner]):
        """Imposta lo scanner corrente e aggiorna la visualizzazione."""
        self._scanner = scanner

        if scanner:
            # CORREZIONE: Verifica lo stato di connessione in modo più affidabile
            from client.controllers.scanner_controller import ScannerController
            is_connected = scanner.status in (ScannerStatus.CONNECTED, ScannerStatus.STREAMING)
            is_streaming = scanner.status == ScannerStatus.STREAMING

            # Se abbiamo il controller, verifica anche la connessione diretta
            direct_connection = False
            try:
                if hasattr(self.parent(), 'scanner_controller'):
                    controller = self.parent().scanner_controller
                    if controller and hasattr(controller, 'is_connected'):
                        direct_connection = controller.is_connected(scanner.device_id)
            except:
                pass

            # Un dispositivo è considerato connesso se è nello stato di connessione
            # o se è in streaming o se la connessione diretta è attiva
            is_really_connected = is_connected or is_streaming or direct_connection

            # Aggiorna i campi informativi
            self.title_label.setText(scanner.name)
            self.device_id_label.setText(scanner.device_id)

            # CORREZIONE: Mostra lo stato più accurato possibile
            if is_streaming:
                self.status_label.setText("STREAMING")
            elif is_really_connected:
                self.status_label.setText("CONNECTED")
            else:
                self.status_label.setText(scanner.status.name)

            self.ip_address_label.setText(f"{scanner.ip_address}:{scanner.port}")

            # Formatta le capacità
            capabilities = []
            if scanner.capabilities.dual_camera:
                capabilities.append("Dual Camera")
            if scanner.capabilities.color_mode:
                capabilities.append("Modalità Colore")
            if scanner.capabilities.supports_tof:
                capabilities.append("Sensore ToF")
            if scanner.capabilities.supports_dlp:
                capabilities.append("Proiettore DLP")

            self.capabilities_label.setText(", ".join(capabilities) if capabilities else "Sconosciute")

            # Formatta l'ultimo contatto
            elapsed = time.time() - scanner.last_seen
            if elapsed < 5:
                last_seen = "Ora"
            elif elapsed < 60:
                last_seen = f"{int(elapsed)} secondi fa"
            else:
                last_seen = f"{int(elapsed / 60)} minuti fa"

            self.last_seen_label.setText(last_seen)

            # Aggiorna lo stato dei pulsanti
            self.connect_button.setEnabled(not is_really_connected)
            self.disconnect_button.setEnabled(is_really_connected)

            # Mostra i dettagli
            self.info_container.setVisible(True)
        else:
            # Nessuno scanner selezionato
            self.title_label.setText("Seleziona uno scanner")
            self.info_container.setVisible(False)
            self.connect_button.setEnabled(False)
            self.disconnect_button.setEnabled(False)

    def update_ui(self):
        """Aggiorna l'interfaccia utente con i dati attuali dello scanner."""
        if self._scanner:
            self.set_scanner(self._scanner)

    @Slot()
    def _on_connect_clicked(self):
        """Gestisce il clic sul pulsante Connetti."""
        if self._scanner:
            self.connect_requested.emit(self._scanner.device_id)

            # Aggiorna l'interfaccia utente immediatamente
            self._scanner.status = ScannerStatus.CONNECTING
            self.status_label.setText(self._scanner.status.name)
            self.connect_button.setEnabled(False)

    @Slot()
    def _on_disconnect_clicked(self):
        """Gestisce il clic sul pulsante Disconnetti."""
        if self._scanner:
            self.disconnect_requested.emit(self._scanner.device_id)


class ScannerDiscoveryWidget(QWidget):
    """
    Widget che mostra la lista degli scanner disponibili e permette
    di connettersi ad essi.
    """

    def __init__(self, scanner_controller: ScannerController, parent=None):
        super().__init__(parent)
        self.scanner_controller = scanner_controller
        self._scanner_items: Dict[str, ScannerListItem] = {}

        # Timer per aggiornare l'UI
        self._update_timer = QTimer(self)
        self._update_timer.timeout.connect(self._update_last_seen_times)
        self._update_timer.start(5000)  # Aggiorna ogni 5 secondi

        # Configura l'interfaccia utente
        self._setup_ui()

        # Collega i segnali
        self._connect_signals()

        # Aggiorna la lista degli scanner
        self._update_scanner_list()

    def _setup_ui(self):
        """Configura l'interfaccia utente."""
        # Layout principale
        layout = QHBoxLayout(self)

        # Splitter per dividere la lista e i dettagli
        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter)

        # Contenitore per la lista degli scanner
        list_container = QWidget()
        list_layout = QVBoxLayout(list_container)

        # Etichetta e casella di controllo per l'auto-scoperta
        header_layout = QHBoxLayout()
        list_label = QLabel("Scanner disponibili")
        font = list_label.font()
        font.setBold(True)
        list_label.setFont(font)

        self.auto_discovery_checkbox = QCheckBox("Scoperta automatica")
        self.auto_discovery_checkbox.setChecked(True)

        header_layout.addWidget(list_label)
        header_layout.addWidget(self.auto_discovery_checkbox)

        list_layout.addLayout(header_layout)

        # Lista degli scanner
        self.scanner_list = QListWidget()
        self.scanner_list.setMinimumWidth(250)
        self.scanner_list.setSortingEnabled(True)
        list_layout.addWidget(self.scanner_list)

        # Pulsanti di azione
        list_buttons_layout = QHBoxLayout()

        self.refresh_button = QPushButton("Aggiorna")
        self.refresh_button.clicked.connect(self._on_refresh_clicked)

        list_buttons_layout.addWidget(self.refresh_button)
        list_buttons_layout.addStretch(1)

        list_layout.addLayout(list_buttons_layout)

        # Aggiungi il contenitore della lista allo splitter
        splitter.addWidget(list_container)

        # Widget per i dettagli dello scanner
        self.scanner_info = ScannerInfoWidget()
        splitter.addWidget(self.scanner_info)

        # Imposta le proporzioni dello splitter
        splitter.setSizes([300, 500])

    def _connect_signals(self):
        """Collega i segnali dell'interfaccia."""
        # Segnali del controller degli scanner
        self.scanner_controller.scanners_changed.connect(self._update_scanner_list)

        # Segnali dell'interfaccia
        self.scanner_list.currentItemChanged.connect(self._on_scanner_selected)
        self.auto_discovery_checkbox.toggled.connect(self._on_auto_discovery_toggled)

        # Segnali del widget informazioni scanner
        self.scanner_info.connect_requested.connect(self._on_connect_requested)
        self.scanner_info.disconnect_requested.connect(self._on_disconnect_requested)

    @Slot()
    @Slot()
    def _update_scanner_list(self):
        """Aggiorna la lista degli scanner disponibili."""
        # Memorizza l'ID dello scanner selezionato corrente
        current_device_id = None
        current_item = self.scanner_list.currentItem()
        if current_item:
            current_device_id = current_item.data(Qt.UserRole)

        # Blocca i segnali per evitare attivazioni durante l'aggiornamento
        self.scanner_list.blockSignals(True)

        # Memorizza gli scanner attualmente nella lista
        old_scanner_items = {}
        for i in range(self.scanner_list.count()):
            item = self.scanner_list.item(i)
            if item:
                scanner_id = item.data(Qt.UserRole)
                old_scanner_items[scanner_id] = item

        # Svuota la lista
        self.scanner_list.clear()
        self._scanner_items.clear()

        # Aggiungi gli scanner disponibili
        scanners = self.scanner_controller.scanners
        for scanner in scanners:
            # CORREZIONE: Verifica in modo più affidabile lo stato di connessione
            is_connected = scanner.status in (ScannerStatus.CONNECTED, ScannerStatus.STREAMING)
            is_streaming = scanner.status == ScannerStatus.STREAMING

            # Verifica anche direttamente con il connection manager
            direct_connection = self.scanner_controller.is_connected(scanner.device_id)

            # Un dispositivo è considerato connesso se è nello stato di connessione
            # o se è in streaming o se la connessione diretta è attiva
            is_really_connected = is_connected or is_streaming or direct_connection

            # Aggiorna lo stato dello scanner se necessario
            if is_really_connected and scanner.status == ScannerStatus.DISCONNECTED:
                scanner.status = ScannerStatus.CONNECTED

            # Crea o riutilizza un item per lo scanner
            item = ScannerListItem(scanner)
            self.scanner_list.addItem(item)
            self._scanner_items[scanner.device_id] = item

        # Restituisci il focus all'elemento precedentemente selezionato
        if current_device_id:
            for i in range(self.scanner_list.count()):
                item = self.scanner_list.item(i)
                if item.data(Qt.UserRole) == current_device_id:
                    self.scanner_list.setCurrentItem(item)
                    break

        # Ripristina i segnali
        self.scanner_list.blockSignals(False)

    @Slot()
    def _update_last_seen_times(self):
        """Aggiorna i tempi di ultimo contatto per gli scanner."""
        # Aggiorna le informazioni dettagliate per riflettere i nuovi tempi
        self.scanner_info.update_ui()

    @Slot(QListWidgetItem, QListWidgetItem)
    def _on_scanner_selected(self, current: QListWidgetItem, previous: QListWidgetItem):
        """Gestisce la selezione di uno scanner nella lista."""
        if not current:
            self.scanner_info.set_scanner(None)
            return

        # Ottieni l'ID dello scanner selezionato
        device_id = current.data(Qt.UserRole)

        # Trova lo scanner corrispondente
        for scanner in self.scanner_controller.scanners:
            if scanner.device_id == device_id:
                # Imposta lo scanner nel controller
                self.scanner_controller.select_scanner(device_id)
                # Aggiorna la visualizzazione delle informazioni
                self.scanner_info.set_scanner(scanner)
                break

    @Slot(bool)
    def _on_auto_discovery_toggled(self, checked: bool):
        """Gestisce l'attivazione/disattivazione della scoperta automatica."""
        if checked:
            self.scanner_controller.start_discovery()
            self.refresh_button.setEnabled(True)
        else:
            self.scanner_controller.stop_discovery()
            self.refresh_button.setEnabled(False)

    @Slot()
    def _on_refresh_clicked(self):
        """Gestisce il clic sul pulsante Aggiorna."""
        # Riavvia la scoperta degli scanner
        self.scanner_controller.stop_discovery()
        self.scanner_controller.start_discovery()

    @Slot(str)
    def _on_connect_requested(self, device_id: str):
        """Gestisce la richiesta di connessione a uno scanner."""
        self.scanner_controller.connect_to_scanner(device_id)

    @Slot(str)
    def _on_disconnect_requested(self, device_id: str):
        """Gestisce la richiesta di disconnessione da uno scanner."""
        self.scanner_controller.disconnect_from_scanner(device_id)