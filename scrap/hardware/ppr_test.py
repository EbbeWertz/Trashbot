from gpiozero import RotaryEncoder
from time import sleep
import sys

# --- Configuration ---
PPR = 11.0  # Known encoder Pulses Per Revolution
TARGET_ROTATIONS = 1.0  # How many full physical wheel turns you will make

# Encoder Pins (Matching your original setup)
ENC_A = RotaryEncoder(5, 6, max_steps=0)
ENC_B = RotaryEncoder(26, 16, max_steps=0)

def run_calibration():
    print("=" * 50)
    print("        MOTOR GEAR RATIO CALIBRATION")
    print("=" * 50)
    print(f"1. Mark a clear starting point on your wheel/axle.")
    print(f"2. You will turn the wheels EXACTLY {TARGET_ROTATIONS} full rotations.")
    print("=" * 50)
    
    input("Press Enter when you are ready to start turning...")
    
    # Reset/record baseline ticks
    start_ticks_a = ENC_A.steps
    start_ticks_b = ENC_B.steps
    
    print("\nCounting ticks now. Turn the wheels slowly...")
    print("Press Ctrl+C when you have finished the rotations.")
    
    try:
        while True:
            # Live readout so you see if encoders are working
            ticks_a = ENC_A.steps - start_ticks_a
            ticks_b = ENC_B.steps - start_ticks_b
            print(f"\rCurrent Ticks -> Motor A: {ticks_a} | Motor B: {ticks_b}", end="", flush=True)
            sleep(0.1)
            
    except KeyboardInterrupt:
        print("\n\nCalibration stopped. Calculating results...")
        
        final_ticks_a = abs(ENC_A.steps - start_ticks_a)
        final_ticks_b = abs(ENC_B.steps - start_ticks_b)
        
        print("\n" + "=" * 40)
        print("RESULTS")
        print("=" * 40)
        
        for name, ticks in [("Motor A (Left) ", final_ticks_a), ("Motor B (Right)", final_ticks_b)]:
            if ticks == 0:
                print(f"{name}: No pulses detected. Check wiring!")
                continue
                
            # Calculation: Gear Ratio = Ticks / (PPR * Rotations)
            calculated_ratio = ticks / (PPR * TARGET_ROTATIONS)
            
            print(f"{name}:")
            print(f"  - Total Raw Ticks: {ticks}")
            print(f"  - Calculated Gear Ratio: {calculated_ratio:.2f}")
            
            # Common standard gear ratios for context
            print(f"  - Likely standard ratio: ~{round(calculated_ratio)}:1")
        print("=" * 40)

if __name__ == "__main__":
    run_calibration()