from gpiozero import PWMOutputDevice, DigitalOutputDevice
import numpy as np

class MotorHAL:
    def __init__(self):
        # Motor A (Left)
        self.pwm_a = PWMOutputDevice(12)
        self.in1 = DigitalOutputDevice(24)
        self.in2 = DigitalOutputDevice(23)
        # Motor B (Right)
        self.pwm_b = PWMOutputDevice(13)
        self.in3 = DigitalOutputDevice(27)
        self.in4 = DigitalOutputDevice(22)

    def drive(self, speed):
        """speed: -1.0 to 1.0 (Shared for vertical centering)"""
        speed = np.clip(speed, -0.7, 0.7) # Safety limit
        for pwm, p1, p2 in [(self.pwm_a, self.in1, self.in2), (self.pwm_b, self.in3, self.in4)]:
            if speed > 0.05:
                p1.on(); p2.off()
            elif speed < -0.05:
                p1.off(); p2.on()
            else:
                p1.off(); p2.off()
            pwm.value = abs(speed)
