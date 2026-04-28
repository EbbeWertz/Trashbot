from hardware.Motor import Motor
from hardware.IMU import IMU
from hardware.Camera import Camera

class TrashbotHardware:

    # params
    WHEEL_SEPERATION = 0.175 # meters
    WHEEL_RADIUS = 0.035 # meters
    TICKS = 20.0 * 48.0 # PPR * Gear Ratio
    CAM_W = 640
    CAM_H = 480

    def __init__(self):
        self.imu = IMU(0x68)
        self.left_motor = Motor(12, 24, 23, 5, 6, self.TICKS)
        self.right_motor = Motor(13, 27, 22, 26, 16, self.TICKS)
        self.left_camera = Camera(self.CAM_W, self.CAM_H, 0)
        self.right_camera = Camera(self.CAM_W, self.CAM_H, 1)
    
    def startCams(self):
        self.left_camera.start()
        self.right_camera.start()
    
    def getCamFrames(self):
        lf = self.left_camera.get_frame()
        rf = self.right_camera.get_frame()
        return (lf, rf)

    def stop(self):
        self.left_motor.set_speed(0)
        self.right_motor.set_speed(0)