import serial
import time

# Usa 115200 anziché 9600
ser = serial.Serial(
    port='/dev/serial0',
    baudrate=115200,
    bytesize=serial.EIGHTBITS,
    parity=serial.PARITY_NONE,
    stopbits=serial.STOPBITS_ONE,
    timeout=1
)
time.sleep(0.1)

def calc_checksum(data):
    return sum(data) & 0xFF

def send_cmd(subaddr, payload=b''):
    length = len(payload) + 1
    # MainCmd di Read = 0x32
    frame = bytearray([0x55, 0x32, length, subaddr]) + payload
    frame.append(calc_checksum(frame[1:]))
    frame.append(0x0A)
    print("TX:", frame.hex())
    ser.write(frame)
    ser.flush()

def read_resp():
    time.sleep(0.05)
    # Legge fino a 64 byte
    resp = ser.read(64)
    print("RX:", resp.hex())

# --- read version (subaddr 0x28) ---
send_cmd(subaddr=0x28)
read_resp()
