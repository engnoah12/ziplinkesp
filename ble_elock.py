############################
# date: 2026-06-04 00:00 #
#
# BLE hands-free authentication protocol:
#
#   1. ESP32 advertises as "ZipLink" over BLE.
#   2. Phone connects to the GATT service.
#   3. ESP32 generates a 16-byte cryptographic nonce using os.urandom(),
#      writes it to the CHALLENGE characteristic, and notifies the phone.
#   4. Phone has BLE_CONN_TIMEOUT_S seconds to respond. If it doesn't,
#      the connection is dropped and advertising resumes automatically.
#   5. Phone sends 31 bytes to the RESPONSE characteristic:
#        byte[0]     : port number to unlock (1–3)
#        byte[1:15]  : purchase expiry as ASCII "YYYYMMDDHHMMSS" (14 bytes)
#        byte[15:31] : HMAC-SHA256(HASH_KEY_NEW, hex(nonce)+':'+port+':'+expiry)[:16]
#   6. ESP32 recomputes the expected HMAC, compares 16 bytes, then checks that
#      the expiry timestamp is strictly newer than the last accepted BLE ticket
#      stored in NVS ('bledate'/'last'). Both checks must pass → unlock.
#
# The nonce is single-use: a new one is generated on every connection, so
# capturing and replaying a valid response provides no access.
# The expiry ties access to a server-issued purchase ticket, so a leaked key
# alone cannot grant permanent access — the ticket must be current.
#
import gc
gc.collect()

import bluetooth
import os
import uasyncio as asyncio
from micropython import const

from _cfg_ble import (
    BLE_DEVICE_NAME, BLE_ADV_INTERVAL_US, BLE_CONN_TIMEOUT_S,
    BLE_SVC_UUID, BLE_CHR_CHALLENGE, BLE_CHR_RESPONSE,
    BLE_MAX_FAIL, BLE_LOCKOUT_S,
)
from _utils import dbg, green, red

# BLE IRQ event constants (from MicroPython bluetooth module)
_IRQ_CENTRAL_CONNECT    = const(1)
_IRQ_CENTRAL_DISCONNECT = const(2)
_IRQ_GATTS_WRITE        = const(3)

# GATT characteristic property flags
_FLAG_READ   = const(0x0002)
_FLAG_WRITE  = const(0x0008)
_FLAG_NOTIFY = const(0x0010)

_NONCE_LEN  = const(16)  # Bytes of randomness in the challenge
_EXPIRY_LEN = const(14)  # "YYYYMMDDHHMMSS" — ASCII digits from the purchase ticket
_HMAC_LEN   = const(16)  # 128-bit truncated HMAC (1 + 14 + 16 = 31 bytes total)

# GATT service definition: one service with two characteristics.
# Defined once at module level so it lives in flash (const data), not RAM.
_SERVICE = (
    bluetooth.UUID(BLE_SVC_UUID),
    (
        (bluetooth.UUID(BLE_CHR_CHALLENGE), _FLAG_READ | _FLAG_NOTIFY),
        (bluetooth.UUID(BLE_CHR_RESPONSE),  _FLAG_WRITE),
    ),
)


class BLELock:
    def __init__(self, updater=None, nfc_writer=None):
        self._ble = bluetooth.BLE()
        self._ble.active(True)
        self._ble.config(mtu=256)
        self._ble.irq(self._irq)

        self._updater    = updater
        self._nfc_writer = nfc_writer

        # Register all services in one gatts_register_services call — subsequent
        # calls would replace the entire service table.
        svcs = [_SERVICE]
        if updater    is not None: svcs.append(updater.SERVICE)
        if nfc_writer is not None: svcs.append(nfc_writer.SERVICE)

        handles = self._ble.gatts_register_services(tuple(svcs))
        (self._h_challenge, self._h_response) = handles[0]
        idx = 1
        if updater is not None:
            updater.set_handles(self._ble, *handles[idx])
            idx += 1
        if nfc_writer is not None:
            nfc_writer.set_handles(self._ble, *handles[idx])

        # Pre-allocate a 31-byte buffer for RESPONSE so MicroPython doesn't truncate
        # incoming writes to the default 20-byte attribute buffer.
        self._ble.gatts_write(self._h_response, bytes(31))

        self._conn       = None   # Active connection handle, None when idle
        self._nonce      = None   # Current challenge bytes, cleared on disconnect
        self._payload    = None   # Raw bytes written by phone, consumed by task()
        self._fail_count = 0      # Failed HMAC attempts for the current connection
        self._locked_out = False  # True while advertising is paused after too many failures

        # ThreadSafeFlag is safe to set() from the BLE IRQ context (outside asyncio).
        # _connect_flag: fired when a phone connects, starts the timeout window.
        # _verify_flag:  fired when the phone writes a response, wakes the verifier.
        self._connect_flag = asyncio.ThreadSafeFlag()
        self._verify_flag  = asyncio.ThreadSafeFlag()

        # unlock_flag + unlock_ports are read by the monitor task in esp32_elock.py
        self.unlock_flag  = asyncio.ThreadSafeFlag()
        self.unlock_ports = []

        self._advertise()
        dbg("BLE: init ok")

    def _irq(self, event, data):
        if event == _IRQ_CENTRAL_CONNECT:
            conn_handle, _, _ = data
            self._conn       = conn_handle
            self._fail_count = 0  # Fresh connection → reset the failure counter
            # Generate a fresh nonce for this session. os.urandom() uses the
            # ESP32's hardware RNG, making the challenge unpredictable.
            self._nonce = os.urandom(_NONCE_LEN)
            # Write nonce to characteristic so it can be read, but do NOT notify yet.
            # The notify is sent from task() after a short delay to give the phone
            # time to subscribe before the value arrives.
            self._ble.gatts_write(self._h_challenge, self._nonce)
            self._connect_flag.set()
            if self._updater is not None:
                self._updater.on_connect(conn_handle)
            if self._nfc_writer is not None:
                self._nfc_writer.on_connect(conn_handle)
            dbg("BLE: connected")

        elif event == _IRQ_CENTRAL_DISCONNECT:
            self._conn  = None
            self._nonce = None  # Invalidate nonce so a late write can't be processed
            if self._updater is not None:
                self._updater.on_disconnect()
            if self._nfc_writer is not None:
                self._nfc_writer.on_disconnect()
            # During a lockout, task() is responsible for calling _advertise() after
            # the pause — skip it here so we don't re-open advertising too early.
            if not self._locked_out:
                self._advertise()
            dbg("BLE: disconnected")

        elif event == _IRQ_GATTS_WRITE:
            _, value_handle = data
            # Route writes addressed to secondary services before checking lock handles
            if self._updater is not None and value_handle in self._updater._handles:
                self._updater.on_write(value_handle)
                return
            if self._nfc_writer is not None and value_handle in self._nfc_writer._handles:
                self._nfc_writer.on_write(value_handle)
                return
            # Only process writes to RESPONSE, and only if we have an active nonce
            if value_handle == self._h_response and self._nonce is not None:
                self._payload = self._ble.gatts_read(self._h_response)
                self._verify_flag.set()

    def _advertise(self):
        name = BLE_DEVICE_NAME.encode()
        # Standard BLE advertising packet: Flags (LE General Discoverable) + Complete Local Name
        adv = bytes([0x02, 0x01, 0x06, len(name) + 1, 0x09]) + name
        self._ble.gap_advertise(BLE_ADV_INTERVAL_US, adv_data=adv)
        dbg("BLE: advertising")

    async def task(self):
        """Main async loop. Runs as a task in esp32_elock's event loop."""
        while True:
            # Wait for a phone to connect before starting the timeout clock
            await self._connect_flag.wait()

            # Give the phone 1 second to subscribe to notifications before
            # sending the nonce — otherwise the notify arrives before the
            # phone has enabled indications and the value is silently dropped.
            await asyncio.sleep_ms(1000)

            # Send nonce now that the phone has had time to subscribe
            if self._conn is not None:
                self._ble.gatts_notify(self._conn, self._h_challenge, self._nonce)
                dbg("BLE: nonce sent")

            try:
                # Phone must reply within the timeout window, otherwise we assume
                # it connected accidentally (e.g. background BLE scan) and disconnect.
                await asyncio.wait_for(self._verify_flag.wait(), BLE_CONN_TIMEOUT_S)
            except asyncio.TimeoutError:
                # If the updater has an active session the phone is uploading files,
                # not unlocking — wait for it to finish rather than killing the connection.
                if (self._updater    is not None and self._updater._authed) or \
                   (self._nfc_writer is not None and self._nfc_writer._authed):
                    while self._conn is not None:
                        await asyncio.sleep(1)
                    continue
                red("BLE: response timeout, disconnecting")
                if self._conn is not None:
                    # gap_disconnect triggers _IRQ_CENTRAL_DISCONNECT which calls _advertise()
                    self._ble.gap_disconnect(self._conn)
                continue

            payload = self._payload
            nonce   = self._nonce
            self._payload = None

            # Guard against a race where the phone disconnected between setting
            # _verify_flag and this line clearing the nonce
            if nonce is None or payload is None:
                continue

            # Expected payload: 1 byte port + 14 bytes expiry + 16 bytes HMAC = 31 bytes
            if len(payload) != 1 + _EXPIRY_LEN + _HMAC_LEN:
                red(f"BLE: bad payload len {len(payload)}")
                continue

            port_num   = payload[0]
            expiry_raw = payload[1:1 + _EXPIRY_LEN]
            recv_hmac  = payload[1 + _EXPIRY_LEN:]

            if not 1 <= port_num <= 3:
                red(f"BLE: invalid port {port_num}")
                continue

            # Expiry must be 14 ASCII decimal digits ("YYYYMMDDHHMMSS")
            if not all(0x30 <= b <= 0x39 for b in expiry_raw):
                red("BLE: invalid expiry format")
                continue

            expiry_str = expiry_raw.decode()

            # Build the message: hex(nonce) + ':' + port + ':' + expiry
            # Expiry is included so the HMAC covers the purchase time-window,
            # preventing reuse of a key without a valid server-issued ticket.
            from binascii import hexlify
            from elock_hmac_sha256 import hmac_sha256
            from _key_new import HASH_KEY_NEW

            msg      = hexlify(nonce).decode() + ':' + str(port_num) + ':' + expiry_str
            expected = hmac_sha256(HASH_KEY_NEW, msg)
            del HASH_KEY_NEW, hmac_sha256, hexlify, msg
            gc.collect()

            if expected[:_HMAC_LEN] != recv_hmac:
                self._fail_count += 1
                red(f"BLE: auth fail ({self._fail_count}/{BLE_MAX_FAIL})")
                if self._fail_count >= BLE_MAX_FAIL:
                    red(f"BLE: too many failures, locking out for {BLE_LOCKOUT_S}s")
                    self._locked_out = True
                    if self._conn is not None:
                        self._ble.gap_disconnect(self._conn)
                    await asyncio.sleep(BLE_LOCKOUT_S)
                    self._locked_out = False
                    self._advertise()
                continue

            # HMAC OK — check expiry against NVS (replay + purchase-expiry protection)
            from config import NVS_ACTIVE
            if NVS_ACTIVE:
                import utime
                from esp32 import NVS
                _ticket_ok = False
                try:
                    tdate = (
                        int(expiry_str[0:4]),
                        int(expiry_str[4:6]),
                        int(expiry_str[6:8]),
                        int(expiry_str[8:10]),
                        int(expiry_str[10:12]),
                        int(expiry_str[12:14]),
                        0, 0,
                    )
                    tcount   = utime.mktime(tdate)
                    nvs_ble  = NVS('bledate')
                    nvs_last = nvs_ble.get_i32('last')
                    if tcount <= nvs_last:
                        red("BLE: ticket expired or replayed")
                    else:
                        nvs_ble.set_i32('last', tcount)
                        nvs_ble.commit()
                        _ticket_ok = True
                    del nvs_ble
                except Exception as e:
                    red(f"BLE: NVS error {e}")
                del NVS, utime
                gc.collect()
                if not _ticket_ok:
                    continue

            green("BLE: auth ok")
            self.unlock_ports = [str(port_num)]
            self.unlock_flag.set()