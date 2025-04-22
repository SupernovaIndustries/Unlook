import time, serial

# Apri la UART corretta (es. ttyAMA5) a 115200 bps
ser = serial.Serial('/dev/ttyAMA5', 115200, timeout=1)
time.sleep(2.0)               # lascia il tempo al DLP di fare boot

# Pulisci buffer
ser.reset_input_buffer()
ser.reset_output_buffer()

def checksum(data):
    return sum(data) & 0xFF

def send_mspm0(subaddr, payload=b''):
    size     = len(payload) + 1
    main_cmd = (size << 2) | 0x02
    frame    = bytearray([0x55, main_cmd, subaddr]) + payload
    frame.append(checksum(frame[1:]))
    frame.append(0x0A)
    print("TX:", frame.hex())
    ser.write(frame)
    ser.flush()
    time.sleep(0.1)

def read_resp():
    resp = ser.read(128)
    if resp:
        print("RX:", resp.hex())

# 1) (Opzionale) leggi la versione
send_mspm0(0x28)   # Read Version
read_resp()

# 2) Freeze per evitare artefatti
send_mspm0(0x1A, b'\x01')

# 3) Disabilita qualsiasi input video esterno (già in precedenza, ma non fa male)
send_mspm0(0x07, b'\x00')

# 4) Imposta il Test Pattern desiderato
payload_tpg = bytes([0x03,  # horizontal lines
                     0x70,  # FG=white(7)<<4, BG=black(0)
                     0x01,  # fore width
                     0x09]) # back width
send_mspm0(0x0B, payload_tpg)

# 5) **Scrivi l’Operating Mode sulla modalità TPG**
#    subaddr = 0x04, payload = 0x01 (Display – Test Pattern Generator)
send_mspm0(0x04, b'\x01')

# 6) Unfreeze per applicare il pattern
send_mspm0(0x1A, b'\x00')

print("Guardati il proiettore: dovresti finalmente vedere le linee orizzontali.")
