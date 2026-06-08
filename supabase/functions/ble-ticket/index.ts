// supabase/functions/ble-ticket/index.ts
//
// Generates a BLE unlock ticket for a user with a valid purchase.
//
// Request  (POST, JSON): { nonce: string (32 hex chars), port: number (1-3) }
// Response (JSON):       { expiry: string ("YYYYMMDDHHMMSS"), hmac: string (32 hex chars) }
//
// The HMAC is computed as:
//   HMAC-SHA256(HASH_KEY_NEW, hex(nonce) + ':' + port + ':' + expiry)[:16]
// which matches exactly what the ESP32 verifies in ble_elock.py.

// ─── HMAC helper ─────────────────────────────────────────────────────────────

async function computeHmac(key: string, message: string): Promise<string> {
  // Import the secret key into Web Crypto
  const cryptoKey = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(key),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );

  // Sign the message
  const signature = await crypto.subtle.sign(
    "HMAC",
    cryptoKey,
    new TextEncoder().encode(message),
  );

  // Take the first 16 bytes and convert to hex (matches _HMAC_LEN in ble_elock.py)
  return Array.from(new Uint8Array(signature).slice(0, 16))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

// ─── Main handler ─────────────────────────────────────────────────────────────

Deno.serve(async (req) => {
  if (req.method !== "POST") {
    return new Response("Method not allowed", { status: 405 });
  }

  // ── 1. Parse and validate input ──────────────────────────────────────────

  let nonce: string, port: number;
  try {
    ({ nonce, port } = await req.json());
  } catch {
    return new Response("Invalid JSON", { status: 400 });
  }

  // nonce is 16 bytes from the ESP32, hex-encoded → 32 characters
  if (typeof nonce !== "string" || nonce.length !== 32 || !/^[0-9a-f]+$/i.test(nonce)) {
    return new Response("Invalid nonce", { status: 400 });
  }
  if (![1, 2, 3].includes(port)) {
    return new Response("Invalid port", { status: 400 });
  }

  // ── 2. Verify user has a valid purchase ──────────────────────────────────
  //
  // TODO: query your purchases table here once you have access to Supabase.
  //
  // Example (using Supabase client):
  //
  //   const { data, error } = await supabase
  //     .from("purchases")           // ← replace with your table name
  //     .select("expires_at")        // ← replace with your expiry column
  //     .eq("user_id", user.id)
  //     .gt("expires_at", new Date().toISOString())
  //     .single();
  //
  //   if (error || !data) {
  //     return new Response("No valid purchase", { status: 403 });
  //   }
  //
  // For now we use a hardcoded expiry so you can test the HMAC logic:
  const expiry = "20261231235959"; // "YYYYMMDDHHMMSS" — replace with data.expires_at

  // ── 3. Compute HMAC ──────────────────────────────────────────────────────

  const hashKey = Deno.env.get("HASH_KEY_NEW");
  if (!hashKey) {
    return new Response("Server misconfigured", { status: 500 });
  }

  // This message must match what ble_elock.py constructs on the ESP32:
  //   msg = hexlify(nonce).decode() + ':' + str(port_num) + ':' + expiry_str
  const message = `${nonce}:${port}:${expiry}`;
  const hmac = await computeHmac(hashKey, message);

  // ── 4. Return ticket to the phone ────────────────────────────────────────

  return new Response(JSON.stringify({ expiry, hmac }), {
    headers: { "Content-Type": "application/json" },
  });
});
