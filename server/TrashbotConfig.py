import json

class TrashbotConfig:
    def __init__(self, filepath="config/config.json"):
        self._filepath = filepath
        self._data = {}
        self._load()

    def _load(self):
        with open(self._filepath, 'r') as f:
            self._data.update(json.load(f))

    def save(self):
        with open(self._filepath, 'w') as f:
            json.dump(self._data, f, indent=4)

    # side = "left" | "right"
    def reverse_motor(self, side: str):
        if side in self._data["motors"]:
            current = self._data["motors"][side]["reverse"]
            self._data["motors"][side]["reverse"] = not current
            self.save()

    def swap_motors(self):
        left_pins = self._data["motors"]["left"]
        right_pins = self._data["motors"]["right"]
        self._data["motors"]["left"], self._data["motors"]["right"] = right_pins, left_pins
        self.save()

    def swap_cameras(self):
        l_ch = self._data["camera"]["left_ch"]
        r_ch = self._data["camera"]["right_ch"]
        self._data["camera"]["left_ch"], self._data["camera"]["right_ch"] = r_ch, l_ch
        self.save()

    def update_camera_calibration(self, new_path: str):
        self._data["camera"]["calibration_file"] = new_path
        self.save()

    @property
    def motor_left(self): return self._data["motors"]["left"]
    
    @property
    def motor_right(self): return self._data["motors"]["right"]

    @property
    def camera_left_ch(self): return self._data["cameras"]["left_ch"]

    @property
    def camera_full_res(self): return self._data["cameras"]["full_resolution"]

    @property
    def camera_low_res(self): return self._data["cameras"]["low_resolution"]

    @property
    def camera_right_ch(self): return self._data["cameras"]["right_ch"]


    @property
    def cameras(self): return self._data["cameras"]

    @property
    def imu_channel(self): return self._data["imu"]["i2c_channel"]

    @property
    def encoder(self): return self._data["encoder"]