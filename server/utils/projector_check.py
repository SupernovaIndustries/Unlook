import time, serial

ser = serial.Serial('/dev/ttyAMA5', 115200, timeout=1)
time.sleep(2.0)
ser.reset_input_buffer()
ser.reset_output_buffer()

def send_mspm1(subaddr, payload=b''):
    size     = len(payload) + 1
    main_cmd = (size << 2) | 0x03
    frame    = bytearray([0x55, main_cmd, subaddr]) + payload
    frame.append(sum(frame[1:]) & 0xFF)
    frame.append(0x0A)
    print("TX:", frame.hex())
    ser.write(frame)
    ser.flush()
    time.sleep(0.1)

def read_resp():
    resp = ser.read(128)
    if resp:
        print("RX:", resp.hex())

# 1) Read Version (subaddr 0x28)
send_mspm1(0x28)
read_resp()

# 2) Freeze (0x1A, payload=0x01)
send_mspm1(0x1A, b'\x01')

# 3) Disable video input (0x07, payload=0x00)
send_mspm1(0x07, b'\x00')

# 4) Test Pattern Select “horizontal lines” (0x0B)
send_mspm1(0x0B, bytes([0x03, 0x70, 0x01, 0x09]))

# 5) Operating Mode = Display TPG (0x04, payload=0x01)
send_mspm1(0x04, b'\x01')

# 6) Unfreeze (0x1A, payload=0x00)
send_mspm1(0x1A, b'\x00')

print("Ora guarda il proiettore per le linee orizzontali.")
