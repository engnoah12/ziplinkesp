############################
# date: 2026-03-27 00:00 #
from machine import reset,reset_cause; import gc
if reset_cause() >3: print("Need hardreset!!!")
del reset_cause

from micropython import opt_level;opt_level(5) #mem_info,qstr_info
from _key_new import HASH_KEY_NEW_ID,HASH_KEY_NEW
print("\tboot.py")
print(f"Key{'':<10}:{HASH_KEY_NEW[0:8]}")
print(f"Key-ID{'':>7}:{HASH_KEY_NEW_ID}")
del HASH_KEY_NEW,HASH_KEY_NEW_ID
gc.collect()

