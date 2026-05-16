"""
InterceptEngine.py — Ballistic interception planner.

Accumulates 3-D position samples, fits a ground-plane line to X/Y motion
and a parabola to height (Z) vs time, then computes:

  • The predicted catch time  t_catch  (when Z ≤ CATCH_HEIGHT_MM)
  • The predicted catch point (X_catch, Y_catch) on the fitted XY line
  • The required turn angle   θ  relative to the robot's current heading
  • A time-budget for the intercept drive

State machine
─────────────
  IDLE        – waiting for mode to be enabled
  OBSERVING   – collecting samples; fitting improves each frame
  COMMITTED   – prediction locked, intercept drive in progress
  BRAKING     – Z ≤ CATCH_HEIGHT_MM, applying reverse pulse
  DONE        – manoeuvre complete, waiting for reset
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

import numpy as np


# ── tuneable constants ─────────────────────────────────────────────────────

CATCH_HEIGHT_MM      = 150.0   # Trigger braking below this Z (mm)
MIN_SAMPLES          = 8       # Minimum observations before fitting
HISTORY_WINDOW_S     = 1.5     # Only use the most recent N seconds of data
FIT_RESIDUAL_MAX     = 40.0    # Max RMS residual (mm) for a "good" parabola fit
COMMIT_LEAD_S        = 0.30    # Commit to intercept this many seconds before predicted catch
BURST_DURATION_S     = 0.08    # Duration of initial 1.0 PWM burst
BRAKE_PULSE_S        = 0.12    # Duration of reverse braking pulse
WHEEL_TO_ROBOT_SCALE = 1.0     # Placeholder if encoder→mm needs a correction factor

# Turn PD gains (fraction-per-tick-error)
TURN_KP  = 0.0030
TURN_KD  = 0.0015


class Phase(Enum):
    IDLE       = auto()
    OBSERVING  = auto()
    COMMITTED  = auto()
    BRAKING    = auto()
    DONE       = auto()


@dataclass
class InterceptPlan:
    """Everything the motor controller needs to execute the intercept."""
    catch_x:      float = 0.0   # mm, in camera frame
    catch_y:      float = 0.0
    catch_t:      float = 0.0   # perf_counter timestamp
    turn_rad:     float = 0.0   # signed radians (+ = left, − = right)
    time_budget:  float = 0.0   # seconds available to reach catch point


@dataclass
class InterceptTelemetry:
    """Snapshot published to the web UI each frame."""
    phase:          str   = "IDLE"
    n_samples:      int   = 0
    fit_rms_z:      float = 0.0
    fit_rms_xy:     float = 0.0
    predicted_t:    float = 0.0   # seconds until predicted catch (0 = unknown)
    catch_x:        float = 0.0
    catch_y:        float = 0.0
    turn_deg:       float = 0.0
    robot_heading:  float = 0.0   # dead-reckoned heading, degrees


@dataclass
class _Sample:
    t: float   # perf_counter
    x: float   # mm, camera frame (+right)
    y: float   # mm, camera frame (+forward? depends on rig)
    z: float   # mm, height above ground plane


class InterceptEngine:
    """
    Thread-safe intercept planner.  Call `update()` from the vision loop;
    call `tick_motors()` from the same loop to get (speed_a, speed_b) outputs.
    The caller is responsible for actually driving the motors.
    """

    def __init__(self, motors, catch_height_mm: float = CATCH_HEIGHT_MM):
        self._motors        = motors          # MotorHAL instance (for heading math)
        self._catch_h       = catch_height_mm
        self._history: deque[_Sample] = deque()
        self._phase         = Phase.IDLE
        self._plan: Optional[InterceptPlan] = None
        self._telemetry     = InterceptTelemetry()

        # Dead-reckoned robot pose (camera-frame coords, mm + radians)
        self._pose_x        = 0.0
        self._pose_y        = 0.0
        self._heading       = 0.0   # radians, 0 = forward along +Y

        # Encoder baseline captured at each phase transition
        self._enc_baseline  = (0, 0)

        # Timing
        self._committed_at  = 0.0
        self._burst_done    = False
        self._braking_start = 0.0
        self._last_tick_t   = time.perf_counter()

    # ── public API ────────────────────────────────────────────────────────

    @property
    def phase(self) -> Phase:
        return self._phase

    @property
    def telemetry(self) -> InterceptTelemetry:
        return self._telemetry

    def enable(self):
        """Transition from IDLE → OBSERVING and reset all state."""
        self._history.clear()
        self._plan    = None
        self._phase   = Phase.OBSERVING
        self._burst_done = False
        self._enc_baseline = self._motors.get_ticks()
        self._last_tick_t  = time.perf_counter()
        self._pose_x = self._pose_y = self._heading = 0.0

    def disable(self):
        self._phase = Phase.IDLE
        self._history.clear()
        self._plan = None

    def reset(self):
        """Return to OBSERVING after a completed or failed intercept."""
        self.enable()

    def update(self, pos: list[float], found: bool) -> tuple[float, float]:
        """
        Call once per vision frame.

        Args:
            pos   – [X, Y, Z] in mm from VisionEngine
            found – whether the object is currently visible

        Returns:
            (speed_a, speed_b) to apply to motors.  (0, 0) when not active.
        """
        now = time.perf_counter()
        dt  = max(now - self._last_tick_t, 1e-4)
        self._last_tick_t = now

        # Update dead-reckoned pose from encoders
        self._update_odometry(dt)

        if self._phase == Phase.IDLE:
            return 0.0, 0.0

        # ── OBSERVING ─────────────────────────────────────────────────────
        if self._phase == Phase.OBSERVING:
            if found:
                self._history.append(_Sample(t=now, x=pos[0], y=pos[1], z=pos[2]))
            # Prune old samples
            cutoff = now - HISTORY_WINDOW_S
            while self._history and self._history[0].t < cutoff:
                self._history.popleft()

            self._update_telemetry()

            if len(self._history) >= MIN_SAMPLES:
                plan = self._fit_and_plan(now)
                if plan is not None:
                    time_to_catch = plan.catch_t - now
                    if time_to_catch <= COMMIT_LEAD_S:
                        self._plan        = plan
                        self._phase       = Phase.COMMITTED
                        self._committed_at = now
                        self._burst_done  = False

            return 0.0, 0.0   # motors idle during observation

        # ── COMMITTED ─────────────────────────────────────────────────────
        if self._phase == Phase.COMMITTED:
            # Live Z check — brake early if already at catch height
            if found and pos[2] <= self._catch_h:
                self._phase        = Phase.BRAKING
                self._braking_start = now
                return self._brake_output()

            sa, sb = self._intercept_drive(now, dt)

            # Fallback: if time is up, go to DONE
            if self._plan and now > self._plan.catch_t + 0.5:
                self._phase = Phase.DONE

            self._update_telemetry()
            return sa, sb

        # ── BRAKING ───────────────────────────────────────────────────────
        if self._phase == Phase.BRAKING:
            elapsed = now - self._braking_start
            if elapsed < BRAKE_PULSE_S:
                return self._brake_output()
            else:
                self._phase = Phase.DONE
                return 0.0, 0.0

        # ── DONE ──────────────────────────────────────────────────────────
        if self._phase == Phase.DONE:
            self._update_telemetry()
            return 0.0, 0.0

        return 0.0, 0.0

    # ── internal helpers ──────────────────────────────────────────────────

    def _update_odometry(self, dt: float):
        """Dead-reckon robot pose from encoder tick deltas."""
        ta, tb = self._motors.get_ticks()
        ba, bb = self._enc_baseline

        dist_a = ((ta - ba) / self._motors.ticks_per_rev) * self._motors.wheel_circumference * 1000  # mm
        dist_b = ((tb - bb) / self._motors.ticks_per_rev) * self._motors.wheel_circumference * 1000

        # Differential drive kinematics
        dist_center = (dist_a + dist_b) / 2.0
        d_theta      = (dist_b - dist_a) / (self._motors.track_width_m * 1000)  # radians

        self._heading  += d_theta
        self._pose_x   += dist_center * math.sin(self._heading)
        self._pose_y   += dist_center * math.cos(self._heading)

        # Reset baseline so increments don't accumulate unboundedly
        self._enc_baseline = self._motors.get_ticks()

    def _fit_and_plan(self, now: float) -> Optional[InterceptPlan]:
        """
        Fit:
          • Degree-1 polynomial to X,Y (ground plane line)
          • Degree-2 polynomial to Z vs t (parabola)

        Solve the parabola for Z = catch_height and compute the catch point.
        Returns None if data quality is insufficient.
        """
        samples = list(self._history)
        if len(samples) < MIN_SAMPLES:
            return None

        ts = np.array([s.t - samples[0].t for s in samples])  # relative time
        xs = np.array([s.x for s in samples])
        ys = np.array([s.y for s in samples])
        zs = np.array([s.z for s in samples])

        # ── Parabola fit: Z(t) = a·t² + b·t + c ────────────────────────
        try:
            p_z  = np.polyfit(ts, zs, 2, full=True)
            coef_z   = p_z[0]           # [a, b, c]
            resid_z  = math.sqrt(p_z[1][0] / len(ts)) if p_z[1].size else 999.0
        except (np.linalg.LinAlgError, IndexError):
            return None

        if resid_z > FIT_RESIDUAL_MAX:
            return None

        # Solve a·t² + b·t + (c − catch_h) = 0
        a, b, c = coef_z
        c_adj   = c - self._catch_h
        disc    = b ** 2 - 4 * a * c_adj

        if disc < 0:
            return None   # parabola never reaches catch height

        sqrt_disc = math.sqrt(disc)
        t_roots   = [(-b + sqrt_disc) / (2 * a), (-b - sqrt_disc) / (2 * a)]
        # Keep only future roots (relative to last sample)
        t_last_rel = ts[-1]
        future     = [r for r in t_roots if r > t_last_rel]
        if not future:
            return None

        t_catch_rel  = min(future)                         # first future intersection
        t_catch_abs  = samples[0].t + t_catch_rel

        # ── Ground-plane line fit: Y = m·X + q ──────────────────────────
        try:
            p_xy     = np.polyfit(xs, ys, 1, full=True)
            coef_xy  = p_xy[0]
            resid_xy = math.sqrt(p_xy[1][0] / len(xs)) if p_xy[1].size else 999.0
        except (np.linalg.LinAlgError, IndexError):
            return None

        m, q = coef_xy
        # Predict X at catch time using linear time→X regression
        p_tx = np.polyfit(ts, xs, 1)
        x_catch = np.polyval(p_tx, t_catch_rel)
        y_catch = m * x_catch + q

        # ── Required turn angle ──────────────────────────────────────────
        # Vector from robot's estimated camera-frame position to catch point
        dx = x_catch - self._pose_x
        dy = y_catch - self._pose_y
        bearing = math.atan2(dx, dy)           # angle from +Y axis (forward)
        turn    = bearing - self._heading       # relative to current heading
        # Normalise to (−π, π]
        turn = (turn + math.pi) % (2 * math.pi) - math.pi

        time_budget = t_catch_abs - now

        # Store residuals for telemetry
        self._last_rms_z  = resid_z
        self._last_rms_xy = resid_xy

        return InterceptPlan(
            catch_x=x_catch,
            catch_y=y_catch,
            catch_t=t_catch_abs,
            turn_rad=turn,
            time_budget=time_budget,
        )

    def _intercept_drive(self, now: float, dt: float) -> tuple[float, float]:
        """
        Produce (speed_a, speed_b) to:
          1. Burst at 1.0 PWM for BURST_DURATION_S
          2. Then steer toward intercept point while running at max speed
        """
        elapsed = now - self._committed_at

        if elapsed < BURST_DURATION_S:
            # Full-power straight burst (bypasses min/max clamp via raw method)
            return 1.0, 1.0

        # After burst: steer toward catch point
        plan = self._plan
        if plan is None:
            return 0.7, 0.7

        # Remaining turn error (recalculate from current pose)
        dx = plan.catch_x - self._pose_x
        dy = plan.catch_y - self._pose_y
        bearing = math.atan2(dx, dy)
        turn_err_rad = (bearing - self._heading + math.pi) % (2 * math.pi) - math.pi

        # Simple proportional steering overlay on top of full speed
        steer = TURN_KP * turn_err_rad * (180.0 / math.pi)   # in [-1, 1] range
        steer = max(-0.5, min(0.5, steer))

        speed = 0.85   # sustained intercept speed
        sa = max(-1.0, min(1.0, speed - steer))
        sb = max(-1.0, min(1.0, speed + steer))
        return sa, sb

    def _brake_output(self) -> tuple[float, float]:
        """Reverse pulse to brake."""
        return -0.7, -0.7

    def _update_telemetry(self):
        plan = self._plan
        now  = time.perf_counter()
        self._telemetry = InterceptTelemetry(
            phase         = self._phase.name,
            n_samples     = len(self._history),
            fit_rms_z     = round(getattr(self, "_last_rms_z",  0.0), 2),
            fit_rms_xy    = round(getattr(self, "_last_rms_xy", 0.0), 2),
            predicted_t   = round(plan.catch_t - now, 3) if plan else 0.0,
            catch_x       = round(plan.catch_x, 1) if plan else 0.0,
            catch_y       = round(plan.catch_y, 1) if plan else 0.0,
            turn_deg      = round(math.degrees(plan.turn_rad), 1) if plan else 0.0,
            robot_heading = round(math.degrees(self._heading), 1),
        )