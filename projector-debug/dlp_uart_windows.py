# main_i2c.py

from pyftdi.i2c import I2cController
import os, sys, time

# 1) PYTHONPATH per il package TI
proj_root = os.path.dirname(__file__)
sys.path.insert(0, proj_root)

# 2) Import dei comandi auto-generati
from dlpc342x.dlpc342x import DLPC342Xinit, WriteOperatingModeSelect, ReadOperatingModeSelect, OperatingMode

# 3) Configura l’adattatore FTDI in modalità I²C
i2c = I2cController()
# sostituisci l’URL con quello del tuo dispositivo FTDI
i2c.configure('ftdi://ftdi:2232h/1')
slave = i2c.get_port(0x36)  # 0x36 = indirizzo I²C del DLPC342x in write mode

# 4) Callback I²C per il driver TI
def write_command(payload, protocol_data):
    # payload = [opcode, param1, param2…]
    slave.write(bytes(payload))

def read_command(num_bytes, payload, protocol_data):
    # invia il comando
    slave.write(bytes(payload))
    # legge la risposta
    data = slave.read(num_bytes)
    return list(data)

# 5) Inizializza il driver TI con i callback I²C
DLPC342Xinit(read_command, write_command)
time.sleep(0.1)

# 6) Test di funzionamento
print("Imposto TestPatternGenerator…")
wr = WriteOperatingModeSelect(OperatingMode.TestPatternGenerator)
print("  Write OK?", wr.Successful)

time.sleep(0.05)
sr, mode = ReadOperatingModeSelect()
print(f"  Mode: {mode.name}  (Success: {sr.Successful})")

# 7) Chiudi l’I2C
i2c.terminate()
