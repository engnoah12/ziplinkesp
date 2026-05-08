############################
# date: 2025-02-25 00:00 #

from micropython import const

SERIAL_PORT_DELAY_MS: int = const(10)           # Polling interval while draining UART buffer
SERIAL_TIMEOUT_NS: int    = const(60 * 1_000_000)  # 60 ms in nanoseconds (time_ns() units)
GLOBAL_TIME: int          = const(8000)         # Shared base for all hold timings (ms)

# How long each state lasts after a valid scan
HOLD_LOCK_TIME_MS: int       = const(GLOBAL_TIME)  # PWM stays energized for this long
HOLD_BLINK_TIME_MS: int      = const(GLOBAL_TIME)  # GM60 blink feedback duration
HOLD_ERROR_BLINK_TIME_MS: int = const(GLOBAL_TIME) # GM60 blink on auth failure

# The GM60 scanner wraps every scanned payload between these byte strings.
# They are configured into the scanner via wZone(0x62..0x72) in _init_gm60.py,
# so we know exactly where the QR content starts and ends in the serial frame.
PRE: bytes = const("begin".encode())
SUF: bytes = const("ending".encode())
