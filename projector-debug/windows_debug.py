import os
import sys
import clr

# Percorso alla DLL principale
dll_path = "G:\\Supernova\\Prototipi\\UnLook\\Software\\Unlook\\projector-debug\\dlpc342x"
dll_file = os.path.join(dll_path, "DLPComposer.Commands.DLPC342x.x64.dll")

# Verifica che il file esista
if not os.path.exists(dll_file):
    print(f"ERRORE: DLL non trovata in: {dll_file}")
    sys.exit(1)

print(f"DLL principale: {dll_file}")

# Cerca altre DLL nella stessa cartella che potrebbero essere dipendenze
dll_files = [f for f in os.listdir(dll_path) if f.endswith('.dll')]
print(f"\nDLL trovate nella cartella:")
for dll in dll_files:
    print(f"  - {dll}")

# Aggiungi tutte le DLL trovate come riferimenti
print("\nCaricamento di tutte le DLL trovate...")
for dll in dll_files:
    try:
        dll_full_path = os.path.join(dll_path, dll)
        clr.AddReference(dll_full_path)
        print(f"  √ {dll} caricata con successo")
    except Exception as e:
        print(f"  ✗ {dll} errore: {e}")

# Importa System.Reflection per esaminare le LoaderExceptions
from System.Reflection import Assembly, ReflectionTypeLoadException

# Carica l'assembly principale
try:
    assembly = Assembly.LoadFrom(dll_file)
    print(f"\nAssembly caricato: {assembly.FullName}")

    # Prova a ottenere i tipi, catturando le eccezioni specifiche
    try:
        types = assembly.GetTypes()
        print(f"Tipi trovati: {len(types)}")

        # Elenca alcuni dei tipi trovati
        print("\nAlcuni tipi trovati:")
        for i, t in enumerate(types[:5]):  # Mostra solo i primi 5
            print(f"  {i + 1}. {t.FullName}")

    except ReflectionTypeLoadException as rtle:
        print("\nERRORE: ReflectionTypeLoadException")
        print("LoaderExceptions:")
        for i, ex in enumerate(rtle.LoaderExceptions):
            print(f"  {i + 1}. {ex.Message}")
            if hasattr(ex, 'FileName'):
                print(f"     File: {ex.FileName}")

except Exception as e:
    print(f"\nErrore nel caricamento dell'assembly: {e}")

# Controllo versione .NET
print("\nVerifica della versione .NET:")
try:
    from System import Environment

    print(f"Versione .NET: {Environment.Version}")
except Exception as e:
    print(f"Impossibile determinare la versione .NET: {e}")

print("\nScript diagnostico completato")