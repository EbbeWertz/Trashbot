"""
CameraHAL.py — Stereo camera hardware abstraction layer.
Configuration is loaded from config.yml; calibration from the path it specifies.
"""

import cv2
import numpy as np
from picamera2 import Picamera2


# ---------------------------------------------------------------------------
# Helpers for parsing OpenCV's .yml matrix format via cv2.FileStorage
# ---------------------------------------------------------------------------

def _load_calibration(path: str) -> dict:
    """Load an OpenCV stereo calibration YAML and return a plain dict of ndarrays."""
    fs = cv2.FileStorage(path, cv2.FILE_STORAGE_READ)
    if not fs.isOpened():
        raise FileNotFoundError(f"Cannot open calibration file: {path}")

    keys = ["K1", "D1", "K2", "D2", "R", "T", "R1", "R2", "P1", "P2", "Q"]
    data = {}
    for k in keys:
        node = fs.getNode(k)
        if node.empty():
            raise ValueError(f"Key '{k}' missing from calibration file: {path}")
        data[k] = node.mat()

    fs.release()
    return data


# ---------------------------------------------------------------------------
# Resolved mode constants
# ---------------------------------------------------------------------------

_SENSOR_RES = {
    "hi-res": (2304, 1296),
    "lo-res": (1536, 864),
}
_FULL_RES = (2304, 1296)  # Always the full sensor resolution for offset math


class CameraHAL:
    """
    Manages two Picamera2 instances for synchronised stereo capture.

    Attributes exposed after __init__:
        calib   – dict of calibration matrices (K1, D1, K2, D2, R1, R2, P1, P2, Q, …)
        sensor_res  – (w, h) at which the sensor is configured
        stream_res  – (w, h) of the lores stream used for processing
        fps         – configured frame rate
    """

    def __init__(self, cfg: dict, stream_res: tuple, target_fps: float):
        cam_cfg = cfg["camera"]
        mode = cam_cfg.get("mode", "hi-res")

        self.sensor_res: tuple = _SENSOR_RES[mode]
        self.stream_res: tuple = stream_res
        self.fps: float = target_fps
        self._mode = mode

        # --- Camera indices -----------------------------------------------
        left_idx = int(cam_cfg.get("left_index", 0))
        right_idx = int(cam_cfg.get("right_index", 1))
        if cam_cfg.get("swap", False):
            left_idx, right_idx = right_idx, left_idx

        self._cam_l = Picamera2(left_idx)
        self._cam_r = Picamera2(right_idx)

        # --- Calibration ---------------------------------------------------
        calib_path = cam_cfg.get("calibration_file", "calibration.yml")
        self.calib = _load_calibration(calib_path)

        # Pre-compute the pixel offset applied when using lo-res mode
        # (lo-res crop is centred on the full sensor)
        self._offset_x = (_FULL_RES[0] - self.sensor_res[0]) // 2
        self._offset_y = (_FULL_RES[1] - self.sensor_res[1]) // 2

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def start(self):
        """Configure and start both cameras."""
        for cam in (self._cam_l, self._cam_r):
            config = cam.create_video_configuration(
                main={"format": "RGB888", "size": self.sensor_res},
                lores={"format": "RGB888", "size": self.stream_res},
            )
            cam.configure(config)
            cam.set_controls({
                "LensPosition": 0,
                "AfMode": 0,
                "FrameRate": self.fps,
            })
            cam.start()

    def capture(self) -> tuple:
        """
        Capture one lores frame from each camera as close in time as possible.

        Returns:
            (img_l, t_l, img_r, t_r)  – RGB ndarrays + perf_counter timestamps
        """
        import time
        img_l = self._cam_l.capture_array("lores")
        t_l = time.perf_counter()
        img_r = self._cam_r.capture_array("lores")
        t_r = time.perf_counter()
        return img_l, t_l, img_r, t_r

    def sensor_to_full_coords(self, x: float, y: float) -> tuple:
        """
        Convert a point in sensor-resolution coordinates to full-sensor (2304×1296)
        coordinates, accounting for the crop offset used in lo-res mode.
        """
        scale_x = self.sensor_res[0] / self.stream_res[0]
        scale_y = self.sensor_res[1] / self.stream_res[1]
        return (
            x * scale_x + self._offset_x,
            y * scale_y + self._offset_y,
        )

    def stop(self):
        for cam in (self._cam_l, self._cam_r):
            try:
                cam.stop()
            except Exception:
                pass