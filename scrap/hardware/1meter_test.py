from gpiozero import PWMOutputDevice, DigitalOutputDevice, RotaryEncoder
from time import sleep, time
import math
import sys

# ==============================================================================
# 1. HARDWARE REWIRING CONFIGURATION
# ==============================================================================
SWAP_LEFT_RIGHT_MOTORS = False  # Set True to swap Motor A and Motor B assignments

REVERSE_MOTOR_A = True         # Set True if Left motor runs backward on positive power
REVERSE_MOTOR_B = True         # Set True if Right motor runs backward on positive power

REVERSE_ENCODER_A = True       # Set True if Left encoder counts down moving forward
REVERSE_ENCODER_B = True       # Set True if Right encoder counts down moving forward

# ==============================================================================
# 2. PHYSICAL ROBOT CONFIGURATION
# ==============================================================================
PPR = 11.0
GEAR_RATIO = 18.75
TICKS_PER_REV = PPR * GEAR_RATIO

WHEEL_DIAMETER_M = 0.064  
WHEEL_CIRCUMFERENCE = math.pi * WHEEL_DIAMETER_M

# Distance between the center of the 40mm wide tires
TRACK_WIDTH_M = 0.170  

# Speed Caps
MIN_PWM = 0.21  
MAX_PWM = 0.32  

# ==============================================================================
# 3. HARDWARE INITIALIZATION
# ==============================================================================
_PWM_12 = PWMOutputDevice(12)
_IN1 = DigitalOutputDevice(24)
_IN2 = DigitalOutputDevice(23)
_ENC_LEFT = RotaryEncoder(5, 6, max_steps=0)

_PWM_13 = PWMOutputDevice(13)
_IN3 = DigitalOutputDevice(27)
_IN4 = DigitalOutputDevice(22)
_ENC_RIGHT = RotaryEncoder(26, 16, max_steps=0)

if not SWAP_LEFT_RIGHT_MOTORS:
    PWM_A, IN1, IN2, ENC_A = _PWM_12, _IN1, _IN2, _ENC_LEFT
    PWM_B, IN3, IN4, ENC_B = _PWM_13, _IN3, _IN4, _ENC_RIGHT
else:
    PWM_A, IN1, IN2, ENC_A = _PWM_13, _IN3, _IN4, _ENC_RIGHT
    PWM_B, IN3, IN4, ENC_B = _PWM_12, _IN1, _IN2, _ENC_LEFT

# ==============================================================================
# 4. UTILITY FUNCTIONS
# ==============================================================================
def get_encoder_ticks():
    ticks_a = ENC_A.steps * (-1 if REVERSE_ENCODER_A else 1)
    ticks_b = ENC_B.steps * (-1 if REVERSE_ENCODER_B else 1)
    return ticks_a, ticks_b

def set_motor(motor, speed):
    if motor == 'A':
        pwm, p1, p2 = PWM_A, IN1, IN2
        if REVERSE_MOTOR_A: speed = -speed
    else:
        pwm, p1, p2 = PWM_B, IN3, IN4
        if REVERSE_MOTOR_B: speed = -speed

    direction = 1 if speed >= 0 else -1
    abs_speed = abs(speed)

    if abs_speed > 0.01:
        actual_speed = max(MIN_PWM, min(abs_speed, MAX_PWM))
    else:
        actual_speed = 0.0

    if actual_speed == 0:
        p1.off(); p2.off()
    elif direction == 1:
        p1.on(); p2.off()
    else:  
        p1.off(); p2.on()
        
    pwm.value = actual_speed

def hard_stop():
    IN1.off(); IN2.off(); IN3.off(); IN4.off()
    PWM_A.value = 0; PWM_B.value = 0

# ==============================================================================
# 5. TEST COMMANDS
# ==============================================================================
def test_single_motor(motor_name):
    """Spins one motor forward raw for 1.0s and evaluates real-time rev/s."""
    print(f"Testing Motor {motor_name} forward... [Ctrl+C to abort]")
    
    start_time = time()
    last_time = start_time
    start_a, start_b = get_encoder_ticks()
    last_a, last_b = start_a, start_b
    
    set_motor(motor_name, 0.26)
    
    try:
        while (time() - start_time) < 1.0:
            sleep(0.05)
            now = time()
            dt = now - last_time
            curr_a, curr_b = get_encoder_ticks()
            
            # Instantaneous Rev/s calculation
            rev_s_a = ((curr_a - last_a) / TICKS_PER_REV) / dt
            rev_s_b = ((curr_b - last_b) / TICKS_PER_REV) / dt
            
            print(f"\rSpeed -> Motor A: {rev_s_a:6.2f} rev/s | Motor B: {rev_s_b:6.2f} rev/s", end="", flush=True)
            
            last_a, last_b = curr_a, curr_b
            last_time = now
    except KeyboardInterrupt:
        pass
    finally:
        hard_stop()
        sleep(0.1)
        end_a, end_b = get_encoder_ticks()
        print(f"\nStopped. Total test displacement -> ΔA: {end_a - start_a} ticks | ΔB: {end_b - start_b} ticks")

# ==============================================================================
# 6. CLOSED LOOP PROFILE REGULATOR
# ==============================================================================
def execute_profile(target_a, target_b):
    start_ticks_a, start_ticks_b = get_encoder_ticks()
    
    Kp = 0.0035  
    Kd = 0.0018  
    
    last_error_a = target_a
    last_error_b = target_b
    last_a, last_b = start_ticks_a, start_ticks_b
    
    loop_dt = 0.01  
    last_time = time()
    settle_count = 0
    
    try:
        while True:
            start_loop_time = time()
            curr_a, curr_b = get_encoder_ticks()
            
            # Calculations for PD Controller (Positional Error)
            delta_a = curr_a - start_ticks_a
            delta_b = curr_b - start_ticks_b
            error_a = target_a - delta_a
            error_b = target_b - delta_b
            
            # Calculations for Telemetry (Velocity in Rev/s)
            dt = start_loop_time - last_time
            if dt > 0:
                rev_s_a = ((curr_a - last_a) / TICKS_PER_REV) / dt
                rev_s_b = ((curr_b - last_b) / TICKS_PER_REV) / dt
            else:
                rev_s_a, rev_s_b = 0.0, 0.0
            
            # Settle evaluation
            if abs(error_a) <= 2 and abs(error_b) <= 2:
                settle_count += 1
                if settle_count >= 15:
                    print("\nTarget reached.")
                    break
            else:
                settle_count = 0

            # PD Controller Outputs
            deriv_a = (error_a - last_error_a) / loop_dt
            deriv_b = (error_b - last_error_b) / loop_dt
            speed_a = (error_a * Kp) + (deriv_a * Kd)
            speed_b = (error_b * Kp) + (deriv_b * Kd)
            
            set_motor('A', speed_a)
            set_motor('B', speed_b)
            
            # Retain states
            last_error_a, last_error_b = error_a, error_b
            last_a, last_b = curr_a, curr_b
            last_time = start_loop_time
            
            # Render Dynamic Telemetry
            print(f"\rSpeed A: {rev_s_a:5.2f} r/s, B: {rev_s_b:5.2f} r/s | Remaining -> A: {error_a:4} Ticks, B: {error_b:4} Ticks", end="", flush=True)
            
            elapsed = time() - start_loop_time
            sleep(max(0.001, loop_dt - elapsed))
            
    except KeyboardInterrupt:
        print("\nExecution broken by operator.")
    finally:
        hard_stop()
        sleep(0.2)

# ==============================================================================
# 7. INTERACTIVE SHELL EXECUTION
# ==============================================================================
if __name__ == "__main__":
    print("RobotOS v1.1.0-alpha")
    print("Type 'help' to review structural commands or 'exit' to disconnect.\n")
    
    while True:
        try:
            # Custom shell prompt styling
            cmd_line = input("bot-sh$ ").strip()
            if not cmd_line:
                continue
                
            parts = cmd_line.split()
            cmd = parts[0].lower()
            
            if cmd in ['exit', 'quit', 'q']:
                print("Closing core shell loops. Goodbye.")
                break
                
            elif cmd == 'help':
                print("System shell commands:")
                print("  test_left        Executes a 1-second raw run of Motor A")
                print("  test_right       Executes a 1-second raw run of Motor B")
                print("  drive [meters]   Closed-loop translation profile (e.g., drive 1.2 or drive -0.5)")
                print("  spin [degrees]   Closed-loop rotation profile (e.g., spin 360 or spin -90)")
                print("  exit             Closes the controller connection layer")
                
            elif cmd == 'test_left':
                test_single_motor('A')
                
            elif cmd == 'test_right':
                test_single_motor('B')
                
            elif cmd in ['drive', 'spin']:
                if len(parts) < 2:
                    print(f"Error: Command '{cmd}' requires a numerical magnitude argument.")
                    continue
                    
                val = float(parts[1])
                
                if cmd == 'drive':
                    target_ticks = int((val / WHEEL_CIRCUMFERENCE) * TICKS_PER_REV)
                    execute_profile(target_ticks, target_ticks)
                    
                elif cmd == 'spin':
                    turn_fraction = val / 360.0
                    turn_distance_m = (math.pi * TRACK_WIDTH_M) * turn_fraction
                    target_ticks = int((turn_distance_m / WHEEL_CIRCUMFERENCE) * TICKS_PER_REV)
                    execute_profile(target_ticks, -target_ticks)
            else:
                print(f"bot-sh: {cmd}: command not found")
                
        except (IndexError, ValueError):
            print("bot-sh: syntax error: unable to parse arguments into float variables")
        except KeyboardInterrupt:
            print("\nUse 'exit' to terminate shell instance safely.")
        finally:
            hard_stop()