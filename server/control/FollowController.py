import cv2
import numpy as np

class FollowController:
    def __init__(self, hardware, k_p=0.002, base_speed=0.2, max_motor_speed=0.3, mirrored_turn=False, mirrored_drive=True):
        self.hw = hardware
        self.prev_center = None
        
        # --- Control Parameters ---
        self.k_p = k_p                
        self.base_speed = base_speed  
        self.max_motor_speed = max_motor_speed # Global limit (e.g., 0.6 = 60% power)
        self.mirrored_turn = mirrored_turn    
        self.mirrored_drive = mirrored_drive  
        
        # --- Threshold Parameters ---
        self.max_slew = 0.05          
        self.center_threshold = 40    
        self.edge_threshold = 100     
        
        self.last_l = 0.0             
        self.last_r = 0.0             
        
        # Red HSV Ranges
        self.lower_red1 = np.array([0, 120, 70])
        self.upper_red1 = np.array([10, 255, 255])
        self.lower_red2 = np.array([170, 120, 70])
        self.upper_red2 = np.array([180, 255, 255])

    def drive(self, left, right):
        """Final output stage with slew limiting, global max speed, and dual mirroring."""
        
        # 1. Apply Slew Limiting (Prevents sudden voltage drops)
        left = np.clip(left, self.last_l - self.max_slew, self.last_l + self.max_slew)
        right = np.clip(right, self.last_r - self.max_slew, self.last_r + self.max_slew)
        self.last_l, self.last_r = left, right

        # 2. Global Power Limit (Clamping to your custom max)
        # This replaces the hard -1 to 1 range
        left = np.clip(left, -self.max_motor_speed, self.max_motor_speed)
        right = np.clip(right, -self.max_motor_speed, self.max_motor_speed)

        # 3. Mirroring Logic
        drive_mult = -1 if self.mirrored_drive else 1
        out_l = right if self.mirrored_turn else left
        out_r = left if self.mirrored_turn else right

        # 4. Hardware Output
        self.hw.left_motor.set_speed(out_l * drive_mult)
        self.hw.right_motor.set_speed(out_r * drive_mult)

    def update_loop(self):
        frame = self.hw.left_camera.get_frame()
        if frame is None: return None

        frame = cv2.resize(frame, (640, 360), interpolation=cv2.INTER_LINEAR)

        height, width = frame.shape[:2]
        screen_center_x = width // 2

        # 1. Image Processing
        blurred = cv2.GaussianBlur(frame, (11, 11), 0)
        hsv = cv2.cvtColor(blurred, cv2.COLOR_BGR2HSV)
        mask = cv2.add(cv2.inRange(hsv, self.lower_red1, self.upper_red1),
                       cv2.inRange(hsv, self.lower_red2, self.upper_red2))
        mask = cv2.erode(mask, None, iterations=2)
        mask = cv2.dilate(mask, None, iterations=2)

        # 2. Target Detection
        contours, _ = cv2.findContours(mask.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        if len(contours) > 0:
            c = max(contours, key=cv2.contourArea)
            ((x, y), radius) = cv2.minEnclosingCircle(c)
            
            if radius > 10:
                M = cv2.moments(c)
                center_x = int(M["m10"] / M["m00"])
                error_x = center_x - screen_center_x
                
                # --- 3. ORIENTATION LOGIC ---
                # Always calculate turn effort
                turn_effort = error_x * self.k_p
                l_speed = turn_effort
                r_speed = -turn_effort

                # --- 4. DRIVE LOGIC ---
                # If centered: Drive forward + maintain turn correction
                if abs(error_x) < self.center_threshold:
                    l_speed += self.base_speed
                    r_speed += self.base_speed
                # If between thresholds: Stop (wait for ball to hit edge or enter center)
                elif abs(error_x) < self.edge_threshold:
                    l_speed = 0
                    r_speed = 0
                # Else: Just rotate (already handled by default l_speed/r_speed)

                self.drive(l_speed, r_speed)

                # Visual Guides
                # Blue lines = Edge Threshold, Cyan lines = Center Threshold
                color = (0, 255, 0) if abs(error_x) < self.center_threshold else (0, 0, 255)
                cv2.circle(frame, (int(x), int(y)), int(radius), color, 2)
                cv2.line(frame, (screen_center_x - self.center_threshold, 0), (screen_center_x - self.center_threshold, height), (255, 255, 0), 1)
                cv2.line(frame, (screen_center_x + self.center_threshold, 0), (screen_center_x + self.center_threshold, height), (255, 255, 0), 1)
                cv2.line(frame, (screen_center_x - self.edge_threshold, 0), (screen_center_x - self.edge_threshold, height), (255, 0, 0), 1)
                cv2.line(frame, (screen_center_x + self.edge_threshold, 0), (screen_center_x + self.edge_threshold, height), (255, 0, 0), 1)
        else:
            self.drive(0, 0)

        return frame