#!/usr/bin/env python3
# main_i2c.py
import time
import os, sys
from smbus2 import SMBus

# 1) Metti il folder padre di dlpc342x/ in PYTHONPATH
proj_root = os.path.dirname(__file__)
sys.path.insert(0, proj_root)

# 2) Importa i moduli auto-generati TI
from dlpc342x.dlpc342x import (
    DLPC342Xinit,
    WriteOperatingModeSelect,
    ReadOperatingModeSelect,
    OperatingMode
)

# 3) Apri il bus I2C-1 e definisci l’indirizzo del DLPC3421 (0x36)
bus = SMBus(3)
DLPC_ADDR = 0x36

# 4) Callback per scrittura e lettura
def write_command(payload, protocol_data):
    # payload = [opcode, param1, ...]
    opcode = payload[0]
    params = payload[1:]
    # write_i2c_block_data(addr, cmd, data_list)
    bus.write_i2c_block_data(DLPC_ADDR, opcode, params)

def read_command(num_bytes, payload, protocol_data):
    opcode = payload[0]
    params = payload[1:]
    # invia comando
    bus.write_i2c_block_data(DLPC_ADDR, opcode, params)
    # leggi num_bytes dal registro “0” (dummy)
    data = bus.read_i2c_block_data(DLPC_ADDR, 0, num_bytes)
    return list(data)

# 5) Inizializza il driver TI con i callback I2C
DLPC342Xinit(read_command, write_command)
time.sleep(0.1)  # piccolo delay

# 6) Test: imposta TestPatternGenerator e leggilo
print(">> Imposto TestPatternGenerator…")
wr = WriteOperatingModeSelect(OperatingMode.TestPatternGenerator)
print("   WriteSuccessful:", wr.Successful)

time.sleep(0.05)
sr, mode = ReadOperatingModeSelect()
print(f">> ReadSuccessful: {sr.Successful}, Modalità = {mode.name} ({mode.value})")

# 7) Chiudi il bus I2C
bus.close()
