class PIDController:
    def __init__(self, kp=0.004, ki=0.0002, kd=0.0001):
        self.kp, self.ki, self.kd = kp, ki, kd
        self.last_err = 0
        self.integral = 0

    def step(self, error, dt):
        if abs(error) < 10: return 0 # Deadzone
        self.integral += error * dt
        deriv = (error - self.last_err) / dt
        self.last_err = error
        return (self.kp * error) + (self.ki * self.integral) + (self.kd * deriv)
