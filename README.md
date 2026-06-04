# ZipLink ESP32 Lock Controller

MicroPython firmware för ESP32 som styr elektromagnetiska dörrlås via QR-kod (GM60-scanner) och BLE (hands-free).

---

## Aktivera/inaktivera funktioner

Alla funktioner styrs med booleanska flaggor i `config.py`:

| Flagga | Beskrivning |
|---|---|
| `DEBUG` | Verbose utskrift till seriell konsol |
| `SERIAL_ACTIVE` | Aktiverar QR-kodläsaren (GM60 via UART) |
| `PORTS_ACTIVE` | Aktiverar PWM-utmatning till lås |
| `BLE_ACTIVE` | Aktiverar BLE-upplåsning (se nedan) |
| `NVS_ACTIVE` | Lagrar tidsstämplar i flash (replay-skydd) |
| `WIFI_ACTIVE` | Skickar öppningshändelser till kameror via TCP |
| `TUNE_ACTIVE` | Spelar melodin vid upplåsning |

---

## BLE-upplåsning kopplad till köp

### Hur det fungerar

1. ESP32 annonserar som `ZipLink` över BLE.
2. Telefonen ansluter och läser en slumpmässig **nonce** (16 bytes) från CHALLENGE-characteristiken.
3. Telefonen skickar 31 bytes till RESPONSE-characteristiken:

```
byte[0]     : portnummer att låsa upp (1–3)
byte[1:15]  : utgångsdatum för köpet, ASCII "YYYYMMDDHHMMSS" (14 bytes)
byte[15:31] : HMAC-SHA256(HASH_KEY_NEW, hex(nonce)+':'+port+':'+expiry)[:16]
```

4. ESP32 verifierar HMAC och kontrollerar att utgångsdatumet är **nyare** än senast accepterade BLE-biljett (lagrat i NVS). Båda måste stämma → dörren låses upp.

Nonce är engångsanvänd — replay-attacker fungerar inte. Utgångsdatumet kopplar åtkomst till ett serverutfärdat köp.

---

### Aktivering — checklista

#### 1. Firmware (redan klart)
- [x] `BLE_ACTIVE = True` i `config.py`
- [x] `NVS_ACTIVE = True` i `config.py` (krävs för replay-skydd)
- [x] NVS-namnrymden `bledate` initieras automatiskt vid uppstart

#### 2. Byt ut hårdkodad nyckel
Filen `_key_new.py` innehåller en testfil. Ersätt med en riktig nyckel innan driftsättning:

```python
# _key_new.py
HASH_KEY_NEW: str = const(r'DIN_HEMLIGA_NYCKEL_HÄR')
HASH_KEY_NEW_ID: str = const(r'prod')
```

Nyckeln ska **aldrig** committas till versionshantering — lägg till `_key_new.py` i `.gitignore`.

#### 3. Backend — utfärda BLE-biljett vid köp

När ett köp genomförs ska backend returnera ett utgångsdatum till appen:

```python
from datetime import datetime, timedelta

def issue_ble_ticket(purchase_duration_hours: int, port: int) -> dict:
    expiry = datetime.now() + timedelta(hours=purchase_duration_hours)
    expiry_str = expiry.strftime("%Y%m%d%H%M%S")  # "YYYYMMDDHHMMSS"
    return {
        "port": port,
        "expiry": expiry_str,
    }
```

Biljetten behöver **inte** signeras av backend — signaturen beräknas av appen i steg 4.

#### 4. App — beräkna och skicka BLE-payload

Appen tar emot nonce från ESP32 och bygger svaret:

```python
import hmac, hashlib, binascii

def build_ble_payload(nonce: bytes, port: int, expiry: str, key: str) -> bytes:
    msg = binascii.hexlify(nonce).decode() + ':' + str(port) + ':' + expiry
    full_hmac = hmac.new(key.encode(), msg.encode(), hashlib.sha256).digest()
    return bytes([port]) + expiry.encode() + full_hmac[:16]  # 31 bytes
```

> **OBS:** `key` är `HASH_KEY_NEW` från `_key_new.py`. Antingen distribueras nyckeln till appen (klienthemlighet) eller så signerar backend meddelandet och returnerar HMAC direkt — då behöver appen aldrig känna till nyckeln.

#### 5. Säkerhetsnivåer att välja mellan

| Alternativ | Nyckel finns i | Säkerhet |
|---|---|---|
| **A. Nyckel i app** | Appen + ESP32 | Enklare, men nyckel kan extraheras ur appen |
| **B. Backend signerar** | Endast backend + ESP32 | Starkare — appen skickar bara `(nonce, port, expiry)` till backend och får tillbaka HMAC |

För alternativ B skickar appen till backend:
```json
{ "nonce": "<hex>", "port": 1, "expiry": "20261231235959" }
```
Backend returnerar:
```json
{ "hmac": "<16 bytes hex>" }
```
Appen bygger sedan payload: `bytes([port]) + expiry.encode() + bytes.fromhex(hmac_hex)`.

---

## QR-kodformat

```
YYYYMMDDHHMMSS[/pPORT,PORT][/uUNIT][/iID][/c]::BASE64_HMAC
```

Exempel:
```
20261231235959/p1::ABC123==          (port 1)
20261231235959/p1,2/u5/i42::ABC123== (port 1+2, enhet 5, id 42)
20261231235959/c::ABC123==           (admin, öppnar ej lås)
```

---

## GPIO-pinnar

| Pin | Funktion |
|---|---|
| GPIO 18 | Port 1 (PWM → MOSFET → lås) |
| GPIO 19 | Port 2 |
| GPIO 4 | Port 3 |
| UART2 | GM60 QR-kodscanner |
