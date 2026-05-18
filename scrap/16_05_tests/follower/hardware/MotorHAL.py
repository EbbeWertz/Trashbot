import math
from gpiozero import PWMOutputDevice, DigitalOutputDevice, RotaryEncoder
import time


class MotorHAL:
   
    def __init__(self, cfg: dict):
        mcfg = cfg["motors"]
        ma = mcfg["motor_a"]
        mb = mcfg["motor_b"]
        enc = mcfg["encoders"]

        # --- Raw GPIO objects -------------------------------------------
        _pwm_a = PWMOutputDevice(int(ma["pwm_pin"]))
        _in1   = DigitalOutputDevice(int(ma["in1_pin"]))
        _in2   = DigitalOutputDevice(int(ma["in2_pin"]))
        _enc_l = RotaryEncoder(int(enc["left_pin_a"]), int(enc["left_pin_b"]), max_steps=0)

        _pwm_b = PWMOutputDevice(int(mb["pwm_pin"]))
        _in3   = DigitalOutputDevice(int(mb["in3_pin"]))
        _in4   = DigitalOutputDevice(int(mb["in4_pin"]))
        _enc_r = RotaryEncoder(int(enc["right_pin_a"]), int(enc["right_pin_b"]), max_steps=0)

        # --- Swap left/right if requested --------------------------------
        if mcfg.get("swap_left_right", False):
            self._pwm_a, self._in1, self._in2, self._enc_a = _pwm_b, _in3, _in4, _enc_r
            self._pwm_b, self._in3, self._in4, self._enc_b = _pwm_a, _in1, _in2, _enc_l
        else:
            self._pwm_a, self._in1, self._in2, self._enc_a = _pwm_a, _in1, _in2, _enc_l
            self._pwm_b, self._in3, self._in4, self._enc_b = _pwm_b, _in3, _in4, _enc_r

        # --- Direction flags ---------------------------------------------
        self._rev_a     = bool(ma.get("reverse", False))
        self._rev_b     = bool(mb.get("reverse", False))
        self._rev_enc_a = bool(enc.get("reverse_left", False))
        self._rev_enc_b = bool(enc.get("reverse_right", False))

        # --- PWM limits --------------------------------------------------
        self.min_pwm = float(mcfg.get("min_pwm", 0.21))
        self.max_pwm = float(mcfg.get("max_pwm", 0.32))

        # --- Mechanical constants ----------------------------------------
        ppr        = float(mcfg.get("ppr", 11.0))
        gear_ratio = float(mcfg.get("gear_ratio", 18.75))
        self.ticks_per_rev      = ppr * gear_ratio
        self.wheel_diameter_m   = float(mcfg.get("wheel_diameter_m", 0.064))
        self.wheel_circumference = math.pi * self.wheel_diameter_m
        self.track_width_m      = float(mcfg.get("track_width_m", 0.170))

    # ------------------------------------------------------------------
    # Encoder
    # ------------------------------------------------------------------

    def get_encoder_ticks(self) -> tuple:
        ta = self._enc_a.steps * (-1 if self._rev_enc_a else 1)
        tb = self._enc_b.steps * (-1 if self._rev_enc_b else 1)
        return ta, tb

    # ------------------------------------------------------------------
    # Motor drive helpers
    # ------------------------------------------------------------------

    # speed = [-1.0, 1.0]
    def _set_motor(self, side: str, speed: float):
        if side == "A":
            pwm, p1, p2 = self._pwm_a, self._in1, self._in2
            if self._rev_a:
                speed = -speed
        else:
            pwm, p1, p2 = self._pwm_b, self._in3, self._in4
            if self._rev_b:
                speed = -speed

        direction  = 1 if speed >= 0 else -1
        abs_speed  = abs(speed)
        duty       = max(self.min_pwm, min(abs_speed, self.max_pwm)) if abs_speed > 0.01 else 0.0

        if duty == 0.0:
            p1.off(); p2.off()
        elif direction == 1:
            p1.on(); p2.off()
        else:
            p1.off(); p2.on()

        pwm.value = duty

    # ------------------------------------------------------------------
    # Abstracties
    # ------------------------------------------------------------------

    def drive(self, speed_a: float, speed_b: float):
        self._set_motor("A", speed_a)
        self._set_motor("B", speed_b)

    def drive_raw(self, speed_a: float, speed_b: float):
        for side, speed in (("A", speed_a), ("B", speed_b)):
            if side == "A":
                pwm, p1, p2 = self._pwm_a, self._in1, self._in2
                if self._rev_a: speed = -speed
            else:
                pwm, p1, p2 = self._pwm_b, self._in3, self._in4
                if self._rev_b: speed = -speed

            speed = max(-1.0, min(1.0, speed))
            if abs(speed) < 0.01:
                p1.off(); p2.off(); pwm.value = 0.0
            elif speed > 0:
                p1.on(); p2.off(); pwm.value = speed
            else:
                p1.off(); p2.on(); pwm.value = abs(speed)

    def drive_straight(self, speed: float):
        """Drive both motors at the same speed (vertical tracking)."""
        self.drive(speed, speed)

    def stop(self):
        """Brake both motors."""
        self._in1.off(); self._in2.off()
        self._in3.off(); self._in4.off()
        self._pwm_a.value = 0
        self._pwm_b.value = 0

    # ------------------------------------------------------------------
    # Closed-loop profile executor (blocking, runs on caller's thread)
    # ------------------------------------------------------------------

    def execute_profile(self, target_a: int, target_b: int,
                        kp: float = 0.0035, kd: float = 0.0018,
                        settle_ticks: int = 2, settle_count_needed: int = 15,
                        progress_cb=None):

        start_a, start_b = self.get_encoder_ticks()
        last_err_a, last_err_b = target_a, target_b
        last_a, last_b = start_a, start_b
        loop_dt = 0.01
        last_time = time.perf_counter()
        settle_count = 0

        try:
            while True:
                t0 = time.perf_counter()
                cur_a, cur_b = self.get_encoder_ticks()

                err_a = target_a - (cur_a - start_a)
                err_b = target_b - (cur_b - start_b)

                dt = t0 - last_time
                if dt > 0:
                    rev_s_a = ((cur_a - last_a) / self.ticks_per_rev) / dt
                    rev_s_b = ((cur_b - last_b) / self.ticks_per_rev) / dt
                else:
                    rev_s_a = rev_s_b = 0.0

                if progress_cb:
                    progress_cb(rev_s_a, rev_s_b, err_a, err_b)

                if abs(err_a) <= settle_ticks and abs(err_b) <= settle_ticks:
                    settle_count += 1
                    if settle_count >= settle_count_needed:
                        break
                else:
                    settle_count = 0

                d_a = (err_a - last_err_a) / loop_dt
                d_b = (err_b - last_err_b) / loop_dt
                self._set_motor("A", err_a * kp + d_a * kd)
                self._set_motor("B", err_b * kp + d_b * kd)

                last_err_a, last_err_b = err_a, err_b
                last_a, last_b = cur_a, cur_b
                last_time = t0

                elapsed = time.perf_counter() - t0
                time.sleep(max(0.001, loop_dt - elapsed))

        finally:
            self.stop()