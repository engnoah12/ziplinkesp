############################
# date: 2025-03-11 00:00 #
#
import gc
from config import NVS_ACTIVE

def calcHashes(_str)-> tuple: # TODO: Optimize import/mem
    from elock_hmac_sha256 import hmac_sha256
    from binascii import b2a_base64
    from _key_new import HASH_KEY_NEW
    from _key_old import HASH_KEY
    _hash: str = b2a_base64(hmac_sha256(HASH_KEY, _str)).decode().strip('\r\n')
    _hash_new: str =b2a_base64(hmac_sha256(HASH_KEY_NEW, _str)).decode().strip('\r\n')
    del hmac_sha256, b2a_base64 ,HASH_KEY,HASH_KEY_NEW
    gc.collect()
    return tuple((_hash,_hash_new))


async def hashTest(_hash,_str) -> bool:
    from _utils import safePrint
    print("Check keys:",safePrint(_str))
    safePrint(_hash);del safePrint;gc.collect()
    
    _rehash,_rehash_new = calcHashes(_str)
    _old = (_hash == _rehash)
    _new = (_hash == _rehash_new)
    
    del _hash,_rehash;_rehash_new;gc.collect()

    if not _old and not _new:
        print("No match!")
        del _old,_new;gc.collect()
        return False
    print("MATCH!!!")
    if NVS_ACTIVE:
        from esp32 import NVS
        _old_nvs = NVS('oldkey')
        del NVS;gc.collect()
        _old_keys = _old_nvs.get_i32('count')

        if _old:     
            if _old_keys<1:
                print("Old Key disabled!")
                del _old_nvs;_old_keys;gc.collect()
                return False
            elif _old_keys>0:
                print("This is an old key:\n",_old_keys, end=' ')
                del _old_nvs;_old_keys;gc.collect()
                return True
        elif _new:
            if _old_keys>=1:
                print("This is a new key",end=' ')
                _old_nvs.set_i32('count',_old_keys-1)
                _old_nvs('oldkey').commit()
                print(_old_nvs('oldkey').get_i32('count')," keys left!")
                print("Update keycount")
                del _old_nvs;_old_keys;gc.collect()
        return True
    else:
        print(">> NVS INACTIVE")
        return True
    return False

def setKeys(_knum:int):
    from esp32 import NVS
    _nvs=NVS('oldkey')
    _nvs('oldkey').set_i32('count',_knum)
    _nvs('oldkey').commit()
    del NVS,_nvs
    gc.collect()