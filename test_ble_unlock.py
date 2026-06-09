#!/usr/bin/env python3
"""
BLE unlock test script for ZipLink.

Bypasses Supabase entirely — computes the HMAC locally with the test key
stored in _key_new.py. Use this to verify the full BLE authentication
flow without needing a Vercel/Supabase deployment.

Usage:
    pip install bleak
    python3 test_ble_unlock.py [--port 1] [--key "0123456789ABCDEFG"] [--expiry 20261231235959]
"""

import asyncio
import hashlib
import hmac as hmac_mod
import sys
import argparse

try:
    from bleak import BleakScanner, BleakClient
except ImportError:
    print("[!] 'bleak' is not installed. Run: pip install bleak")
    sys.exit(1)

# ── Defaults (must match _key_new.py and _cfg_ble.py on the ESP32) ────────────

DEVICE_NAME   = "ZipLink"
CHR_CHALLENGE = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
CHR_RESPONSE  = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"

DEFAULT_KEY    = "0123456789ABCDEFG"  # HASH_KEY_NEW in _key_new.py
DEFAULT_EXPIRY = "20261231235959"     # Must be newer than last NVS ticket
DEFAULT_PORT   = 1


# ── HMAC ──────────────────────────────────────────────────────────────────────

def compute_hmac(key: str, message: str) -> bytes:
    """HMAC-SHA256(key, message) — full 32-byte digest."""
    return hmac_mod.new(key.encode(), message.encode(), hashlib.sha256).digest()


# ── BLE flow ──────────────────────────────────────────────────────────────────

async def run(port: int, key: str, expiry: str):
    print(f"[*] Scanning for '{DEVICE_NAME}'...")
    device = await BleakScanner.find_device_by_name(DEVICE_NAME, timeout=10.0)
    if device is None:
        print(f"[!] '{DEVICE_NAME}' not found. Is the ESP32 on and advertising?")
        sys.exit(1)

    print(f"[+] Found {device.name} @ {device.address}")

    async with BleakClient(device, timeout=15.0) as client:
        if not client.is_connected:
            print("[!] Failed to connect.")
            sys.exit(1)

        # Wait for MTU negotiation and for the ESP32 to write the nonce.
        # CoreBluetooth negotiates MTU automatically but needs a moment to complete.
        # Without this, writes are capped at the BLE default of 20 bytes.
        print("[*] Connected. Waiting for MTU negotiation...")
        await asyncio.sleep(2.0)
        print(f"[*] MTU: {client.mtu_size} bytes")
        if client.mtu_size < 34:
            print("[*] MTU still low, waiting another 2s...")
            await asyncio.sleep(2.0)
            print(f"[*] MTU: {client.mtu_size} bytes")

        nonce = bytes(await client.read_gatt_char(CHR_CHALLENGE))
        print(f"[+] Nonce received: {nonce.hex()} ({len(nonce)} bytes)")
        if len(nonce) != 16:
            print(f"[!] Unexpected nonce length: {len(nonce)} (expected 16)")
            sys.exit(1)

        # Reconstruct the exact message that ble_elock.py will verify:
        #   msg = hexlify(nonce).decode() + ':' + str(port_num) + ':' + expiry_str
        message = f"{nonce.hex()}:{port}:{expiry}"
        print(f"[*] HMAC input:  {message!r}")

        digest           = compute_hmac(key, message)
        hmac_truncated   = digest[:16]  # _HMAC_LEN = 16
        print(f"[*] HMAC[:16]:   {hmac_truncated.hex()}")

        # 31-byte response: 1 byte port | 14 bytes expiry ASCII | 16 bytes HMAC
        expiry_bytes = expiry.encode("ascii")
        payload = bytes([port]) + expiry_bytes + hmac_truncated
        assert len(payload) == 31

        print(f"[*] Sending {len(payload)}-byte response: {payload.hex()}")
        await client.write_gatt_char(CHR_RESPONSE, payload, response=True)

        print("[*] Response sent. Waiting for ESP32 to process...")
        await asyncio.sleep(2.0)

    print("[+] Done. Watch the ESP32 serial output for 'BLE: auth ok' or an error.")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="BLE unlock test — bypasses Supabase")
    ap.add_argument("--port",   type=int, default=DEFAULT_PORT, choices=[1, 2, 3],
                    help=f"Port to unlock (default: {DEFAULT_PORT})")
    ap.add_argument("--key",    default=DEFAULT_KEY,
                    help=f"HMAC key from _key_new.py (default: {DEFAULT_KEY!r})")
    ap.add_argument("--expiry", default=DEFAULT_EXPIRY,
                    help=f"Expiry timestamp YYYYMMDDHHMMSS (default: {DEFAULT_EXPIRY})")
    args = ap.parse_args()

    asyncio.run(run(args.port, args.key, args.expiry))
