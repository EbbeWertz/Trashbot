from engine.hal.hw_units.Motor import Motor
from engine.hal.hw_units.IMU import IMU
from engine.hal.hw_units.Camera import Camera
from TrashbotConfig import TrashbotConfig

class TrashbotHardware:

    def __init__(self, config: TrashbotConfig):
        self.imu = IMU(config.imu_channel)
        self.left_motor = Motor(config.motor_left)
        self.right_motor = Motor(config.motor_right)
        self.left_camera = Camera(config.camera_left_ch, config.camera_full_res)
        self.right_camera = Camera(config.camera_right_ch, config.camera_full_res)
    
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