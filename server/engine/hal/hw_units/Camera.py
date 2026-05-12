from picamera2 import Picamera2

class Camera:
    def __init__(self, w, h, port):
        self.width = w
        self.height = h
        self.picamera = Picamera2(port)
        config = self.picamera.create_video_configuration(main={"size": (self.width, self.height), "format": "RGB888"})
        self.picamera.configure(config)
        self.picamera.set_controls({"AfMode": 0, "LensPosition": 0.0})

    def start(self):
        self.picamera.start()

    def get_frame(self):
        return self.picamera.capture_array()