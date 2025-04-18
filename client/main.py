#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
UnLook Client Application - Main Entry Point
"""

import sys
import logging
import os
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QCoreApplication, Qt

# Aggiungi la directory parent al PYTHONPATH per abilitare gli import relativi
# sia per esecuzione diretta che per esecuzione via launcher
current_dir = Path(__file__).resolve().parent
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir.parent))

# Imposta le informazioni dell'applicazione
QCoreApplication.setApplicationName("UnLook")
QCoreApplication.setOrganizationName("SupernovaIndustries")
QCoreApplication.setOrganizationDomain("supernovaindustries.com")

# Configura logging
log_dir = Path.home() / '.unlook'
log_dir.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(log_dir / 'unlook.log', mode='a')
    ]
)
logger = logging.getLogger(__name__)

# Importa dopo la configurazione del logging
try:
    from client.views.main_window import MainWindow
    from client.controllers.scanner_controller import ScannerController
    from client.models.scanner_model import ScannerManager
except ImportError:
    try:
        # Fallback per esecuzione diretta
        from client.views.main_window import MainWindow
        from controllers.scanner_controller import ScannerController
        from models.scanner_model import ScannerManager
        logger.info("Usando import relativi (esecuzione diretta)")
    except ImportError as e:
        logger.exception(f"Errore nell'importazione dei moduli: {e}")
        logger.error("Per avviare l'applicazione, usare lo script 'start_unlook.py' nella directory principale")
        sys.exit(1)


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
        sys.exit(app.exec())

    except Exception as e:
        logger.exception(f"Errore critico nell'applicazione: {str(e)}")
        raise


if __name__ == "__main__":
    main()