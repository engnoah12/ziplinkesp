############################
# date: 2026-06-09 00:00 #

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

# ── BLE Updater service ───────────────────────────────────────────────────────
# Separate GATT service for authenticated file writes from a phone.
# Uses different UUIDs and a different key (HASH_KEY_UPD) from the lock service
# so a compromised unlock key does not grant update access and vice versa.

# UUIDs: same base as the lock service, sub-range 11–16.
UPD_SVC_UUID: str      = const('6E400011-B5A3-F393-E0A9-E50E24DCCA9E')
UPD_CHR_CHALLENGE: str = const('6E400012-B5A3-F393-E0A9-E50E24DCCA9E')
UPD_CHR_AUTH: str      = const('6E400013-B5A3-F393-E0A9-E50E24DCCA9E')
UPD_CHR_FILENAME: str  = const('6E400014-B5A3-F393-E0A9-E50E24DCCA9E')
UPD_CHR_DATA: str      = const('6E400015-B5A3-F393-E0A9-E50E24DCCA9E')
UPD_CHR_COMMIT: str    = const('6E400016-B5A3-F393-E0A9-E50E24DCCA9E')
UPD_CHR_STATUS: str    = const('6E400017-B5A3-F393-E0A9-E50E24DCCA9E')

UPD_AUTH_TIMEOUT_S: int  = const(15)   # Seconds to authenticate before disconnect
UPD_SESSION_TIMEOUT_S: int = const(60) # Inactivity timeout during an open session
UPD_MAX_FILE_BYTES: int  = const(32768) # Largest file is esp32_elock.py ~24 KB

# Files the updater is allowed to overwrite.
# boot.py and key files are intentionally excluded.
UPD_ALLOWED_FILES = (
    'main.py', 'esp32_elock.py', 'ble_elock.py', 'ble_updater.py',
    'ble_nfc_writer.py', 'nfc_access.py', 'nfc_pn532.py',
    'config.py', 'consts.py', 'elock_hmac_sha256.py', 'testHASH.py',
    '_cfg_ble.py', '_cfg_network.py', '_cfg_serial.py', '_utils.py',
    '_crc_xmodem_table.py',
)

# ── NFC Writer service ────────────────────────────────────────────────────────
# Admin-only BLE service for programming ZipLink credentials onto NFC cards/tags.
# Reuses HASH_KEY_UPD for authentication (same key as OTA updater).
# UUIDs: same base as lock/updater, sub-range 21–25.

NFC_WRITER_SVC_UUID: str      = const('6E400021-B5A3-F393-E0A9-E50E24DCCA9E')
NFC_WRITER_CHR_CHALLENGE: str = const('6E400022-B5A3-F393-E0A9-E50E24DCCA9E')
NFC_WRITER_CHR_AUTH: str      = const('6E400023-B5A3-F393-E0A9-E50E24DCCA9E')
NFC_WRITER_CHR_CMD: str       = const('6E400024-B5A3-F393-E0A9-E50E24DCCA9E')
NFC_WRITER_CHR_STATUS: str    = const('6E400025-B5A3-F393-E0A9-E50E24DCCA9E')

NFC_WRITER_AUTH_TIMEOUT_S: int = const(15)   # Seconds to send HMAC after connect
NFC_WRITER_CMD_TIMEOUT_S: int  = const(60)   # Seconds to receive a write command after auth
NFC_WRITER_CARD_TIMEOUT_S: int = const(30)   # Seconds to present a card to the PN532
