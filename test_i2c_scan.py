from machine import SoftI2C, Pin
import utime

i2c = SoftI2C(scl=Pin(17), sda=Pin(16), freq=100000)

print("Scanning I2C bus...")
devices = i2c.scan()

if devices:
    for d in devices:
        print(f"  Found device at address: 0x{d:02X}")
    if 0x24 in devices:
        print("  → PN532 detected (0x24) ✓")
    else:
        print("  → PN532 not found — check jumpers (SEL0=LOW, SEL1=HIGH)")
else:
    print("  No devices found — check wiring and PN532 I2C mode jumpers")
