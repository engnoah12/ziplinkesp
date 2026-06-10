############################
# date: 2025-02-25 00:00 #

# MicroPython's hashlib includes SHA-256 but not HMAC, so we implement it
# manually following RFC 2104: HMAC(K, m) = H((K ⊕ opad) ∥ H((K ⊕ ipad) ∥ m))
import gc

def hmac_sha256(byteHASH_KEY, message):
    from hashlib import sha256
    byteHASH_KEY  = byteHASH_KEY.encode()
    byte_message  = message.encode()
    block_size = 64
    ipad = 0x36   # Inner padding constant (RFC 2104)
    opad = 0x5c   # Outer padding constant (RFC 2104)

    # Keys longer than the block size are hashed down to block_size bytes
    if len(byteHASH_KEY) > block_size:
        byteHASH_KEY = sha256(byteHASH_KEY).digest()
    if len(byteHASH_KEY) < block_size:
        byteHASH_KEY += bytes(block_size - len(byteHASH_KEY))

    key_xor_ipad = bytes((x ^ ipad for x in byteHASH_KEY))
    inner_hash   = sha256(key_xor_ipad + byte_message).digest()
    key_xor_opad = bytes((x ^ opad for x in byteHASH_KEY))
    final_hash   = sha256(key_xor_opad + inner_hash).digest()

    del sha256, byteHASH_KEY, inner_hash, byte_message, block_size, ipad, opad
    gc.collect()
    return final_hash
