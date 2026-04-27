from hardware.Motor import Motor
from hardware.IMU import IMU

class TrashbotHardware:

    # params
    WHEEL_SEPERATION = 0.175 # meters
    WHEEL_RADIUS = 0.035 # meters
    TICKS = 20.0 * 48.0 # PPR * Gear Ratio

    def __init__(self):
        
        self.imu = IMU(0x68)
        self.left_motor = Motor(12, 24, 23, 5, 6, self.TICKS)
        self.right_motor = Motor(13, 27, 22, 26, 16, self.TICKS)

    def stop(self):
        self.left_motor.set_speed(0)
        self.right_motor.set_speed(0)