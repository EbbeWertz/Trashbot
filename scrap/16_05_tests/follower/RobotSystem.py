"""
RobotSystem.py — Top-level orchestrator.
Owns the background capture/process loop and exposes a thread-safe shared
state dict for the FastAPI layer to read and write.
"""

import base64
import threading
import time

import cv2
import numpy as np

from CameraHAL import CameraHAL
from MotorHAL import MotorHAL
from PIDController import PIDController
from VisionEngine import VisionEngine


class RobotSystem:
    def __init__(self, cfg: dict):
        self._cfg = cfg
        vcfg = cfg.get("vision", {})
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

        # Shared state (protected by lock)
        self.lock = threading.Lock()
        self.state = {
            # Streaming
            "encoded_l":   "",
            "encoded_r":   "",
            # Telemetry
            "pos":         [0.0, 0.0, 0.0],
            "found":       False,
            "fps":         0.0,
            "load_pct":    0.0,
            # Control
            "auto_follow": False,
            # Raw left frame for colour sampling (no lock needed if accessed
            # only via sample_color which re-locks internally)
            "_raw_l":      None,
        }

        # Background thread handle
        self._thread: threading.Thread | None = None
        self._running = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self):
        self.cam.start()
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        self.motors.stop()
        self.cam.stop()

    # ------------------------------------------------------------------
    # Motor test commands (called from the web layer in a thread pool)
    # ------------------------------------------------------------------

    def test_motor(self, side: str, duration: float = 1.0) -> list:
        """
        Spin one raw motor for 'duration' seconds at min_pwm and collect
        encoder samples.  Returns list of (t, rev_s_a, rev_s_b) dicts.
        """
        log = []
        ta0, tb0 = self.motors.get_ticks()
        t0 = time.perf_counter()
        t_last = t0
        ta_last, tb_last = ta0, tb0

        speed_a = 0.3 if side == "A" else 0.0
        speed_b = 0.3 if side == "B" else 0.0
        self.motors.drive(speed_a, speed_b)

        try:
            while time.perf_counter() - t0 < duration:
                time.sleep(0.05)
                now = time.perf_counter()
                ta, tb = self.motors.get_ticks()
                dt = now - t_last
                rev_s_a = ((ta - ta_last) / self.motors.ticks_per_rev) / dt if dt else 0
                rev_s_b = ((tb - tb_last) / self.motors.ticks_per_rev) / dt if dt else 0
                log.append({"t": round(now - t0, 3),
                             "rev_s_a": round(rev_s_a, 3),
                             "rev_s_b": round(rev_s_b, 3)})
                ta_last, tb_last = ta, tb
                t_last = now
        finally:
            self.motors.stop()

        ta_end, tb_end = self.motors.get_ticks()
        log.append({"summary": True,
                     "delta_a": ta_end - ta0,
                     "delta_b": tb_end - tb0})
        return log

    def execute_drive(self, meters: float):
        """Blocking closed-loop straight drive (run in a thread pool)."""
        ticks = int((meters / self.motors.wheel_circumference) * self.motors.ticks_per_rev)
        self.motors.execute_profile(ticks, ticks)

    def execute_spin(self, degrees: float):
        """Blocking closed-loop spin (run in a thread pool)."""
        fraction  = degrees / 360.0
        dist_m    = (3.14159265 * self.motors.track_width_m) * fraction
        ticks     = int((dist_m / self.motors.wheel_circumference) * self.motors.ticks_per_rev)
        self.motors.execute_profile(ticks, -ticks)

    # ------------------------------------------------------------------
    # Colour sampling (called from WebSocket handler)
    # ------------------------------------------------------------------

    def sample_color(self, x_norm: float, y_norm: float):
        with self.lock:
            raw = self.state["_raw_l"]
        if raw is not None:
            self.vision.sample_color_from_frame(raw, x_norm, y_norm)

    def set_margins(self, h: int, sv: int):
        self.vision.set_margins(h, sv)

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

            # PID motor control
            with self.lock:
                auto = self.state["auto_follow"]

            if auto and res["found"]:
                # Use Y-axis position (up/down) from the left stream frame
                tgt_l = res["target_l"]
                if tgt_l is not None:
                    cy_ref = self._stream_res[1] / 2.0
                    error  = tgt_l[1] - cy_ref
                    now    = time.perf_counter()
                    dt     = now - prev_time
                    speed  = self.pid.step(error, dt)
                    self.motors.drive_straight(speed)
            elif auto:
                self.motors.stop()

            # Encode frames
            _, buf_l = cv2.imencode(
                ".jpg", res["img_l"],
                [cv2.IMWRITE_JPEG_QUALITY, self._jpeg_q])
            _, buf_r = cv2.imencode(
                ".jpg", res["img_r"],
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