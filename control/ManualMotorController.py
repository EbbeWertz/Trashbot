import asyncio

class ManualMotorController:
    def __init__(self, hardware):
        self.hw = hardware
        self.target_l = 0.0
        self.target_r = 0.0
        self.current_l = 0.0
        self.current_r = 0.0
        self.ease = 0.1 # Acceleration factor
        self.brake_pulse_enabled = True

    async def update_loop(self):
        """Smoothly ramps motor speeds and reads telemetry"""
        while True:
            # Simple easing: current = current + (target - current) * ease
            self.current_l += (self.target_l - self.current_l) * self.ease
            self.current_r += (self.target_r - self.current_r) * self.ease
            
            self.hw.left_motor.set_speed(self.current_l)
            self.hw.right_motor.set_speed(self.current_r)
            await asyncio.sleep(0.05) # 20Hz update

    def set_targets(self, l, r):
        # Logic for reverse thrust braking could be inserted here
        if l == 0 and r == 0 and self.brake_pulse_enabled and abs(self.current_l) > 0.2:
            # Implement short reverse pulse logic here if needed
            pass
        self.target_l = l
        self.target_r = r