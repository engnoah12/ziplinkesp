############################
# date: 2026-03-27 00:00 #

# reset_cause() > 3 means the MCU came back from a watchdog reset or deep sleep,
# which can leave peripherals (UART, BLE) in an undefined state.
from machine import reset, reset_cause
import gc
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
