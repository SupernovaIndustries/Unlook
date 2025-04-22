import time, serial

# 1) Apri la UART5 o AMA0 a 115200
ser = serial.Serial('/dev/ttyAMA5', 115200, timeout=1)
time.sleep(0.1)

def checksum(data_bytes):
    return sum(data_bytes) & 0xFF

def send_mspm0(subaddr, payload=b''):
    # MSPM0: main_cmd = ((len(payload)+1) << 2) | 0x02
    size = len(payload) + 1
    main_cmd = (size << 2) | 0x02
    frame = bytearray([0x55, main_cmd, subaddr]) + payload
    frame.append(checksum(frame[1:]))  # checksum su main_cmd, subaddr e payload
    frame.append(0x0A)                 # delimiter
    print("TX:", frame.hex())
    ser.write(frame)
    ser.flush()
    time.sleep(0.05)

def read_resp():
    resp = ser.read(64)
    print("RX:", resp.hex())

# --- Leggi versione firmware
send_mspm0(0x28)   # subaddr 0x28 = Read Version
read_resp()

# --- Mostra test‐pattern “horizontal lines”
# payload: [pattern=0x03, FG=0x7,BG=0x0 → 0x70, fore_width=1, back_width=9]
send_mspm0(0x0B, bytes([0x03, 0x70, 0x01, 0x09]))
print("Ora guarda il proiettore: dovresti vedere linee orizzontali.")
