from smbus2 import SMBus

def write_vertical_lines(
    i2c_bus=3,              # ← Aggiornato
    i2c_addr=0x1B,          # ← Verifica se diverso per il tuo DLP
    border=1,               # 1 = bordo abilitato
    background_color=6,     # bianco
    foreground_color=3,     # nero
    foreground_line_width=4,
    background_line_width=4
):
    def setbits(val, width, shift):
        mask = (1 << width) - 1
        return (val & mask) << shift

    opcode = 0x0B
    byte1 = setbits(border, 1, 7)
    byte2 = setbits(background_color, 3, 0) | setbits(foreground_color, 2, 4)
    data = [byte1, byte2, foreground_line_width, background_line_width]

    with SMBus(i2c_bus) as bus:
        bus.write_i2c_block_data(i2c_addr, opcode, data)
        print("✅ Griglia verticale nera proiettata su sfondo bianco.")

# ESEMPIO USO
write_vertical_lines()
