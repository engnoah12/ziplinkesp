from machine import Pin, PWM
import utime as time
pwms: list[PWM] = []

# Original values  2960,1023,50,550
######***#########******###########**********################*****************************
_period=30_000		###Main frequency of PWM (in Hz) 18_000+ is beyond average hearing
_kick_duty=800		# ~78% "power" ( max is 1023 )
_kick_hold=10		# Hold time in ms for KICK.
_hold_duty=600		# ~59% of max ( 1023 )
_hold_lockTime = 5000#currentHoldLockTimeMS
#########******##########*************#############**********################

def open_ports(_punch,_kick,_snap,_hold):
    for port in pwms: port.duty(_punch)
    time.sleep_ms(_kick)
    for port in pwms: port.duty(_snap)
    time.sleep_ms(_hold)
    for port in pwms: port.duty(0)
    
for _ in {18, 19, 4}: pwms.append(PWM(Pin(_), freq=_period, duty=0))
open_ports(_kick_duty,_kick_hold,_hold_duty,_hold_lockTime)