############################
# date: 2025-02-25 00:00 #
#
import gc
def hmac_sha256(byteHASH_KEY, message):
    from hashlib import sha256
    byteHASH_KEY = byteHASH_KEY.encode()
    byte_message = message.encode()
    block_size = 64;ipad = 0x36; opad = 0x5c

    if len(byteHASH_KEY) > block_size:
        byteHASH_KEY = sha256(byteHASH_KEY).digest()
    if len(byteHASH_KEY) < block_size:
        byteHASH_KEY += bytes(block_size - len(byteHASH_KEY))
    key_xor_IPad = bytes((x ^ ipad for x in byteHASH_KEY))
    inner_hash = sha256(key_xor_IPad + byte_message).digest()
    key_xor_opad = bytes((x ^ opad for x in byteHASH_KEY))
    final_hash = sha256(key_xor_opad + inner_hash).digest()
    del sha256, byteHASH_KEY,inner_hash, byte_message, block_size, ipad, opad
    gc.collect()
    return final_hash