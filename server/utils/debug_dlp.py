import time, serial

ser = serial.Serial('/dev/serial0', 9600, timeout=1)

def checksum(data):
    return sum(data) & 0xFF

def send_mspm0(subaddr, payload=b''):
    # MainCmd: Mode=MSPM0 (0x02), Size=(len+1)<<2, Addr=0
    size = len(payload) + 1
    main_cmd = (size<<2) | 0x02
    frame = bytearray([0x55, main_cmd, subaddr]) + payload
    frame.append(checksum(frame[1:]))
    frame.append(0x0A)
    print("TX:", frame.hex())
    ser.write(frame)
    ser.flush()
    time.sleep(0.05)

# 0x0B = Test Pattern Select (sub-address MSPM0)
# payload [b1,b2,b3,b4] per manual MSPM0 §2.2: Horizontal lines, FG white, BG black, widths
send_mspm0(0x0B, bytes([0x03, 0x70, 0x01, 0x09]))
