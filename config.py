############################
# date: 2025-02-25 00:00 #
#
from micropython import const

# TODO - seperate SERIAL // GM60 (serial)
DEBUG: bool = const(True)
WIFI_ACTIVE: bool = const(True)
SERIAL_ACTIVE: bool = const(True)
PORTS_ACTIVE: bool = const(True)
TUNE_ACTIVE: bool = const(False)
NVS_ACTIVE: bool = const(True)
