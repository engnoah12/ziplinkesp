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

## BLE-testskript (utan Supabase)

`test_ble_unlock.py` låter dig testa BLE-upplåsningen direkt från en Mac utan att behöva Supabase eller en app. HMAC beräknas lokalt med nyckeln från `_key_new.py`.

**Installation:**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install bleak
```

**Kör:**

```bash
python3 test_ble_unlock.py
```

**Flaggor:**

| Flagga | Beskrivning | Standard |
|---|---|---|
| `--port` | Portnummer att låsa upp (1–3) | `1` |
| `--key` | HMAC-nyckel (måste matcha `_key_new.py`) | `0123456789ABCDEFG` |
| `--expiry` | Utgångsdatum `YYYYMMDDHHMMSS` | `20261231235959` |

**OBS — NVS replay-skydd:** Varje expiry-tidsstämpel kan bara accepteras en gång. Vid upprepade tester måste `--expiry` ökas för varje körning:

```bash
python3 test_ble_unlock.py --expiry 20271231235959
python3 test_ble_unlock.py --expiry 20281231235959
# osv...
```

---

## BLE-filuppdatering (OTA)

Tillåter att `.py`-filer på ESP32:n uppdateras trådlöst via BLE — utan USB-kabel eller WiFi. Kunden behöver ingen teknisk kunskap.

### Hur det fungerar

1. ESP32 exponerar en separat GATT-tjänst (UUID `6E400011-...`) parallellt med låstjänsten.
2. Telefonen ansluter och tar emot en **nonce** från `UPD_CHALLENGE`.
3. Telefonen autentiserar med `HMAC-SHA256(HASH_KEY_UPD, hex(nonce))` → `UPD_AUTH`.
4. Efter godkänd autentisering kan telefonen skicka filer:
   - Filnamn → `UPD_FILENAME`
   - Fildata i ≤200-byte bitar → `UPD_DATA`
   - Avsluta → `UPD_COMMIT` (`0x01` = spara, `0x02` = avbryt, `0x03` = spara + starta om)
5. Flera filer kan skickas i samma session.

Separata nycklar: `HASH_KEY_UPD` är oberoende av `HASH_KEY_NEW` — ett läckt upplåsningsnyckel ger inte åtkomst till uppdatering och vice versa.

### Säkerhetsgränser

Följande filer **kan inte** skrivas om via BLE (skyddas av en whitelist i `_cfg_ble.py`):

- `boot.py` — en trasig boot-fil kan bricka enheten
- `_key_new.py`, `_key_upd.py`, `_key_old.py` — nycklar ska aldrig kunna skrivas över trådlöst

### Sätta upp uppdateringsnyckeln

Skapa `_key_upd.py` med en unik hemlighet:

```python
# _key_upd.py
HASH_KEY_UPD = 'DIN_HEMLIGA_UPPDATERINGSNYCKEL_HÄR'
```

Filen ska **aldrig** committas — den finns redan i `.gitignore`.

### Adminpanel och publicering via Supabase Storage

Uppdateringsflödet är byggt kring en adminpanel (`admin.html`) som publicerar kundsidan direkt till **Supabase Storage**. Kunden får en fast URL som alltid pekar på senaste versionen.

#### Flöde

```
Admin (admin.html)
  1. Fyller i Supabase-inställningar (sparas i webbläsaren)
  2. Anger uppdateringsnyckeln (HASH_KEY_UPD)
  3. Drar in de .py-filer som ska ingå i uppdateringen
  4. Trycker "Publicera"
     → ziplink_update.html laddas upp till Supabase Storage
     → En publik URL visas att kopiera och skicka till kunden

Kund
  5. Öppnar URL:en i Chrome (Android) eller Bluefy (iOS)
  6. Trycker "Starta uppdatering" och väljer ZipLink i listan
     → Telefonen autentiserar och laddar upp filerna via BLE
     → ESP32:n startar om med ny programvara
```

#### Sätta upp Supabase Storage

1. Skapa en publik bucket i Supabase dashboard (t.ex. `updates`)
2. Notera projektets URL (`https://xxx.supabase.co`) och en API-nyckel med skrivbehörighet till storage

#### Generera adminpanel

```bash
python3 bundle_update.py --admin   # → admin.html
```

Öppna `admin.html` i webbläsaren och fyll i inställningarna under **Supabase-inställningar** (sparas automatiskt i `localStorage`).

#### Krav för kundsidan

Sidan måste öppnas via `https://` — Supabase Storage tillhandahåller detta automatiskt.
- **Android:** Chrome
- **iOS:** [Bluefy](https://apps.apple.com/app/bluefy-web-ble-browser/id1492822055) (App Store, gratis)

`ziplink_update.html` och `admin.html` är i `.gitignore` och ska aldrig committas (innehåller nyckeln).

#### Alternativ: generera lokalt

Om Supabase inte används kan kundsidan genereras lokalt och delas manuellt:

```bash
python3 bundle_update.py                     # alla filer
python3 bundle_update.py config.py main.py   # bara valda filer
```

### Testskript (utan telefon)

```bash
python3 test_ble_updater.py --file config.py
python3 test_ble_updater.py --file config.py --reboot
```

| Flagga | Beskrivning | Standard |
|---|---|---|
| `--file` | Lokal fil att ladda upp | *(krävs)* |
| `--dest` | Målfilnamn på ESP32 | samma som `--file` |
| `--key` | HMAC-nyckel (måste matcha `_key_upd.py`) | värdet i `_key_upd.py` |
| `--reboot` | Starta om ESP32 efter uppladdning | `False` |

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
