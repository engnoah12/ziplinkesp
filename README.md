# ZipLink ESP32 Lock Controller

MicroPython firmware för ESP32 som styr elektromagnetiska dörrlås via QR-kod (GM60-scanner) och BLE (hands-free).

---

## Initial setup — ny ESP32

### 1. Flasha MicroPython

Ladda ned senaste MicroPython-firmware för ESP32 från [micropython.org](https://micropython.org/download/ESP32_GENERIC/) och flasha:

```bash
pip install esptool
esptool.py --chip esp32 --port /dev/cu.usbserial-XXXX erase_flash
esptool.py --chip esp32 --port /dev/cu.usbserial-XXXX write_flash -z 0x1000 ESP32_GENERIC-*.bin
```

### 2. Ladda upp firmware-filer

Installera `mpremote` och kopiera alla `.py`-filer till ESP32:n:

```bash
pip install mpremote
mpremote connect /dev/cu.usbserial-XXXX cp boot.py main.py esp32_elock.py ble_elock.py ble_updater.py :
mpremote connect /dev/cu.usbserial-XXXX cp config.py consts.py elock_hmac_sha256.py testHASH.py :
mpremote connect /dev/cu.usbserial-XXXX cp _cfg_ble.py _cfg_network.py _cfg_serial.py _utils.py _crc_xmodem_table.py :
```

Skapa och ladda upp nyckelfilerna (kopieras aldrig från repot — innehåller hemligheter):

```bash
mpremote connect /dev/cu.usbserial-XXXX cp _key_new.py _key_upd.py :
```

### 3. Verifiera

```bash
mpremote connect /dev/cu.usbserial-XXXX repl
# Ctrl+D för soft reboot — du ska se "Enter Main Loop: All ok!"
```

> **OBS:** `boot.py` ligger utanför BLE-whitelisten och kan aldrig uppdateras trådlöst. Ändringar i `boot.py` måste alltid laddas upp via USB:
> ```bash
> mpremote connect /dev/cu.usbserial-XXXX cp boot.py :boot.py
> ```

---

## Aktivera/inaktivera funktioner

Alla funktioner styrs med booleanska flaggor i `config.py`:

| Flagga | Beskrivning |
|---|---|
| `DEBUG` | Verbose utskrift till seriell konsol |
| `SERIAL_ACTIVE` | Aktiverar QR-kodläsaren (GM60 via UART) — **måste vara `False` vid NFC-testning** (GM60 och PN532 delar GPIO 16/17) |
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
   - Avsluta → `UPD_COMMIT` (33 bytes: `[cmd (1)]` + `[SHA256 av filen (32)]`)
     - `0x01` = spara, `0x02` = avbryt, `0x03` = spara + starta om
   - ESP32 verifierar SHA256 mot mottagen data innan filen skrivs till flash
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

**Testa lokalt utan Supabase:** `localhost` fungerar utan HTTPS i Chrome:

```bash
python3 bundle_update.py config.py   # generera ziplink_update.html
python3 -m http.server 8080
# Öppna http://localhost:8080/ziplink_update.html i Chrome
```

`ziplink_update.html` och `admin.html` är i `.gitignore` och ska aldrig committas (innehåller nyckeln).

#### Alternativ: generera lokalt

Om Supabase inte används kan kundsidan genereras lokalt och delas manuellt:

```bash
python3 bundle_update.py                     # alla filer
python3 bundle_update.py config.py main.py   # bara valda filer
```

### Rollback-mekanism

ESP32:n skyddar mot att bli obrukbar vid en trasig eller ofullständig uppdatering:

**Uppdateringsflöde (atomärt):**
```
1. Ny fil skrivs till <filnamn>.tmp
2. SHA256 verifieras mot .tmp
3. Befintlig fil döps om till <filnamn>.bak
4. .tmp döps om till <filnamn>  (atomärt swap)
5. boot_ok.flag tas bort
6. ESP32 startar om
```

**Vid uppstart kontrollerar `boot.py`:**
- `.tmp`-filer → tas bort (avbruten överföring)
- `boot_ok.flag` saknas + `.bak`-filer finns → rollback: alla `.bak` återställs, flaggan skrivs, omstart
- `boot_ok.flag` finns → normal start, `.bak`-filer rensas efter lyckad initiering

**`boot_ok.flag` skrivs** av `esp32_elock.py` när all initiering lyckats (`Enter Main Loop: All ok!`).

Filen `boot.py` finns **inte** i BLE-whitelisten och kan aldrig skrivas över trådlöst — rollback-logiken är alltid intakt.

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

## NFC-access (under utveckling — branch `feature/nfc-access`)

Tillåter upplåsning via NFC-tap med telefon eller kort — utan app, utan BLE-dialog.

### Hårdvara

| Komponent | Koppling |
|---|---|
| PN532 NFC-modul | I2C: SDA → GPIO 16, SCL → GPIO 17 |
| VCC | 5V (PN532 har inbyggd regulator) |
| DIP-switch | SW1 = ON, SW2 = OFF (I2C-läge) |

> **OBS — `SERIAL_ACTIVE` i `config.py`:**
> GPIO 16 och 17 delas av GM60 QR-scannern och PN532 NFC-modulen.
> - **NFC aktiv:** sätt `SERIAL_ACTIVE = False`
> - **GM60 aktiv:** sätt `SERIAL_ACTIVE = True` (och koppla ur PN532)

### Credential-format

Samma format som QR-koden — ingen ny nyckel eller backend-logik behövs:

```
YYYYMMDDHHMMSS/pPORT::BASE64_HMAC
```

### Källor som stöds

| Källa | Protokoll | iOS | Android |
|---|---|---|---|
| **Android HCE** | SELECT AID `F05A49504C4E4B` → GET CREDENTIAL | ✗ | ✓ |
| **Apple Wallet VAS** | SELECT VAS AID → GET VAS DATA | ✓ | ✓ |
| **Fysiskt NFC-kort** | UID-läsning | ✓ | ✓ |

### iOS-begränsning

Apple tillåter inte Web Bluetooth eller tredjepartsappar att använda HCE. iOS-kunder behöver antingen:
- **Apple Wallet-pass** med NFC-credential (kräver Apple Developer-konto + VAS merchant-registrering)
- **BLE-upplåsning** som fallback tills Wallet-integration är klar

### Android HCE — vad som behövs i appen

Android-appen måste registrera en `HostApduService` med ZipLinks AID:

```xml
<!-- AndroidManifest.xml -->
<service android:name=".ZipLinkHceService"
         android:exported="true"
         android:permission="android.permission.BIND_NFC_SERVICE">
    <intent-filter>
        <action android:name="android.nfc.cardemulation.action.HOST_APDU_SERVICE"/>
    </intent-filter>
    <meta-data android:name="android.nfc.cardemulation.host_apdu_service"
               android:resource="@xml/apduservice"/>
</service>
```

```xml
<!-- res/xml/apduservice.xml -->
<host-apdu-service>
    <aid-group category="other">
        <aid-filter name="ZipLink" value="F05A49504C4E4B"/>
    </aid-group>
</host-apdu-service>
```

Tjänsten svarar på `GET CREDENTIAL (80 20 00 00 00)` med credential-strängen + `90 00`:

```kotlin
override fun processCommandApdu(apdu: ByteArray, extras: Bundle?): ByteArray {
    val credential = "20261231235959/p1::BASE64_HMAC"
    return credential.toByteArray() + byteArrayOf(0x90.toByte(), 0x00)
}
```

### Testskript

```bash
# Verifiera att PN532 hittas på I2C
exec(open('test_i2c_scan.py').read())   # i MicroPython REPL

# Testa UID-läsning
exec(open('test_nfc.py').read())

# Testa fullständigt access-flöde
exec(open('test_nfc_access.py').read())
```

### Filer

| Fil | Beskrivning |
|---|---|
| `nfc_pn532.py` | PN532 I2C-drivrutin med APDU-stöd |
| `nfc_access.py` | Access-logik: HCE, VAS, credential-verifiering |
| `test_nfc.py` | Grundläggande UID-scan |
| `test_nfc_access.py` | Fullständigt access-test |
| `test_i2c_scan.py` | I2C-busskan för hårdvaruverifiering |

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
