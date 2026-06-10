############################
# date: 2026-06-10 00:00 #
#
# Full NFC access control test for ZipLink.
# Tests all three credential sources:
#   - Android HCE (phone with ZipLink app)
#   - Apple Wallet VAS (iPhone with ZipLink pass)
#   - Plain NFC card (UID printed)
#
# Run on ESP32 in REPL:
#   exec(open('test_nfc_access.py').read())
#
from machine import SoftI2C, Pin
import utime
from nfc_pn532 import PN532, PN532Error
from nfc_access import check_access, ZIPLINK_AID, APPLE_VAS_AID

i2c = SoftI2C(scl=Pin(17, Pin.PULL_UP), sda=Pin(16, Pin.PULL_UP), freq=100000)
nfc = PN532(i2c)

print("Initializing PN532...")
try:
    fw = nfc.begin()
    print(f"  PN5{fw['ic']:02X}  v{fw['ver']}.{fw['rev']}")
except PN532Error as e:
    print(f"  ERROR: {e}")
    raise

print(f"\nZipLink AID : {ZIPLINK_AID.hex().upper()}")
print(f"Apple VAS   : {APPLE_VAS_AID.hex().upper()}")
print("\nHall ett kort, Android-telefon eller iPhone mot lasaren...")
print("(Ctrl+C for att avbryta)\n")

last_uid = None
while True:
    result = check_access(nfc, timeout_ms=500)

    if result is None:
        last_uid = None
        utime.sleep_ms(100)
        continue

    # Debounce — don't repeat the same card
    if result['uid'] == last_uid:
        utime.sleep_ms(100)
        continue
    last_uid = result['uid']

    print(f"--- NFC presentation ---")
    print(f"  Kalla:    {result['source']}")
    print(f"  Data:     {result['uid'][:40]}{'...' if len(result['uid']) > 40 else ''}")

    if result['source'] == 'card_uid':
        print(f"  Resultat: NEKAT (inget credential, endast UID)")
    elif result['granted']:
        print(f"  Resultat: BEVILJAT  Portar: {', '.join(result['ports'])}")
    else:
        print(f"  Resultat: NEKAT (ogiltigt credential)")
    print()
    utime.sleep_ms(500)
