#!/usr/bin/env python3
# j3_uart.py

import serial
import time

# 1) Porta COM del tuo adattatore USB-TTL
PORT = 'COM3'
BAUD  = 115200

def open_serial():
    ser = serial.Serial(PORT, BAUD, timeout=0.5)
    ser.reset_input_buffer()
    ser.reset_output_buffer()
    return ser

def send_cmd(ser, cmd, delay=0.2):
    """Invia cmd+CRLF e ritorna la risposta ASCII."""
    packet = cmd.strip() + '\r\n'
    ser.write(packet.encode('ascii'))
    time.sleep(delay)
    return ser.read_all().decode('ascii', errors='ignore').strip()

def main():
    ser = open_serial()
    print(f"[+] Connesso a {PORT}@{BAUD}")

    # 1) Leggi la modalità corrente
    resp = send_cmd(ser, 'ROMD')
    print(">> ROMD  →", resp or "(nessuna risposta)")

    # 2) Imposta TestPatternGenerator (codice 1)
    resp = send_cmd(ser, 'WOMD 1')
    print(">> WOMD 1→", resp or "(nessuna risposta)")

    # 3) Rileggi per conferma
    resp = send_cmd(ser, 'ROMD')
    print(">> ROMD  →", resp or "(nessuna risposta)")

    ser.close()

if __name__ == '__main__':
    main()
