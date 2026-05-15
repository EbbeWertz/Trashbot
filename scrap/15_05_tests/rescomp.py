import time
import numpy as np
from PIL import Image
from picamera2 import Picamera2

# Initialize Camera
cam = Picamera2()

# 1. CAPTURE BINNED IMAGE
# Mode 1 for IMX708 is typically 2304x1296 (2x2 binning)
binned_config = cam.create_still_configuration(main={'size': (2304, 1296)})
cam.configure(binned_config)
cam.start()
time.sleep(2) # Let AEC/AWB settle
binned_img = cam.capture_array()
cam.stop()

# 2. CAPTURE HIGH-SPEED IMAGE
# Mode 3 for IMX708 is typically 1536x864 at 120fps
# We use a still configuration at this resolution to match the sensor mode
hs_config = cam.create_still_configuration(main={'size': (1536, 864)})
cam.configure(hs_config)
cam.start()
time.sleep(2)
hs_img = cam.capture_array()
cam.stop()

# 3. SAVE IMAGES
Image.fromarray(binned_img).save("binned_2x2.jpg")
Image.fromarray(hs_img).save("high_speed_120fps.jpg")

# 4. OVERLAY & PIXEL DENSITY CHECK
print(f"Binned Resolution: {binned_img.shape[1]}x{binned_img.shape[0]}")
print(f"High-Speed Resolution: {hs_img.shape[1]}x{hs_img.shape[0]}")

if binned_img.shape == hs_img.shape:
    difference = np.subtract(binned_img, hs_img)
    if not np.any(difference):
        print("The images are identical.")
    else:
        print("The images match in resolution but differ in pixel data.")
else:
    print("MISMATCH: The pixel densities/resolutions do not match.")
    print("They cannot be overlaid 1:1 without rescaling.")
