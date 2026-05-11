from gpiozero import PWMOutputDevice, DigitalOutputDevice, RotaryEncoder
from time import sleep, time
import sys

# --- Configuration ---
# Update these based on your specific motor's datasheet
PPR = 20.0          # Pulses per revolution (encoder ticks per 1 full turn)
GEAR_RATIO = 48.0   # Example gear ratio (if applicable)
TICKS_PER_REV = PPR * GEAR_RATIO 

# Motor A (Left)
PWM_A = PWMOutputDevice(12)
IN1 = DigitalOutputDevice(24)
IN2 = DigitalOutputDevice(23)
ENC_A = RotaryEncoder(5, 6, max_steps=0)

# Motor B (Right)
PWM_B = PWMOutputDevice(13)
IN3 = DigitalOutputDevice(27) # Swapped per your request
IN4 = DigitalOutputDevice(22) # Swapped per your request
ENC_B = RotaryEncoder(26, 16, max_steps=0)

def set_motor(motor, speed):
    """Sets speed from -1.0 to 1.0"""
    if motor == 'A':
        pwm, p1, p2 = PWM_A, IN1, IN2
    else:
        pwm, p1, p2 = PWM_B, IN3, IN4

    if speed > 0:
        p1.on(); p2.off()
    elif speed < 0:
        p1.off(); p2.on()
    else:
        p1.off(); p2.off()
    pwm.value = abs(speed)

def run_test(a_speed, b_speed, duration):
    set_motor('A', a_speed)
    set_motor('B', b_speed)
    
    start_time = time()
    last_time = start_time
    last_ticks_a = ENC_A.steps
    last_ticks_b = ENC_B.steps

    print("\nReal-time Speed (rev/s):")
    print("Motor_A, Motor_B")
    
    try:
        while (time() - start_time) < duration:
            sleep(0.1) # Sample rate (10Hz)
            
            current_time = time()
            dt = current_time - last_time
            
            # Get current pulses
            curr_a = ENC_A.steps
            curr_b = ENC_B.steps
            
            # Calculate Rev/s: (change in ticks / ticks per rev) / time
            rev_s_a = ((curr_a - last_ticks_a) / TICKS_PER_REV) / dt
            rev_s_b = ((curr_b - last_ticks_b) / TICKS_PER_REV) / dt
            
            print(f"{rev_s_a:6.2f}, {rev_s_b:6.2f}")
            
            last_ticks_a, last_ticks_b = curr_a, curr_b
            last_time = current_time

    finally:
        set_motor('A', 0)
        set_motor('B', 0)

# --- Main CLI ---
try:
    while True:
        user_input = input("\nEnter (a_speed, b_speed, duration, break_time) or 'q': ")
        if user_input.lower() == 'q':
            break
            
        try:
            sa, sb, dur, br_t = map(float, user_input.split(','))
            run_test(sa, sb, dur)
            if br_t != 0:
                run_test(-sa, -sb, br_t)
        except ValueError:
            print("Invalid format! Use: 0.5, 0.5, 2")

except KeyboardInterrupt:
    pass
finally:
    PWM_A.value = 0
    PWM_B.value = 0
