#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Script di diagnostica per verificare la configurazione del progetto UnLook.
Controlla le dipendenze, la struttura del progetto e la capacità di importare moduli.
"""

import sys
import os
import importlib
import platform
from pathlib import Path
import subprocess
import shutil

# Lista delle dipendenze da verificare
DEPENDENCIES = [
    ("PySide6", "UI Framework"),
    ("numpy", "Array processing"),
    ("cv2", "OpenCV image processing"),
    ("zmq", "ZeroMQ networking"),
    ("PIL", "Python Imaging Library")
]

# Lista di moduli del progetto da verificare
PROJECT_MODULES = {
    "common": ["protocol"],
    "client": ["main"],
    "client.models": ["scanner_model", "config_model"],
    "client.views": ["main_window", "scanner_view", "streaming_view", "config_view"],
    "client.controllers": ["scanner_controller", "config_controller"],
    "client.network": ["connection_manager", "discovery_service", "stream_receiver"],
    "client.utils": ["thread_safe_queue"]
}


def print_header(text):
    """Stampa una intestazione formattata."""
    width = 80
    print("\n" + "=" * width)
    print(f"{text.center(width)}")
    print("=" * width + "\n")


def print_section(text):
    """Stampa un'intestazione di sezione."""
    print(f"\n--- {text} ---")


def print_result(name, status, details=None):
    """Stampa il risultato di un controllo."""
    status_text = "✅ OK" if status else "❌ ERRORE"
    print(f"{name.ljust(40)} {status_text}")
    if details and not status:
        print(f"  └─ {details}")


def check_python_version():
    """Verifica la versione di Python."""
    version = sys.version_info
    is_valid = version.major >= 3 and version.minor >= 8
    print_result(
        f"Python {version.major}.{version.minor}.{version.micro}",
        is_valid,
        "Richiesto Python 3.8 o superiore" if not is_valid else None
    )
    return is_valid


def check_system_info():
    """Mostra informazioni sul sistema."""
    print(f"Sistema operativo: {platform.system()} {platform.release()}")
    print(f"Piattaforma: {platform.platform()}")
    print(f"Python path: {sys.executable}")
    print(f"Ambiente virtuale: {'VIRTUAL_ENV' in os.environ}")
    if 'VIRTUAL_ENV' in os.environ:
        print(f"  └─ {os.environ['VIRTUAL_ENV']}")


def check_dependencies():
    """Verifica che tutte le dipendenze richieste siano installate."""
    all_ok = True

    for package_name, description in DEPENDENCIES:
        try:
            package = importlib.import_module(package_name)
            version = getattr(package, "__version__", "unknown version")
            print_result(f"{package_name} ({description})", True)
        except ImportError as e:
            print_result(f"{package_name} ({description})", False, str(e))
            all_ok = False

    return all_ok


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

    # Se non troviamo la root, restituiamo None
    return None


def check_project_structure(project_root):
    """Verifica la struttura del progetto."""
    if not project_root:
        print_result("Trovare directory progetto", False, "Impossibile trovare la root del progetto")
        return False

    print_result("Directory progetto", True, f"Trovata in: {project_root}")

    all_ok = True
    expected_dirs = ["client", "common", "client/controllers", "client/models",
                     "client/views", "client/network", "client/utils"]

    for dir_name in expected_dirs:
        directory = project_root / dir_name
        exists = directory.exists() and directory.is_dir()
        print_result(f"Directory {dir_name}", exists)
        all_ok = all_ok and exists

        # Verifica la presenza del file __init__.py
        if exists:
            init_file = directory / "__init__.py"
            init_exists = init_file.exists()
            print_result(f"  └─ __init__.py", init_exists)
            all_ok = all_ok and init_exists

    return all_ok


def check_file_names(project_root):
    """Controlla che i nomi dei file siano corretti."""
    all_ok = True

    # Controlli specifici
    checks = [
        (project_root / "client/views/main_window.py", "main_window.py"),
        (project_root / "client/network/stream_receiver.py", "stream_receiver.py"),
    ]

    for file_path, file_name in checks:
        exists = file_path.exists()
        print_result(f"File {file_name}", exists)
        all_ok = all_ok and exists

        # Controlla se esiste una versione con nome errato
        if not exists:
            # Controlla possibili file con nome errato
            parent_dir = file_path.parent
            possible_files = list(parent_dir.glob(f"{file_path.stem}*.py"))
            if possible_files:
                print(f"  └─ File simili trovati: {[f.name for f in possible_files]}")

    return all_ok


def check_imports(project_root):
    """Verifica che tutti i moduli del progetto possano essere importati."""
    all_ok = True

    # Aggiungi la root del progetto al PYTHONPATH
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    # Prova a importare ogni modulo
    for package, modules in PROJECT_MODULES.items():
        for module_name in modules:
            full_module_name = f"{package}.{module_name}"
            try:
                # Prova a importare il modulo
                importlib.import_module(full_module_name)
                print_result(f"Import di {full_module_name}", True)
            except ImportError as e:
                print_result(f"Import di {full_module_name}", False, str(e))
                all_ok = False

    return all_ok


def fix_file_names(project_root):
    """Corregge i nomi dei file errati."""
    renames = [
        (project_root / "client/views/main_windows.py", project_root / "client/views/main_window.py"),
        (project_root / "client/network/stream_reciever.py", project_root / "client/network/stream_receiver.py"),
    ]

    for src, dst in renames:
        if src.exists() and not dst.exists():
            try:
                src.rename(dst)
                print(f"Rinominato {src.name} in {dst.name}")
            except Exception as e:
                print(f"Errore nel rinominare {src} in {dst}: {e}")


def create_missing_init_files(project_root):
    """Crea i file __init__.py mancanti."""
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
                        f.write(f'"""Pacchetto {directory.name}."""\n')
                    print(f"Creato file __init__.py in {directory}")
                except Exception as e:
                    print(f"Errore nella creazione di {init_file}: {e}")


def run_fix_mode(project_root):
    """Esegue le operazioni di riparazione automatica."""
    print_header("MODALITÀ RIPARAZIONE")

    if not project_root:
        print("Impossibile trovare la root del progetto. Riparazione annullata.")
        return

    print_section("Correzione dei nomi dei file")
    fix_file_names(project_root)

    print_section("Creazione dei file __init__.py mancanti")
    create_missing_init_files(project_root)

    print("\nRiparazione completata. Esegui nuovamente la diagnostica per verificare.")


def main():
    """Funzione principale."""
    if len(sys.argv) > 1 and sys.argv[1] == '--fix':
        run_fix_mode(find_project_root())
        return

    print_header("DIAGNOSTICA PROGETTO UNLOOK")
    print("Questo tool verifica la configurazione del progetto UnLook.")

    print_section("Informazioni di sistema")
    check_system_info()

    print_section("Versione Python")
    check_python_version()

    print_section("Dipendenze")
    deps_ok = check_dependencies()

    project_root = find_project_root()

    print_section("Struttura del progetto")
    structure_ok = check_project_structure(project_root)

    print_section("Nomi dei file")
    files_ok = check_file_names(project_root)

    print_section("Test di importazione")
    imports_ok = True
    if project_root and structure_ok and files_ok:
        imports_ok = check_imports(project_root)
    else:
        print("Impossibile eseguire i test di importazione a causa di errori precedenti.")
        imports_ok = False

    # Riepilogo e consigli
    print_header("RIEPILOGO")
    all_ok = deps_ok and structure_ok and files_ok and imports_ok

    if all_ok:
        print("✅ Tutti i controlli sono passati! Il sistema è pronto per l'uso.")
        print("\nPer avviare l'applicazione, esegui:")
        print("python start_unlook.py")
    else:
        print("❌ Sono stati rilevati alcuni problemi.")
        print("\nPer tentare una riparazione automatica, esegui:")
        print("python diagnostic.py --fix")
        print("\nDopo la riparazione, esegui nuovamente la diagnostica.")


if __name__ == "__main__":
    main()