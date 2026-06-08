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

#### 3. Backend — Supabase Edge Function

Koden finns i `supabase/functions/ble-ticket/index.ts`. Telefonen anropar den med nonce och port, och får tillbaka expiry + HMAC. Nyckeln lämnar aldrig servern.

**Autentisering:** Anropet kräver ett giltigt Supabase JWT i `Authorization`-headern. Utan det returneras `401`.

**Driftsätt:**

```bash
supabase secrets set HASH_KEY_NEW=<din nyckel>
supabase functions deploy ble-ticket
```

**TODO:** Fyll i databasfrågan i filen (markerat med `TODO`) när köp-tabellens struktur är klar.

#### 4. App — bygg och skicka BLE-payload

Telefonen:
1. Ansluter till BLE, tar emot nonce (hex-sträng, 32 tecken)
2. Anropar Edge Function med användarens Supabase-session:

```json
POST /functions/v1/ble-ticket
Authorization: Bearer <supabase-session-token>
{ "nonce": "a3f7c2...", "port": 1 }
```

3. Får tillbaka:

```json
{ "expiry": "20261231235959", "hmac": "9a3f..." }
```

4. Bygger 31-byte payload och skickar till RESPONSE-characteristiken:

```
bytes([port]) + expiry.encode() + bytes.fromhex(hmac)
```

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
