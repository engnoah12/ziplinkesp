#!/usr/bin/env python3
"""
BLE file updater test script for ZipLink.

Authenticates against the BLE updater service and pushes a local file to the
ESP32's filesystem — no USB cable or WiFi needed.

Usage:
    pip install bleak
    python3 test_ble_updater.py --file config.py
    python3 test_ble_updater.py --file config.py --dest config.py --reboot
    python3 test_ble_updater.py --file config.py --key "my_secret_key"
"""

import asyncio
import hashlib
import hmac as hmac_mod
import sys
import os
import argparse

try:
    from bleak import BleakScanner, BleakClient
except ImportError:
    print("[!] 'bleak' is not installed. Run: pip install bleak")
    sys.exit(1)

# ── Constants (must match _cfg_ble.py on the ESP32) ──────────────────────────

DEVICE_NAME    = "ZipLink"
CHR_CHALLENGE  = "6E400012-B5A3-F393-E0A9-E50E24DCCA9E"
CHR_AUTH       = "6E400013-B5A3-F393-E0A9-E50E24DCCA9E"
CHR_FILENAME   = "6E400014-B5A3-F393-E0A9-E50E24DCCA9E"
CHR_DATA       = "6E400015-B5A3-F393-E0A9-E50E24DCCA9E"
CHR_COMMIT     = "6E400016-B5A3-F393-E0A9-E50E24DCCA9E"

CHUNK_SIZE     = 200   # Must not exceed the pre-allocated buffer in ble_updater.py
CMD_COMMIT     = bytes([0x01])
CMD_ABORT      = bytes([0x02])
CMD_REBOOT     = bytes([0x03])

DEFAULT_KEY    = "REPLACE_BEFORE_DEPLOY"  # Must match HASH_KEY_UPD in _key_upd.py


# ── HMAC ──────────────────────────────────────────────────────────────────────

def compute_hmac(key: str, message: str) -> bytes:
    """Full 32-byte HMAC-SHA256 — updater uses no truncation."""
    return hmac_mod.new(key.encode(), message.encode(), hashlib.sha256).digest()


# ── BLE flow ──────────────────────────────────────────────────────────────────

async def run(filepath: str, dest: str, key: str, reboot: bool):
    if not os.path.isfile(filepath):
        print(f"[!] File not found: {filepath}")
        sys.exit(1)

    with open(filepath, 'rb') as f:
        file_data = f.read()

    print(f"[*] File:        {filepath} ({len(file_data)} bytes)")
    print(f"[*] Destination: {dest}")
    print(f"[*] Chunks:      {-(-len(file_data) // CHUNK_SIZE)} × ≤{CHUNK_SIZE} bytes")
    print(f"[*] After write: {'reboot' if reboot else 'stay online'}")
    print()

    print(f"[*] Scanning for '{DEVICE_NAME}'...")
    device = await BleakScanner.find_device_by_name(DEVICE_NAME, timeout=10.0)
    if device is None:
        print(f"[!] '{DEVICE_NAME}' not found. Is the ESP32 on and advertising?")
        sys.exit(1)

    print(f"[+] Found {device.name} @ {device.address}")

    async with BleakClient(device, timeout=20.0) as client:
        if not client.is_connected:
            print("[!] Failed to connect.")
            sys.exit(1)

        print("[*] Connected. Waiting for MTU negotiation...")
        await asyncio.sleep(2.0)
        print(f"[*] MTU: {client.mtu_size} bytes")

        # ── Step 1: read nonce ────────────────────────────────────────────────
        nonce = bytes(await client.read_gatt_char(CHR_CHALLENGE))
        print(f"[+] Nonce: {nonce.hex()} ({len(nonce)} bytes)")
        if len(nonce) != 16:
            print(f"[!] Unexpected nonce length {len(nonce)}, expected 16")
            sys.exit(1)

        # ── Step 2: authenticate ──────────────────────────────────────────────
        # Message is just hex(nonce) — no port/expiry suffix like the lock service.
        message = nonce.hex()
        digest  = compute_hmac(key, message)
        print(f"[*] HMAC input:  {message!r}")
        print(f"[*] HMAC digest: {digest.hex()}")

        print("[*] Sending auth...")
        await client.write_gatt_char(CHR_AUTH, digest, response=True)
        # Give ESP32 time to verify and set self._authed
        await asyncio.sleep(0.5)

        # ── Step 3: send filename ─────────────────────────────────────────────
        filename_bytes = dest.encode('ascii')
        print(f"[*] Sending filename: {dest!r}")
        await client.write_gatt_char(CHR_FILENAME, filename_bytes, response=True)
        await asyncio.sleep(0.2)

        # ── Step 4: stream data chunks ────────────────────────────────────────
        total  = len(file_data)
        offset = 0
        chunk_num = 0
        while offset < total:
            chunk = file_data[offset:offset + CHUNK_SIZE]
            chunk_num += 1
            print(f"[*] Chunk {chunk_num}: bytes {offset}–{offset + len(chunk) - 1}")
            await client.write_gatt_char(CHR_DATA, chunk, response=True)
            offset += len(chunk)

        print(f"[+] All {total} bytes sent in {chunk_num} chunk(s)")

        # ── Step 5: commit (cmd_byte + SHA256 hash = 33 bytes) ───────────────
        cmd_byte    = 0x03 if reboot else 0x01
        file_hash   = hashlib.sha256(file_data).digest()
        commit_data = bytes([cmd_byte]) + file_hash
        print(f"[*] SHA256: {file_hash.hex()}")
        print(f"[*] Sending commit (0x{cmd_byte:02X} + hash)...")
        await client.write_gatt_char(CHR_COMMIT, commit_data, response=True)

        await asyncio.sleep(1.0)

    print()
    print("[+] Done. Check ESP32 serial output for 'UPD: wrote … bytes → …'")
    if reboot:
        print("[+] ESP32 should be rebooting now.")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="BLE file updater test — pushes a file to ESP32")
    ap.add_argument("--file",   required=True,
                    help="Local file to upload (e.g. config.py)")
    ap.add_argument("--dest",   default=None,
                    help="Destination filename on ESP32 (default: basename of --file)")
    ap.add_argument("--key",    default=DEFAULT_KEY,
                    help=f"HMAC key from _key_upd.py (default: {DEFAULT_KEY!r})")
    ap.add_argument("--reboot", action="store_true",
                    help="Reboot ESP32 after writing the file (commit command 0x03)")
    args = ap.parse_args()

    dest = args.dest or os.path.basename(args.file)
    asyncio.run(run(args.file, dest, args.key, args.reboot))
