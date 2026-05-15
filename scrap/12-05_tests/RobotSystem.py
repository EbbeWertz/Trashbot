import time, threading, cv2

from MotorHAL import MotorHAL
from CameraHAL import CameraHAL
from PIDController import PIDController
from VisionEngine import VisionEngine

class RobotSystem:
    def __init__(self):
        self.cam = CameraHAL()
        self.motors = MotorHAL()
        self.vision = VisionEngine()
        self.pid = PIDController()
        
        self.state = {
            "bg_bytes": None,
            "telemetry": {"y_norm": 0.5, "z": 0},
            "auto_follow": False,
            "fps": 24,
            "params_updated": False,
            "exposure": 8000,
            "gain": 8.0
        }
        self.lock = threading.Lock()

    def run_main_loop(self):
        last_time = time.time()
        while True:
            if self.state["params_updated"]:
                self.cam.update_params(self.state["exposure"], self.state["gain"])
                self.state["params_updated"] = False

            frame = self.cam.capture()
            now = time.time()
            dt = now - last_time
            last_time = now

            res = self.vision.process_frame(frame, (640, 360))
            
            with self.lock:
                if "y" in res:
                    self.state["telemetry"] = {"y_norm": res["y"]/360, "z": res["z"]}
                    if self.state["auto_follow"]:
                        err = res["y"] - self.vision.cy_ref
                        speed = self.pid.step(err, dt)
                        self.motors.drive(speed)
                else:
                    if self.state["auto_follow"]: self.motors.drive(0)
                
                _, buf = cv2.imencode('.jpg', res["img"], [cv2.IMWRITE_JPEG_QUALITY, 50])
                self.state["bg_bytes"] = buf.tobytes()
