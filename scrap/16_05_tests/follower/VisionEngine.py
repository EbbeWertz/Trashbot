"""
VisionEngine.py — Stereo colour-blob tracker with temporal interpolation
and 3D triangulation via the Q disparity matrix.
"""

import cv2
import numpy as np


class VisionEngine:
    """
    Processes a pair of stereo frames to locate a coloured object and
    compute its 3-D position relative to the left camera.

    Parameters that affect tracking (hsv_center, h_margin, sv_margin) can
    be updated at runtime without restarting.
    """

    def __init__(self, cfg: dict, calib: dict,
                 sensor_res: tuple, stream_res: tuple):
        """
        Args:
            cfg        – full config dict (vision + camera sections used)
            calib      – calibration dict from CameraHAL (K1/D1/… ndarrays)
            sensor_res – (w, h) of the sensor / full-res capture
            stream_res – (w, h) of the lores stream
        """
        vcfg = cfg["vision"]
        self._calib = calib
        self._sensor_res = sensor_res
        self._stream_res = stream_res

        # Derive the pixel offset when sensor_res < full sensor (2304×1296)
        _full = (2304, 1296)
        self._offset_x = (_full[0] - sensor_res[0]) // 2
        self._offset_y = (_full[1] - sensor_res[1]) // 2

        # Colour tracking bounds (updated via sample_color or set_margins)
        center = vcfg.get("hsv_center", [60, 150, 150])
        self._center_hsv = np.array(center, dtype=np.uint8)
        self._h_margin   = int(vcfg.get("h_margin",  15))
        self._sv_margin  = int(vcfg.get("sv_margin", 60))
        self._min_area   = float(vcfg.get("min_contour_area", 15))
        self._update_bounds()

        # Temporal interpolation history: list of (timestamp, x, y)
        self._history = {"l": [], "r": []}

    # ------------------------------------------------------------------
    # Colour management
    # ------------------------------------------------------------------

    def set_color(self, center_hsv: np.ndarray):
        """Update tracking colour centre (array [H, S, V])."""
        self._center_hsv = np.array(center_hsv, dtype=np.uint8)
        self._update_bounds()

    def set_margins(self, h_margin: int, sv_margin: int):
        self._h_margin  = h_margin
        self._sv_margin = sv_margin
        self._update_bounds()

    def get_color_state(self) -> dict:
        return {
            "center": self._center_hsv.tolist(),
            "h_margin": self._h_margin,
            "sv_margin": self._sv_margin,
            "lower": self._lower.tolist(),
            "upper": self._upper.tolist(),
        }

    def sample_color_from_frame(self, frame_rgb: np.ndarray,
                                x_norm: float, y_norm: float):
        """Sample the HSV colour at a normalised position in an RGB frame."""
        h, w = frame_rgb.shape[:2]
        px = int(np.clip(x_norm * w, 0, w - 1))
        py = int(np.clip(y_norm * h, 0, h - 1))
        pixel = frame_rgb[py, px]
        hsv   = cv2.cvtColor(np.uint8([[pixel]]), cv2.COLOR_RGB2HSV)[0][0]
        self.set_color(hsv)

    def _update_bounds(self):
        h, s, v = int(self._center_hsv[0]), int(self._center_hsv[1]), int(self._center_hsv[2])
        self._lower = np.array([
            max(0,   h - self._h_margin),
            max(40,  s - self._sv_margin),
            max(40,  v - self._sv_margin),
        ], dtype=np.uint8)
        self._upper = np.array([
            min(180, h + self._h_margin),
            255,
            255,
        ], dtype=np.uint8)

    # ------------------------------------------------------------------
    # Frame processing
    # ------------------------------------------------------------------

    def process(self, img_l: np.ndarray, t_l: float,
                img_r: np.ndarray, t_r: float) -> dict:
        """
        Detect the tracked object in both frames, triangulate its 3-D
        position and return annotated frames + telemetry.

        Returns dict with keys:
            img_l, img_r  – annotated BGR frames (stream resolution)
            found         – bool, True if detected in both cameras
            pos           – [X, Y, Z] mm relative to left camera (or last known)
            target_l      – (cx, cy, r) in left stream frame (or None)
            target_r      – (cx, cy, r) in right stream frame (or None)
        """
        targets = {}
        for side, img, t in (("l", img_l, t_l), ("r", img_r, t_r)):
            result = self._detect(img, t, side)
            targets[side] = result

        found = targets["l"] is not None and targets["r"] is not None
        pos = [0.0, 0.0, 0.0]

        if found:
            pos = self._triangulate(targets["l"], targets["r"], t_r)

        # Annotate
        out_l = self._annotate(img_l.copy(), targets["l"])
        out_r = self._annotate(img_r.copy(), targets["r"])

        return {
            "img_l":    out_l,
            "img_r":    out_r,
            "found":    found,
            "pos":      pos,
            "target_l": targets["l"],
            "target_r": targets["r"],
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _detect(self, img: np.ndarray, t: float, side: str):
        """Find the largest blob matching the colour bounds. Updates history."""
        hsv   = cv2.cvtColor(img, cv2.COLOR_RGB2HSV)
        mask  = cv2.inRange(hsv, self._lower, self._upper)
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        if cnts:
            c = max(cnts, key=cv2.contourArea)
            if cv2.contourArea(c) > self._min_area:
                (x, y), r = cv2.minEnclosingCircle(c)
                self._history[side].append((t, x, y))
                if len(self._history[side]) > 2:
                    self._history[side].pop(0)
                return (x, y, r)

        # Lost tracking — clear history for this side
        self._history[side] = []
        return None

    def _interpolate(self, side: str, target_time: float):
        """
        Linearly extrapolate position on 'side' to target_time using the
        last two history points (temporal synchronisation for stereo).
        Falls back to the last known position if only one point exists.
        """
        hist = self._history[side]
        if len(hist) < 2:
            return (hist[-1][1], hist[-1][2]) if hist else None

        (t1, x1, y1), (t2, x2, y2) = hist[-2], hist[-1]
        dt = t2 - t1
        if dt == 0:
            return x2, y2

        vx = (x2 - x1) / dt
        vy = (y2 - y1) / dt
        dt_target = target_time - t2
        return x2 + vx * dt_target, y2 + vy * dt_target

    def _to_full_sensor(self, x: float, y: float) -> tuple:
        """Scale stream coords → full-sensor coords (with crop offset)."""
        sx = self._sensor_res[0] / self._stream_res[0]
        sy = self._sensor_res[1] / self._stream_res[1]
        return x * sx + self._offset_x, y * sy + self._offset_y

    def _rectify_point(self, pt, K, D, R, P) -> tuple:
        arr = np.array([[list(pt)]], dtype=np.float32)
        out = cv2.undistortPoints(arr, K, D, R=R, P=P)
        return float(out[0][0][0]), float(out[0][0][1])

    def _triangulate(self, tgt_l: tuple, tgt_r: tuple, t_r: float):
        """Compute 3-D world coords [X, Y, Z] in mm."""
        # Interpolate left detection to match right camera timestamp
        interp_l = self._interpolate("l", t_r)
        if interp_l is None:
            interp_l = (tgt_l[0], tgt_l[1])

        raw_xl, raw_yl = self._to_full_sensor(*interp_l)
        raw_xr, raw_yr = self._to_full_sensor(tgt_r[0], tgt_r[1])

        c = self._calib
        rx_l, ry_l = self._rectify_point((raw_xl, raw_yl),
                                         c["K1"], c["D1"], c["R1"], c["P1"])
        rx_r, _    = self._rectify_point((raw_xr, raw_yr),
                                         c["K2"], c["D2"], c["R2"], c["P2"])

        disparity = rx_l - rx_r
        if disparity <= 0:
            return [0.0, 0.0, 0.0]

        vec    = np.array([rx_l, ry_l, disparity, 1.0])
        coords = c["Q"] @ vec
        coords /= coords[3]
        return [float(coords[0]), float(-coords[1]), float(coords[2])]

    @staticmethod
    def _annotate(img: np.ndarray, target) -> np.ndarray:
        if target is not None:
            x, y, r = target
            cv2.circle(img, (int(x), int(y)), int(r), (0, 255, 0), 3)
            cv2.circle(img, (int(x), int(y)), 3,      (0, 255, 0), -1)
        return img