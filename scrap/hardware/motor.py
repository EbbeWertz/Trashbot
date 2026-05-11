from gpiozero import PWMOutputDevice, DigitalOutputDevice
from time import sleep
import sys

# Motor A Pins
PWM_A = PWMOutputDevice(12) # Enable A
IN1 = DigitalOutputDevice(23)
IN2 = DigitalOutputDevice(24)

# Motor B Pins
PWM_B = PWMOutputDevice(13) # Enable B
IN3 = DigitalOutputDevice(22)
IN4 = DigitalOutputDevice(27)

def set_motor_speed(motor, speed):
    """
    speed should be between -1.0 and 1.0
    """
    # Select correct pins for the motor
    if motor == 'A':
        pwm, p1, p2 = PWM_A, IN1, IN2
    else:
        pwm, p3, p4 = PWM_B, IN3, IN4

    # Determine direction
    if speed > 0:
        p1.on() if motor == 'A' else IN3.on()
        p2.off() if motor == 'A' else IN4.off()
    elif speed < 0:
        p1.off() if motor == 'A' else IN3.off()
        p2.on() if motor == 'A' else IN4.on()
    else:
        p1.off() if motor == 'A' else IN3.off()
        p2.off() if motor == 'A' else IN4.off()

    pwm.value = abs(speed)

print("--- Raspberry Pi 5 Motor Control ---")
print("Enter speed (-1.0 to 1.0). Enter 'q' to quit.")

try:
    while True:
        val = input("\nEnter Speed (e.g., 0.5): ")
        
        if val.lower() == 'q':
            break
            
        try:
            speed = float(val)
            if -1.0 <= speed <= 1.0:
                set_motor_speed('A', speed)
                set_motor_speed('B', speed)
                print(f"Moving at {speed*100}% power")
            else:
                print("Please keep speed between -1.0 and 1.0")
        except ValueError:
            print("Invalid input. Please enter a number.")

except KeyboardInterrupt:
    pass

finally:
    # Cleanup: Stop motors on exit
    PWM_A.value = 0
    PWM_B.value = 0
    print("\nMotors stopped. Goodbye.")
