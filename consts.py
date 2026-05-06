from micropython import const
safe = const(" !\"#$%&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`abcdefghijklmnopqrstuvwxyz{|}~")

BAUDS = (
    ( 1200, 0x09c4, 0),( 4800, 0x0271, 1),( 9600, 0x0139, 2),( 14400, 0x00d0, 3),
    (19200, 0x009c, 4),(38400, 0x004e, 5),(57600, 0x0034, 6),(115200, 0x001a, 7)
    )

RESETEEPROM = const(b'\x7e\x00\x08\x01\x00\xd9\x55\xab\xcd')
SAVETOEEPROM = const(b'\x7e\x00\x09\x01\x00\x00\x00\xde\xc8')
CHANGEMODE = const(b'\x7e\x00\x08\x03\x00\x00\x09\x00\x00\xab\xcd')
SEEKBPS = const(b'\x7e\x00\x07\x01\x00\x2a\x02\xab\xcd')
