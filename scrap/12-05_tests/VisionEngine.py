import cv2
import numpy as np

class VisionEngine:
    def __init__(self):
        self.hsv_lower = np.array([35, 70, 50])
        self.hsv_upper = np.array([90, 255, 255])
        self.cy_ref = 180.8 # From calibration JSON
        self.fy = 270.9     # Focal length y
        self.ball_diam_mm = 65.0 

    def process_frame(self, frame, target_size):
        bg = cv2.resize(frame, target_size, interpolation=cv2.INTER_NEAREST)
        hsv = cv2.cvtColor(bg, cv2.COLOR_RGB2HSV)
        mask = cv2.inRange(hsv, self.hsv_lower, self.hsv_upper)
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        if cnts:
            c = max(cnts, key=cv2.contourArea)
            if cv2.contourArea(c) > 15:
                ((x, y), r) = cv2.minEnclosingCircle(c)
                # Depth via intercept theorem: Z = (f * real_h) / pixel_h
                depth = (self.fy * self.ball_diam_mm) / (2 * r) if r > 0 else 0
                return {"x": x, "y": y, "r": r, "z": depth, "img": bg}
        return {"img": bg}
