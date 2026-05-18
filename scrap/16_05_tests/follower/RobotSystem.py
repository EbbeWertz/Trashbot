import base64
import threading
import time

import cv2
import numpy as np

from hardware.CameraHAL import CameraHAL
from services.InterceptEngine import InterceptEngine
from hardware.MotorHAL import MotorHAL
from PIDController import PIDController
from services.VisionEngine import VisionEngine


class RobotSystem:
    def __init__(self, cfg: dict):
        self._cfg = cfg
        scfg = cfg.get("stream", {})
        pcfg = cfg.get("pid",    {})

        self._stream_res = (int(scfg.get("width",  640)),
                            int(scfg.get("height", 360)))
        self._target_fps = float(scfg.get("target_fps", 55.0))
        self._jpeg_q     = int(scfg.get("jpeg_quality", 70))

        # Hardware
        self.cam    = CameraHAL(cfg, self._stream_res, self._target_fps)
        self.motors = MotorHAL(cfg)
        self.vision = VisionEngine(
            cfg,
            self.cam.calib,
            self.cam.sensor_res,
            self._stream_res,
        )
        self.pid = PIDController(
            kp=float(pcfg.get("kp", 0.004)),
            ki=float(pcfg.get("ki", 0.0002)),
            kd=float(pcfg.get("kd", 0.0001)),
            deadzone=float(pcfg.get("deadzone", 10)),
        )
        self.intercept = InterceptEngine(self.motors)

        # Shared state (protected by lock)
        self.lock = threading.Lock()
        self.state = {
            # Streaming
            "encoded_l":      "",
            "encoded_r":      "",
            # Telemetry
            "pos":            [0.0, 0.0, 0.0],
            "found":          False,
            "fps":            0.0,
            "load_pct":       0.0,
            # Control modes:  "off" | "follow" | "intercept"
            "mode":           "off",
            # Intercept telemetry (updated each frame in intercept mode)
            "intercept_telem": {},
            # Raw left frame for colour sampling
            "_raw_l":         None,
        }

        # Background thread handle
        self._thread: threading.Thread | None = None
        self._running = False

    def start(self):
        self.cam.start()
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        self.motors.stop()
        self.cam.stop()


    def sample_color(self, x_norm: float, y_norm: float):
        with self.lock:
            raw = self.state["_raw_l"]
        if raw is not None:
            self.vision.sample_color_from_frame(raw, x_norm, y_norm)

    def set_hsv_margins(self, h: int, sv: int):
        self.vision.set_margins(h, sv)

    def set_operating_mode(self, mode: str):
        with self.lock:
            prev = self.state["mode"]
            self.state["mode"] = mode

        if prev == mode:
            return

        # Transition side-effects
        if mode == "off":
            self.intercept.disable()
            self.motors.stop()
            self.pid.reset()
        elif mode == "follow":
            self.intercept.disable()
            self.pid.reset()
        elif mode == "intercept":
            self.pid.reset()
            self.intercept.enable()

    def reset_intercept(self):
        self.intercept.reset()

    # ------------------------------------------------------------------
    # Background loop
    # ------------------------------------------------------------------

    def _loop(self):
        prev_time = time.perf_counter()
        expected  = 1.0 / self._target_fps

        while self._running:
            img_l, t_l, img_r, t_r = self.cam.capture()

            process_start = time.perf_counter()
            res = self.vision.process(img_l, t_l, img_r, t_r)

            with self.lock:
                mode = self.state["mode"]

            # ── Mode dispatch ──────────────────────────────────────────
            if mode == "follow":
                self.operation_mode_follow(res)
            elif mode == "intercept":
                self.operation_mode_intercept(res)
            else:  # "off"
                pass  # set_operating_mode stopt de motors al, dus hier hoef niks extra te gebeuren

            # ── Encode frames ──────────────────────────────────────────
            _, buf_l = cv2.imencode(
                ".jpg", cv2.cvtColor(res["img_l"], cv2.COLOR_RGB2BGR),
                [cv2.IMWRITE_JPEG_QUALITY, self._jpeg_q])
            _, buf_r = cv2.imencode(
                ".jpg", cv2.cvtColor(res["img_r"], cv2.COLOR_RGB2BGR),
                [cv2.IMWRITE_JPEG_QUALITY, self._jpeg_q])

            now  = time.perf_counter()
            fps  = 1.0 / (now - prev_time) if (now - prev_time) > 0 else 0
            load = ((now - process_start) / expected) * 100
            prev_time = now

            enc_l = base64.b64encode(buf_l).decode()
            enc_r = base64.b64encode(buf_r).decode()

            with self.lock:
                self.state["encoded_l"] = enc_l
                self.state["encoded_r"] = enc_r
                self.state["pos"]       = res["pos"]
                self.state["found"]     = res["found"]
                self.state["fps"]       = round(fps, 1)
                self.state["load_pct"]  = round(load, 1)
                self.state["_raw_l"]    = img_l

    def operation_mode_follow(self, res):
        # Decoupled 3D Follow: Tuned steering + 20cm Catch Center Radial Margin
        if res["found"] and res["pos"] is not None:
            target_x_m = res["pos"][0]  # Left/Right deviation
            target_y_m = res["pos"][1]  # Vertical deviation
            target_z_m = res["pos"][2]  # Physical distance from camera lens
            # ! These values are actually millimeters

            # --- 1. Catch Center & Radial Margin Calculations ---
            # Catch center definition (X=0mm, Y=-100mm -> meters: X=0.0, Y=-0.1)
            catch_x_m = 0.0
            catch_y_m = -100.0
            
            # Compute horizontal/vertical offsets relative to the catch center
            dx = target_x_m - catch_x_m
            dy = target_y_m - catch_y_m
            
            # Calculate true 2D radial distance to catch center
            import math
            radial_distance_to_catch = math.sqrt(dx**2 + dy**2)
            
            # 20cm target radius margin
            catch_margin_m = 200

            # --- 2. Persistent Tracking State ---
            if not hasattr(self, '_is_steering'):
                self._is_steering = False

            # --- 3. Horizontal Steering (Tuned Down) ---
            # Kept the hysteresis windows stable, but lowered the gain and maximum cap
            h_deadzone_high = 0.17  
            h_deadzone_low = 0.10   
            abs_x = abs(target_x_m)
            
            if not self._is_steering and abs_x > h_deadzone_high:
                self._is_steering = True
            elif self._is_steering and abs_x < h_deadzone_low:
                self._is_steering = False

            steering_offset = 0.0
            if self._is_steering:
                # Tuned down: kp_steer dropped from 0.6 to 0.45 for gentler adjustments
                kp_steer = 0.45  
                steering_offset = target_x_m * kp_steer
                
                # Tuned down: max_steer dropped from 0.35 to 0.20 to prevent sharp swinging
                max_steer = 0.20  
                steering_offset = max(-max_steer, min(max_steer, steering_offset))

            # --- 4. Base Speed Control with Catch Margin ---
            desired_distance_m = 0.50 
            distance_error = target_z_m - desired_distance_m
            z_deadzone = 0.05 

            # CATCH CHECK: If the ball is anywhere within a 20cm radius of the catch center,
            # cut the base speed entirely to allow a clean catch.
            if radial_distance_to_catch <= catch_margin_m:
                base_speed = 0.0
            else:
                # Otherwise, apply our standard decoupled movement strategies
                if self._is_steering:
                    base_speed = 0.4  # Low stable cruise forward while executing a turn
                else:
                    if abs(distance_error) > z_deadzone:
                        base_speed = 1.0 if distance_error > 0 else -1.0
                    else:
                        base_speed = 0.0

            # --- 5. Reversal Optimization ---
            if target_z_m < -0.02:
                base_speed = -base_speed

            # --- 6. Channel Mixing ---
            speed_a = base_speed + steering_offset
            speed_b = base_speed - steering_offset

            # Send directly to hardware
            self.motors.drive_raw(speed_a, speed_b)
        else:
            self._is_steering = False
            self.motors.stop()

    def operation_mode_intercept(self, res):
        sa, sb = self.intercept.update(res["pos"], res["found"])
        # Burst phase uses unclamped raw drive
        from services.InterceptEngine import Phase, BURST_DURATION_S
        iph = self.intercept.phase
        if iph.name == "COMMITTED":
            elapsed = time.perf_counter() - self.intercept._committed_at
            if elapsed < BURST_DURATION_S:
                self.motors.drive_raw(sa, sb)
            else:
                self.motors.drive(sa, sb)
        elif iph.name == "BRAKING":
            self.motors.drive_raw(sa, sb)
        elif iph.name == "DONE":
            self.motors.stop()
        # OBSERVING: motors idle (InterceptEngine returns 0,0)

        with self.lock:
            self.state["intercept_telem"] = {
                "phase":       self.intercept.telemetry.phase,
                "n_samples":   self.intercept.telemetry.n_samples,
                "fit_rms_z":   self.intercept.telemetry.fit_rms_z,
                "fit_rms_xy":  self.intercept.telemetry.fit_rms_xy,
                "predicted_t": self.intercept.telemetry.predicted_t,
                "catch_x":     self.intercept.telemetry.catch_x,
                "catch_y":     self.intercept.telemetry.catch_y,
                "turn_deg":    self.intercept.telemetry.turn_deg,
                "heading":     self.intercept.telemetry.robot_heading,
            }