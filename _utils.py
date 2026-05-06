########################################################
# date: 2025-02-17 00:00 #
# ... utils
# save on unit as: _utils.py
import gc; gc.collect()
from _crc_xmodem_table import CRC16_XMODEM_TABLE

def calculatecrc16(datas: bytes, crc: int = 0) -> bytes:
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
H1: bytes = const(b"\x7e\x00")
H2: bytes = const(b"\x02\x00")
ROK: bytes = const(H2 + b"\x00")
READZ: bytes = const(H1 + b"\x07")
WRITEZ: bytes = const(H1 + b"\x08")
SAVEZ: bytes = const(H1 + b"\x09")
TAIL: bytes = const(b"\xab\xcd\x0a")


def free():
    return ((gc.mem_alloc()+gc.mem_free())-gc.mem_alloc())



def tb(value: int = 0, length: int = 1, mode: str = "little"):
    return int(value).to_bytes(length, "little")


def tohex(bb):
    from binascii import hexlify
    bb=hexlify(bb)
    del hexlify;gc.collect()
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
    from consts import safe
    if not isinstance(_s, str):
        return ""
    _res = "".join(c if c in safe else _rep for c in _s)
    del safe
    gc.collect()
    return _res
