#!/usr/bin/env python3
"""
Bundles .py files and the update key into ble_updater.html.

Usage:
    python3 bundle_update.py                     # alla filer i ALL_FILES
    python3 bundle_update.py config.py main.py   # bara angivna filer
    python3 bundle_update.py --admin             # genererar admin.html

Reads:
  - ble_updater.html   (template)
  - _key_upd.py        (HASH_KEY_UPD, krävs ej för --admin)

Writes:
  - ziplink_update.html  (kundsida, redo att dela)
  - admin.html           (adminpanel, endast vid --admin)
"""

import hashlib
import json
import sys

# ── Full file list — used when no arguments are given ────────────────────────
# Order matters: files are uploaded in this order. The last file triggers a
# reboot, so put the most critical file last (usually main.py or esp32_elock.py).
ALL_FILES = [
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

TEMPLATE_FILE = 'ble_updater.html'
OUTPUT_FILE   = 'ziplink_update.html'
KEY_FILE      = '_key_upd.py'
ADMIN_FILE    = 'admin.html'

# ── Admin page generation ─────────────────────────────────────────────────────

def generate_admin():
    with open(TEMPLATE_FILE, encoding='utf-8') as f:
        template = f.read()

    # Escape </script> so it doesn't break out of the JS block in admin.html
    template_json = json.dumps(template).replace('</script>', r'<\/script>')

    admin_html = f"""<!DOCTYPE html>
<html lang="sv">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ZipLink Admin</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f5f5f7; min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 24px; }}
  .card {{ background: #fff; border-radius: 20px; padding: 40px 32px; max-width: 560px; width: 100%; box-shadow: 0 4px 24px rgba(0,0,0,0.08); }}
  .logo {{ font-size: 22px; font-weight: 700; letter-spacing: -0.5px; color: #1d1d1f; margin-bottom: 4px; text-align: center; }}
  .subtitle {{ font-size: 14px; color: #6e6e73; margin-bottom: 32px; text-align: center; }}
  .section {{ margin-bottom: 24px; }}
  .section-label {{ font-size: 12px; font-weight: 600; color: #6e6e73; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.5px; }}
  .row {{ display: flex; gap: 8px; }}
  .row input, .full-input {{ flex: 1; padding: 10px 14px; border: 1.5px solid #d1d1d6; border-radius: 10px; font-size: 14px; outline: none; transition: border-color 0.2s; width: 100%; }}
  .row input:focus, .full-input:focus {{ border-color: #0071e3; }}
  .mono {{ font-family: monospace; }}
  .btn-secondary {{ padding: 10px 16px; border: 1.5px solid #d1d1d6; border-radius: 10px; background: #fff; font-size: 14px; cursor: pointer; color: #1d1d1f; white-space: nowrap; }}
  .btn-secondary:hover {{ background: #f5f5f7; }}
  details {{ margin-bottom: 24px; }}
  details summary {{ font-size: 12px; font-weight: 600; color: #6e6e73; text-transform: uppercase; letter-spacing: 0.5px; cursor: pointer; list-style: none; display: flex; align-items: center; gap: 6px; margin-bottom: 8px; }}
  details summary::before {{ content: '▶'; font-size: 10px; transition: transform 0.2s; }}
  details[open] summary::before {{ transform: rotate(90deg); }}
  details .fields {{ display: flex; flex-direction: column; gap: 8px; }}
  .dropzone {{ border: 2px dashed #d1d1d6; border-radius: 12px; padding: 20px; text-align: center; font-size: 14px; color: #6e6e73; cursor: pointer; transition: border-color 0.2s, background 0.2s; }}
  .dropzone.drag-over {{ border-color: #0071e3; background: #f0f7ff; }}
  .dropzone span {{ color: #0071e3; text-decoration: underline; }}
  .file-list {{ margin-top: 10px; display: flex; flex-direction: column; gap: 6px; }}
  .file-item {{ display: flex; align-items: center; gap: 10px; padding: 10px 12px; background: #f5f5f7; border-radius: 10px; font-size: 14px; cursor: grab; user-select: none; transition: background 0.15s; }}
  .file-item.dragging {{ opacity: 0.4; }}
  .file-item.drag-target {{ background: #e8f0fe; }}
  .drag-handle {{ color: #aeaeb2; font-size: 16px; cursor: grab; }}
  .file-name {{ flex: 1; font-family: monospace; color: #1d1d1f; }}
  .file-size {{ color: #6e6e73; font-size: 12px; white-space: nowrap; }}
  .file-sha  {{ font-family: monospace; font-size: 11px; color: #aeaeb2; }}
  .file-badge {{ font-size: 11px; font-weight: 600; padding: 2px 7px; border-radius: 6px; background: #e8f0fe; color: #0071e3; white-space: nowrap; }}
  .file-badge.reboot {{ background: #fff0e8; color: #ff6b00; }}
  .remove-btn {{ background: none; border: none; color: #aeaeb2; cursor: pointer; font-size: 18px; line-height: 1; padding: 0 2px; }}
  .remove-btn:hover {{ color: #ff3b30; }}
  .empty-state {{ text-align: center; color: #aeaeb2; font-size: 14px; padding: 12px 0; }}
  .btn-primary {{ width: 100%; padding: 16px; border: none; border-radius: 12px; background: #0071e3; color: #fff; font-size: 17px; font-weight: 600; cursor: pointer; transition: background 0.2s, opacity 0.2s; margin-top: 8px; }}
  .btn-primary:hover {{ background: #0077ed; }}
  .btn-primary:active {{ background: #006cce; }}
  .btn-primary:disabled {{ opacity: 0.45; cursor: default; }}
  .success-box {{ margin-top: 16px; padding: 16px; background: #f0faf4; border-radius: 12px; display: none; }}
  .success-box p {{ font-size: 14px; color: #34c759; font-weight: 500; margin-bottom: 10px; }}
  .url-row {{ display: flex; gap: 8px; align-items: center; }}
  .url-row input {{ flex: 1; padding: 9px 12px; border: 1.5px solid #c8f0d6; border-radius: 8px; font-size: 13px; font-family: monospace; background: #fff; color: #1d1d1f; outline: none; }}
  .error-msg {{ margin-top: 16px; padding: 14px; background: #fff2f2; border-radius: 10px; font-size: 14px; color: #ff3b30; display: none; }}
  .spinner {{ display: inline-block; width: 16px; height: 16px; border: 2px solid rgba(255,255,255,0.4); border-top-color: #fff; border-radius: 50%; animation: spin 0.7s linear infinite; vertical-align: middle; margin-right: 6px; }}
  @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
</style>
</head>
<body>
<div class="card">
  <div class="logo">ZipLink</div>
  <div class="subtitle">Admin — Publicera uppdateringssida</div>

  <details id="settings-details">
    <summary>Supabase-inställningar</summary>
    <div class="fields">
      <input class="full-input mono" id="sb-url"    placeholder="https://xxx.supabase.co"      oninput="saveSettings()">
      <input class="full-input mono" id="sb-key"    placeholder="service_role eller anon key" type="password" oninput="saveSettings()">
      <input class="full-input mono" id="sb-bucket" placeholder="Bucket-namn, t.ex. updates"    oninput="saveSettings()">
    </div>
  </details>

  <div class="section">
    <div class="section-label">Uppdateringsnyckel</div>
    <div class="row">
      <input type="password" id="key-input" class="mono" placeholder="HASH_KEY_UPD från _key_upd.py">
      <button class="btn-secondary" onclick="toggleKey()">Visa</button>
    </div>
  </div>

  <div class="section">
    <div class="section-label">Filer att inkludera</div>
    <div class="dropzone" id="dropzone"
         onclick="document.getElementById('file-input').click()"
         ondragover="onDragOver(event)" ondragleave="onDragLeave()" ondrop="onDrop(event)">
      Dra filer hit eller <span>välj filer</span>
    </div>
    <input type="file" id="file-input" multiple accept=".py,.json,.txt" hidden onchange="addFiles(this.files)">
    <div class="file-list" id="file-list"></div>
  </div>

  <button class="btn-primary" id="pub-btn" onclick="publish()">Publicera</button>

  <div class="success-box" id="success-box">
    <p>Sidan är publicerad!</p>
    <div class="url-row">
      <input type="text" id="pub-url" readonly>
      <button class="btn-secondary" onclick="copyUrl()">Kopiera</button>
    </div>
  </div>
  <div class="error-msg" id="error-msg"></div>
</div>

<script>
const TEMPLATE = {template_json};
const FILENAME  = 'ziplink_update.html';

let files   = [];
let dragSrc = null;

function saveSettings() {{
  localStorage.setItem('zl_sb_url',    document.getElementById('sb-url').value.trim());
  localStorage.setItem('zl_sb_key',    document.getElementById('sb-key').value.trim());
  localStorage.setItem('zl_sb_bucket', document.getElementById('sb-bucket').value.trim());
}}

function loadSettings() {{
  document.getElementById('sb-url').value    = localStorage.getItem('zl_sb_url')    || '';
  document.getElementById('sb-key').value    = localStorage.getItem('zl_sb_key')    || '';
  document.getElementById('sb-bucket').value = localStorage.getItem('zl_sb_bucket') || '';
  if (!localStorage.getItem('zl_sb_url')) document.getElementById('settings-details').open = true;
}}

function toggleKey() {{
  const inp = document.getElementById('key-input');
  inp.type  = inp.type === 'password' ? 'text' : 'password';
}}

function showError(msg) {{
  const el = document.getElementById('error-msg');
  el.textContent   = msg;
  el.style.display = 'block';
  document.getElementById('success-box').style.display = 'none';
}}

function copyUrl() {{
  navigator.clipboard.writeText(document.getElementById('pub-url').value).then(() => {{
    const btn = document.querySelector('.url-row .btn-secondary');
    btn.textContent = 'Kopierad!';
    setTimeout(() => btn.textContent = 'Kopiera', 2000);
  }});
}}

function onDragOver(e) {{ e.preventDefault(); document.getElementById('dropzone').classList.add('drag-over'); }}
function onDragLeave()  {{ document.getElementById('dropzone').classList.remove('drag-over'); }}
function onDrop(e)      {{ e.preventDefault(); document.getElementById('dropzone').classList.remove('drag-over'); addFiles(e.dataTransfer.files); }}

async function addFiles(fileList) {{
  await Promise.all(Array.from(fileList).map(async file => {{
    const content = await file.text();
    const bytes   = new TextEncoder().encode(content);
    const hashBuf = await crypto.subtle.digest('SHA-256', bytes);
    const sha256  = Array.from(new Uint8Array(hashBuf)).map(b => b.toString(16).padStart(2, '0')).join('');
    const idx     = files.findIndex(f => f.name === file.name);
    const entry   = {{ name: file.name, content, size: file.size, sha256 }};
    if (idx >= 0) files[idx] = entry; else files.push(entry);
  }}));
  renderList();
}}

function formatSize(b) {{ return b < 1024 ? b + ' B' : (b / 1024).toFixed(1) + ' kB'; }}

function renderList() {{
  const list = document.getElementById('file-list');
  if (!files.length) {{ list.innerHTML = '<div class="empty-state">Inga filer valda ännu</div>'; return; }}
  list.innerHTML = files.map((f, i) => {{
    const isLast = i === files.length - 1;
    const badge  = isLast ? '<span class="file-badge reboot">↺ startar om</span>' : '<span class="file-badge">commit</span>';
    return `<div class="file-item" draggable="true"
        ondragstart="dragStart(event,${{i}})" ondragover="dragOver(event,${{i}})"
        ondrop="dragDrop(event,${{i}})" ondragend="dragEnd()">
      <span class="drag-handle">⠇</span>
      <span class="file-name">${{f.name}}</span>
      <span class="file-size">${{formatSize(f.size)}}</span>
      <span class="file-sha" title="${{f.sha256 || ''}}">${{f.sha256 ? f.sha256.slice(0, 8) + '…' : ''}}</span>
      ${{badge}}
      <button class="remove-btn" onclick="removeFile(${{i}})">&#215;</button>
    </div>`;
  }}).join('');
}}

function removeFile(i) {{ files.splice(i, 1); renderList(); }}

function dragStart(e, i) {{ dragSrc = i; e.target.classList.add('dragging'); e.dataTransfer.effectAllowed = 'move'; }}
function dragOver(e, i)  {{ e.preventDefault(); document.querySelectorAll('.file-item').forEach((el, j) => el.classList.toggle('drag-target', j === i && i !== dragSrc)); }}
function dragDrop(e, i)  {{ e.preventDefault(); if (dragSrc === null || dragSrc === i) return; files.splice(i, 0, files.splice(dragSrc, 1)[0]); renderList(); }}
function dragEnd()       {{ dragSrc = null; document.querySelectorAll('.file-item').forEach(el => el.classList.remove('dragging', 'drag-target')); }}

async function publish() {{
  document.getElementById('error-msg').style.display   = 'none';
  document.getElementById('success-box').style.display = 'none';

  const key    = document.getElementById('key-input').value.trim();
  const sbUrl  = (localStorage.getItem('zl_sb_url')    || '').replace(/\\/$/, '');
  const sbKey  = localStorage.getItem('zl_sb_key')    || '';
  const bucket = localStorage.getItem('zl_sb_bucket') || '';

  if (!sbUrl || !sbKey || !bucket) {{ document.getElementById('settings-details').open = true; showError('Fyll i Supabase-inställningarna först.'); return; }}
  if (!key)          {{ showError('Ange uppdateringsnyckeln.'); return; }}
  if (!files.length) {{ showError('Lägg till minst en fil.'); return; }}

  const btn     = document.getElementById('pub-btn');
  btn.disabled  = true;
  btn.innerHTML = '<span class="spinner"></span>Publicerar...';

  try {{
    const bundle = files.map(f => ({{ name: f.name, content: f.content, sha256: f.sha256 }}));
    let   html   = TEMPLATE;
    html = html.replace("'__KEY__'", JSON.stringify(key));
    html = html.replace('__FILES__',  JSON.stringify(bundle));

    const resp = await fetch(`${{sbUrl}}/storage/v1/object/${{bucket}}/${{FILENAME}}`, {{
      method:  'POST',
      headers: {{ 'Authorization': `Bearer ${{sbKey}}`, 'Content-Type': 'text/html', 'x-upsert': 'true' }},
      body:    html,
    }});

    if (!resp.ok) throw new Error(`Supabase svarade ${{resp.status}}: ${{await resp.text()}}`);

    const publicUrl = `${{sbUrl}}/storage/v1/object/public/${{bucket}}/${{FILENAME}}`;
    document.getElementById('pub-url').value          = publicUrl;
    document.getElementById('success-box').style.display = 'block';

  }} catch (err) {{
    showError('Uppladdning misslyckades: ' + err.message);
  }} finally {{
    btn.disabled  = false;
    btn.innerHTML = 'Publicera';
  }}
}}

loadSettings();
renderList();
</script>
</body>
</html>"""

    with open(ADMIN_FILE, 'w', encoding='utf-8') as f:
        f.write(admin_html)

    print(f"[+] {ADMIN_FILE} genererad — öppna i webbläsaren")


# ── Customer page generation ──────────────────────────────────────────────────

def generate_customer(files_to_bundle):
    key_ns = {}
    with open(KEY_FILE) as f:
        exec(f.read(), key_ns)

    key = key_ns.get('HASH_KEY_UPD', '')
    if not key or key == 'REPLACE_BEFORE_DEPLOY':
        print(f"[!] HASH_KEY_UPD i {KEY_FILE} är fortfarande platshållarvärdet.")
        print("    Sätt en riktig nyckel innan du delar sidan med kunder.")
        sys.exit(1)

    bundle  = []
    missing = []
    for filename in files_to_bundle:
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                content = f.read()
            sha256 = hashlib.sha256(content.encode('utf-8')).hexdigest()
            bundle.append({'name': filename, 'content': content, 'sha256': sha256})
            print(f"  + {filename} ({len(content)} bytes)  {sha256[:16]}…")
        except FileNotFoundError:
            missing.append(filename)
            print(f"  - {filename} SAKNAS, hoppas över")

    if missing:
        print(f"\n[!] {len(missing)} fil(er) saknas och ingår inte i uppdateringen.")

    with open(TEMPLATE_FILE, encoding='utf-8') as f:
        html = f.read()

    html = html.replace("'__KEY__'", json.dumps(key))
    html = html.replace('__FILES__',  json.dumps(bundle, ensure_ascii=False))

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"\n[+] {OUTPUT_FILE} genererad ({len(bundle)} filer, {len(html)} bytes totalt)")
    print(f"    Dela med kunder — öppna i Chrome (Android) eller Bluefy (iOS).")


# ── Entry point ───────────────────────────────────────────────────────────────

args  = [a for a in sys.argv[1:] if not a.startswith('-')]
flags = [a for a in sys.argv[1:] if a.startswith('-')]

if '--admin' in flags:
    generate_admin()
elif args:
    print(f"[*] Buntar {len(args)} angiven(a) fil(er):")
    generate_customer(args)
else:
    print(f"[*] Buntar alla {len(ALL_FILES)} filer:")
    generate_customer(ALL_FILES)
