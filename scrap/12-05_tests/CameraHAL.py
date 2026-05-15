from picamera2 import Picamera2

class CameraHAL:
    def __init__(self, size=(2304, 1296)):
        self.cam = Picamera2(0)
        config = self.cam.create_video_configuration(main={"format": "RGB888", "size": size})
        config["sensor_mode"] = 4
        self.cam.configure(config)
        self.cam.start()

    def capture(self):
        return self.cam.capture_array()

    def update_params(self, exp, gain):
        self.cam.set_controls({"ExposureTime": exp, "AnalogueGain": gain, "FrameRate": 60.0})
