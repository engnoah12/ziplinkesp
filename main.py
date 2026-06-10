############################
# date: 2025-02-25 00:00 #

if not 'gc' in globals():
    import gc; gc.collect()

print('\tmain.py')

# 1-second delay gives the serial monitor time to connect before boot output starts,
# and also allows a KeyboardInterrupt window to abort to the REPL for debugging.
print('\nBooting using 1sec delay:', end='')

try:
    from utime import sleep
    sleep(1)
    del sleep
    gc.collect()
    del gc
    print('0\nLoading esp32_elock.py')
    import esp32_elock
except KeyboardInterrupt:
    print('Abort boot...')
