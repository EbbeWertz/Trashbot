import serial
import time

# --- Configuration ---
SERIAL_PORT = '/dev/serial0'
BAUD_RATE = 38400
# 3s LiPo Voltage Range (Adjust based on your preference)
V_MAX = 12.6  # 4.2V per cell
V_MIN = 9.9   # 3.3V per cell (Safe cutoff)

def get_strompi_voltage():
    try:
        with serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1) as ser:
            # Wake up and request status
            ser.write(str.encode('status-rpi\x0D'))
            time.sleep(0.5)
            
            # StromPi status returns ~30 lines. 
            # We need the 28th line for Battery ADC (sp3_ADC_BAT)
            lines = []
            for _ in range(35):
                line = ser.readline().decode('utf-8').strip()
                if line:
                    lines.append(line)
            
            # The Battery voltage is the 28th value in the status dump
            # It is returned in mV (e.g., 11500)
            raw_bat_mv = float(lines[27]) 
            return raw_bat_mv / 1000.0
    except Exception as e:
        print(f"Error reading StromPi: {e}")
        return None

def calculate_percentage(voltage):
    if voltage >= V_MAX: return 100.0
    if voltage <= V_MIN: return 0.0
    percent = ((voltage - V_MIN) / (V_MAX - V_MIN)) * 100
    return round(percent, 1)

if __name__ == "__main__":
    voltage = get_strompi_voltage()
    if voltage:
        percent = calculate_percentage(voltage)
        print(f"Battery Voltage: {voltage:.2f}V")
        print(f"Charge Level:    {percent}%")
    else:
        print("Could not retrieve voltage.")
