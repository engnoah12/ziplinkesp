import gc,utime as time
from machine import UART
from micropython import const,opt_level
opt_level(0)

def fname(f,*args,**kvargs):
    name=str(f).split(' ')[1]
    def fun(*args,**kvargs):
        print(f"\n{'*'*10+name+'*'*10:^80}")
        return f(*args,**kvargs)
    return fun

from consts import BAUDS
__BAUDS=list(BAUDS)
__BAUDS.insert(0,BAUDS[6]) # Target = #6,57600bps
del BAUDS;gc.collect()

uart=UART(2,timeout=500) # 500ms needed for bps/EEPROM changes.

@fname
def resetEEPROM():
    uart.init(timeout=500)
    from consts import RESETEEPROM
    uart.write(RESETEEPROM)
    print("\nresetEEPROM:",waitSerial())
    del RESETEEPROM; gc.collect()

@fname
def savetoEEPROM():
    uart.init(timeout=500)
    from consts import SAVETOEEPROM
    uart.write(SAVETOEEPROM)
    print("\nSavetoEEPROM:",waitSerial())
    del SAVETOEEPROM; gc.collect()
    
@fname
def waitSerial(_nb=7):
    while not uart.txdone(): time.sleep_ms(1)
    return uart.read(_nb)

@fname
def changeBPS(_bps)->bool:
    uart.init(timeout=500)
    print("\nChange bps:",end='  ')
    _bauds=b'\x7e\x00\x08\x02\x00\x2a'
    _bauds+=int(__BAUDS[_bps][1]).to_bytes(2,'little')+b'\xab\xcd'
    print(_bauds.hex(':'))
    uart.write(_bauds)
    _res=waitSerial()
    if _res is not None: print(_res.hex(':'))
    if _res is not None and\
    _res[:4] == b'\x02\x00\x00\x02' and\
           int.from_bytes(_res[4:6],'little') == __BAUDS[_bps][1]:
            print("\nFound bps:",b,int(b[1]).to_bytes(2,'big').hex(':'))
            print(_res.hex(':'),end='')
            del _bauds, _bps, _res; gc.collect()
            return True
    del _bauds, _bps, _res; gc.collect()
    return False

@fname
def changeMode():
    uart.init(timeout=500)
    from consts import CHANGEMODE
    print("Change mode:",end='  ')
    for b in __BAUDS:
        print(b[0],end=' ')
        uart.init(b[0])
        uart.write(CHANGEMODE)
        time.sleep_ms(500)
    print()
    print(waitSerial())
    del CHANGEMODE, b; gc.collect()

@fname
def seekBPS()->None|tuple:
    uart.init(timeout=300)
    while uart.any():
        uart.read(uart.any())
        print("R",end='')

    from consts import SEEKBPS
    print("Seek bps:",end='  ')
    for b in __BAUDS:    
        print(b[0],end=' ')
        uart.init(b[0])
        uart.write(SEEKBPS)
        _res=waitSerial(8)
        if _res is not None: print(_res.hex(':'))
        if _res is not None and\
           _res[:4] == b'\x02\x00\x00\x02' and\
           int.from_bytes(_res[4:6],'little') == b[1]:
            print("\nFound bps:",b,int(b[1]).to_bytes(2,'big').hex(':'))
            print(_res.hex(':'),end='')
            del SEEKBPS, _res; gc.collect()
            return b
    del SEEKBPS, b, _res; gc.collect()
    return None

@fname
def initGM60():
    while True:
        _bps=seekBPS()
        if _bps is __BAUDS[0]: break
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