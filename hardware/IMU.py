from mpu6050 import mpu6050
import time

class IMU:
    def __init__(self, address=0x68):
        self.sensor = mpu6050(address)
        self.offset_x = 0.0
        self.offset_y = 0.0

    def zero(self):
        """Calibrates the current tilt as the zero point."""
        data = self.sensor.get_accel_data()
        # Simple tilt calculation from acceleration
        self.offset_x = data['x']
        self.offset_y = data['y']

    def get_tilt(self):
        """Returns the tilt in degrees (simplified)"""
        data = self.sensor.get_accel_data()
        # Subtracting offsets and scaling
        # In a real scenario, use math.atan2 for precise degrees
        tilt_x = (data['x'] - self.offset_x) * 10 # Rough scaling for UI demo
        return round(tilt_x, 2)

    def get_acceleration(self):
        return self.sensor.get_accel_data()