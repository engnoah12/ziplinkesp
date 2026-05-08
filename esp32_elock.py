############################
# date: 2025-02-25 00:00 #
#
# Core lock controller. Runs on ESP32 with MicroPython.
#
# Data flow:
#   GM60 scanner → UART → serialRead() → testHMAC() → tuneandUnlock() → PWM → door
#   BLE phone     → BLE  → ble_elock   → _ble_monitor()→ tuneandUnlock() → PWM → door
#   Door unlock event → ioWrite() → TCP → camera
#
import gc; gc.collect()
from _utils import calculatecrc16
import network
import uasyncio as asyncio
import utime as time
from esp32 import NVS
from machine import UART, Pin

from _cfg_serial import (
    SERIAL_PORT_DELAY_MS,
    SERIAL_TIMEOUT_NS,
    HOLD_BLINK_TIME_MS,
    HOLD_ERROR_BLINK_TIME_MS,
    HOLD_LOCK_TIME_MS,
    PRE,
    SUF,
)
from _cfg_network import NET_SSID, NET_PASSWD, NET_HIDDEN
from _utils import TAIL, WRITEZ, blue, dbg, green, red, tb, ROK,free
from config import BLE_ACTIVE, NVS_ACTIVE, PORTS_ACTIVE, SERIAL_ACTIVE, TUNE_ACTIVE, WIFI_ACTIVE
from micropython import const

#########################################
## Find baudrate
uart=UART(2)
print("Find baudrate")
import _init_gm60
del _init_gm60
gc.collect()

#########################################
## ********* pre_Main Start *************#
print("pre_Main Start")
waitforSerial = asyncio.ThreadSafeFlag()
waitforWifi = asyncio.ThreadSafeFlag()
runningUnlock = asyncio.Event()
abortUnlock = asyncio.Event()
abortBlink = asyncio.Event()
gc.collect()


async def startNIC(
    wifi_mode, _SSID, _PASSWD, _HIDDEN=False
) -> None:  # Connect or start the network interface
    if not WIFI_ACTIVE:
        dbg("No Wi-Fi")
        return
    nic = network.WLAN(wifi_mode)
    _STARS_ = "********"
    dbg(f"Starting NIC using{wifi_mode, _SSID, _STARS_ , _HIDDEN}")
    if nic.isconnected():
        await asyncio.sleep_ms(10)
        nic.disconnect()
    if nic.active():
        # Toggle active state to clear any stale connection from a previous soft reset
        nic.active(False)
        await asyncio.sleep_ms(10)
        nic.active(True)
    while not nic.active():
        dbg(".", "")
        await asyncio.sleep_ms(300)
        nic.active(True)

    if wifi_mode == network.STA_IF:
        dbg(f"STA_IF: {_SSID} :: {_STARS_}\nActive!?: {nic.active()}\nWaiting...")
        nic.connect(_SSID, _PASSWD)
        # nic.ifconfig((NET_IP, NET_MASK, NET_DNS1, NET_DNS2)) ## Force IP,,,,+++-

    while not nic.isconnected():
        if nic.status() == network.STAT_IDLE:
            dbg("Idle")
        if nic.status() == network.STAT_CONNECTING:
            dbg("Connecting")
        if nic.status() == network.STAT_WRONG_PASSWORD:
            dbg("Wrong Password")
        if nic.status() == network.STAT_NO_AP_FOUND:
            dbg("No AP found")
        if nic.status() == network.STAT_GOT_IP:
            dbg("Got IP")
        await asyncio.sleep_ms(300)
    dbg(f"{nic.ifconfig()}\n")
    del _STARS_


async def startNetwork():
    if not WIFI_ACTIVE:
        dbg("No Wi-Fi")
        return
    await startNIC(network.STA_IF, NET_SSID, NET_PASSWD, NET_HIDDEN)
    waitforWifi.set()


async def networkCheck():  # Daemon: logs WiFi drops and updates LED feedback
    await waitforWifi.wait()  # wait for Wifi
    nic = network.WLAN(network.STA_IF)
    stat: bool = False
    while True:
        await asyncio.sleep(1)
        dbg(".", "")
        active: bool = nic.isconnected()
        if stat is active:
            continue
        stat = active
        if stat:
            asyncio.create_task(colors_normal())
            green("Got Wifi!")
        if not stat:
            red("Lost Wifi, try reconnect!")
            asyncio.create_task(colors())


async def ioWrite(mssg: str | bytes, target_ip: str = None):
    # Notify a camera that a door was opened so it can timestamp/record the event.
    if not WIFI_ACTIVE:
        dbg("No Wi-Fi")
        return

    # Use provided IP or default to first camera
    if target_ip is None:
        from _cfg_network import CLIENT_ADDRESSES

        target_ip = list(CLIENT_ADDRESSES.values())[0]

    from _cfg_network import CLIENT_PORT

    dbg(f"ioWrite to {target_ip}:{CLIENT_PORT}")
    from _utils import tohex

    dbg(f"{tohex(mssg)}")

    IOreader = None  # ← FIX: Initialize variables
    IOwriter = None  # ← FIX: Initialize variables

    try:
        IOreader, IOwriter = await asyncio.wait_for(
            (asyncio.open_connection(target_ip, CLIENT_PORT)), 3
        )
        dbg("PORT OPEN", e="")
        IOwriter.write(mssg.encode())
        dbg(" :: MSG SENT", e="")
        await IOwriter.drain()
        dbg(" :: PORT FLUSHED", e="")
        dataIN = await IOreader.read()
        dbg(" :: READ PORT", e="")
        await IOreader.wait_closed()
        dbg(" :: PORT CLOSED", e="")
        gc.collect()
        return dataIN

    except asyncio.TimeoutError:
        red(f"\nTimeout: {target_ip}")
        gc.collect()
        return b""

    except Exception as e:
        red(f"Network error: {e}")
        # ← FIX: Check if variables exist before closing
        if IOwriter:
            try:
                await IOwriter.wait_closed()
            except:
                pass
        if IOreader:
            try:
                await IOreader.wait_closed()
            except:
                pass
        gc.collect()
        return b""


# TODO - Change into ringbuffer (save them cycles :P)
async def checkQRBuffer(buff):
    # In-memory replay protection: reject a QR code whose HMAC hash we've seen recently.
    # _buffer holds the last 40 accepted hashes; older entries are rotated out.
    # This catches rapid replay attempts that arrive within the same session.
    # NVS timestamp checking (in testHMAC) handles cross-session replays.
    if buff in _buffer:
        return False
    for c in range(len(_buffer) - 1):
        _buffer[c] = _buffer[c + 1]  # Rotate
    _buffer[len(_buffer) - 1] = buff  # Add
    return True


async def gmBlink(mode=0b111, _blink_time: int = 1000, _reset: bool = True) -> None:
    # Visual feedback via the GM60's built-in RGB LEDs.
    # mode bits: R=bit2, G=bit1, B=bit0  (e.g. 0b010 = green, 0b100 = red)
    # _reset=False leaves the scanner in blink mode (used for "door held open" indication).
    if abortBlink.is_set():
        abortBlink.clear()
    dbg("gmBlink - Entered")
#     await wZone(0x00, 0b1000_0101)  # Triggermode=suspend=fast response
    await wZone(0x1B, 1 << 7 | mode << 4 | 0b1111)  # Change flash color
    await wZone(0x1F, 0x01)  # Flash time FAST (0x01)
#     await wZone(0x00, 0b1000_0110)  # Trigger mode Continous
    dbg("GM60 Blink ON")

    from utime import ticks_ms

    _timeout = ticks_ms() + _blink_time

    while ticks_ms() < _timeout and abortBlink.is_set() is not True:
        await asyncio.sleep_ms(100)
    if abortBlink.is_set():
        print(">>> Aborting GMblink!!! <<< <<<")

    if not _reset:
        dbg("GM60 Blink NO-RESET")
        return
#     await wZone(0x00, 0b1000_0101)  # Triggermode=suspend=fast response
    await wZone(0x1B, 0b1100_1111)  # Reset flash color
    await wZone(0x1F, 0x1E)  # Flash time reset (0x1e)
#     await wZone(0x00, 0b1000_0110)  # Trigger mode Continous
    dbg("GM60 Blink OFF")
    if abortBlink.is_set():
        abortBlink.clear()


async def colors() -> None:  # Make prettier
#     await wZone(0x00, 0b1000_0101)  # Triggermode=suspend=fast response.
    await wZone(0x1B, (0b1001_1111, 0b1011_1010, 0b1101_1100, 0b1111_11101))
    await wZone(0x1F, 0x01)  # Cycle time for singel led/zone  x100ms
#     await wZone(0x00, 0b1000_0110)  # Trigger mode Continous


async def colors_normal() -> None:  # Make normal
#     await wZone(0x00, 0b1000_0101)  # Triggermode=suspend=fast response.
    await wZone(0x1B, (0b1100_1111, 0b0011_0010, 0b0101_0100, 0b0111_0110))
    await wZone(0x1F, 0x1E)  # Cycle time for singel led/zone  x100ms
#     await wZone(0x00, 0b1000_0110)  # Trigger mode Continous


async def serialWrite(b):
    if not SERIAL_ACTIVE:
        dbg('Serial is not active!')
        return
    sWrite.write(b)
    await asyncio.sleep_ms(SERIAL_PORT_DELAY_MS)
    await sWrite.drain()


async def serialWait() -> bytes: # Wait for all data to be recived
    while not uart.txdone():
        await asyncio.sleep_ms(SERIAL_PORT_DELAY_MS)
    data: bytes = b''
    timeout: int = time.time_ns()+SERIAL_TIMEOUT_NS
    while not uart.any() and time.time_ns() < timeout:
        await asyncio.sleep_ms(5)
    if uart.any():
        while uart.any():
            if tmp := uart.read(256):
                data += tmp
            dbg('.', '')
            await asyncio.sleep_ms(SERIAL_PORT_DELAY_MS)
        return data
    else:
        dbg('Timeout::', '')
        return data


async def serialRead():
    # GM60 output frame format for a scanned code:
    #   byte[0]   = 0x04  (data frame marker)
    #   byte[1:3] = payload length as big-endian uint16
    #   byte[3:]  = PRE + qr_content + SUF
    #   last 4    = CRC-16 as 2 ASCII hex chars (e.g. b'1A2B')
    #   last byte = 0x0A (newline / frame end)
    if not SERIAL_ACTIVE: dbg('Serial is not active!'); return
    dbg('Starting: serialRead', '>> ')
    while True:
        dbg('Serial await', '>> ')
        data: bytes = await sRead.read(4)
        data += await loop.create_task(serialWait())
        if data[:3] == ROK:
            waitforSerial.set()
            continue
        elif data[0]==0x04:
            _reslen:int=int.from_bytes(data[1:3],'big')
            if not len(data)>=_reslen:
                dbg('Error in string')
                continue
            _resString:bytes 	= bytes(data[0:_reslen+7])
            crc16:bytes 		= bytes(_resString[-4:]) # TODO: Optimize
            crc16_calced:bytes 	= bytes(calculatecrc16(_resString[:-4]))
            crc16_calced 		= bytes(f"{crc16_calced[0]:02X}{crc16_calced[1]:02X}",'latin1')
            qrString:bytes 		= bytes(_resString[3:-4])
            msgString:bytes 	= bytes(qrString[len(PRE):-len(SUF)])
            if crc16==crc16_calced:
                asyncio.create_task(testHMAC(msgString))
            else:
                asyncio.create_task(gmBlink(0b100,3000))
        else:
            dbg('Wrong format')
        gc.collect()


async def wZone(
    zone: int | bytes = 0x00, values: bytes | int | tuple[int | bytes] = 0x00, lens=1
) -> None:
    dbg("WZ:", "")
    if type(values) is int:
        dbg("INT  ", "")
        values = tb(values)
    elif type(values) is tuple:
        dbg("TUPLE", "")
        tmp = b""
        for _ in values:
            tmp += tb(_)
        values = tmp
        lens = len(tmp)
    elif type(values) is bytes:
        dbg("BYTES", "")
        lens = len(values)
    dbg("\t", "")
    cmd: bytes = WRITEZ + tb(lens, 2) + tb(zone) + values + TAIL
    dbg(cmd.hex(), "\t")
    dbg(values.hex(), "\n")
    await serialWrite(cmd)
    await waitforSerial.wait()


async def testHMAC(inByte: bytes = b"") -> None:
    # Entry point for QR code validation. Expected QR content format:
    #   YYYYMMDDHHMMSS[/pPORT,PORT][/uUNIT][/iID][/c]::BASE64_HMAC
    #
    # Examples:
    #   20261231235959/p1::ABC123==          (port 1 only)
    #   20261231235959/p1,2/u5/i42::ABC123== (ports 1+2, unit 5, id 42)
    #   20261231235959/c::ABC123==           (admin code)
    #
    # /p = ports to unlock (comma-separated)
    # /u = unit identifier (which door unit this code is for)
    # /i = user/access ID
    # /c = admin flag (no physical unlock, for management operations)
    _inStr: str = "".join((chr(x) for x in inByte))  # Prevent unicode error, hack?
    blue("testHMAC", " >> ")
    if not "::" in inByte:
        red("WRONG FORMAT")
        asyncio.create_task(gmBlink(0b100, HOLD_ERROR_BLINK_TIME_MS, True))
        del _inStr; gc.collect()
        return

    blue("Start check", " >> ")
    # TODO: Make sure only supported chars
    _pos: int = _inStr.find("::")
    _hash: str = _inStr[_pos + 2 :]
    _str: str = _inStr[:_pos]

    import testHASH

    green("await testHash", " >> ")
    if not await testHASH.hashTest(_hash, _str):
        red("WRONG FORMAT")
        asyncio.create_task(gmBlink(0b100, HOLD_ERROR_BLINK_TIME_MS, True))
        del testHASH; gc.collect()
        return
    del testHASH; gc.collect()

    # return if old qr-code found
    if await checkQRBuffer(_hash) == False:
        red("USED QR-CODE")
        loop.create_task(gmBlink(0b100, HOLD_ERROR_BLINK_TIME_MS, True))
        _hash; gc.collect()
        return

    blue("EXTRACT DATA", " ")
    _cmd: str = _str
    _date: str = ""
    _ports: list[str] = []
    _unit: str = ""
    _id: str = ""
    _is_admin: bool = False
    from _utils import safePrint

    blue(f"_str:\t{safePrint(_cmd)}")
    if "/" in _cmd:  # Rewrite / cleanup!
        _split = _cmd.split("/")
        _date = _split[0]
        blue(f"{_split[0]}")
        for tx in _split:
            if not len(tx):
                continue  # Failed for // or /'<EOF
            if tx[0] == "c":
                _is_admin = True
            if tx[0] == "p":
                _ports = [
                    _p for _p in tx.strip('p').split(",") if _p.isdigit()
                    ]
            if tx[0] == "u":
                _unit = tx
            if tx[0] == "i":
                _id = tx
#         if len(_ports) == 0:
#             _ports = _inStr[_inStr.find("/") + 1 : _inStr.find("::")].split(",")
    else:
        _ports = ["1"]
        _date = _inStr[: _inStr.find("::")]

    # TODO: check that every chars are decimal
    if not _date:
        red("CAN'T FIND TIMESTAMP")
        loop.create_task(gmBlink(0b100, HOLD_ERROR_BLINK_TIME_MS, True))
        return
    # Anything before 2025 get's trown out ^^
    if int(_date[0:4]) < 2026:
        red("THIS CODE IS WAY TO OLD")
        loop.create_task(gmBlink(0b100, HOLD_ERROR_BLINK_TIME_MS, True))
        return

    tdate = (
        int(_date[0:4]),  # Year
        int(_date[4:6]),  # Month
        int(_date[6:8]),  # Day
        int(_date[8:10]),  # Hour
        int(_date[10:12]),  # Minute
        int(_date[12:14]),  # Second
        0,
        0,
    )

    if NVS_ACTIVE:
        if not "NVS" in locals():
            from esp32 import NVS
        nvs_date = NVS("date")
        del NVS;gc.collect()
        tcount: int    = time.mktime(tdate)
        nvs_count: int = nvs_date.get_i32("last")
        time_diff: int = tcount - nvs_count
        green(f"Time diff: {time_diff}")

        if time_diff <= 0:
            # Code timestamp is not newer than the last accepted code → replay attempt
            red("OLD QR-CODE")
            loop.create_task(gmBlink(0b100, HOLD_ERROR_BLINK_TIME_MS, True))
            return
        if time_diff > 60 and NVS_ACTIVE:
            # Only update NVS if the new timestamp is more than 60 s ahead.
            # This avoids EEPROM write wear when the same person scans rapidly.
            nvs_date.set_i32("last", tcount)
            nvs_date.commit()
            green("NVS-DATE UPPDATED")
        green("QR-CODE ACCEPTED")
        del nvs_date

    # make function for wifi n ports
    # TODO: Add support for custom HEAD/TAIL
    if _is_admin:
        print(f"{'*'*20} !!!ADMIN!!! {'*'*20}")
    if WIFI_ACTIVE and not _is_admin:
        print(f"Opening door(s) for units: {_ports}")

        # Import camera addresses
        from _cfg_network import CLIENT_ADDRESSES

        # Send command to each camera unit
        for port_num in _ports:
            if port_num in CLIENT_ADDRESSES:
                target_ip = CLIENT_ADDRESSES[port_num]
                print(f"  → Sending to Unit {port_num} at {target_ip}")

                # Create non-blocking task to send to this camera
                loop.create_task(
                    ioWrite(
                        chr(6) + chr(7) + _str + chr(7) + chr(6),
                        target_ip,  # Send to specific camera IP
                    )
                )
            else:
                red(f"  ✗ Unknown unit: {port_num}")
                red(f"    Valid units: {list(CLIENT_ADDRESSES.keys())}")

        # Clean up
        del CLIENT_ADDRESSES
        gc.collect()

    if PORTS_ACTIVE:  # Calc holdtime
        _HOLDBLINKTIME_MS = HOLD_BLINK_TIME_MS
        if runningUnlock.is_set():
            abortUnlock.set()
            abortBlink.set()
            print("\nAborting unlock!!!\n")
            while not runningUnlock.is_set():
                await asyncio.sleep_ms(50)
        loop.create_task(gmBlink(0b010, _HOLDBLINKTIME_MS, True))
        loop.create_task(tuneandUnlock(_ports))
    gc.collect()


# TODO: Clean up _PORTS before entering loop
# TODO: do the todo dooo... test for numeric portvalues
async def tuneandUnlock(_PORTS) -> None:
    # Drives the electromagnetic door strike via PWM.
    # Kick-then-hold pattern: a short high-duty burst pulls the solenoid in,
    # then a lower duty holds it engaged without overheating the coil.
    runningUnlock.set()
    if not PORTS_ACTIVE:
        dbg("Ports no active!")
        return

    # TODO: limit ports to number of pwm's (channels out)
    dbg(f"tuneandUnlock:{_PORTS}")
    if len(_PORTS) > 2:
        dbg(f"To many ports {_PORTS}\nLimiting...")
    _PORTS = _PORTS[0:3]

    if TUNE_ACTIVE:
        dbg("Playing opening tune:")
        for _ in (622, 300, 100), (830, 300, 100), (1174, 300, 100):
            dbg(f"CH-0: {_[0]: 6} Hz with {_[1]: 3} duty for {_[2]: 6} ms")
            pwms[0].init(freq=_[0], duty=_[1])
            await asyncio.sleep_ms(_[2])

        if not "1" in _PORTS:  # change to use PORT #1 in current ports.
            dbg("Turning port1 (tune) off.")
            pwms[0].duty(0)

    dbg(f"opening ports {_PORTS}")
    if len(_PORTS) == 1:
        dbg(f"Found 1 port, unlock set to {HOLD_LOCK_TIME_MS}")
        currentHoldLocktimeMS = HOLD_LOCK_TIME_MS
    else:
        dbg(f"Found more than 1 port, unlock set to {HOLD_LOCK_TIME_MS}")
        currentHoldLocktimeMS = HOLD_LOCK_TIME_MS
    #         dbg(f"Found more than 1 port, unlock set to {HOLD_LOCK_TIME_MS*2}")
    #         currentHoldLocktimeMS = 2*HOLD_LOCK_TIME_MS # special case
    # Original values  2960,1023,50,550
    ######***#########******###########**********################*****************************
    _period = 30_000  ###Main frequency of PWM (in Hz) 18_000+ is beyond average hearing
    _kick_duty = 800  # ~78% "power" ( max is 1023 )
    _kick_hold = 10  # Hold time in ms for KICK.
    _hold_duty = 600  # ~59% of max ( 1023 )
    _hold_lockTime = currentHoldLocktimeMS
    #########******##########*************#############**********################

    for _unlock in (
        (_period, _kick_duty, _kick_hold),
        (_period, _hold_duty, currentHoldLocktimeMS),
        (_period, 0, 100),
    ):
        for _selected_port in _PORTS:
            _current_port = int(_selected_port)
            if _current_port <= len(pwms):
                dbg(
                    f"CH-{_current_port}:{_unlock[0]: 6} Hz with \
                {_unlock[1]: 3} duty for {_unlock[2]: 6} ms"
                )
                pwms[_current_port - 1].init(freq=_unlock[0], duty=_unlock[1])
            else:
                dbg(f"Portindex out of range: {_current_port}")

        # Apply freq and duty from 'unlocks'
        if _unlock[2] < 100:
            await asyncio.sleep_ms(_unlock[2])  # ms of delay
        else:
            import utime

            _timeout = utime.ticks_ms() + _unlock[2]
            while utime.ticks_ms() <= _timeout and abortUnlock.is_set() is not True:
                await asyncio.sleep_ms(10)
            if abortUnlock.is_set():
                print("\nUnlock aborted...")

    dbg("Closing ports")
    for _selected_port in pwms:
        _selected_port.duty(0)
    dbg("Done!")
    if abortUnlock.is_set():
        abortUnlock.clear()
    runningUnlock.clear()
    from _utils import free
    gc.collect()
    free()
    del free
    gc.collect()


print("Start of Main")
#########################################
# **** --Start of Main-- ****************#
dbg(f"\n{'-'*40}\n", "")

if (
    NVS_ACTIVE
):  # // FIXED!!!  // If no NVS data is set, testHMAC will fail when trying to read NVS
    print(" NVS", end="")
    dbg("Checking NVS:", " ")
    if not "NVS" in globals():
        from esp32 import NVS

        dbg("Importing NVS", " ")

    # Will create 'date' if missing
    try:
        NVS("date").get_i32("last")
    except OSError as ose:
        if ose.args[0] == -4354:
            dbg("Date not found, creating...", " ")
            NVS("date").set_i32("last", 0)
            NVS("date").commit()

    # Will create 'oldkeys' if missing
    dbg("Checking keys...", " ")
    try:
        NVS("oldkey").get_i32("count")
    except OSError as ose:
        if ose.args[0] == -4354:
            dbg("Old Key's count not found, creating...", " ")
            NVS("oldkey").set_i32("count", 20)
            NVS("oldkey").commit()
            dbg("Key's set to 20", " ")
    del NVS
    dbg("Ok!")
gc.collect()

dbg("Aquiring main loop:")
loop = asyncio.new_event_loop()
# for gm60 to work, serial need to be enabled.
_buffer: list = ["" for x in range(40)]
if SERIAL_ACTIVE:
    print(" SERIAL", end="")
    dbg("Serial-Init")
    sRead = asyncio.StreamReader(uart)  # Global serial Stream
    sWrite = asyncio.StreamWriter(uart)  # Global serial Stream
    loop.create_task(serialRead())

if not WIFI_ACTIVE:
    print(" NO-WIFI", end="")
    asyncio.create_task(colors_normal())


if PORTS_ACTIVE:
    # GPIO 18 → Port 1 (P1), GPIO 19 → Port 2 (P2), GPIO 4 → Port 3 (P3)
    # duty is 10-bit (0–1023). Pins connect to the gate of a MOSFET driving the strike coil.
    print(" PORTS", end="")
    dbg("Ports-Init")
    from machine import PWM, Pin

    pwms: list[PWM] = []
    _pwm_basefreq = 5000
    for _ in {18, 19, 4}: pwms.append(PWM(Pin(_), freq=_pwm_basefreq, duty=0))
#     for _ in {32, 33, 25, 26}: pwms.append(PWM(Pin(_), freq=_pwm_basefreq, duty=0))


def trySleep(_s: int = 0, _sysexit: bool = False) -> bool:
    try:
        time.sleep(_s)
        return True
    except KeyboardInterrupt as k:
        print("Sleep interupted by keyboard")
        if _sysexit:
            import sys

            sys.exit(0)

        return False
    finally:
        gc.collect()


# Setup AP for cam to connect to.
# TODO: test if running asyncio.run() exits 'loop'/main loop aka. make things go *booom*
if WIFI_ACTIVE:
    print(" WIFI", end="")
    dbg("Wifi-Init")
    loop.create_task(startNetwork())
    loop.create_task(networkCheck())

if BLE_ACTIVE:
    print(" BLE", end="")
    dbg("BLE-Init")
    from ble_elock import BLELock
    _ble_lock = BLELock()
    loop.create_task(_ble_lock.task())

    async def _ble_monitor():
        # Bridge between the BLE auth result and the existing unlock/blink logic.
        # Runs as a daemon; wakes only when BLELock signals a verified unlock.
        while True:
            await _ble_lock.unlock_flag.wait()
            ports = _ble_lock.unlock_ports[:]
            _ble_lock.unlock_ports.clear()
            loop.create_task(gmBlink(0b010, HOLD_BLINK_TIME_MS, True))
            loop.create_task(tuneandUnlock(ports))

    loop.create_task(_ble_monitor())

print("\nEnter Main Loop:\nAll ok!\n")
while True:
    try:
        loop.run_forever()
    except KeyboardInterrupt as k:
        print("Interupted by keyboard:")
    except BaseException as b:
        print(f"Base Exception {b.args}")
    finally:
        print("-- FINALLY --")
    print("Delay 1sec before retry...")
    trySleep(1, True)
    continue
