############################
# date: 2025-02-25 00:00 #
#
from micropython import const
import uasyncio as asyncio
import utime as time
import usocket as socket
import network
import gc
from machine import Pin
from esp32 import NVS
from ubinascii import hexlify
from config import *
from _utils import *

#########################################
## Find baudrate
print("Find baudrate")
import findBaudrate
uart=findBaudrate.getBPS()
if uart:
    print("_init_gm60")
    import _init_gm60

del findBaudrate, _init_gm60

#########################################
## ********* pre_Main Start *************#
print("pre_Main Start")
waitforSerial = asyncio.ThreadSafeFlag()
waitforWifi = asyncio.ThreadSafeFlag()
gc.collect()

async def startNIC(wifi_mode, _SSID, _PASSWD, _HIDDEN=False) -> None:  # Initiate NIC as AP
    if not WIFI_ACTIVE: dbg('No Wi-Fi'); return
    nic = network.WLAN(wifi_mode); _STARS_='********'
    dbg(f'Starting NIC using{wifi_mode, _SSID, _STARS_ , _HIDDEN}')
    if nic.isconnected():
        await asyncio.sleep_ms(10)
        nic.disconnect()
    if nic.active():
        nic.active(False)
        await asyncio.sleep_ms(10)
        nic.active(True)
    while not nic.active():
        dbg('.', '')
        await asyncio.sleep_ms(300)
        nic.active(True)

    if wifi_mode == network.STA_IF:
        dbg(f'STA_IF: {_SSID} :: {_STARS_}\nActive!?: {nic.active()}\nWaiting...')
        nic.connect(_SSID, _PASSWD)
        #nic.ifconfig((NET_IP, NET_MASK, NET_DNS1, NET_DNS2)) ## Force IP,,,,+++-

#     if wifi_mode == network.AP_IF:
#         dbg(f'AP_IF: {_SSID}\n{_PASSWD}\n{nic.active()}\nWaiting')
#         nic.config(essid=_SSID, password=_PASSWD, authmode=4, hidden=_HIDDEN)

    while not nic.isconnected():
        if nic.status() == network.STAT_IDLE: dbg("Idle")
        if nic.status() == network.STAT_CONNECTING: dbg("Connecting")
        if nic.status() == network.STAT_WRONG_PASSWORD: dbg("Wrong Password")
        if nic.status() == network.STAT_NO_AP_FOUND: dbg("No AP found")
        if nic.status() == network.STAT_GOT_IP: dbg("Got IP")
        await asyncio.sleep_ms(300)
    dbg(f'{nic.ifconfig()}\n')
    del _STARS_

async def startNetwork():
    if not WIFI_ACTIVE: dbg('No Wi-Fi'); return
    await startNIC(network.STA_IF, NET_SSID, NET_PASSWD, NET_HIDDEN)
    waitforWifi.set()
    loop.create_task(gmBlink(0b010, HOLD_BLINK_TIME_MS, True))

async def networkCheck():  # Daemon
    await waitforWifi.wait()  # wait for Wifi
    nic = network.WLAN(network.STA_IF)
    stat: bool = False
    while True:
        await asyncio.sleep(1)
        dbg('.', '')
        active: bool = nic.isconnected()
        if stat is active:
            continue
        stat = active
        if stat:
            asyncio.create_task(colors_normal())
            green('Got Wifi!')
        if not stat:
            red("Lost Wifi, try reconnect!")
            asyncio.create_task(colors())


async def ioWrite(mssg: str | bytes, retry: bool = True):  # Wifi
    if not WIFI_ACTIVE:
        dbg('No Wi-Fi')
        return
    dbg(f'ioWrite {mssg}\n{hexlify(mssg)}')
    while True:
        try:
            IOreader, IOwriter = await asyncio.wait_for(  # 3sec timout>>|
                (asyncio.open_connection(CLIENT_ADDRESS, CLIENT_PORT)), 3)
            dbg('PORT OPEN', e='')
            IOwriter.write(mssg.encode())
            dbg(' :: MSG SENT', e='')
            await IOwriter.drain()
            dbg(' :: PORT FLUSHED', e='')
            dataIN = await IOreader.read()
            dbg(' :: READ PORT', e='')
            await IOreader.wait_closed()
            dbg(' :: PORT CLOSED', e='')
            gc.collect()
            return dataIN
        except (asyncio.TimeoutError, BaseException) as e:
            if type(e) is asyncio.TimeoutError:
                red("\nTimeout: WIFI")
                gc.collect()
                return
            dbg(f'<<-- {e} :: ', e='')
            try:
                await IOwriter.wait_closed()
                dbg('>>', e='')
            except BaseException as e:
                dbg('_', e='')
            try:
                dbg('ReadClose ', e='')
                await IOreader.wait_closed()
                dbg('>>', e='')
            except BaseException as e:
                dbg('_network error!')
                await asyncio.sleep(0.1)
            gc.collect()
            return b''


# TODO - Change into ringbuffer (save them cycles :P)
async def checkQRBuffer(buff):  # Check buffer for used QR-Code
    if buff in _buffer: return False
    for c in range(len(_buffer) - 1):
        _buffer[c] = _buffer[c + 1]  # Rotate
    _buffer[len(_buffer) - 1] = buff  # Add
    return True


async def gmBlink(mode=0b111, _blink_time: int=1000, _reset: bool=True) -> None:
    dbg('gmBlink - Entered')
    await wZone(0x00, 0b1000_0101)  # Triggermode=suspend=fast response
    await wZone(0x1b, 1 << 7 | mode << 4 | 0b1111)  # Change flash color
    await wZone(0x1f, 0x01)  # Flash time FAST (0x01)
    await wZone(0x00, 0b1000_0110)  # Trigger mode Continous
    dbg('GM60 Blink ON')
    await asyncio.sleep_ms(_blink_time)

    if not _reset:
        dbg('GM60 Blink NO-RESET')
        return
    await wZone(0x00, 0b1000_0101)  # Triggermode=suspend=fast response
    await wZone(0x1b, 0b1100_1111)  # Reset flash color
    await wZone(0x1f, 0x1e)  # Flash time reset (0x1e)
    await wZone(0x00, 0b1000_0110)  # Trigger mode Continous
    dbg('GM60 Blink OFF')


async def colors() -> None:  # Make prettier
    await wZone(0x00, 0b1000_0101)  # Triggermode=suspend=fast response.
    await wZone(0x1b, (0b1001_1111, 0b1011_1010, 0b1101_1100, 0b1111_11101))
    await wZone(0x1f, 0x01)  # Cycle time for singel led/zone  x100ms
    await wZone(0x00, 0b1000_0110)  # Trigger mode Continous


async def colors_normal() -> None:  # Make normal
    await wZone(0x00, 0b1000_0101)  # Triggermode=suspend=fast response.
    await wZone(0x1b, (0b1100_1111, 0b0011_0010, 0b0101_0100, 0b0111_0110))
    await wZone(0x1f, 0x1e)  # Cycle time for singel led/zone  x100ms
    await wZone(0x00, 0b1000_0110)  # Trigger mode Continous


async def serialWrite(b):
    if not SERIAL_ACTIVE:
        dbg('Serial is not active!')
        return
#     dbg(f'S>{tohex(b)}', '')
    sWrite.write(b)
    await asyncio.sleep_ms(SERIAL_PORT_DELAY_MS)
    await sWrite.drain()

# TODO: Make circular buffer, better checks
# TODO: Check GM60 Feedback vs. GM60-QR-Message
# TODO: check for GM60 resp or PRE
# TODO: seperate unlock,blink from hmactest

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

def conv(_s:str): return "".join([f"{x:02X}" for x in _s])

async def serialRead():
    if not SERIAL_ACTIVE: dbg('Serial is not active!'); return
    dbg('Starting: serialRead','>> ')
    while True:
        dbg('Serial await', '>> ')
        data:bytes = await sRead.read(4)
        data+=await loop.create_task(serialWait())
        if data[:3]==ROK:
            waitforSerial.set()
            continue
        elif data[0]==0x04:
#             _reslen:int=data[1]<<8|data[2]
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
#             print(f'Response length: {_reslen}')
#             print(f'CRC16: {crc16}')
#             print(f'Calculated CRC16: {crc16_calced}')
#             print(f'QR-String: {qrString}')
#             print(f'msgString: {msgString}')
            if crc16==crc16_calced:
                asyncio.create_task(testHMAC(msgString))
            else:
                asyncio.create_task(gmBlink(0b100,3000))
        else:
            dbg('Wrong format')
        gc.collect()


async def wZone(zone: int | bytes = 0x00, values: bytes | int | tuple[int|bytes] = 0x00, lens=1) -> None:
    dbg('WZ:', '')
    if type(values) is int:
        dbg('INT  ', '')
        values = tb(values)
    elif type(values) is tuple:
        dbg('TUPLE', '')
        tmp = b''
        for _ in values:
            tmp += tb(_)
        values = tmp
        lens = len(tmp)
    elif type(values) is bytes:
        dbg('BYTES', '')
        lens = len(values)
    dbg('\t', '')
    cmd: bytes = WRITEZ+tb(lens, 2)+tb(zone)+values+TAIL
    uart.write(cmd)
    dbg(cmd.hex(), '\t')
    dbg(values.hex(), '\n')
    
    await serialWrite(cmd)
    await waitforSerial.wait()

def safePrint(_s:str,_rep:str="_")->str: # TODO: Optimize
    if not isinstance(_s,str): return ""
    _safe:str="""!"#$%&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\]^_`abcdefghijklmnopqrstuvwxyz{|}~¡¢£¤¥¦§¨©ª«¬®¯°±²³´µ¶·¸¹º»¼½¾¿ÀÁÂÃÄÅÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖ×ØÙÚÛÜÝÞßàáâãäåæçèéêëìíîïðñòóôõö÷øùúûüýþÿ"""
    
    _res:str=""
    for _ in enumerate(_s):
        _l=_s[_[0]] in _safe
        _res+=_s[_[0]] if _l else _rep
    return _res

# MAKE SURE TO HANDLE DATA AS BYTES!!! // Sanetize input and length!
async def testHMAC(inByte:bytes=b'') -> None:  # TODO: more precise decoder!
    _inStr:str ="".join([chr(x) for x in inByte]) # Prevent unicode error, hack?
#     _inStr:str=inByte.decode() # get unicode error
    blue('testHMAC', ' >> ')
    # if inByte[:inByte.find(b'::')].count(b'/') < 2: # Dont accept v1 format
    # Add prefix and suffix to prevent parsing errors
    if not '::' in inByte:
        red("WRONG FORMAT")
        asyncio.create_task(gmBlink(0b100, HOLD_ERROR_BLINK_TIME_MS, True))
        return

    blue('Start check', ' >> ')
    # TODO: Make sure only supported chars
    _pos: int = _inStr.find('::')
    _hash: str = _inStr[_pos + 2:]
    _str: str = _inStr[:_pos]

    import testHASH
    green('await testHash'," >> ")
    if not await testHASH.hashTest(_hash,_str):
        red("WRONG FORMAT")
        asyncio.create_task(gmBlink(0b100, HOLD_ERROR_BLINK_TIME_MS, True))
        return
    del testHASH
    gc.collect()
    
# return if old qr-code found
    if await checkQRBuffer(_hash) == False:
        red("USED QR-CODE")
        loop.create_task(gmBlink(0b100, HOLD_ERROR_BLINK_TIME_MS, True))
        return

    blue('EXTRACT DATA', ' ')
    _cmd: str = _str
    _date: str=''
    _ports: list[str]=[]
    _unit: str=''
    _id: str=''
    _is_admin: bool = False
    blue(f'_str:\t{safePrint(_cmd)}')
    if '/' in _cmd:  # Rewrite / cleanup!
        _split = _cmd.split('/')
        _date = _split[0]
        blue(f'{_split[0]}')
        for tx in _split:
            if not len(tx): continue # Failed for // or /'<EOF
            if tx[0] == 'c':
                _is_admin = True
            if tx[0] == 'p':
                _ports = tx.strip('p').split(',')
            if tx[0] == 'u':
                _unit = tx
            if tx[0] == 'i':
                _id = tx
        if len(_ports)==0:
            _ports = _inStr[_inStr.find('/') + 1: _inStr.find('::')].split(',')
    else:
        _ports = ['1']
        _date = _inStr[: _inStr.find('::')]

    # TODO: check that every chars are decimal
    if not _date:
        red("CAN'T FIND TIMESTAMP")
        loop.create_task(gmBlink(0b100, HOLD_ERROR_BLINK_TIME_MS, True))
        return
    # Anything before 2025 get's trown out ^^
    if int(_date[0:4]) < 2025:
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
        0, 0,)
    
    if NVS_ACTIVE:
        if not 'NVS' in locals(): from esp32 import NVS
        nvs_date = NVS('date')
        tcount: int = time.mktime(tdate)
        nvs_count: int = nvs_date.get_i32('last')
        time_diff: int = tcount - nvs_count
        green(f'Time diff: {time_diff}')

        if time_diff <= 0:
            red("OLD QR-CODE")
            loop.create_task(gmBlink(0b100, HOLD_ERROR_BLINK_TIME_MS, True))
            return
        if time_diff > 60 and NVS_ACTIVE:
            nvs_date.set_i32('last', tcount)
            nvs_date.commit()
            green('NVS-DATE UPPDATED')
        green('QR-CODE ACCEPTED')
        del nvs_date

    # make function for wifi n ports
    # TODO: Add support for custom HEAD/TAIL
    if _is_admin:
        print(f"{'*'*20} !!!ADMIN!!! {'*'*20}")
    if WIFI_ACTIVE and not _is_admin:
        print("Opening door(s)")
        loop.create_task(
            ioWrite(chr(6) + chr(7) + _str + chr(7) + chr(6), True))
    if PORTS_ACTIVE:
        if len(_ports)>1 :
            _HOLDBLINKTIME_MS = HOLD_BLINK_TIME_MS
        else:
            _HOLDBLINKTIME_MS = HOLD_BLINK_TIME_MS

        loop.create_task(tuneandUnlock(_ports))
    loop.create_task(gmBlink(0b010, _HOLDBLINKTIME_MS, True))
#     print("<end of testHMAC>")
    gc.collect()


# TODO: Clean up _PORTS before entering loop
# TODO: do the todo dooo... test for numeric portvalues
async def tuneandUnlock(_PORTS) -> None:
    if not PORTS_ACTIVE:
        dbg('Ports no active!')
        return
    
# TODO: limit ports to number of pwm's (channels out)
    dbg(f'tuneandUnlock:{_PORTS}')
    if len(_PORTS) > 2:
        dbg(f'To many ports {_PORTS}\nLimiting...')
    _PORTS = _PORTS[0:3]

    if TUNE_ACTIVE:
        dbg('Playing opening tune:')
        for _ in (622, 300, 100), (830, 300, 100), (1174, 300, 100):
            dbg(f"CH-0: {_[0]: 6} Hz with {_[1]: 3} duty for {_[2]: 6} ms")
            pwms[0].init(freq=_[0], duty=_[1])
            await asyncio.sleep_ms(_[2])

        if not '1' in _PORTS:
            dbg('Turning port1 (tune) off.')
            pwms[0].duty(0)

    dbg(f"opening ports {_PORTS}")
    if len(_PORTS) == 1:
        dbg(f"Found 1 port, unlock set to {HOLD_LOCK_TIME_MS}")
        currentHoldLocktimeMS = HOLD_LOCK_TIME_MS
    else:
        dbg(f"Found more than 1 port, unlock set to {HOLD_LOCK_TIME_MS*2}")
        currentHoldLocktimeMS = 2*HOLD_LOCK_TIME_MS

    for _unlock in (2960, 1023, 50),(2960, 350, currentHoldLocktimeMS),(2960, 0, 100):
        for _selected_port in _PORTS:
            _current_port = int(_selected_port)
            if _current_port <= len(pwms)+1:
                dbg(f"CH-{_current_port}:{_unlock[0]: 6} Hz with \
                {_unlock[1]: 3} duty for {_unlock[2]: 6} ms")
                pwms[_current_port - 1].init(freq=_unlock[0], duty=_unlock[1])
            else:
                dbg(f"Portindex out of range: {_current_port}")
        # Apply freq and duty from 'unlocks'
        await asyncio.sleep_ms(_unlock[2])
    dbg('Closing ports')
    for _selected_port in pwms:
        _selected_port.duty(0)
    dbg('Done!')
    gc.collect()

print("Start of Main")
#########################################
# **** --Start of Main-- ****************#
dbg(f"\n{'-'*40}\n", '')

if NVS_ACTIVE: # // FIXED!!!  // If no NVS data is set, testHMAC will fail when trying to read NVS
    print(" NVS",end="")
    dbg('Checking NVS:', ' ')
    if not 'NVS' in globals():
        from esp32 import NVS
        dbg('Importing NVS', ' ')

    # Will create 'date' if missing
    try: NVS('date').get_i32('last')
    except OSError as ose:
        if ose.args[0] == -4354:
            dbg('Date not found, creating...', ' ')
            NVS('date').set_i32('last', 0)
            NVS('date').commit()

    # Will create 'oldkeys' if missing
    dbg("Checking keys..."," ")
    try: NVS("oldkey").get_i32("count")
    except OSError as ose:
        if ose.args[0] == -4354:
            dbg("Old Key's count not found, creating...", " ")
            NVS("oldkey").set_i32("count", 20);NVS("oldkey").commit()
            dbg("Key's set to 20", " ")
    del NVS
    dbg('Ok!')

gc.collect()

dbg('Aquiring main loop:')
loop = asyncio.new_event_loop()
# for gm60 to work, serial need to be enabled.
if SERIAL_ACTIVE:
    print(" SERIAL",end="")
    dbg('Serial-Init')
    sRead = asyncio.StreamReader(uart)  # Global serial Stream
    sWrite = asyncio.StreamWriter(uart)  # Global serial Stream
    loop.create_task(serialRead())

if not WIFI_ACTIVE:
    print(" NO-WIFI",end="")
    asyncio.create_task(colors_normal())
   

if PORTS_ACTIVE:  # Ports P1=18, P2=19, P3=4 || duty is 10bit // duty_u16 is 16bit
    print(" PORTS",end="")
    dbg('Ports-Init')
    from machine import Pin, PWM
    pwms: list[PWM] = []
    _pwm_basefreq = 5000
    for _ in {18, 19, 4}: pwms.append(PWM(Pin(_), freq=_pwm_basefreq, duty=0))
#     for _ in {32, 33, 25, 26}: pwms.append(PWM(Pin(_), freq=_pwm_basefreq, duty=0))
        
    _buffer: list = ['' for x in range(40)]

def trySleep(_s:int=0,_sysexit:bool=False)->bool:
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
    return False

# Setup AP for cam to connect to.
# TODO: test if running asyncio.run() exits 'loop'/main loop aka. make things go *booom*
if WIFI_ACTIVE:
    print(" WIFI",end="")
    dbg('Wifi-Init')
    loop.create_task(startNetwork())
    loop.create_task(networkCheck())

print('\nEnter Main Loop:\nAll ok!\n')
while True:
    try:
        loop.run_forever()
    except KeyboardInterrupt as k:
        print('Interupted by keyboard:')
    except  BaseException as b:
        print(f"Base Exception {b.args}")
    finally:
        print("-- FINALLY --")        
    print("Delay 1sec before retry...")
    trySleep(1,True)
    continue

