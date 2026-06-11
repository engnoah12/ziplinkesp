############################
# date: 2026-06-10 00:00 #
#
# Skriver ett giltigt ZipLink-credential till ett NFC-kort.
# Stöder NTAG213/Ultralight och Mifare Classic 1K/4K.
# Kortet kan sedan skannas för att låsa upp porten.
#
# Kör i MicroPython REPL:
#   exec(open('nfc_write_credential.py').read())
#
from machine import SoftI2C, Pin
import utime
from nfc_pn532 import PN532, PN532Error

EXPIRY = "20271231235959"
PORT   = "1"

i2c = SoftI2C(scl=Pin(17, Pin.PULL_UP), sda=Pin(16, Pin.PULL_UP), freq=100000)
nfc = PN532(i2c)

print("Initierar PN532...")
try:
    fw = nfc.begin()
    print(f"  PN5{fw['ic']:02X} v{fw['ver']}.{fw['rev']}")
except PN532Error as e:
    print(f"  FEL: {e}")
    raise

# ── Generera credential ───────────────────────────────────────────────────────

print("\nGenererar credential...")
from testHASH import calcHashes
data        = f"{EXPIRY}/p{PORT}"
_, new_hash = calcHashes(data)
credential  = f"{data}::{new_hash}"
print(f"  Credential: {credential[:48]}...")
print(f"  Längd:      {len(credential)} tecken")

# ── Identifiera korttyp ───────────────────────────────────────────────────────

print("\nHall kortet mot lasaren...")
uid, tg, sak = None, None, None
while uid is None:
    result = nfc.read_card_full(timeout_ms=500)
    if result:
        uid, tg, sak = result

if sak in (0x08, 0x18):
    card_type = 'mifare_classic'
    print(f"  Korttyp: Mifare Classic ({'1K' if sak == 0x08 else '4K'})")
elif sak == 0x00:
    card_type = 'ntag'
    print(f"  Korttyp: NTAG / Ultralight")
else:
    card_type = 'unknown'
    print(f"  Korttyp: okand (SAK=0x{sak:02X})")

print(f"  UID: {uid.hex().upper()}")

# ── Skriv credential ──────────────────────────────────────────────────────────

print("\nSkriver credential...")
ok = False
if card_type == 'mifare_classic':
    ok = nfc.mifare_write_text(tg, credential, uid)
elif card_type == 'ntag':
    ok = nfc.write_ndef_text(tg, credential)
else:
    print("  Okand korttyp — kan inte skriva")
    raise RuntimeError("Unsupported card type")

if not ok:
    print("  FEL: skrivning misslyckades")
    raise RuntimeError("Write failed")
print("  Skrivet OK!")

# ── Verifiera ─────────────────────────────────────────────────────────────────

utime.sleep_ms(500)
print("\nVerifierar — laser tillbaka (hall kvar kortet)...")
# Ny skanning for frascht tg-kontext
r2 = None
while r2 is None:
    r2 = nfc.read_card_full(timeout_ms=500)
uid2, tg2, _ = r2
if card_type == 'mifare_classic':
    read_back = nfc.mifare_read_text(tg2, uid2)
elif card_type == 'ntag':
    read_back = nfc.read_ndef_text(tg2)

if read_back == credential:
    print("  Verifiering OK!")
else:
    print(f"  FEL: fick tillbaka: {read_back}")
    raise RuntimeError("Verification failed")

print(f"\nKlart! Hall kortet mot lasaren och kar test_nfc_access.py for att testa upplasningen.")
