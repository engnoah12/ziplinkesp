############################
# date: 2025-03-11 00:00 #
#
from micropython import const

NET_SSID: str = const(r"iHaveNoSSID")
NET_PASSWD: str = const(r"Ziplink4Life")
NET_HIDDEN: bool = const(False)

# NEW - Add this dictionary:
CLIENT_ADDRESSES = {
    "1": "10.0.0.3",  # CAM1
}

CLIENT_PORT: int = const(42_000)
