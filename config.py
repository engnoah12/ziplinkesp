############################
# date: 2025-02-25 00:00 #

try:
	from micropython import const
except Exception:  # not running on MicroPython (e.g. type checkers, editors)
	def const(x: bool) -> bool:  # fallback for CPython environment
		return x

DEBUG: bool         = const(True)   # Print verbose output to serial console
WIFI_ACTIVE: bool   = const(False)   # Send open-door events to cameras over TCP
SERIAL_ACTIVE: bool = const(True)   # Read QR codes from the GM60 scanner via UART
PORTS_ACTIVE: bool  = const(True)   # Drive electromagnetic locks via PWM output
TUNE_ACTIVE: bool   = const(False)  # Play an unlock melody on port 1 (uses the same PWM)
NVS_ACTIVE: bool    = const(True)   # Store last-accepted timestamp in flash (replay protection)
BLE_ACTIVE: bool    = const(True)   # Accept hands-free unlock via BLE challenge-response
