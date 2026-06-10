############################
# date: 2026-06-10 00:00 #
#
# NFC access control for ZipLink.
# Supports three sources of credential:
#
#   1. Android HCE (Host Card Emulation)
#      Phone acts as NFC card. ESP32 selects ZipLink AID and reads
#      the credential string in a proprietary GET CREDENTIAL APDU.
#      Requires a ZipLink Android app with an HCE service.
#
#   2. Apple Wallet VAS (Value Added Service)
#      Phone presents an Apple Wallet pass. ESP32 selects Apple VAS AID
#      and reads the pass data via GET VAS DATA. The pass must contain
#      a ZipLink credential in its NFC message.
#      Requires an Apple Developer account + Wallet pass certificate.
#
#   3. Physical NFC card (Mifare/ISO 14443A)
#      Plain card UID — can be used for a pre-registered whitelist.
#
# Credential format (same as QR code, for maximum code reuse):
#   YYYYMMDDHHMMSS/pPORT::BASE64_HMAC
#
# Example:
#   20261231235959/p1::abc123==
#
import gc
import utime
from nfc_pn532 import PN532

# ── AIDs ──────────────────────────────────────────────────────────────────────

# ZipLink proprietary AID: F0 (proprietary prefix) + "ZIPLINK" in ASCII
# Android HCE app must register this AID in its AndroidManifest.xml
ZIPLINK_AID = bytes([0xF0, 0x5A, 0x49, 0x50, 0x4C, 0x4E, 0x4B])

# Apple VAS AID (Value Added Service)
# Used to read data from Apple Wallet passes via NFC
APPLE_VAS_AID = bytes([0xA0, 0x00, 0x00, 0x06, 0x17, 0x00, 0x07, 0x00, 0x08])

# ── APDU constants ────────────────────────────────────────────────────────────

# ISO 7816 SELECT AID
_SELECT_AID     = bytes([0x00, 0xA4, 0x04, 0x00])
_SW_OK          = bytes([0x90, 0x00])

# Proprietary GET CREDENTIAL command (Android HCE)
# CLA=0x80 (proprietary), INS=0x20, P1=0x00, P2=0x00, Le=0x00
_GET_CREDENTIAL = bytes([0x80, 0x20, 0x00, 0x00, 0x00])

# Apple VAS GET VAS DATA command
_GET_VAS_DATA   = bytes([0x00, 0x01, 0x00, 0x00, 0x00])


def _select_aid(nfc, tg, aid):
    """Send SELECT AID APDU. Returns True if 90 00 received."""
    apdu = _SELECT_AID + bytes([len(aid)]) + aid + bytes([0x00])
    resp = nfc.send_apdu(tg, apdu)
    return resp is not None and resp[-2:] == _SW_OK


# ── Credential reading ────────────────────────────────────────────────────────

def read_credential(nfc, timeout_ms=2000):
    """
    Wait for an NFC presentation and return a (credential, source) tuple.

    credential : str  — ZipLink credential string, or UID hex for plain cards
    source     : str  — 'hce_android' | 'vas_ios' | 'card_uid'

    Returns (None, None) if nothing was found within timeout_ms.
    """
    result = nfc.read_card_full(timeout_ms=timeout_ms)
    if result is None:
        return None, None

    uid, tg = result

    # 1. Try Android HCE
    cred = _read_hce(nfc, tg)
    if cred:
        gc.collect()
        return cred, 'hce_android'

    # 2. Try Apple VAS
    cred = _read_vas(nfc, tg)
    if cred:
        gc.collect()
        return cred, 'vas_ios'

    # 3. Fall back to plain card UID
    gc.collect()
    return uid.hex().upper(), 'card_uid'


def _read_hce(nfc, tg):
    """
    Android HCE flow:
      SELECT ZipLink AID → GET CREDENTIAL → credential string
    Returns credential string or None.
    """
    try:
        if not _select_aid(nfc, tg, ZIPLINK_AID):
            return None
        resp = nfc.send_apdu(tg, _GET_CREDENTIAL, timeout_ms=1500)
        if resp is None or len(resp) < 3:
            return None
        if resp[-2:] != _SW_OK:
            return None
        return resp[:-2].decode('ascii')
    except Exception:
        return None


def _read_vas(nfc, tg):
    """
    Apple VAS flow:
      SELECT VAS AID → GET VAS DATA → credential string from pass NFC field.

    NOTE: In production, the VAS response is AES-128-EBC encrypted with the
    merchant private key. Until the ZipLink Apple Developer account and VAS
    merchant ID are registered, this returns the raw (unencrypted) payload for
    development/testing only.
    """
    try:
        if not _select_aid(nfc, tg, APPLE_VAS_AID):
            return None
        resp = nfc.send_apdu(tg, _GET_VAS_DATA, timeout_ms=1500)
        if resp is None or len(resp) < 5:
            return None
        if resp[-2:] != _SW_OK:
            return None
        # VAS response: [version(1)] [status(1)] [payload_len(2)] [payload(...)]
        # For production: payload is AES-128 encrypted — decrypt here with merchant key
        payload = resp[4:-2]
        if not payload:
            return None
        try:
            return payload.decode('ascii')
        except Exception:
            return None
    except Exception:
        return None


# ── Credential verification ───────────────────────────────────────────────────

def verify_credential(credential):
    """
    Verify a ZipLink NFC credential using the same logic as QR codes.
    Returns (valid: bool, ports: list[str]).

    Credential format: YYYYMMDDHHMMSS/p1::BASE64_HMAC
    Reuses testHASH.hashTest() and NVS replay protection.
    """
    if '::' not in credential:
        return False, []
    try:
        from testHASH import hashTest
        import uasyncio as asyncio
        pos   = credential.index('::')
        _hash = credential[pos + 2:]
        _data = credential[:pos]

        valid = asyncio.run(hashTest(_hash, _data))
        if not valid:
            return False, []

        ports = ['1']
        if '/p' in _data:
            for part in _data.split('/'):
                if part.startswith('p'):
                    candidates = [p for p in part[1:].split(',') if p.isdigit()]
                    if candidates:
                        ports = candidates
                        break

        return True, ports

    except Exception as e:
        from _utils import red
        red(f"NFC: verify error {e}")
        return False, []


# ── High-level access check ───────────────────────────────────────────────────

def check_access(nfc, timeout_ms=2000):
    """
    Full access check: read NFC → verify credential → return result.

    Returns dict:
      {
        'granted': bool,
        'ports':   list[str],   # e.g. ['1'] or ['1','2']
        'source':  str,         # 'hce_android' | 'vas_ios' | 'card_uid'
        'uid':     str,         # raw credential or UID
      }
    or None if no NFC presentation detected.
    """
    credential, source = read_credential(nfc, timeout_ms=timeout_ms)
    if credential is None:
        return None

    if source == 'card_uid':
        # Plain card — no cryptographic credential, access denied by default.
        # A whitelist check could be added here in the future.
        return {'granted': False, 'ports': [], 'source': source, 'uid': credential}

    valid, ports = verify_credential(credential)
    return {'granted': valid, 'ports': ports, 'source': source, 'uid': credential}
