import serial, time

ser = serial.Serial('/dev/ttyAMA5', 115200, timeout=1)
time.sleep(0.1)

# Read Version: 55 0A 28 2E 0A
ser.write(bytes([0x55,0x0A,0x28,0x2E,0x0A]))
resp = ser.read(16)
print("RX:", resp.hex())
