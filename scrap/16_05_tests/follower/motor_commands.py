from hardware.MotorHAL import MotorHAL
import time

def command_test_motor(motors: MotorHAL, side: str, duration: float = 1.0) -> list:
    log = []
    ta0, tb0 = motors.get_ticks()
    t0 = time.perf_counter()
    t_last = t0
    ta_last, tb_last = ta0, tb0
    speed_a = 0.3 if side == "A" else 0.0
    speed_b = 0.3 if side == "B" else 0.0
    motors.drive(speed_a, speed_b)
    try:
        while time.perf_counter() - t0 < duration:
            time.sleep(0.05)
            now = time.perf_counter()
            ta, tb = motors.get_ticks()
            dt = now - t_last
            rev_s_a = ((ta - ta_last) / motors.ticks_per_rev) / dt if dt else 0
            rev_s_b = ((tb - tb_last) / motors.ticks_per_rev) / dt if dt else 0
            log.append({"t": round(now - t0, 3),
                         "rev_s_a": round(rev_s_a, 3),
                         "rev_s_b": round(rev_s_b, 3)})
            ta_last, tb_last = ta, tb
            t_last = now
    finally:
        motors.stop()
    ta_end, tb_end = motors.get_ticks()
    log.append({"summary": True,
                 "delta_a": ta_end - ta0,
                 "delta_b": tb_end - tb0})
    return log
def command_execute_drive(motors: MotorHAL, meters: float):
    ticks = int((meters / motors.wheel_circumference) * motors.ticks_per_rev)
    motors.execute_profile(ticks, ticks)


def command_execute_spin(motors: MotorHAL, degrees: float):
    fraction  = degrees / 360.0
    dist_m    = (3.14159265 * motors.track_width_m) * fraction
    ticks     = int((dist_m / motors.wheel_circumference) * motors.ticks_per_rev)
    motors.execute_profile(ticks, -ticks)