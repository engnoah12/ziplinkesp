############################
# date: 2026-06-10 00:00 #
#
# Test script for PN532 NFC reader.
# Run on ESP32 via mpremote or paste into REPL.
# Initializes PN532, prints firmware version, then loops scanning for cards.
# Hold a card or phone against the reader to see its UID.
#
from machine import SoftI2C, Pin
import utime
from nfc_pn532 import PN532, PN532Error

i2c = SoftI2C(scl=Pin(17, Pin.PULL_UP), sda=Pin(16, Pin.PULL_UP), freq=100000)
nfc = PN532(i2c)

print("Initializing PN532...")
try:
    fw = nfc.begin()
    print(f"  IC:      PN5{fw['ic']:02X}")
    print(f"  Version: {fw['ver']}.{fw['rev']}")
    print(f"  Support: 0x{fw['support']:02X}")
except PN532Error as e:
    print(f"  ERROR: {e}")
    raise

print("\nHall ett kort eller telefon mot lasaren...")
print("(Ctrl+C for att avbryta)\n")

last_uid = None
while True:
    uid = nfc.read_card(timeout_ms=500)
    if uid and uid != last_uid:
        print(f"Kort hittat! UID: {uid.hex().upper()}  ({len(uid)} bytes)")
        last_uid = uid
    elif not uid:
        last_uid = None
    utime.sleep_ms(100)
