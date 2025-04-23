#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Test semplice per il DLP LightCrafter 160CP
Focalizzato su comandi che non richiedono risposta
"""

import time
import serial
import sys
import logging
import argparse

# Configurazione logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("DLP_TEST")


def send_command(port, baudrate, data, description=""):
    """Invia un comando al DLP."""
    logger.info(f"Invio comando: {description}")
    logger.info(f"Dati: {data.hex()}")

    try:
        # Apri la connessione seriale
        ser = serial.Serial(
            port=port,
            baudrate=baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=1.0
        )

        # Pulizia dei buffer
        ser.reset_input_buffer()
        ser.reset_output_buffer()

        # Invia il comando
        ser.write(data)

        # Breve attesa
        time.sleep(0.1)

        # Tenta di leggere una risposta
        response = ser.read(100)

        if response:
            logger.info(f"Risposta: {response.hex()}")
        else:
            logger.info("Nessuna risposta (previsto per comandi di scrittura)")

        # Chiudi la connessione
        ser.close()
        return True

    except Exception as e:
        logger.error(f"Errore nell'invio del comando: {e}")
        return False


def build_test_pattern_command(pattern):
    """
    Costruisce un comando per mostrare un pattern di test.

    Pattern disponibili:
    0: Nessun pattern (campo solido)
    1: Griglia
    2: Scacchiera
    4: Linee verticali
    8: Linee orizzontali
    9: Linee diagonali
    """
    # Byte di sincronizzazione
    sync = 0x55

    # Payload del comando
    dlpc_addr = 0x36
    read_len = 0x00
    sub_addr = 0x0B
    params = bytes([0x03, 0x70, 0x01, pattern])

    payload = bytes([dlpc_addr, read_len, sub_addr]) + params

    # Calcola la dimensione del payload
    cmd_size = len(payload)

    # Comando principale
    main_cmd = (cmd_size << 2) & 0xFF  # Mode 0, dimensione nei bit 2-6

    # Calcola checksum
    checksum = (main_cmd + sum(payload)) % 256

    # Assembla il comando completo
    command = bytes([sync, main_cmd]) + payload + bytes([checksum, 0x0A])

    return command


def test_all_patterns(port, baudrate):
    """Testa tutti i pattern disponibili."""
    patterns = [
        (0, "Nessun pattern (campo solido)"),
        (1, "Griglia"),
        (2, "Scacchiera"),
        (4, "Linee verticali"),
        (8, "Linee orizzontali"),
        (9, "Linee diagonali")
    ]

    for pattern_id, description in patterns:
        cmd = build_test_pattern_command(pattern_id)
        send_command(port, baudrate, cmd, f"Pattern #{pattern_id}: {description}")

        # Attendi che l'utente osservi il pattern
        input(f"Pattern {pattern_id} - {description}. Premi Invio per continuare...")


def set_power_mode(port, baudrate, mode):
    """
    Imposta la modalità di alimentazione.

    Modalità:
    0: Normale
    1: Standby
    2: Sleep
    """
    # Byte di sincronizzazione
    sync = 0x55

    # Payload del comando
    dlpc_addr = 0x36
    read_len = 0x00
    sub_addr = 0x02
    params = bytes([mode])

    payload = bytes([dlpc_addr, read_len, sub_addr]) + params

    # Calcola la dimensione del payload
    cmd_size = len(payload)

    # Comando principale
    main_cmd = (cmd_size << 2) & 0xFF  # Mode 0, dimensione nei bit 2-6

    # Calcola checksum
    checksum = (main_cmd + sum(payload)) % 256

    # Assembla il comando completo
    command = bytes([sync, main_cmd]) + payload + bytes([checksum, 0x0A])

    mode_names = ["Normale", "Standby", "Sleep"]
    mode_name = mode_names[mode] if mode < len(mode_names) else f"Modalità {mode}"

    return send_command(port, baudrate, command, f"Imposta modalità di alimentazione: {mode_name}")


def set_source_select(port, baudrate, source):
    """
    Seleziona la sorgente di input.

    Sorgenti:
    0: RGB parallelo
    2: DSI
    """
    # Byte di sincronizzazione
    sync = 0x55

    # Payload del comando
    dlpc_addr = 0x36
    read_len = 0x00
    sub_addr = 0x05
    params = bytes([source])

    payload = bytes([dlpc_addr, read_len, sub_addr]) + params

    # Calcola la dimensione del payload
    cmd_size = len(payload)

    # Comando principale
    main_cmd = (cmd_size << 2) & 0xFF  # Mode 0, dimensione nei bit 2-6

    # Calcola checksum
    checksum = (main_cmd + sum(payload)) % 256

    # Assembla il comando completo
    command = bytes([sync, main_cmd]) + payload + bytes([checksum, 0x0A])

    source_names = {0: "RGB parallelo", 2: "DSI"}
    source_name = source_names.get(source, f"Sorgente {source}")

    return send_command(port, baudrate, command, f"Selezione sorgente: {source_name}")


def send_raw_command(port, baudrate, hex_string):
    """Invia un comando grezzo sotto forma di stringa esadecimale."""
    try:
        # Converti la stringa hex in bytes
        data = bytes.fromhex(hex_string)

        # Invia il comando
        return send_command(port, baudrate, data, "Comando grezzo")

    except ValueError:
        logger.error("Formato esadecimale non valido")
        return False


def main():
    """Funzione principale."""
    parser = argparse.ArgumentParser(description='Test DLP LightCrafter 160CP')
    parser.add_argument('-p', '--port', default='/dev/ttyAMA5', help='Porta seriale (default: /dev/ttyAMA5)')
    parser.add_argument('-b', '--baudrate', type=int, default=9600, help='Baud rate (default: 9600)')
    parser.add_argument('-t', '--test-patterns', action='store_true', help='Testa tutti i pattern')
    parser.add_argument('-m', '--power-mode', type=int, choices=[0, 1, 2],
                        help='Imposta modalità di alimentazione (0=Normale, 1=Standby, 2=Sleep)')
    parser.add_argument('-s', '--source', type=int, choices=[0, 2],
                        help='Seleziona sorgente (0=RGB, 2=DSI)')
    parser.add_argument('-r', '--raw', help='Invia comando grezzo (in formato esadecimale)')

    args = parser.parse_args()

    logger.info(f"Utilizzo della porta {args.port} a {args.baudrate} baud")

    # Esegui i comandi richiesti
    if args.test_patterns:
        test_all_patterns(args.port, args.baudrate)

    if args.power_mode is not None:
        set_power_mode(args.port, args.baudrate, args.power_mode)

    if args.source is not None:
        set_source_select(args.port, args.baudrate, args.source)

    if args.raw:
        send_raw_command(args.port, args.baudrate, args.raw)

    # Se nessun argomento specifico è fornito, mostra pattern orizzontali
    if not any([args.test_patterns, args.power_mode is not None,
                args.source is not None, args.raw]):
        logger.info("Nessun comando specifico, mostro pattern di linee orizzontali...")
        cmd = build_test_pattern_command(8)
        send_command(args.port, args.baudrate, cmd, "Pattern di linee orizzontali")

    logger.info("Test completato")


if __name__ == "__main__":
    main()