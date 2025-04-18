#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
UnLook Client Application - Main Entry Point
"""

import sys
import logging
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QCoreApplication, Qt

# Imposta le informazioni dell'applicazione
QCoreApplication.setApplicationName("UnLook")
QCoreApplication.setOrganizationName("SupernovaIndustries")
QCoreApplication.setOrganizationDomain("supernovaindustries.com")

# Configura logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(Path.home() / '.unlook' / 'unlook.log', mode='a')
    ]
)
logger = logging.getLogger(__name__)

# Assicura che la directory per i log esista
log_dir = Path.home() / '.unlook'
log_dir.mkdir(exist_ok=True)

# Importa dopo la configurazione del logging
from views.main_window import MainWindow
from controllers.scanner_controller import ScannerController
from models.scanner_model import ScannerManager


def main():
    """Entry point principale dell'applicazione."""
    try:
        # Crea l'applicazione Qt
        app = QApplication(sys.argv)

        # Abilita stile moderno
        app.setStyle("Fusion")

        # Disabilita AA per migliorare le prestazioni di rendering
        app.setAttribute(Qt.AA_DisableHighDpiScaling, True)

        # Crea i componenti principali
        scanner_manager = ScannerManager()
        scanner_controller = ScannerController(scanner_manager)

        # Crea la finestra principale
        window = MainWindow(scanner_controller)
        window.show()

        logger.info("UnLook Client Application avviata")

        # Avvia il loop principale dell'applicazione
        sys.exit(app.exec_())

    except Exception as e:
        logger.exception(f"Errore critico nell'applicazione: {str(e)}")
        raise


if __name__ == "__main__":
    main()