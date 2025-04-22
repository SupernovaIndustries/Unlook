import serial
import time

# Apri la seriale
ser = serial.Serial('/dev/serial0', 9600, timeout=1)
time.sleep(0.1)

def calc_checksum(data):
    return sum(data) & 0xFF

def send_cmd(subaddr, payload=b''):
    length = len(payload) + 1
    frame = bytearray([0x55, 0x32, length, subaddr]) + payload      # 0x32 = Read Main Cmd
    frame.append(calc_checksum(frame[1:]))
    frame.append(0x0A)
    ser.write(frame)
    ser.flush()

# Manda Read Version
send_cmd(subaddr=0x28)
time.sleep(0.1)

# Leggi e stampa tutti i byte in arrivo
resp = ser.read(ser.in_waiting or 32)
print("Got:", resp.hex())
