############################
# date: 2026-06-09 00:00 #
#
# BLE file updater service.
# Registers a GATT service alongside BLELock so a phone can push new .py files
# to the ESP32 over Bluetooth without needing a USB cable or WiFi.
#
# Auth uses the same HMAC-SHA256 challenge-response pattern as BLELock, but
# with a separate key (HASH_KEY_UPD from _key_upd.py) and the full 32-byte
# digest (not truncated) since file writes are higher-stakes than unlocking.
#
# Phone protocol (one session):
#   1. Connect → ESP32 notifies a 16-byte nonce on UPD_CHALLENGE
#   2. Phone writes HMAC-SHA256(HASH_KEY_UPD, hex(nonce)) → UPD_AUTH
#   3. Phone writes ASCII filename, e.g. b"main.py" → UPD_FILENAME
#   4. Phone writes file data in ≤200-byte chunks → UPD_DATA  (repeat as needed)
#   5. Phone writes one command byte → UPD_COMMIT:
#        0x01 = write file to flash
#        0x02 = abort, discard buffer
#        0x03 = write file to flash, then reboot ESP32
#
# Steps 3–5 can be repeated in the same session to update multiple files
# before disconnecting.
#
# BLELock owns the BLE instance and IRQ handler. It calls on_connect(),
# on_disconnect(), and on_write() on this class to forward relevant events.
# Handles are injected via set_handles() after gatts_register_services().
#
import gc
gc.collect()

import bluetooth
import os
import uasyncio as asyncio
from micropython import const

from _cfg_ble import (
    UPD_SVC_UUID, UPD_CHR_CHALLENGE, UPD_CHR_AUTH,
    UPD_CHR_FILENAME, UPD_CHR_DATA, UPD_CHR_COMMIT,
    UPD_AUTH_TIMEOUT_S, UPD_SESSION_TIMEOUT_S,
    UPD_MAX_FILE_BYTES, UPD_ALLOWED_FILES,
)
from _utils import dbg, green, red

_FLAG_READ   = const(0x0002)
_FLAG_WRITE  = const(0x0008)
_FLAG_NOTIFY = const(0x0010)

_NONCE_LEN = const(16)
_HMAC_LEN  = const(32)  # Full SHA-256 digest — not truncated like the lock service

_CMD_COMMIT = const(0x01)
_CMD_ABORT  = const(0x02)
_CMD_REBOOT = const(0x03)


def _ct_eq(a, b):
    """Constant-time bytes comparison to avoid timing side-channels."""
    if len(a) != len(b):
        return False
    result = 0
    for x, y in zip(a, b):
        result |= x ^ y
    return result == 0


class BLEUpdater:
    # Service definition read by BLELock to register both services in one call.
    SERVICE = (
        bluetooth.UUID(UPD_SVC_UUID),
        (
            (bluetooth.UUID(UPD_CHR_CHALLENGE), _FLAG_READ | _FLAG_NOTIFY),
            (bluetooth.UUID(UPD_CHR_AUTH),      _FLAG_WRITE),
            (bluetooth.UUID(UPD_CHR_FILENAME),  _FLAG_WRITE),
            (bluetooth.UUID(UPD_CHR_DATA),      _FLAG_WRITE),
            (bluetooth.UUID(UPD_CHR_COMMIT),    _FLAG_WRITE),
        ),
    )

    def __init__(self):
        self._ble      = None
        self._conn     = None
        self._nonce    = None
        self._authed   = False
        self._filename = None
        self._buf      = bytearray()
        self._overflow = False

        # Data captured in IRQ, consumed in task()
        self._auth_data     = None
        self._filename_data = None
        self._commit_cmd    = None

        # Flags: ThreadSafeFlag is safe to set() from BLE IRQ context
        self._connect_flag = asyncio.ThreadSafeFlag()
        self._write_flag   = asyncio.ThreadSafeFlag()

        # Characteristic handles — filled by BLELock via set_handles()
        self._h_challenge = None
        self._h_auth      = None
        self._h_filename  = None
        self._h_data      = None
        self._h_commit    = None
        # Tuple of write handles so BLELock can route IRQ writes here
        self._handles     = ()

    def set_handles(self, ble, h_challenge, h_auth, h_filename, h_data, h_commit):
        self._ble         = ble
        self._h_challenge = h_challenge
        self._h_auth      = h_auth
        self._h_filename  = h_filename
        self._h_data      = h_data
        self._h_commit    = h_commit
        self._handles     = (h_auth, h_filename, h_data, h_commit)
        # Pre-allocate attribute buffers so incoming writes are not silently truncated
        ble.gatts_write(h_auth,     bytes(_HMAC_LEN))
        ble.gatts_write(h_filename, bytes(32))
        ble.gatts_write(h_data,     bytes(200))
        ble.gatts_write(h_commit,   bytes(1))
        dbg("UPD: handles set")

    # ── IRQ callbacks ─────────────────────────────────────────────────────────
    # Called from BLELock._irq — must be fast, no allocation beyond bytearray.extend().

    def on_connect(self, conn_handle):
        self._conn     = conn_handle
        self._authed   = False
        self._filename = None
        self._buf      = bytearray()
        self._overflow = False
        self._connect_flag.set()

    def on_disconnect(self):
        self._conn   = None
        self._nonce  = None
        self._authed = False

    def on_write(self, value_handle):
        if value_handle == self._h_data:
            # Accumulate chunks directly — phone may send many without waiting.
            # Only accepted after successful auth.
            if not self._authed:
                return
            chunk = self._ble.gatts_read(self._h_data)
            if len(self._buf) + len(chunk) <= UPD_MAX_FILE_BYTES:
                self._buf.extend(chunk)
            else:
                self._overflow = True
            return
        # Auth / filename / commit: capture and wake the task
        if value_handle == self._h_auth:
            self._auth_data = self._ble.gatts_read(self._h_auth)
        elif value_handle == self._h_filename:
            self._filename_data = self._ble.gatts_read(self._h_filename)
        elif value_handle == self._h_commit:
            cmd = self._ble.gatts_read(self._h_commit)
            self._commit_cmd = cmd[0] if cmd else 0
        self._write_flag.set()

    # ── Async task ────────────────────────────────────────────────────────────

    async def task(self):
        while True:
            await self._connect_flag.wait()

            # Generate nonce in task context (not in IRQ), then notify the phone.
            # 500 ms delay gives the phone time to subscribe to notifications.
            self._nonce = os.urandom(_NONCE_LEN)
            if self._ble is None:
                continue
            self._ble.gatts_write(self._h_challenge, self._nonce)
            await asyncio.sleep_ms(500)
            if self._conn is not None:
                self._ble.gatts_notify(self._conn, self._h_challenge, self._nonce)
                dbg("UPD: nonce sent")

            # Phase 1: wait for auth within the timeout window
            try:
                await asyncio.wait_for(self._write_flag.wait(), UPD_AUTH_TIMEOUT_S)
            except asyncio.TimeoutError:
                red("UPD: auth timeout")
                continue

            auth_data = self._auth_data
            self._auth_data = None
            if not self._verify_auth(auth_data):
                red("UPD: auth failed")
                if self._conn is not None:
                    self._ble.gap_disconnect(self._conn)
                continue

            self._authed = True
            green("UPD: authenticated")

            # Phase 2: session loop — filename → data chunks → commit
            # The loop exits on commit, abort, disconnect, or inactivity timeout.
            while self._conn is not None:
                try:
                    await asyncio.wait_for(
                        self._write_flag.wait(), UPD_SESSION_TIMEOUT_S
                    )
                except asyncio.TimeoutError:
                    red("UPD: session timeout")
                    if self._conn is not None:
                        self._ble.gap_disconnect(self._conn)
                    break

                if self._filename_data is not None:
                    raw = self._filename_data
                    self._filename_data = None
                    try:
                        name = raw.rstrip(b'\x00').decode('ascii')
                        self._filename = name
                        self._buf      = bytearray()
                        self._overflow = False
                        dbg(f"UPD: filename={name}")
                    except Exception:
                        red("UPD: invalid filename encoding")
                        self._filename = None
                    continue

                if self._commit_cmd is not None:
                    cmd = self._commit_cmd
                    self._commit_cmd = None
                    if cmd == _CMD_ABORT:
                        red("UPD: session aborted by phone")
                        break
                    elif cmd == _CMD_COMMIT:
                        self._do_commit(cmd)
                        # Stay in session — phone may send more files
                    elif cmd == _CMD_REBOOT:
                        self._do_commit(cmd)
                        break

            self._authed   = False
            self._filename = None
            self._buf      = bytearray()
            gc.collect()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _verify_auth(self, auth_data):
        if self._nonce is None or auth_data is None:
            return False
        if len(auth_data) != _HMAC_LEN:
            return False
        try:
            from binascii import hexlify
            from elock_hmac_sha256 import hmac_sha256
            from _key_upd import HASH_KEY_UPD
            msg      = hexlify(self._nonce).decode()
            expected = hmac_sha256(HASH_KEY_UPD, msg)
            del HASH_KEY_UPD, hmac_sha256, hexlify
            gc.collect()
            return _ct_eq(expected, auth_data)
        except Exception as e:
            red(f"UPD: auth error {e}")
            return False

    def _do_commit(self, cmd):
        if self._overflow:
            red(f"UPD: file exceeds {UPD_MAX_FILE_BYTES}b limit, aborting")
            return
        if not self._filename:
            red("UPD: no filename set before commit")
            return
        if self._filename not in UPD_ALLOWED_FILES:
            red(f"UPD: '{self._filename}' not in allowed-files whitelist")
            return

        try:
            os.rename(self._filename, self._filename + '.bak')
        except OSError:
            pass  # File doesn't exist yet — first write, no backup needed

        try:
            with open(self._filename, 'wb') as f:
                f.write(self._buf)
            green(f"UPD: wrote {len(self._buf)} bytes → {self._filename}")
        except Exception as e:
            red(f"UPD: write failed: {e}")
            return

        self._buf      = bytearray()
        self._filename = None
        gc.collect()

        if cmd == _CMD_REBOOT:
            green("UPD: rebooting")
            try:
                os.remove('boot_ok.flag')
            except OSError:
                pass
            import machine
            machine.reset()
