#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Script di avvio per l'applicazione UnLook.
Questo script configura il PYTHONPATH correttamente e avvia l'applicazione.
"""

import os
import sys
import subprocess
import logging
from pathlib import Path

# Configura logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger("UnLookLauncher")


def find_project_root():
    """
    Trova la root del progetto cercando verso l'alto fino a trovare una directory
    che contiene sia 'client' che 'common'.
    """
    current_dir = Path(__file__).resolve().parent

    # Cerca fino a 5 livelli verso l'alto
    for _ in range(5):
        if (current_dir / 'client').exists() and (current_dir / 'common').exists():
            return current_dir

        # Sali di un livello
        parent = current_dir.parent
        if parent == current_dir:  # Siamo arrivati alla root del filesystem
            break
        current_dir = parent

    # Se non troviamo la root, usiamo la directory corrente
    return Path(__file__).resolve().parent


def verify_dependencies():
    """
    Verifica che tutte le dipendenze necessarie siano installate.
    Restituisce True se tutto è a posto, False altrimenti.
    """
    try:
        import PySide6
        import numpy
        import cv2
        import zmq

        logger.info("Tutte le dipendenze principali sono installate.")
        return True
    except ImportError as e:
        logger.error(f"Dipendenza mancante: {e}")
        logger.error("Si prega di installare le dipendenze richieste con: pip install -r requirements.txt")
        return False


def fix_stream_receiver_filename(project_root):
    """
    Corregge il nome del file stream_reciever.py in stream_receiver.py se necessario.
    """
    wrong_filename = project_root / 'client' / 'network' / 'stream_reciever.py'
    correct_filename = project_root / 'client' / 'network' / 'stream_receiver.py'

    if wrong_filename.exists() and not correct_filename.exists():
        try:
            wrong_filename.rename(correct_filename)
            logger.info(f"File rinominato: {wrong_filename} -> {correct_filename}")
        except Exception as e:
            logger.error(f"Errore nel rinominare il file: {e}")


def create_missing_init_files(project_root):
    """
    Crea file __init__.py mancanti nelle directory del progetto.
    """
    directories = [
        project_root / 'common',
        project_root / 'client',
        project_root / 'client' / 'controllers',
        project_root / 'client' / 'models',
        project_root / 'client' / 'network',
        project_root / 'client' / 'utils',
        project_root / 'client' / 'views',
    ]

    for directory in directories:
        if directory.exists():
            init_file = directory / '__init__.py'
            if not init_file.exists():
                try:
                    with open(init_file, 'w') as f:
                        f.write('"""Pacchetto {}."""\n'.format(directory.name))
                    logger.info(f"Creato file __init__.py in {directory}")
                except Exception as e:
                    logger.error(f"Errore nella creazione di {init_file}: {e}")


def main():
    """
    Funzione principale che avvia l'applicazione.
    """
    logger.info("Avvio del launcher UnLook...")

    # Trova la root del progetto
    project_root = find_project_root()
    logger.info(f"Root del progetto: {project_root}")

    # Verifica le dipendenze
    if not verify_dependencies():
        logger.error("Impossibile avviare l'applicazione a causa di dipendenze mancanti.")
        sys.exit(1)

    # Corregge il nome del file stream_reciever.py se necessario
    fix_stream_receiver_filename(project_root)

    # Crea file __init__.py mancanti
    create_missing_init_files(project_root)

    # Aggiungi la root del progetto al PYTHONPATH
    sys.path.insert(0, str(project_root))

    # Imposta le variabili d'ambiente
    os.environ['PYTHONPATH'] = str(project_root)

    try:
        # Importa e avvia l'applicazione
        from client.main import main as client_main
        logger.info("Avvio dell'applicazione client...")
        client_main()
    except Exception as e:
        logger.exception(f"Errore nell'avvio dell'applicazione: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()