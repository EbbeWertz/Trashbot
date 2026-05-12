import os
import psutil
import serial
import time

class SystemStatus:
    def __init__(self, serial_port='/dev/serial0', baud_rate=38400):
        self.serial_port = serial_port
        self.baud_rate = baud_rate
        # 3s LiPo Configuration
        self.V_MAX = 12.6
        self.V_MIN = 9.9

    def _get_strompi_data(self):
        """Internal helper to fetch raw data from StromPi 3"""
        try:
            with serial.Serial(self.serial_port, self.baud_rate, timeout=1) as ser:
                ser.write(b'status-rpi\x0D')
                time.sleep(0.1)
                raw_data = ser.read_all().decode('utf-8', errors='ignore')
                lines = [line.strip() for line in raw_data.splitlines() if line.strip()]
                return lines if len(lines) >= 36 else None
        except Exception:
            return None

    def get_full_report(self):
        """Returns a dictionary with all requested telemetry"""
        strompi = self._get_strompi_data()
        
        # --- StromPi Voltages ---
        # Indices: 31=Bat, 33=3.3V(Wide), 34=5V(USB)
        v_bat = float(strompi[31]) / 1000 if strompi else 0.0
        v_33  = float(strompi[33]) / 1000 if strompi else 0.0
        v_50  = float(strompi[34]) / 1000 if strompi else 0.0
        
        # --- Battery Percentage ---
        percent = 0.0
        if v_bat > 0:
            percent = ((v_bat - self.V_MIN) / (self.V_MAX - self.V_MIN)) * 100
            percent = round(max(0.0, min(100.0, percent)), 1)

        # --- Internal Pi Data ---
        # 1. CPU Utilization
        cpu_pct = psutil.cpu_percent(interval=None)
        
        # 2. CPU Temperature
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            temp_c = float(f.read()) / 1000.0

        # 3. Pi Power Rail (Measured by the SoC)
        # Note: 'volt' from vcgencmd typically returns core voltage, not input 5V.
        # To get the internal core rail:
        core_v_raw = os.popen('vcgencmd measure_volts core').readline()
        core_v = float(core_v_raw.replace("volt=", "").replace("V", ""))

        # 4. Fan Speed
        # If using a standard RPi PoE/Official fan, speed is stored in the system pwm
        try:
            with open("/sys/class/thermal/cooling_device0/cur_state", "r") as f:
                fan_level = int(f.read()) # Usually 0-4 or 0-255 depending on driver
        except:
            fan_level = 0

        return {
            "battery_v": v_bat,
            "battery_percent": percent,
            "rail_3_3v": v_33,
            "rail_5_0v": v_50,
            "pi_core_v": core_v,
            "cpu_util": cpu_pct,
            "temp_c": temp_c,
            "fan_level": fan_level
        }

# --- Example Usage ---
if __name__ == "__main__":
    status = SystemStatus()
    report = status.get_full_report()
    
    print(f"--- Power System ---")
    print(f"Battery: {report['battery_v']}V ({report['battery_percent']}%)")
    print(f"StromPi Rails: 3.3V: {report['rail_3_3v']}V | 5V: {report['rail_5_0v']}V")
    print(f"Pi Core Voltage: {report['pi_core_v']}V")
    print(f"\n--- Performance ---")
    print(f"CPU Load: {report['cpu_util']}%")
    print(f"Temperature: {report['temp_c']}°C")
    print(f"Fan Level: {report['fan_level']}")