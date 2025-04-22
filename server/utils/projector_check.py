import time, serial

# 1) Apri la porta UART5 (o AMA0 se preferisci) a 115200, timeout 1 s
ser = serial.Serial('/dev/ttyAMA5', 115200, timeout=1)
# 2) Lascialo riposare per dargli il tempo di boot (~2 s)
time.sleep(2.0)

# 3) Pulisci eventuali dati spuri
ser.reset_input_buffer()
ser.reset_output_buffer()

def checksum(data_bytes):
    return sum(data_bytes) & 0xFF

def send_mspm0(subaddr, payload=b''):
    """
    Costruisce e invia un frame MSPM0:
      Sync = 0x55
      MainCmd = ((len(payload)+1) << 2) | 0x02
      Sub‑Address = subaddr
      Payload = …
      Checksum = sum(MainCmd,Subaddr,Payload) mod 256
      Delimiter = 0x0A
    """
    size     = len(payload) + 1
    main_cmd = (size << 2) | 0x02
    frame    = bytearray([0x55, main_cmd, subaddr]) + payload
    frame.append(checksum(frame[1:]))
    frame.append(0x0A)
    print("TX:", frame.hex())
    ser.write(frame)
    ser.flush()
    # attendi un po’ prima del prossimo comando
    time.sleep(0.1)

def read_resp():
    resp = ser.read(128)
    if resp:
        print("RX:", resp.hex())

# --- 1. (Opzionale) Leggi versione firmware ---
send_mspm0(0x28)  # Read Version
read_resp()

# --- 2. Disabilita ogni input video esterno (Write External Video Source Format) ---
# subaddr=0x07, payload 0x00 = no video
send_mspm0(0x07, b'\x00')

# --- 3. Freeze (blocca il DMD per riconfigurare in sicurezza) ---
send_mspm0(0x1A, b'\x01')

# --- 4. Seleziona Test Pattern Generator come sorgente ---
send_mspm0(0x05, b'\x01')

# --- 5. Invia il pattern “linee orizzontali” ---
payload = bytes([0x03,  # Horizontal lines
                 0x70,  # FG=White(7) in alto nibble, BG=Black(0) in basso
                 0x01,  # foreground width
                 0x09]) # background width
send_mspm0(0x0B, payload)

# --- 6. Unfreeze (mostra il nuovo pattern) ---
send_mspm0(0x1A, b'\x00')

print("Se tutto è OK, ora sul proiettore dovresti vedere le linee orizzontali.")
