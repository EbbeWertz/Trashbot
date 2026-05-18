class PIDController:
    def __init__(self, kp: float = 0.004, ki: float = 0.0002,
                 kd: float = 0.0001, deadzone: float = 10.0,
                 integral_limit: float = 500.0):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.deadzone = deadzone
        self.integral_limit = integral_limit

        self._last_err = 0.0
        self._integral = 0.0

    def reset(self):
        self._last_err = 0.0
        self._integral = 0.0

    def step(self, error: float, dt: float) -> float:
        if abs(error) < self.deadzone:
            return 0.0

        self._integral += error * dt
        # Anti-windup clamp
        self._integral = max(-self.integral_limit,
                             min(self.integral_limit, self._integral))

        derivative = (error - self._last_err) / dt if dt > 0 else 0.0
        self._last_err = error

        return (self.kp * error) + (self.ki * self._integral) + (self.kd * derivative)