import time, serial

# --- Configura la seriale su UART5 ---
ser = serial.Serial('/dev/ttyAMA5', 115200, timeout=1)
time.sleep(0.1)

def checksum(data_bytes):
    return sum(data_bytes) & 0xFF

def send_mspm0(subaddr, payload=b''):
    size = len(payload) + 1
    main_cmd = (size << 2) | 0x02
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

# --- 1) Leggi versione firmware (opzionale) ---
send_mspm0(0x28)   # Read Version
read_resp()

# --- 2) Freeze immagine (Write Image Freeze = subaddr 0x1A, payload 0x01) ---
send_mspm0(0x1A, b'\x01')

# --- 3) Seleziona Test Pattern Generator (Input Source = subaddr 0x05, payload 0x01) ---
send_mspm0(0x05, b'\x01')

# --- 4) Imposta il Test Pattern “horizontal lines” (subaddr 0x0B) ---
send_mspm0(0x0B, bytes([0x03, 0x70, 0x01, 0x09]))

# --- 5) Unfreeze immagine (Write Image Freeze = subaddr 0x1A, payload 0x00) ---
send_mspm0(0x1A, b'\x00')

print("Ora sul proiettore dovresti vedere le linee orizzontali.")
