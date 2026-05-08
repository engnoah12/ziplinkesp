from micropython import const

# Printable ASCII range used by safePrint() to strip control characters
# from untrusted input (e.g. QR payload) before writing to the console.
safe = const(" !\"#$%&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`abcdefghijklmnopqrstuvwxyz{|}~")

# GM60 supported baud rates: (bps, register_value, index)
# register_value is the little-endian word the scanner stores in its EEPROM.
# Index 6 (57600 bps) is our target rate — fast enough for reliable streaming,
# slow enough for the ESP32 UART at 3.3 V logic level.
BAUDS = (
    ( 1200, 0x09c4, 0), ( 4800, 0x0271, 1), ( 9600, 0x0139, 2), (14400, 0x00d0, 3),
    (19200, 0x009c, 4), (38400, 0x004e, 5), (57600, 0x0034, 6), (115200, 0x001a, 7)
)

# Raw GM60 serial commands (full protocol frames including header and checksum)
RESETEEPROM  = const(b'\x7e\x00\x08\x01\x00\xd9\x55\xab\xcd')   # Factory-reset EEPROM
SAVETOEEPROM = const(b'\x7e\x00\x09\x01\x00\x00\x00\xde\xc8')   # Persist current config to EEPROM
CHANGEMODE   = const(b'\x7e\x00\x08\x03\x00\x00\x09\x00\x00\xab\xcd')  # Switch to output mode
SEEKBPS      = const(b'\x7e\x00\x07\x01\x00\x2a\x02\xab\xcd')   # Query current baud rate
