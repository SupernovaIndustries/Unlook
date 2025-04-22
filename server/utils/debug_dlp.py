import time, serial

# Apri UART5 a 115200
ser = serial.Serial('/dev/ttyAMA5', 115200, timeout=1)
time.sleep(0.1)

def checksum(data):
    return sum(data) & 0xFF

def send_mspm0(subaddr, payload=b''):
    size = len(payload) + 1
    main_cmd = (size << 2) | 0x02   # MSPM0 mode bitfield
    frame = bytearray([0x55, main_cmd, subaddr]) + payload
    frame.append(checksum(frame[1:]))
    frame.append(0x0A)
    print("TX:", frame.hex())
    ser.write(frame)
    ser.flush()
    time.sleep(0.05)

def read_resp():
    resp = ser.read(64)
    print("RX:", resp.hex())

# 1) Leggi versione firmware
send_mspm0(0x28)   # subaddr 0x28 = Read Version
read_resp()

# 2) Mostra test‐pattern “horizontal lines”
send_mspm0(0x0B, bytes([0x03, 0x70, 0x01, 0x09]))  # subaddr 0x0B
# (non c’è risposta su TPG, quindi basta guardare il proiettore)
