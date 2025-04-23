#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Comando minimale per il DLP - usa la sintassi più basilare possibile
"""

import serial
import time
import sys


def send_simple_byte(port, value):
    """Invia un singolo byte e attende risposta."""
    print(f"Invio singolo byte {hex(value)} alla porta {port}")

    try:
        ser = serial.Serial(port, 9600, timeout=1)
        ser.write(bytes([value]))
        time.sleep(0.1)
        response = ser.read(10)

        if response:
            print(f"Risposta: {response.hex()}")
        else:
            print("Nessuna risposta")

        ser.close()

    except Exception as e:
        print(f"Errore: {e}")


def test_sync_only(port):
    """Invia solo il byte di sincronizzazione."""
    send_simple_byte(port, 0x55)


# Il più semplice comando completo possibile: solo sync + cmd nullo + checksum + delimitatore
def test_minimal_command(port):
    """Invia il comando più minimale possibile."""
    try:
        ser = serial.Serial(port, 9600, timeout=1)

        # Comando minimo: sync (0x55) + comando (0x00) + checksum (0x00) + delimitatore (0x0A)
        cmd = bytes([0x55, 0x00, 0x00, 0x0A])

        print(f"Invio comando minimo: {cmd.hex()}")
        ser.write(cmd)

        time.sleep(0.1)
        response = ser.read(10)

        if response:
            print(f"Risposta: {response.hex()}")
        else:
            print("Nessuna risposta")

        ser.close()

    except Exception as e:
        print(f"Errore: {e}")


def main():
    """Funzione principale."""
    if len(sys.argv) < 2:
        print("Uso: python dlp_minimal_command.py <porta> [test]")
        print("     test: 1=sync, 2=comando minimo (default: entrambi)")
        sys.exit(1)

    port = sys.argv[1]
    test = int(sys.argv[2]) if len(sys.argv) > 2 else 0

    if test == 0 or test == 1:
        test_sync_only(port)
        time.sleep(1)

    if test == 0 or test == 2:
        test_minimal_command(port)


if __name__ == "__main__":
    main()