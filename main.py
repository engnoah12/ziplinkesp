############################
# date: 2025-02-25 00:00 #
#
if not 'gc' in globals():
    import gc; gc.collect()

print('\tmain.py')
print('\nBooting using 1sec delay:',end='')

try:
    from utime import sleep
    sleep(1)
    del sleep
    gc.collect()
    del gc
    print('0\nLoading esp32_elock.py')
    import esp32_elock
except KeyboardInterrupt as k:
    print('Abort boot...')