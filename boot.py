############################
# date: 2026-03-27 00:00 #

# reset_cause() > 3 means the MCU came back from a watchdog reset or deep sleep,
# which can leave peripherals (UART, BLE) in an undefined state.
from machine import reset, reset_cause
import gc
import os as _os

# Remove any .tmp files left by an interrupted transfer before they can cause confusion.
for _f in [f for f in _os.listdir('/') if f.endswith('.tmp')]:
    try: _os.remove(_f)
    except: pass

# If boot_ok.flag is missing but .bak files exist, the previous update never
# completed a successful boot — restore backups and reboot into known-good firmware.
_bak = [f for f in _os.listdir('/') if f.endswith('.bak')]
try:
    _os.stat('boot_ok.flag')
except OSError:
    if _bak:
        print("boot_ok.flag missing — rolling back")
        for _f in _bak:
            try:
                _os.rename(_f, _f[:-4])
                print(f"  restored {_f[:-4]}")
            except Exception as _e:
                print(f"  rollback err {_f}: {_e}")
        with open('boot_ok.flag', 'w') as _f:
            _f.write('1')
        reset()
del _os, _bak

if reset_cause() > 3:
    print("Need hardreset!!!")
del reset_cause

# opt_level(5): max MicroPython optimization — disables assertions and line-number
# tracking, which saves a few KB of RAM on a heavily loaded MCU.
from micropython import opt_level
opt_level(5)

# Load the HMAC key early so we can print its prefix for visual verification,
# then delete it immediately to minimize the window it lives in RAM.
from _key_new import HASH_KEY_NEW, HASH_KEY_NEW_ID
print("\tboot.py")
print(f"Key{'':<10}:{HASH_KEY_NEW[0:8]}")
print(f"Key-ID{'':>7}:{HASH_KEY_NEW_ID}")
del HASH_KEY_NEW, HASH_KEY_NEW_ID
gc.collect()
