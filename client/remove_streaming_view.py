#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Script per rimuovere tutte le importazioni e i riferimenti a streaming_view.py
"""

import os
import re
import glob

# Directory del progetto (modificare se necessario)
PROJECT_DIR = "."

# Pattern per le importazioni da cercare
IMPORT_PATTERNS = [
    r"from\s+client\.views\.streaming_view\s+import\s+.*",
    r"import\s+client\.views\.streaming_view",
    r"from\s+.*\s+import\s+.*DualStreamView.*",
]

# Files da escludere (backup, ecc.)
EXCLUDE_PATTERNS = [
    r".*\.bak$",
    r".*~$",
    r".*\.pyc$",
    r"__pycache__.*",
]


def should_process_file(filepath):
    """Verifica se il file deve essere processato."""
    # Controlla le esclusioni
    for pattern in EXCLUDE_PATTERNS:
        if re.match(pattern, filepath):
            return False

    # Processa solo file Python
    return filepath.endswith(".py")


def find_streaming_references(filepath):
    """Trova riferimenti a streaming_view nel file."""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Conta importazioni
    import_count = 0
    for pattern in IMPORT_PATTERNS:
        import_count += len(re.findall(pattern, content))

    # Cerca riferimenti
    streaming_view_refs = len(re.findall(r'streaming_view', content))
    dual_stream_view_refs = len(re.findall(r'DualStreamView', content))
    streaming_widget_refs = len(re.findall(r'streaming_widget', content))

    return {
        'imports': import_count,
        'streaming_view_refs': streaming_view_refs,
        'dual_stream_view_refs': dual_stream_view_refs,
        'streaming_widget_refs': streaming_widget_refs,
        'total': import_count + streaming_view_refs + dual_stream_view_refs + streaming_widget_refs
    }


def main():
    """Funzione principale."""
    print("Scanning for streaming_view references...")

    # Trova tutti i file Python
    py_files = []
    for root, dirs, files in os.walk(PROJECT_DIR):
        for file in files:
            filepath = os.path.join(root, file)
            if should_process_file(filepath):
                py_files.append(filepath)

    # Cerca riferimenti
    files_with_refs = {}
    total_refs = 0

    for filepath in py_files:
        refs = find_streaming_references(filepath)
        if refs['total'] > 0:
            files_with_refs[filepath] = refs
            total_refs += refs['total']

    # Mostra risultati
    print(f"\nFound {total_refs} references in {len(files_with_refs)} files:\n")

    for filepath, refs in files_with_refs.items():
        print(f"{filepath}:")
        print(f"  - Import statements: {refs['imports']}")
        print(f"  - streaming_view refs: {refs['streaming_view_refs']}")
        print(f"  - DualStreamView refs: {refs['dual_stream_view_refs']}")
        print(f"  - streaming_widget refs: {refs['streaming_widget_refs']}")
        print(f"  - Total: {refs['total']}")
        print("")

    print("\nPlease manually check and update these files before removing streaming_view.py")
    print("NOTE: This script does not modify any files, it only identifies references")


if __name__ == "__main__":
    main()