############################
# date: 2025-03-11 00:00 #

import gc
from config import NVS_ACTIVE


def calcHashes(_str) -> tuple:
    """Compute HMAC-SHA256 of _str against both the old and new key.
    Returns (old_hash_b64, new_hash_b64) as base64 strings."""
    from elock_hmac_sha256 import hmac_sha256
    from binascii import b2a_base64
    from _key_new import HASH_KEY_NEW
    from _key_old import HASH_KEY
    _hash     = b2a_base64(hmac_sha256(HASH_KEY,     _str)).decode().strip('\r\n')
    _hash_new = b2a_base64(hmac_sha256(HASH_KEY_NEW, _str)).decode().strip('\r\n')
    del hmac_sha256, b2a_base64, HASH_KEY, HASH_KEY_NEW
    gc.collect()
    return (_hash, _hash_new)


async def hashTest(_hash, _str) -> bool:
    """Verify that _hash matches either the old or new HMAC key for _str.

    Key rotation mechanism: HASH_KEY (old) is still accepted for NVS 'oldkey/count'
    more scans. Each successful new-key scan decrements the counter. When count
    reaches 0 the old key is disabled, completing the rotation without a hard cutover.
    """
    from _utils import safePrint
    print("Check keys:", safePrint(_str))
    safePrint(_hash); del safePrint; gc.collect()

    _rehash, _rehash_new = calcHashes(_str)
    _old = (_hash == _rehash)
    _new = (_hash == _rehash_new)

    del _hash, _rehash; _rehash_new; gc.collect()

    if not _old and not _new:
        print("No match!")
        del _old, _new; gc.collect()
        return False

    print("MATCH!!!")

    if NVS_ACTIVE:
        from esp32 import NVS
        _old_nvs  = NVS('oldkey')
        del NVS; gc.collect()
        _old_keys = _old_nvs.get_i32('count')

        if _old:
            if _old_keys < 1:
                # Old key has been fully rotated out
                print("Old Key disabled!")
                del _old_nvs; _old_keys; gc.collect()
                return False
            elif _old_keys > 0:
                print("This is an old key:\n", _old_keys, end=' ')
                del _old_nvs; _old_keys; gc.collect()
                return True
        elif _new:
            if _old_keys >= 1:
                # Decrement the remaining old-key grace count on every new-key success
                print("This is a new key", end=' ')
                _old_nvs.set_i32('count', _old_keys - 1)
                _old_nvs('oldkey').commit()
                print(_old_nvs('oldkey').get_i32('count'), " keys left!")
                print("Update keycount")
                del _old_nvs; _old_keys; gc.collect()
        return True
    else:
        print(">> NVS INACTIVE")
        return True
    return False


def setKeys(_knum: int):
    """Manually set the old-key grace counter in NVS. Used during key rotation setup."""
    from esp32 import NVS
    _nvs = NVS('oldkey')
    _nvs('oldkey').set_i32('count', _knum)
    _nvs('oldkey').commit()
    del NVS, _nvs
    gc.collect()
