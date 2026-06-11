############################
# date: 2026-06-11 00:00 #
#
# BLE NFC writer service.
# Lets an admin program ZipLink credentials onto NFC cards/tags over BLE.
#
# Protocol (one session):
#   1. Connect → ESP32 notifies 16-byte nonce on NFC_CHALLENGE
#   2. Admin writes HMAC-SHA256(HASH_KEY_UPD, hex(nonce)) → NFC_AUTH
#   3. Admin writes 15 bytes → NFC_CMD:
#        byte[0]     : port number (1–3)
#        byte[1:15]  : expiry "YYYYMMDDHHMMSS" (14 bytes ASCII)
#   4. ESP32 generates credential, scans for card, writes it
#   5. ESP32 notifies progress on NFC_STATUS:
#        0x01 = waiting for card
#        0x02 = card detected
#        0x03 = writing
#        0x10 + ct_byte + uid = write OK (ct: 0x01=Mifare1K 0x02=Mifare4K 0x03=NTAG)
#        0xF0 = error: card not presented within timeout
#        0xF1 = error: write to card failed
#        0xF2 = error: unsupported card type
#        0xF3 = error: read-back verification failed
#        0xF5 = error: PN532 did not respond
#
# Steps 3–5 can repeat in the same session to program multiple cards.
# Uses HASH_KEY_UPD for auth — same key as the OTA updater.
# BLELock owns the BLE instance; this class receives forwarded IRQ events.
#
import gc
gc.collect()

import bluetooth
import os
import uasyncio as asyncio
from micropython import const

from _cfg_ble import (
    NFC_WRITER_SVC_UUID, NFC_WRITER_CHR_CHALLENGE,
    NFC_WRITER_CHR_AUTH, NFC_WRITER_CHR_CMD, NFC_WRITER_CHR_STATUS,
    NFC_WRITER_AUTH_TIMEOUT_S, NFC_WRITER_CMD_TIMEOUT_S, NFC_WRITER_CARD_TIMEOUT_S,
)
from _utils import dbg, green, red

_FLAG_READ   = const(0x0002)
_FLAG_WRITE  = const(0x0008)
_FLAG_NOTIFY = const(0x0010)

_NONCE_LEN = const(16)
_HMAC_LEN  = const(32)
_CMD_LEN   = const(15)   # 1 byte port + 14 bytes expiry ASCII

_ST_WAITING        = const(0x01)
_ST_DETECTED       = const(0x02)
_ST_WRITING        = const(0x03)
_ST_OK             = const(0x10)
_ST_ERR_TIMEOUT    = const(0xF0)
_ST_ERR_WRITE      = const(0xF1)
_ST_ERR_UNSUPPORT  = const(0xF2)
_ST_ERR_VERIFY     = const(0xF3)
_ST_ERR_PN532      = const(0xF5)
_ST_WIPE_OK        = const(0x11)
_ST_READ_OK        = const(0x20)
_ST_BLANK          = const(0x21)
_ST_ERR_WIPE       = const(0xF4)


def _ct_eq(a, b):
    """Constant-time bytes comparison."""
    if len(a) != len(b):
        return False
    result = 0
    for x, y in zip(a, b):
        result |= x ^ y
    return result == 0


class BLENFCWriter:
    SERVICE = (
        bluetooth.UUID(NFC_WRITER_SVC_UUID),
        (
            (bluetooth.UUID(NFC_WRITER_CHR_CHALLENGE), _FLAG_READ | _FLAG_NOTIFY),
            (bluetooth.UUID(NFC_WRITER_CHR_AUTH),      _FLAG_WRITE),
            (bluetooth.UUID(NFC_WRITER_CHR_CMD),       _FLAG_WRITE),
            (bluetooth.UUID(NFC_WRITER_CHR_STATUS),    _FLAG_READ | _FLAG_NOTIFY),
        ),
    )

    def __init__(self):
        self._ble    = None
        self._conn   = None
        self._nonce  = None
        self._authed = False

        self._auth_data = None
        self._cmd_data  = None

        self._connect_flag = asyncio.ThreadSafeFlag()
        self._auth_flag    = asyncio.ThreadSafeFlag()
        self._cmd_flag     = asyncio.ThreadSafeFlag()

        self._h_challenge = None
        self._h_auth      = None
        self._h_cmd       = None
        self._h_status    = None
        self._handles     = ()

        self._nfc = None  # set by esp32_elock after PN532 init

        # True while a write is in progress — nfc_monitor in esp32_elock pauses
        self.writing_active = False

    def set_handles(self, ble, h_challenge, h_auth, h_cmd, h_status):
        self._ble         = ble
        self._h_challenge = h_challenge
        self._h_auth      = h_auth
        self._h_cmd       = h_cmd
        self._h_status    = h_status
        self._handles     = (h_auth, h_cmd)
        ble.gatts_write(h_auth,      bytes(_HMAC_LEN))
        ble.gatts_write(h_cmd,       bytes(_CMD_LEN))
        ble.gatts_write(h_challenge, bytes(_NONCE_LEN))
        ble.gatts_write(h_status,    bytes(128))
        dbg("NFC-W: handles set")

    def set_nfc(self, nfc):
        """Called by esp32_elock after PN532 initialises — shares the single instance."""
        self._nfc = nfc
        dbg("NFC-W: nfc instance shared")

    # ── IRQ callbacks (called from BLELock._irq — must be fast) ──────────────

    def on_connect(self, conn_handle):
        self._conn      = conn_handle
        self._authed    = False
        self._auth_data = None
        self._cmd_data  = None
        self._connect_flag.set()

    def on_disconnect(self):
        self._conn          = None
        self._nonce         = None
        self._authed        = False
        self.writing_active = False
        # Wake up any waiting coroutines so task() exits the session loop immediately
        self._auth_flag.set()
        self._cmd_flag.set()

    def on_write(self, value_handle):
        if value_handle == self._h_auth:
            self._auth_data = self._ble.gatts_read(self._h_auth)
            self._auth_flag.set()
        elif value_handle == self._h_cmd:
            self._cmd_data = self._ble.gatts_read(self._h_cmd)
            self._cmd_flag.set()

    # ── Async task ────────────────────────────────────────────────────────────

    async def task(self):
        while True:
            await self._connect_flag.wait()

            self._nonce = os.urandom(_NONCE_LEN)
            if self._ble is None:
                continue
            self._ble.gatts_write(self._h_challenge, self._nonce)
            await asyncio.sleep_ms(500)
            if self._conn is not None:
                self._ble.gatts_notify(self._conn, self._h_challenge, self._nonce)
                dbg("NFC-W: nonce sent")

            # Phase 1: wait for HMAC auth
            try:
                await asyncio.wait_for(self._auth_flag.wait(), NFC_WRITER_AUTH_TIMEOUT_S)
            except asyncio.TimeoutError:
                red("NFC-W: auth timeout")
                continue

            auth_data = self._auth_data
            self._auth_data = None
            if not self._verify_auth(auth_data):
                red("NFC-W: auth failed")
                if self._conn is not None:
                    self._ble.gap_disconnect(self._conn)
                continue

            self._authed   = True
            self._cmd_data = None
            green("NFC-W: authenticated")

            # Phase 2: session — receive CMD, write card, repeat
            while self._conn is not None:
                try:
                    await asyncio.wait_for(self._cmd_flag.wait(), NFC_WRITER_CMD_TIMEOUT_S)
                except asyncio.TimeoutError:
                    red("NFC-W: cmd timeout")
                    if self._conn is not None:
                        self._ble.gap_disconnect(self._conn)
                    break

                cmd = self._cmd_data
                self._cmd_data = None
                if cmd is None or len(cmd) < _CMD_LEN:
                    red(f"NFC-W: bad cmd len {len(cmd) if cmd else 0}")
                    continue

                op = cmd[0]
                if op == 0x00:
                    dbg("NFC-W: read cmd")
                    await self._do_read()
                elif op == 0xFF:
                    dbg("NFC-W: wipe cmd")
                    await self._do_wipe()
                else:
                    port_num = op
                    expiry   = bytes(cmd[1:15]).decode('ascii', 'ignore')
                    dbg(f"NFC-W: write cmd port={port_num} expiry={expiry}")
                    await self._do_write(port_num, expiry)
                gc.collect()

            self._authed        = False
            self.writing_active = False
            gc.collect()

    # ── Write flow ────────────────────────────────────────────────────────────

    async def _do_write(self, port_num, expiry):
        self.writing_active = True
        await asyncio.sleep_ms(300)  # let nfc_monitor finish its current read cycle
        try:
            await self._write_card(port_num, expiry)
        finally:
            self.writing_active = False
        gc.collect()

    async def _write_card(self, port_num, expiry):
        nfc = self._nfc
        if nfc is None:
            red("NFC-W: no PN532 instance")
            self._notify(bytes([_ST_ERR_PN532]))
            return

        # Generate credential on-device (key never leaves ESP32)
        try:
            from testHASH import calcHashes
            data       = f"{expiry}/p{port_num}"
            _, h       = calcHashes(data)
            credential = f"{data}::{h}"
            del calcHashes, h
            gc.collect()
        except Exception as e:
            red(f"NFC-W: credential gen failed {e}")
            self._notify(bytes([_ST_ERR_PN532]))
            return

        # Wait for card
        self._notify(bytes([_ST_WAITING]))
        import utime
        deadline = utime.ticks_add(utime.ticks_ms(), NFC_WRITER_CARD_TIMEOUT_S * 1000)
        uid = tg = sak = None
        while utime.ticks_diff(deadline, utime.ticks_ms()) > 0:
            if self._conn is None:
                del utime
                return
            result = nfc.read_card_full(timeout_ms=300)
            if result:
                uid, tg, sak = result
                break
            await asyncio.sleep_ms(50)
        del utime

        if uid is None:
            red("NFC-W: card timeout")
            self._notify(bytes([_ST_ERR_TIMEOUT]))
            return

        self._notify(bytes([_ST_DETECTED]))
        await asyncio.sleep_ms(100)

        if sak in (0x08, 0x18):
            card_type = 'mifare'
        elif sak == 0x00:
            card_type = 'ntag'
        else:
            red(f"NFC-W: unsupported SAK=0x{sak:02X}")
            self._notify(bytes([_ST_ERR_UNSUPPORT]))
            return

        # Write
        self._notify(bytes([_ST_WRITING]))
        await asyncio.sleep_ms(50)
        if card_type == 'mifare':
            ok = nfc.mifare_write_text(tg, credential, uid)
        else:
            ok = nfc.write_ndef_text(tg, credential)

        if not ok:
            red("NFC-W: write failed")
            self._notify(bytes([_ST_ERR_WRITE]))
            return

        # Read back to verify
        await asyncio.sleep_ms(400)
        import utime as _t
        dl = _t.ticks_add(_t.ticks_ms(), 3000)
        r2 = None
        while _t.ticks_diff(dl, _t.ticks_ms()) > 0:
            r2 = nfc.read_card_full(timeout_ms=300)
            if r2:
                break
            await asyncio.sleep_ms(50)
        del _t

        if r2 is None:
            red("NFC-W: verify read failed")
            self._notify(bytes([_ST_ERR_VERIFY]))
            return

        uid2, tg2, _ = r2
        readback = nfc.mifare_read_text(tg2, uid2) if card_type == 'mifare' else nfc.read_ndef_text(tg2)
        if readback != credential:
            red("NFC-W: verify mismatch")
            self._notify(bytes([_ST_ERR_VERIFY]))
            return

        green(f"NFC-W: OK card={card_type} uid={uid.hex()}")
        ct_byte = 0x01 if sak == 0x08 else (0x02 if sak == 0x18 else 0x03)
        self._notify(bytes([_ST_OK, ct_byte]) + uid)

    # ── Read flow ─────────────────────────────────────────────────────────────

    async def _do_read(self):
        self.writing_active = True
        await asyncio.sleep_ms(300)
        try:
            await self._read_card()
        finally:
            self.writing_active = False
        gc.collect()

    async def _read_card(self):
        nfc = self._nfc
        if nfc is None:
            red("NFC-W: no PN532 instance")
            self._notify(bytes([_ST_ERR_PN532]))
            return

        self._notify(bytes([_ST_WAITING]))
        import utime
        deadline = utime.ticks_add(utime.ticks_ms(), NFC_WRITER_CARD_TIMEOUT_S * 1000)
        uid = tg = sak = None
        while utime.ticks_diff(deadline, utime.ticks_ms()) > 0:
            if self._conn is None:
                del utime; return
            result = nfc.read_card_full(timeout_ms=300)
            if result:
                uid, tg, sak = result
                break
            await asyncio.sleep_ms(50)
        del utime

        if uid is None:
            self._notify(bytes([_ST_ERR_TIMEOUT]))
            return

        self._notify(bytes([_ST_DETECTED]))
        await asyncio.sleep_ms(100)
        ct_byte = 0x01 if sak == 0x08 else (0x02 if sak == 0x18 else 0x03)

        try:
            if sak in (0x08, 0x18):
                text = nfc.mifare_read_text(tg, uid)
            elif sak == 0x00:
                text = nfc.read_ndef_text(tg)
            else:
                self._notify(bytes([_ST_ERR_UNSUPPORT]))
                return
        except Exception as e:
            red(f"NFC-W: read failed {e}")
            self._notify(bytes([_ST_ERR_WRITE]))
            return

        if not text:
            green(f"NFC-W: blank card uid={uid.hex()}")
            self._notify(bytes([_ST_BLANK, ct_byte]) + uid)
            return

        green(f"NFC-W: read ok uid={uid.hex()}")
        self._notify(bytes([_ST_READ_OK, ct_byte, len(uid)]) + uid + text.encode('utf-8'))

    # ── Wipe flow ─────────────────────────────────────────────────────────────

    async def _do_wipe(self):
        self.writing_active = True
        await asyncio.sleep_ms(300)
        try:
            await self._wipe_card()
        finally:
            self.writing_active = False
        gc.collect()

    async def _wipe_card(self):
        nfc = self._nfc
        if nfc is None:
            red("NFC-W: no PN532 instance")
            self._notify(bytes([_ST_ERR_PN532]))
            return

        self._notify(bytes([_ST_WAITING]))
        import utime
        deadline = utime.ticks_add(utime.ticks_ms(), NFC_WRITER_CARD_TIMEOUT_S * 1000)
        uid = tg = sak = None
        while utime.ticks_diff(deadline, utime.ticks_ms()) > 0:
            if self._conn is None:
                del utime; return
            result = nfc.read_card_full(timeout_ms=300)
            if result:
                uid, tg, sak = result
                break
            await asyncio.sleep_ms(50)
        del utime

        if uid is None:
            self._notify(bytes([_ST_ERR_TIMEOUT]))
            return

        self._notify(bytes([_ST_DETECTED]))
        await asyncio.sleep_ms(100)

        try:
            if sak in (0x08, 0x18):
                ok = nfc.mifare_write_text(tg, '', uid)
            elif sak == 0x00:
                ok = nfc.write_ndef_text(tg, '')
            else:
                self._notify(bytes([_ST_ERR_UNSUPPORT]))
                return
        except Exception as e:
            red(f"NFC-W: wipe failed {e}")
            ok = False

        if not ok:
            self._notify(bytes([_ST_ERR_WIPE]))
            return

        green(f"NFC-W: wiped uid={uid.hex()}")
        self._notify(bytes([_ST_WIPE_OK]))

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _notify(self, data):
        if self._ble is None or self._conn is None:
            return
        self._ble.gatts_write(self._h_status, data)
        self._ble.gatts_notify(self._conn, self._h_status, data)

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
            red(f"NFC-W: auth error {e}")
            return False
