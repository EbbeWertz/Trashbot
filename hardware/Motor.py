from gpiozero import PWMOutputDevice, DigitalOutputDevice, RotaryEncoder
import time

class Motor:
    def __init__(self, pwm_pin, in1_pin, in2_pin, enc_a, enc_b, ticks_per_rev):
        self.pwm = PWMOutputDevice(pwm_pin)
        self.in1 = DigitalOutputDevice(in1_pin)
        self.in2 = DigitalOutputDevice(in2_pin)
        self.encoder = RotaryEncoder(enc_a, enc_b, max_steps=0)
        self.ticks_per_rev = ticks_per_rev
        self._last_ticks = 0
        self._last_time = time.time()

    def set_speed(self, speed):
        """speed between -1.0 and 1.0"""
        speed = max(-1.0, min(1.0, speed))
        if speed > 0:
            self.in1.on(); self.in2.off()
        elif speed < 0:
            self.in1.off(); self.in2.on()
        else:
            self.in1.off(); self.in2.off()
        self.pwm.value = abs(speed)

    def get_rpm(self):
        now = time.time()
        dt = now - self._last_time
        curr_ticks = self.encoder.steps
        delta_ticks = curr_ticks - self._last_ticks
        
        revs = delta_ticks / self.ticks_per_rev
        rpm = (revs / dt) * 60 if dt > 0 else 0
        
        self._last_ticks = curr_ticks
        self._last_time = now
        return rpm

