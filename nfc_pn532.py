############################
# date: 2026-06-10 00:00 #
#
# Minimal PN532 I2C driver for MicroPython.
# Supports GetFirmwareVersion, SAMConfiguration and InListPassiveTarget
# (ISO 14443A card/phone UID reading).
#
# Usage:
#   from machine import SoftI2C, Pin
#   from nfc_pn532 import PN532
#   i2c = SoftI2C(scl=Pin(17, Pin.PULL_UP), sda=Pin(16, Pin.PULL_UP), freq=100000)
#   nfc = PN532(i2c)
#   nfc.begin()
#   uid = nfc.read_card()
#
import utime
from micropython import const

_PN532_ADDR    = const(0x24)
_HOSTTOPN532   = const(0xD4)
_PN532TOHOST   = const(0xD5)
_CMD_GETFW     = const(0x02)
_CMD_SAMCONFIG = const(0x14)
_CMD_INLIST    = const(0x4A)
_ACK           = b'\x00\x00\xff\x00\xff\x00'


def _lcs(n):
    return (~n + 1) & 0xFF


def _dcs(data):
    return (~sum(data) + 1) & 0xFF


class PN532Error(Exception):
    pass


class PN532:

    def __init__(self, i2c):
        self._i2c = i2c

    # ── Low-level I/O ─────────────────────────────────────────────────────────

    def _write(self, cmd_bytes):
        """Build and send a PN532 frame."""
        data = bytes([_HOSTTOPN532]) + bytes(cmd_bytes)
        n    = len(data)
        frame = bytearray(7 + n)
        frame[0] = 0x00          # preamble
        frame[1] = 0x00          # start code 1
        frame[2] = 0xFF          # start code 2
        frame[3] = n & 0xFF      # length
        frame[4] = _lcs(n)       # LCS
        frame[5:5+n] = data      # TFI + payload
        frame[5+n]   = _dcs(data)  # DCS
        frame[6+n]   = 0x00      # postamble
        self._i2c.writeto(_PN532_ADDR, bytes(frame))

    def _read_raw(self, length, timeout_ms=500):
        """Read from PN532, polling until status byte = 0x01 (ready)."""
        deadline = utime.ticks_add(utime.ticks_ms(), timeout_ms)
        while utime.ticks_diff(deadline, utime.ticks_ms()) > 0:
            try:
                buf = self._i2c.readfrom(_PN532_ADDR, length + 1)
                if buf[0] == 0x01:
                    return buf[1:]
            except OSError:
                pass
            utime.sleep_ms(10)
        return None

    def _read_ack(self):
        buf = self._read_raw(6, timeout_ms=200)
        return buf is not None and buf[:6] == _ACK

    def _read_response(self, timeout_ms=1000):
        """Read and parse a PN532 response frame. Returns payload bytes."""
        buf = self._read_raw(64, timeout_ms=timeout_ms)
        if buf is None:
            return None
        for i in range(len(buf) - 6):
            if buf[i] == 0x00 and buf[i+1] == 0x00 and buf[i+2] == 0xFF:
                length = buf[i+3]
                if (length + buf[i+4]) & 0xFF != 0:
                    continue
                if buf[i+5] != _PN532TOHOST:
                    continue
                # Return everything after TFI up to (but not including) DCS+postamble
                return bytes(buf[i+6 : i+5+length])
        return None

    # ── Public API ────────────────────────────────────────────────────────────

    def get_firmware_version(self):
        """Returns dict {ic, ver, rev, support} or None."""
        self._write([_CMD_GETFW])
        if not self._read_ack():
            return None
        utime.sleep_ms(50)
        resp = self._read_response()
        if resp and len(resp) >= 5 and resp[0] == _CMD_GETFW + 1:
            return {'ic': resp[1], 'ver': resp[2], 'rev': resp[3], 'support': resp[4]}
        return None

    def SAM_config(self):
        """Configure SAM in normal mode (required before card reading)."""
        self._write([_CMD_SAMCONFIG, 0x01, 0x14, 0x01])
        self._read_ack()
        utime.sleep_ms(20)
        self._read_response(timeout_ms=100)

    def begin(self):
        """Initialize PN532. Raises PN532Error if not found."""
        utime.sleep_ms(100)
        fw = self.get_firmware_version()
        if fw is None:
            raise PN532Error("PN532 not found or not responding")
        self.SAM_config()
        return fw

    def read_card(self, timeout_ms=500):
        """
        Scan for one ISO 14443A card or phone.
        Returns UID as bytes, or None if nothing found within timeout.
        """
        result = self.read_card_full(timeout_ms)
        return result[0] if result else None

    def read_card_full(self, timeout_ms=500):
        """
        Scan for one ISO 14443A target.
        Returns (uid, tg_num) where tg_num is used for send_apdu(),
        or None if nothing found.
        """
        self._write([_CMD_INLIST, 0x01, 0x00])
        if not self._read_ack():
            return None
        resp = self._read_response(timeout_ms=timeout_ms)
        if resp is None or len(resp) < 8:
            return None
        if resp[0] != _CMD_INLIST + 1:
            return None
        if resp[1] < 1:
            return None
        tg_num  = resp[2]           # target number for InDataExchange
        uid_len = resp[6]
        if len(resp) < 7 + uid_len:
            return None
        return bytes(resp[7 : 7 + uid_len]), tg_num

    def send_apdu(self, tg_num, apdu, timeout_ms=1000):
        """
        Send an ISO 7816 APDU to a target and return the response bytes,
        or None on error. Uses InDataExchange (0x40).
        The last two bytes of a successful response are SW1=0x90, SW2=0x00.
        """
        self._write([0x40, tg_num] + list(apdu))
        if not self._read_ack():
            return None
        resp = self._read_response(timeout_ms=timeout_ms)
        if resp is None or len(resp) < 2:
            return None
        # resp[0] = 0x41, resp[1] = error byte (0x00 = ok), resp[2:] = card data
        if resp[0] != 0x41 or resp[1] != 0x00:
            return None
        return bytes(resp[2:])
