########################################################
# date: 2025-04-17 00:00 #
from micropython import const
import gc
from utime import ticks_add,ticks_diff,ticks_ms,sleep_ms

ROK: bytes = const(b'\x02\x00\x00\x01\x00\x33\x31')
WRITEZ: bytes = const(b'\x7e\x00\x08')
TAIL: bytes = const(b'\xab\xcd')
PRE: bytes = const(b'begin')
SUF: bytes = const(b'ending')

from findBaudrate import initGM60
uart=initGM60()
del initGM60; gc.collect()

def tb(value: int = 0, length: int = 1):
    return int(value).to_bytes(length, "little")

def serialWait():
    print("Wait:", ">> ",end='')
    while not uart.txdone(): sleep_ms(1)        
    data = uart.read(7)
    if data == ROK:
        print("Got response",data.hex(':'))
        return True
    return False

def wZone(zone: int, values: int | bytes | tuple) -> None:
    while uart.any():
        print("R",end='')
        uart.read(uart.any())
    while True:    
        if type(values) is int:
            values = tb(values)
        elif type(values) is tuple:
            tmp = bytearray()
            for v in values:
                tmp += tb(v)
            values = bytes(tmp)
        lens: int = len(values)
        uart.write(WRITEZ + tb(lens, 2) + tb(zone) + values + TAIL)
        if serialWait():
            break
        print("Retry")        


def init_gm60():
    wZone(0x00, 0x01)  # Triggermode=suspend=fast response.
    wZone(0x02, (0x00, 0b00))  # Notrigger / no settlement
    wZone(0x05, 0x00)  # (I)nterval in x100ms ( like response )
    wZone(0x06, 0x00)  # (T)ime active in x100ms ( I=10,T=5, Scanner 5 on, 5 off)
    wZone(0x07, 0x00)  # Autosleep
    wZone(0x0B, 0x35)  # 0x25)  # Time for sound = BLINK speed (no response)
    wZone(0x0D, 0b0000_0000)  # Input / Output Coding
    wZone(0x0E, 0x00)  # Turn off sounds
    wZone(0x13, 1 << 7 | 0xff)  # 90)  # Same QR read delay x 100ms (Off)
    wZone(0x14, 0x00)  # Reserved time for information output (x10ms)
    wZone(0x15, 0x63)  # Lamp brightness
    wZone(0x1A, 0b0100_0001)  # OutConfig 0x04+2bytes (len)
    wZone(0x1B, (0b1001_1111, 0b1011_1010, 0b1101_1100, 0b1111_1110))
    wZone(0x1F, 0x1)  # Cycle time for singel led/zone  x100ms
    wZone(0x60, 0b1010_1010)  # Output format
    wZone(0x62, len(PRE) << 4 | len(SUF))  # B7-4=PRE/B3-0=SUF
    wZone(0x63, PRE)  # Prefix 0x63 -> 0x71
    wZone(0x72, SUF)  # Suffix ...
    wZone(0xB0, 0)  # Output whole datastring
    wZone(0x00, 0b1_000_01_10)  # Trigger mode Continous

init_gm60()