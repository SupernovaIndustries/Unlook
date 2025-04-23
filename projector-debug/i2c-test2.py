from dlpc342x.dlpc342x import *
from smbus2 import SMBus

# Impostazioni
I2C_BUS  = 3    # tipicamente 1 su Raspberry Pi
I2C_ADDR = 0x1B # indirizzo I2C del DLPC3421 (7-bit)

# Comando WriteGridLines con un pattern base
# OpCode = 0x0B (WriteGridLines)
# Parametri: GridLines = 0x03 per una griglia standard

with SMBus(I2C_BUS) as bus:
    opcode     = 0x0B
    grid_param = 0x00  # o 0x00 se preferisci disabilitare la griglia

    command = [opcode, grid_param]
    bus.write_i2c_block_data(I2C_ADDR, opcode, [grid_param])
    print("✅ Comando inviato: WriteGridLines con parametri:", command)
