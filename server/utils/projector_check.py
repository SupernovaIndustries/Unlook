#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Script di diagnosi per il DLP LightCrafter 160CP
Tenta vari approcci per comunicare con il dispositivo
"""

import time
import serial
import sys
import logging
import binascii

# Configurazione logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("DLP_DIAG")

# Porta da utilizzare
PORT = "/dev/ttyAMA5"  # Cambia questo se necessario
BAUD_RATES = [9600, 115200, 57600, 38400, 19200]


def send_raw_bytes(port, baudrate, data, timeout=1.0):
    """Invia byte grezzi e legge la risposta."""
    logger.info(f"Tentativo su {port} a {baudrate} baud con dati: {data.hex()}")

    try:
        # Configura la porta seriale con varie opzioni
        ser = serial.Serial(
            port=port,
            baudrate=baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=timeout
        )

        # Pulizia dei buffer
        ser.reset_input_buffer()
        ser.reset_output_buffer()

        # Invia i dati
        ser.write(data)
        logger.debug(f"Dati inviati: {data.hex()}")

        # Attesa prima di leggere
        time.sleep(0.2)

        # Leggi la risposta
        response = ser.read(100)  # Leggi fino a 100 byte

        if response:
            logger.info(f"Risposta ricevuta: {response.hex()}")
        else:
            logger.warning("Nessuna risposta ricevuta")

        # Chiudi la connessione
        ser.close()
        return response

    except Exception as e:
        logger.error(f"Errore nella comunicazione: {e}")
        return None


def build_read_version_command():
    """Costruisce il comando di lettura versione."""
    sync = 0x55
    main_cmd = 0x08  # Mode 0, size 2
    dlpc_addr = 0x36
    read_len = 0x04
    sub_addr = 0x28

    # Calcola checksum
    checksum = (main_cmd + dlpc_addr + read_len + sub_addr) % 256
    delimiter = 0x0A

    return bytes([sync, main_cmd, dlpc_addr, read_len, sub_addr, checksum, delimiter])


def build_test_pattern_command(pattern_num=8):
    """Costruisce il comando per mostrare un pattern di test."""
    sync = 0x55

    # Parametri del comando
    dlpc_addr = 0x36
    read_len = 0x00
    sub_addr = 0x0B
    params = bytes([0x03, 0x70, 0x01, pattern_num])

    # Calcola la dimensione del payload
    payload = bytes([dlpc_addr, read_len, sub_addr]) + params
    cmd_size = len(payload)

    # Costruisci il comando principale
    main_cmd = cmd_size << 2  # Mode 0, size in bits 2-6

    # Calcola checksum
    checksum_data = bytes([main_cmd]) + payload
    checksum = sum(checksum_data) % 256

    # Assemblaggio comando completo
    command = bytes([sync, main_cmd]) + payload + bytes([checksum, 0x0A])

    return command


def try_different_formats(port):
    """Prova diversi formati di comando per vedere quali funzionano."""
    logger.info("==== TEST CON FORMATI DIVERSI ====")

    # Versione originale dalla documentazione
    cmd1 = bytes([0x55, 0x0C, 0x36, 0x04, 0x28, 0x6E, 0x0A])

    # Versione alternativa
    cmd2 = build_read_version_command()

    # Versione con punteggiatura alternativa - alcuni dispositivi usano CR+LF
    cmd3 = bytes([0x55, 0x0C, 0x36, 0x04, 0x28, 0x6E, 0x0D, 0x0A])

    # Pattern di test orizzontale
    cmd4 = build_test_pattern_command(8)

    commands = [
        ("Standard dalla documentazione", cmd1),
        ("Formato ricostruito", cmd2),
        ("Con CR+LF", cmd3),
        ("Pattern di test", cmd4)
    ]

    for baudrate in BAUD_RATES:
        for name, cmd in commands:
            logger.info(f"Provo comando {name} a {baudrate} baud")
            send_raw_bytes(port, baudrate, cmd)
            time.sleep(1)  # Pausa tra i comandi


def loopback_test(port):
    """Test di loopback per verificare che la porta UART funzioni correttamente."""
    logger.info("==== TEST DI LOOPBACK ====")

    logger.info("Questo test richiede di collegare TX a RX del dispositivo di test.")
    logger.info("Verifica che TX di Raspberry Pi sia connesso a RX del DLP e viceversa.")

    try:
        ser = serial.Serial(port, 9600, timeout=1)
        test_data = b"TESTLOOPBACK"

        logger.info(f"Invio: {test_data}")
        ser.write(test_data)
        time.sleep(0.1)

        response = ser.read(len(test_data))
        logger.info(f"Risposta: {response}")

        if response == test_data:
            logger.info("Test di loopback riuscito! La connessione UART funziona.")
        else:
            logger.info("Test di loopback fallito. Verifica le connessioni.")

        ser.close()
    except Exception as e:
        logger.error(f"Errore nel test di loopback: {e}")


def brute_force_test(port, baudrate=9600):
    """Tenta un approccio brute force inviando vari pattern di bit."""
    logger.info("==== TEST BRUTE FORCE ====")

    patterns = [
        bytes([0x55]),  # Solo sync
        bytes([0xAA]),  # Pattern alternativo
        bytes([0x55, 0x00]),  # Sync + zero
        bytes([0x55, 0x0A]),  # Sync + newline
        bytes([0xFF, 0xFF, 0xFF]),  # Tutti 1s
        bytes([0x00, 0x00, 0x00]),  # Tutti 0s
        bytes([0x55, 0x55, 0x55]),  # Ripetizione sync
        bytes(range(0, 10)),  # Conteggio
        bytes([0x55, 0x01, 0x00, 0x0A]),  # Comando minimo
    ]

    for i, pattern in enumerate(patterns):
        logger.info(f"Test pattern #{i + 1}: {pattern.hex()}")
        response = send_raw_bytes(port, baudrate, pattern)
        time.sleep(0.5)


def main():
    """Funzione principale."""
    port = PORT
    if len(sys.argv) > 1:
        port = sys.argv[1]

    logger.info(f"Utilizzo della porta {port} per i test di diagnosi")

    # Esegui i test
    try_different_formats(port)
    brute_force_test(port)
    # loopback_test(port)  # Richiede connessione TX-RX, disabilitare se non necessario

    logger.info("Test di diagnosi completati.")


if __name__ == "__main__":
    main()