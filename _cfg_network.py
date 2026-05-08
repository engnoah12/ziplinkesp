############################
# date: 2025-03-11 00:00 #

from micropython import const

NET_SSID: str    = const(r"iHaveNoSSID")
NET_PASSWD: str  = const(r"Ziplink4Life")
NET_HIDDEN: bool = const(False)

# Maps port number strings to camera IP addresses.
# When a door is opened the ESP32 sends a TCP message to the matching camera
# so it can timestamp or record the event. Keys must match the 'p' field in QR codes.
CLIENT_ADDRESSES = {
    "1": "10.0.0.3",  # CAM1
}

# TCP port the camera listens on for open-door notifications
CLIENT_PORT: int = const(42_000)
