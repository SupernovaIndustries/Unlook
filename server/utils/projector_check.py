import time, serial

# Sostituisci con la tua porta (es. '/dev/ttyAMA5' o '/dev/serial0')
PORT = '/dev/ttyAMA5'
BAUD = 115200

# Comandi da testare: (subaddr, payload_bytes)
COMMANDS = [
    (0x28, b''),                    # Read Version
    (0x0B, bytes([0x03,0x70,0x01,0x09])),  # Test Pattern Select (horizontal lines)
]

# Mode bits da provare: 0x00..0x03 (plain, MSPM1, MSPM0, ecc.)
MODES = [0x00, 0x01, 0x02, 0x03]

def checksum(data):
    return sum(data) & 0xFF

def build_frame(mode, subaddr, payload):
    size     = len(payload) + 1
    main_cmd = ((size << 2) | mode) & 0xFF
    frame    = bytearray([0x55, main_cmd, subaddr]) + payload
    frame.append(checksum(frame[1:]))
    frame.append(0x0A)
    return frame

def try_all():
    ser = serial.Serial(PORT, BAUD, timeout=0.5)
    time.sleep(1)
    ser.reset_input_buffer()
    ser.reset_output_buffer()
    for subaddr, payload in COMMANDS:
        print(f"\n=== Testing subaddr=0x{subaddr:02X}, payload={payload.hex() or '(none)'} ===")
        for mode in MODES:
            frame = build_frame(mode, subaddr, payload)
            print(f"MODE={mode:02b} → TX: {frame.hex()}")
            ser.write(frame)
            time.sleep(0.1)
            resp = ser.read(64)
            print("    RX:", resp.hex() or "(none)")
    ser.close()

if __name__ == '__main__':
    try_all()
