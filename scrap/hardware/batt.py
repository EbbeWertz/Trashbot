def print_readable_status(raw_lines):
    # Ensure we have enough data to avoid IndexErrors
    if len(raw_lines) < 36:
        print("Error: Received incomplete data dump from StromPi.")
        return

    # Extraction with unit conversion (mV to V)
    battery_v = float(raw_lines[31]) / 1000
    rail_3_3  = float(raw_lines[33]) / 1000
    rail_5_0  = float(raw_lines[34]) / 1000
    
    print("--- STROMPI 3 POWER STATUS ---")
    print(f"Main Battery Input:  {battery_v:>6.2f} V")
    print(f"Internal 3.3V Rail:  {rail_3_3:>6.2f} V")
    print(f"Internal 5.0V Rail:  {rail_5_0:>6.2f} V")
    print("------------------------------")
    
    # Simple Health Check
    if battery_v < 10.5:
        print("(!) WARNING: Battery Low")
    else:
        print("Status: Battery Healthy")

# Example usage with your data:
data = ['2648', '180501', '2', '4', '0', '1', '0', '0', '1', '1', '1', '0', '0', '0', '0', '10', '1', '0', '0', '0', '0', '0', '0', '1', '0', '30', '0', '0', '0', '30', '1', '12179', '0', '3295', '5128', '2', '0', 'v1.73']
print_readable_status(data)