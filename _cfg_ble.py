############################
# date: 2026-05-07 00:00 #

from micropython import const

BLE_DEVICE_NAME: str = const("ZipLink")

# 100 ms advertising interval — short enough for fast discovery, long enough
# to not dominate the BLE radio when the lock is idle.
BLE_ADV_INTERVAL_US: int = const(100_000)

# How long the ESP32 waits for the phone to send its HMAC response after connecting.
# If no response arrives within this window the connection is dropped and advertising resumes.
BLE_CONN_TIMEOUT_S: int = const(15)

# Rate-limiting: after this many failed HMAC attempts in one connection the phone is
# disconnected and advertising is paused for BLE_LOCKOUT_S seconds.
BLE_MAX_FAIL: int    = const(5)
BLE_LOCKOUT_S: int   = const(30)

# 128-bit UUIDs for the ZipLink GATT service, modelled on Nordic UART Service layout.
# CHALLENGE: ESP32 sends a random nonce here (read + notify)
# RESPONSE:  phone writes port + HMAC here (write)
BLE_SVC_UUID: str      = const('6E400001-B5A3-F393-E0A9-E50E24DCCA9E')
BLE_CHR_CHALLENGE: str = const('6E400002-B5A3-F393-E0A9-E50E24DCCA9E')
BLE_CHR_RESPONSE: str  = const('6E400003-B5A3-F393-E0A9-E50E24DCCA9E')
