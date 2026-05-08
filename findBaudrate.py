############################
# date: 2025-02-25 00:00 #
#
# Detects and configures the GM60 QR scanner's baud rate at startup.
#
# Strategy:
#   1. Try 57600 bps first (our target rate, listed first in __BAUDS).
#   2. If the scanner doesn't respond, try all other supported rates.
#   3. If found at a wrong rate, send a change-baud command, save to EEPROM,
#      and verify before continuing.
#   4. If the scanner doesn't respond at any rate, send CHANGEMODE at all
#      rates (in case it's stuck in a different output mode) and retry.
#
import gc, utime as time
from machine import UART
from micropython import const, opt_level
opt_level(0)


def fname(f, *args, **kvargs):
    """Decorator that prints a prominent banner with the function name before each call.
    Makes the boot log easier to parse when multiple operations run sequentially."""
    name = str(f).split(' ')[1]
    def fun(*args, **kvargs):
        print(f"\n{'*'*10+name+'*'*10:^80}")
        return f(*args, **kvargs)
    return fun


from consts import BAUDS
# Put target baudrate (57600, index 6) first so seekBPS() usually succeeds on the first try
__BAUDS = list(BAUDS)
__BAUDS.insert(0, BAUDS[6])
del BAUDS; gc.collect()

# 500 ms UART timeout is required because EEPROM write and baud-rate change
# commands take up to ~300 ms for the GM60 to process and acknowledge.
uart = UART(2, timeout=500)


@fname
def resetEEPROM():
    """Factory-reset the GM60 configuration EEPROM. Use only if the scanner
    is in an unknown state that seekBPS() cannot recover from."""
    uart.init(timeout=500)
    from consts import RESETEEPROM
    uart.write(RESETEEPROM)
    print("\nresetEEPROM:", waitSerial())
    del RESETEEPROM; gc.collect()


@fname
def savetoEEPROM():
    """Persist the current GM60 register settings to EEPROM so they survive power cycles."""
    uart.init(timeout=500)
    from consts import SAVETOEEPROM
    uart.write(SAVETOEEPROM)
    print("\nSavetoEEPROM:", waitSerial())
    del SAVETOEEPROM; gc.collect()


@fname
def waitSerial(_nb=7):
    """Block until TX is done, then read _nb bytes from the scanner's response."""
    while not uart.txdone(): time.sleep_ms(1)
    return uart.read(_nb)


@fname
def changeBPS(_bps) -> bool:
    """Send a baud-rate change command for the entry at index _bps in __BAUDS.
    Returns True if the scanner confirms the new rate."""
    uart.init(timeout=500)
    print("\nChange bps:", end='  ')
    _bauds = b'\x7e\x00\x08\x02\x00\x2a'
    _bauds += int(__BAUDS[_bps][1]).to_bytes(2, 'little') + b'\xab\xcd'
    print(_bauds.hex(':'))
    uart.write(_bauds)
    _res = waitSerial()
    if _res is not None: print(_res.hex(':'))
    if _res is not None and \
       _res[:4] == b'\x02\x00\x00\x02' and \
       int.from_bytes(_res[4:6], 'little') == __BAUDS[_bps][1]:
            print("\nFound bps:", b, int(b[1]).to_bytes(2, 'big').hex(':'))
            print(_res.hex(':'), end='')
            del _bauds, _bps, _res; gc.collect()
            return True
    del _bauds, _bps, _res; gc.collect()
    return False


@fname
def changeMode():
    """Broadcast CHANGEMODE at every supported baud rate.
    Used when the scanner is in an unknown mode and won't respond to seekBPS()."""
    uart.init(timeout=500)
    from consts import CHANGEMODE
    print("Change mode:", end='  ')
    for b in __BAUDS:
        print(b[0], end=' ')
        uart.init(b[0])
        uart.write(CHANGEMODE)
        time.sleep_ms(500)
    print()
    print(waitSerial())
    del CHANGEMODE, b; gc.collect()


@fname
def seekBPS() -> None | tuple:
    """Try each baud rate in __BAUDS and return the matching entry if the GM60 responds,
    or None if the scanner cannot be reached at any speed."""
    uart.init(timeout=300)
    while uart.any():
        uart.read(uart.any())
        print("R", end='')

    from consts import SEEKBPS
    print("Seek bps:", end='  ')
    for b in __BAUDS:
        print(b[0], end=' ')
        uart.init(b[0])
        uart.write(SEEKBPS)
        _res = waitSerial(8)
        if _res is not None: print(_res.hex(':'))
        if _res is not None and \
           _res[:4] == b'\x02\x00\x00\x02' and \
           int.from_bytes(_res[4:6], 'little') == b[1]:
                print("\nFound bps:", b, int(b[1]).to_bytes(2, 'big').hex(':'))
                print(_res.hex(':'), end='')
                del SEEKBPS, _res; gc.collect()
                return b
    del SEEKBPS, b, _res; gc.collect()
    return None


@fname
def initGM60():
    """Ensure the GM60 is communicating at 57600 bps (first entry in __BAUDS).
    Handles scanner at wrong rate or stuck in wrong mode. Returns the configured UART."""
    while True:
        _bps = seekBPS()
        if _bps is __BAUDS[0]:
            break
        if _bps is None:
            print("\n\tCan't find gm60, change mode!")
            changeMode()
            continue
        elif _bps is not __BAUDS[0]:
            print("\n\tFound gm60, but wrong baudrate, change bps!")
            changeBPS(0)
            if seekBPS() is __BAUDS[0]:
                print("\n\tSaving settings to EEPROM")
                savetoEEPROM()
            continue
        break
    print("\nAll done!!!")
    del _bps; gc.collect()
    return uart
