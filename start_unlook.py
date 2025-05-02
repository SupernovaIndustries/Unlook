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
import shutil
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
    Controlla e corregge il file stream_receiver.py, verificando che non ci siano
    problemi di naming o duplicazioni.
    """
    receiver_path = project_root / 'client' / 'network' / 'stream_receiver.py'
    wrong_filename = project_root / 'client' / 'network' / 'stream_reciever.py'

    # Verifica se il file con nome sbagliato esiste
    if wrong_filename.exists():
        logger.info(f"Trovato file con nome errato: {wrong_filename}")

        # Se il file corretto non esiste, rinominalo
        if not receiver_path.exists():
            try:
                wrong_filename.rename(receiver_path)
                logger.info(f"File rinominato: {wrong_filename} -> {receiver_path}")
            except Exception as e:
                logger.error(f"Errore nel rinominare il file: {e}")
                # Se non possiamo rinominare, proviamo a copiare
                try:
                    shutil.copy2(str(wrong_filename), str(receiver_path))
                    logger.info(f"File copiato: {wrong_filename} -> {receiver_path}")
                except Exception as copy_err:
                    logger.error(f"Errore anche nella copia del file: {copy_err}")
        else:
            # Entrambi i file esistono, verifichiamo se sono identici
            try:
                with open(wrong_filename, 'r') as f1, open(receiver_path, 'r') as f2:
                    content1 = f1.read()
                    content2 = f2.read()

                if content1 == content2:
                    # I file sono identici, possiamo rimuovere quello sbagliato
                    wrong_filename.unlink()
                    logger.info(f"File duplicato rimosso: {wrong_filename}")
                else:
                    # I file sono diversi, manteniamo quello corretto ma salviamo backup
                    backup_path = wrong_filename.with_suffix('.py.bak')
                    wrong_filename.rename(backup_path)
                    logger.info(f"File con nome errato rinominato come backup: {wrong_filename} -> {backup_path}")
            except Exception as e:
                logger.error(f"Errore nella gestione dei file duplicati: {e}")

    # Verifica se il file corretto esiste
    if not receiver_path.exists():
        logger.error(f"File essenziale mancante: {receiver_path}")
        logger.error("Sarà necessario creare manualmente il file stream_receiver.py nella directory client/network")
        return False

    # Verifica che il file contenga la classe StreamReceiver
    try:
        with open(receiver_path, 'r') as f:
            content = f.read()
            if 'class StreamReceiver' not in content:
                logger.error(f"Il file {receiver_path} non contiene la classe StreamReceiver necessaria!")
                logger.error("Sarà necessario aggiornare manualmente il file con l'implementazione corretta")
                return False
    except Exception as e:
        logger.error(f"Errore nella verifica del contenuto di {receiver_path}: {e}")
        return False

    return True


def verify_scan_directories():
    """
    Verifica che le directory di scansione siano accessibili e scrivibili.
    """
    import os
    from pathlib import Path

    # Controlla directory home utente
    home_dir = Path.home()
    if not os.access(str(home_dir), os.W_OK):
        logger.error(f"La directory home {home_dir} non è scrivibile!")
    else:
        logger.info(f"Directory home {home_dir} OK (scrivibile)")

    # Verifica directory scansioni predefinita
    scan_dir = home_dir / "UnLook" / "scans"

    # Crea la directory se non esiste
    try:
        scan_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Directory scansioni {scan_dir} creata/verificata")

        # Verifica diritti di scrittura
        if not os.access(str(scan_dir), os.W_OK):
            logger.error(f"La directory scansioni {scan_dir} non è scrivibile!")
        else:
            logger.info(f"Directory scansioni {scan_dir} OK (scrivibile)")

        # Test di scrittura
        test_file = scan_dir / "test_write.tmp"
        try:
            with open(test_file, 'w') as f:
                f.write("Test di scrittura")
            logger.info(f"Test di scrittura riuscito: {test_file}")

            # Pulisci
            os.remove(test_file)
        except Exception as e:
            logger.error(f"Test di scrittura fallito: {e}")

    except Exception as e:
        logger.error(f"Errore nella creazione directory scansioni: {e}")

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

    # Corregge il nome del file stream_receiver.py se necessario
    if not fix_stream_receiver_filename(project_root):
        logger.warning("Problemi con il modulo stream_receiver. L'applicazione potrebbe non funzionare correttamente.")
        # Chiediamo conferma all'utente se continuare
        user_input = input("Continuare comunque? (s/n): ")
        if user_input.lower() != 's':
            logger.info("Avvio annullato dall'utente.")
            sys.exit(1)

    # Verifica le directory di scansione
    verify_scan_directories()

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