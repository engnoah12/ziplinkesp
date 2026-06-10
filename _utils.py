########################################################
# date: 2025-02-17 00:00 #
import gc; gc.collect()

from _crc_xmodem_table import CRC16_XMODEM_TABLE

def calculatecrc16(datas: bytes, crc: int = 0) -> bytes:
    """Table-driven CRC-16/XMODEM over a byte sequence. Returns 2 big-endian bytes."""
    for byte in datas:
        crc = ((crc << 8) & 0xFF00) ^ CRC16_XMODEM_TABLE[((crc >> 8) & 0xFF) ^ byte]
    return int(crc & 0xFFFF).to_bytes(2, "big")

from micropython import const
from config import DEBUG,

ESC: str = "\033["
RST: str = const(f"{ESC}39;49m")
RED: str = const(f"{ESC}31m")
GREEN: str = const(f"{ESC}32m")
BLUE: str = const(f"{ESC}34m")

# GM60 serial protocol frame fragments
# A "write zone" command frame is: WRITEZ + len16_LE + zone_byte + value_bytes + TAIL
H1: bytes    = const(b"\x7e\x00")
H2: bytes    = const(b"\x02\x00")
ROK: bytes   = const(H2 + b"\x00")       # ACK response from GM60 after a successful write
READZ: bytes = const(H1 + b"\x07")       # Read a zone register
WRITEZ: bytes = const(H1 + b"\x08")      # Write a zone register
SAVEZ: bytes  = const(H1 + b"\x09")      # Save current config to GM60 EEPROM
TAIL: bytes   = const(b"\xab\xcd\x0a")   # Frame terminator


def free():
    """Returns available heap in bytes (total - allocated)."""
    return ((gc.mem_alloc() + gc.mem_free()) - gc.mem_alloc())


def tb(value: int = 0, length: int = 1, mode: str = "little"):
    """Convert int to bytes. Shorthand used throughout for building protocol frames."""
    return int(value).to_bytes(length, "little")


def tohex(bb):
    from binascii import hexlify
    bb = hexlify(bb)
    del hexlify; gc.collect()
    return bb


def dbg(st: str, e: str = "\n"):
    if DEBUG:
        print(f"{st}", end=e)


def red(st, nl="\n") -> None:
    dbg(f"{RED}{st}{RST}", e=nl)


def blue(st, nl="\n") -> None:
    dbg(f"{BLUE}{st}{RST}", e=nl)


def green(st, nl="\n") -> None:
    dbg(f"{GREEN}{st}{RST}", e=nl)


def safePrint(_s: str, _rep: str = "_") -> str:
    """Replace non-printable characters before writing to the console.
    Prevents ANSI injection from malicious QR payloads corrupting the terminal."""
    from consts import safe
    if not isinstance(_s, str):
        return ""
    _res = "".join(c if c in safe else _rep for c in _s)
    del safe
    gc.collect()
    return _res
