"""
Script semplice per inviare pattern di test al DLP LightCrafter 160CP su Windows
"""

import serial
import time
import sys
import os


def send_test_pattern(port, pattern_num):
    """
    Invia il comando per mostrare un pattern di test.

    Args:
        port: Porta COM (es. 'COM1')
        pattern_num: Numero del pattern di test
            0: Nessun pattern (campo solido)
            1: Griglia
            2: Scacchiera
            4: Linee verticali
            8: Linee orizzontali
            9: Linee diagonali
    """
    try:
        # Apri la connessione seriale
        ser = serial.Serial(
            port=port,
            baudrate=9600,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=1.0
        )

        # Costruisci il comando di test pattern

        # Byte di sincronizzazione
        sync = 0x55

        # Parametri DLPC3421
        dlpc_addr = 0x36  # Indirizzo di scrittura
        read_len = 0x00  # 0 per comandi di scrittura
        sub_addr = 0x0B  # SubAddress per Test Pattern

        # Parametri per il comando di test pattern
        params = bytes([0x03, 0x70, 0x01, pattern_num])

        # Costruisci payload
        payload = bytes([dlpc_addr, read_len, sub_addr]) + params
        cmd_size = len(payload)

        # Costruisci comando principale
        main_cmd = (0 & 0x03) | ((cmd_size & 0x1F) << 2) | (0 << 7)

        # Costruisci frame completo
        frame = bytearray([sync, main_cmd])
        frame.extend(payload)

        # Calcola checksum
        checksum = sum(frame[1:]) % 256
        frame.append(checksum)

        # Aggiungi delimitatore
        frame.append(0x0A)

        print(f"Invio comando pattern {pattern_num} su {port}: {frame.hex()}")

        # Svuota buffer
        ser.reset_input_buffer()
        ser.reset_output_buffer()

        # Invia il comando
        ser.write(frame)

        # Attendi un po'
        time.sleep(0.2)

        # Leggi eventuale risposta
        response = ser.read(100)
        if response:
            print(f"Risposta: {response.hex()}")
        else:
            print("Nessuna risposta (normale per comandi di scrittura)")

        # Chiudi la connessione
        ser.close()
        print(f"Comando inviato. Pattern {pattern_num} dovrebbe essere visibile se il comando è stato accettato.")

    except Exception as e:
        print(f"Errore: {e}")


def list_com_ports():
    """Elenca le porte COM disponibili."""
    try:
        import serial.tools.list_ports
        ports = serial.tools.list_ports.comports()
        if not ports:
            print("Nessuna porta COM trovata!")
            return []

        print("Porte COM disponibili:")
        port_list = []
        for i, port in enumerate(ports):
            print(f"  {i + 1}. {port.device} - {port.description}")
            port_list.append(port.device)
        return port_list
    except Exception as e:
        print(f"Errore nell'ottenere la lista delle porte: {e}")
        return []


def main():
    """Funzione principale."""
    print("\n== DLP LightCrafter 160CP Test Pattern Tool ==\n")

    # Ottieni la lista delle porte COM
    ports = list_com_ports()
    if not ports:
        print("Nessuna porta COM trovata. Verifica che il dispositivo sia collegato.")
        input("Premi Invio per uscire...")
        return

    # Chiedi all'utente di selezionare una porta
    if len(ports) == 1:
        port = ports[0]
        print(f"Utilizzo dell'unica porta disponibile: {port}")
    else:
        choice = input("\nSeleziona il numero della porta da utilizzare: ")
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(ports):
                port = ports[idx]
            else:
                print("Selezione non valida.")
                input("Premi Invio per uscire...")
                return
        except ValueError:
            print("Input non valido. Inserisci un numero.")
            input("Premi Invio per uscire...")
            return

    # Mostra menu pattern di test
    print("\nPattern di Test disponibili:")
    print("0: Nessun pattern (campo solido)")
    print("1: Griglia")
    print("2: Scacchiera")
    print("4: Linee verticali")
    print("8: Linee orizzontali")
    print("9: Linee diagonali")

    # Chiedi all'utente quale pattern mostrare
    pattern_choice = input("\nSeleziona il pattern da mostrare: ")
    try:
        pattern_num = int(pattern_choice)
    except ValueError:
        print("Input non valido. Inserisci un numero.")
        input("Premi Invio per uscire...")
        return

    # Invia il comando per mostrare il pattern
    send_test_pattern(port, pattern_num)

    input("\nPremi Invio per uscire...")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Errore non gestito: {e}")
        input("Premi Invio per uscire...")