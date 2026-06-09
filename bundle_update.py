#!/usr/bin/env python3
"""
Bundles .py files and the update key into ble_updater.html.

Usage:
    python3 bundle_update.py

Reads:
  - ble_updater.html       (template — the source of truth for the UI)
  - _key_upd.py            (HASH_KEY_UPD)
  - FILES_TO_BUNDLE list   (edit below to choose which files to include)

Writes:
  - ziplink_update.html    (self-contained, ready to host or share with customers)
"""

import json
import re
import sys

# ── Files to include in the update bundle ────────────────────────────────────
# Order matters: files are uploaded in this order. The last file triggers a
# reboot, so put the most critical file last (usually main.py or esp32_elock.py).
FILES_TO_BUNDLE = [
    'config.py',
    'consts.py',
    '_cfg_ble.py',
    '_cfg_network.py',
    '_cfg_serial.py',
    '_utils.py',
    '_crc_xmodem_table.py',
    'elock_hmac_sha256.py',
    'testHASH.py',
    'ble_elock.py',
    'ble_updater.py',
    'esp32_elock.py',
    'main.py',
]

OUTPUT_FILE   = 'ziplink_update.html'
TEMPLATE_FILE = 'ble_updater.html'
KEY_FILE      = '_key_upd.py'

# ── Read key ─────────────────────────────────────────────────────────────────

key_ns = {}
with open(KEY_FILE) as f:
    exec(f.read(), key_ns)

key = key_ns.get('HASH_KEY_UPD', '')
if not key or key == 'REPLACE_BEFORE_DEPLOY':
    print(f"[!] HASH_KEY_UPD in {KEY_FILE} is still the placeholder value.")
    print("    Set a real secret before distributing the HTML to customers.")
    sys.exit(1)

# ── Read and bundle files ─────────────────────────────────────────────────────

bundle = []
missing = []
for filename in FILES_TO_BUNDLE:
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            content = f.read()
        bundle.append({'name': filename, 'content': content})
        print(f"  + {filename} ({len(content)} bytes)")
    except FileNotFoundError:
        missing.append(filename)
        print(f"  - {filename} NOT FOUND, skipping")

if missing:
    print(f"\n[!] {len(missing)} file(s) missing — they will not be included in the update.")

# ── Inject into template ──────────────────────────────────────────────────────

with open(TEMPLATE_FILE, encoding='utf-8') as f:
    html = f.read()

html = html.replace("'__KEY__'",       json.dumps(key))
html = html.replace('__FILES__',       json.dumps(bundle, ensure_ascii=False))

with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
    f.write(html)

print(f"\n[+] {OUTPUT_FILE} generated ({len(bundle)} files, {len(html)} bytes total)")
print(f"    Share this file with customers — open in Chrome on Android,")
print(f"    or host on HTTPS for any device that supports Web Bluetooth.")
