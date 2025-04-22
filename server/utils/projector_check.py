import time
import numpy as np
import cv2
import serial

# 1. Configura la seriale
ser = serial.Serial(
    port='/dev/serial0',
    baudrate=9600,
    bytesize=serial.EIGHTBITS,
    parity=serial.PARITY_NONE,
    stopbits=serial.STOPBITS_ONE,
    timeout=1
)

def calc_checksum(data_bytes):
    return sum(data_bytes) & 0xFF

def send_uart(subaddr, payload=b''):
    """
    Frame UART per DLPC3421 via MSPM0:
    [0]=0x55
    [1]=MainCmd (Write = 0x36)
    [2]=len(payload)+1   (+1 per subaddr)
    [3]=subaddr (Sub-Address, es. 0x1A)
    [4..]=payload
    [..]=checksum
    [..]=0x0A
    """
    length = len(payload) + 1
    frame = bytearray([0x55, 0x36, length, subaddr]) + payload
    frame.append(calc_checksum(frame[1:]))
    frame.append(0x0A)
    ser.write(frame)
    time.sleep(0.005)

# 2. Freeze immagine (Write Image Freeze = 0x1A, payload 01h) :contentReference[oaicite:0]{index=0}
send_uart(subaddr=0x1A, payload=bytes([0x01]))

# 3. Crop full‑DMD (Write Image Crop = 0x10) a 0,0 → 640×360 :contentReference[oaicite:1]{index=1}
# coord x,y start = 0 → [0,0], width=640 → 0x80,0x02, height=360 → 0x68,0x01 (LSB,MSB)
payload_crop = bytes([0x00,0x00,   # X start LSB,MSB
                      0x00,0x00,   # Y start LSB,MSB
                      0x80,0x02,   # pixels/line = 640
                      0x68,0x01])  # lines/frame = 360
send_uart(subaddr=0x10, payload=payload_crop)

# 4. Test Pattern Select = 0x0B :contentReference[oaicite:2]{index=2}
#   pattern=Horizontal lines (03h), border disabled (b7=0) → Byte1=0x03
#   colore FG=White(7), BG=Black(0) → Byte2=0x70
#   foreground width=1 (LSB=1), background width=9 (LSB=9) → Bytes3,4
payload_tpg = bytes([
    0x03,       # Byte1: pattern=03h
    0x70,       # Byte2: FG=7,BG=0
    0x01,       # Byte3: fore width
    0x09        # Byte4: back width
    # nessun Byte5/6 per horizontal lines
])
send_uart(subaddr=0x0B, payload=payload_tpg)

# 5. Seleziona Test Pattern Generator (Write Input Source Select = 0x05, payload 01h) :contentReference[oaicite:3]{index=3}
send_uart(subaddr=0x05, payload=bytes([0x01]))

# 6. Sblocca immagine (Write Image Freeze = 0x1A, payload 00h)
send_uart(subaddr=0x1A, payload=bytes([0x00]))
