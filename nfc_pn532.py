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
        Returns (uid, tg_num, sak) or None if nothing found.

        sak values:
          0x08 = Mifare Classic 1K
          0x18 = Mifare Classic 4K
          0x00 = NTAG / Mifare Ultralight
          0x20 = ISO 14443-4 (Android HCE, Apple)
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
        tg_num  = resp[2]
        sak     = resp[5]
        uid_len = resp[6]
        if len(resp) < 7 + uid_len:
            return None
        return bytes(resp[7 : 7 + uid_len]), tg_num, sak

    # ── Mifare Classic ───────────────────────────────────────────────────────

    _MIFARE_KEY_DEFAULT = bytes([0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF])

    def mifare_auth(self, tg, block, uid, key=None):
        """Authenticate a Mifare Classic sector (containing block) with Key A."""
        if key is None:
            key = self._MIFARE_KEY_DEFAULT
        apdu = bytes([0x60, block]) + key + uid[:4]
        resp = self.send_apdu(tg, apdu, timeout_ms=500)
        # Successful auth returns empty payload (just SW 90 00 stripped by send_apdu)
        return resp is not None

    def mifare_read_block(self, tg, block):
        """Read 16 bytes from a Mifare Classic block (must be pre-authenticated)."""
        resp = self.send_apdu(tg, bytes([0x30, block]))
        if resp and len(resp) >= 16:
            return bytes(resp[:16])
        return None

    def mifare_write_block(self, tg, block, data):
        """Write exactly 16 bytes to a Mifare Classic block (must be pre-authenticated)."""
        if len(data) != 16:
            data = (bytes(data) + bytes(16))[:16]
        resp = self.send_apdu(tg, bytes([0xA0, block]) + bytes(data))
        return resp is not None

    def mifare_write_text(self, tg, text, uid,
                          blocks=(4, 5, 6, 8, 9), key=None):
        """
        Write a text string to Mifare Classic data blocks.
        Uses blocks in two sectors — authenticates each sector as needed.
        Default blocks: 4,5,6 (sector 1) and 8 (sector 2) = 64 bytes.
        Returns True on success.
        """
        raw = text.encode('utf-8')
        # Store as: 2-byte length (big-endian) + text, padded to block boundaries
        payload = bytes([len(raw) >> 8, len(raw) & 0xFF]) + raw
        payload = (payload + bytes(len(blocks) * 16))[:len(blocks) * 16]

        current_sector = -1
        for i, block in enumerate(blocks):
            sector = block // 4
            if sector != current_sector:
                if not self.mifare_auth(tg, block, uid, key):
                    return False
                current_sector = sector
            chunk = payload[i*16:(i+1)*16]
            if not self.mifare_write_block(tg, block, chunk):
                return False
        return True

    def mifare_read_text(self, tg, uid,
                         blocks=(4, 5, 6, 8, 9), key=None):
        """
        Read a text string written by mifare_write_text().
        Returns the text string, or None on failure.
        """
        current_sector = -1
        payload = bytearray()
        for block in blocks:
            sector = block // 4
            if sector != current_sector:
                if not self.mifare_auth(tg, block, uid, key):
                    return None
                current_sector = sector
            data = self.mifare_read_block(tg, block)
            if data is None:
                return None
            payload.extend(data)

        length = (payload[0] << 8) | payload[1]
        if length == 0 or length > len(payload) - 2:
            return None
        try:
            return payload[2:2 + length].decode('utf-8')
        except Exception:
            return None

    # ── NTAG / Mifare Ultralight page R/W ────────────────────────────────────

    def read_page(self, tg, page):
        """Read 16 bytes (4 pages) from NTAG/Ultralight starting at page."""
        resp = self.send_apdu(tg, bytes([0x30, page]))
        if resp and len(resp) >= 16:
            return bytes(resp[:16])
        return None

    def write_page(self, tg, page, data):
        """Write exactly 4 bytes to NTAG/Ultralight page."""
        if len(data) != 4:
            return False
        resp = self.send_apdu(tg, bytes([0xA2, page]) + bytes(data))
        return resp is not None

    # ── NDEF Text record ──────────────────────────────────────────────────────

    def write_ndef_text(self, tg, text, start_page=4):
        """
        Write a UTF-8 string as an NDEF Text record to an NTAG/Ultralight card.
        Overwrites user memory starting at start_page (default 4).
        Returns True on success.
        """
        text_b   = text.encode('utf-8')
        lang     = b'en'
        # NDEF payload: status(1) + lang(2) + text
        payload  = bytes([len(lang)]) + lang + text_b
        # NDEF record: header(1) + type_len(1) + payload_len(1) + type(1) + payload
        record   = bytes([0xD1, 0x01, len(payload), 0x54]) + payload
        # TLV wrapper: T=03, L=msg_len, V=record, T=FE (end)
        msg      = bytes([0x03, len(record)]) + record + bytes([0xFE])
        # Pad to multiple of 4
        if len(msg) % 4:
            msg += bytes(4 - len(msg) % 4)
        for i in range(0, len(msg), 4):
            if not self.write_page(tg, start_page + i // 4, msg[i:i+4]):
                return False
        return True

    def read_ndef_text(self, tg, start_page=4, max_pages=12):
        """
        Read an NDEF Text record from an NTAG/Ultralight card.
        Returns the text string, or None if no valid NDEF text is found.
        """
        data = bytearray()
        for page in range(start_page, start_page + max_pages, 4):
            chunk = self.read_page(tg, page)
            if chunk is None:
                break
            data.extend(chunk)
            if 0xFE in data:
                break

        if len(data) < 6 or data[0] != 0x03:
            return None
        msg_len = data[1]
        if msg_len + 2 > len(data):
            return None
        rec = data[2:2 + msg_len]
        # rec[0]=header, rec[1]=type_len, rec[2]=payload_len, rec[3]=type('T')
        if len(rec) < 5 or rec[3] != 0x54:
            return None
        payload_len = rec[2]
        payload     = rec[4:4 + payload_len]
        lang_len    = payload[0] & 0x1F
        try:
            return payload[1 + lang_len:].decode('utf-8').rstrip('\x00')
        except Exception:
            return None

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
