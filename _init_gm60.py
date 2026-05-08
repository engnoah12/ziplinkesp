########################################################
# date: 2025-04-17 00:00 #
#
# Configures the GM60 QR/barcode scanner via its zone-register protocol.
# All settings are written to RAM here; call savetoEEPROM() separately
# if you want them to survive a scanner power cycle.
#
from micropython import const
import gc
from utime import ticks_add, ticks_diff, ticks_ms, sleep_ms

# These mirror the definitions in _utils.py but are redefined here because
# this module runs before _utils is imported (it's called from esp32_elock.py's init path).
ROK: bytes    = const(b'\x02\x00\x00\x01\x00\x33\x31')  # ACK from GM60
WRITEZ: bytes = const(b'\x7e\x00\x08')                   # Write-zone command header
TAIL: bytes   = const(b'\xab\xcd')                       # Frame terminator
PRE: bytes    = const(b'begin')                           # Payload prefix configured into scanner
SUF: bytes    = const(b'ending')                          # Payload suffix configured into scanner

from findBaudrate import initGM60
uart = initGM60()
del initGM60; gc.collect()


def tb(value: int = 0, length: int = 1):
    return int(value).to_bytes(length, "little")


def serialWait():
    """Block until TX is complete and the GM60 sends an ACK (ROK)."""
    print("Wait:", ">> ", end='')
    while not uart.txdone(): sleep_ms(1)
    data = uart.read(7)
    if data == ROK:
        print("Got response", data.hex(':'))
        return True
    return False


def wZone(zone: int, values: int | bytes | tuple) -> None:
    """Write a value to a GM60 zone register. Retries until the scanner ACKs."""
    while uart.any():
        print("R", end='')
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
    """Write the full GM60 configuration sequence.

    Register map (selected entries):
      0x00 - Trigger mode: 0x01=suspend (wait for command), 0b1_000_01_10=continuous scan
      0x02 - Trigger/settlement: disable auto-trigger and settlement delay
      0x05 - Interval between scans in x100ms (0=minimum)
      0x06 - Active scan window in x100ms (0=always on in continuous mode)
      0x07 - Auto-sleep timeout (0=disabled)
      0x0B - LED blink speed when no QR is found (0x35 = fast)
      0x0D - I/O coding: all disabled
      0x0E - Buzzer: 0x00=silent (we use LED feedback instead)
      0x13 - Minimum interval before re-reading the same code, x100ms (0x80 = off)
      0x14 - Output hold time x10ms (0=immediate)
      0x15 - Illumination LED brightness (0x63 = 99%)
      0x1A - Output format: 0x41 = include 2-byte length prefix in frame
      0x1B - LED zone colours (4-zone RGB config)
      0x1F - LED zone cycle time x100ms
      0x60 - Output format flags
      0x62 - PRE length (high nibble) / SUF length (low nibble)
      0x63 - Prefix bytes (written across registers 0x63..0x71)
      0x72 - Suffix bytes
      0xB0 - Transmit the full raw data string
    """
    wZone(0x00, 0x01)               # Suspend trigger mode during config
    wZone(0x02, (0x00, 0b00))       # No auto-trigger, no settlement
    wZone(0x05, 0x00)               # Minimum scan interval
    wZone(0x06, 0x00)               # Continuous active window
    wZone(0x07, 0x00)               # No auto-sleep
    wZone(0x0B, 0x35)               # Fast blink when searching
    wZone(0x0D, 0b0000_0000)        # I/O coding off
    wZone(0x0E, 0x00)               # Buzzer off
    wZone(0x13, 1 << 7 | 0xff)     # Same-code re-read delay: off (bit7=1)
    wZone(0x14, 0x00)               # No output hold delay
    wZone(0x15, 0x63)               # 99% LED brightness
    wZone(0x1A, 0b0100_0001)        # Include 2-byte length prefix in output frame
    wZone(0x1B, (0b1001_1111, 0b1011_1010, 0b1101_1100, 0b1111_1110))  # Zone LED colours
    wZone(0x1F, 0x1)                # LED cycle time: 100ms
    wZone(0x60, 0b1010_1010)        # Output format flags
    wZone(0x62, len(PRE) << 4 | len(SUF))   # Pack PRE and SUF lengths into one byte
    wZone(0x63, PRE)                # Write prefix string (starts at register 0x63)
    wZone(0x72, SUF)                # Write suffix string
    wZone(0xB0, 0)                  # Output full data string (not just symbology type)
    wZone(0x00, 0b1_000_01_10)      # Switch to continuous scan mode


init_gm60()
