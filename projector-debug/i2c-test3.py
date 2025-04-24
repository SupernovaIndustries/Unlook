#!/usr/bin/env python3
# grid_via_i2c.py

import time
from smbus2 import SMBus

# Parametri I²C
I2C_BUS   = 3     # bus hardware su Raspberry Pi (SDA=GPIO2, SCL=GPIO3)
DLPC_ADDR = 0x1B  # indirizzo 7-bit (0x36/0x37 → 0x1B)

def send_i2c_command(bus, opcode, params):
    """Scrive opcode e params su I²C."""
    bus.write_i2c_block_data(DLPC_ADDR, opcode, params)

def read_i2c_response(bus, opcode, length):
    """Invia il byte di sub-address (opcode) e legge length byte di risposta."""
    # manda solo il registro (senza dati) per iniziare la read
    bus.write_byte(DLPC_ADDR, opcode)
    # legge length byte dal registro “0x00”
    return list(bus.read_i2c_block_data(DLPC_ADDR, 0x00, length))

def main():
    with SMBus(I2C_BUS) as bus:
        # 1) Imposta TestPatternGenerator (opcode 0x05, param 0x01)
        print("→ Scrivo TestPatternGenerator…")
        send_i2c_command(bus, 0x05, [0x01])
        time.sleep(0.05)

        # 2) Leggi e verifica la modalità (opcode 0x06 restituisce 1 byte)
        resp = read_i2c_response(bus, 0x06, 1)
        print("← Modalità letta:", resp)

        # 3) Stampa la griglia (opcode 0x0B, param 0x03)
        print("→ Disegno griglia…")
        send_i2c_command(bus, 0x0B, [0x03])
        time.sleep(0.05)

        # 4) (opz.) cancella la griglia ripristinando border=0
        # print("→ Rimuovo griglia…")
        # send_i2c_command(bus, 0x0B, [0x00])

if __name__ == "__main__":
    main()
