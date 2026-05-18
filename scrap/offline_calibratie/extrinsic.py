import cv2
import numpy as np
import glob
import os

# --- 1. Configuration ---
OUT_DIR = "stereo_debug"
os.makedirs(OUT_DIR, exist_ok=True)
CHECKERBOARD = (8, 5)        # 8x5 internal corners
SQUARE_SIZE = 28.714         # mm
MAX_RMS_THRESHOLD = 0.8      # Goal for final pass
IMAGE_EXT = "png"

def load_intrinsics(path):
    fs = cv2.FileStorage(path, cv2.FILE_STORAGE_READ)
    k = fs.getNode("camera_matrix").mat()
    d = fs.getNode("distortion_coefficients").mat()
    w = int(fs.getNode("image_width").real())
    h = int(fs.getNode("image_height").real())
    fs.release()
    return k, d, (w, h)

K1, D1, size = load_intrinsics('calibration_output/left_intrinsics.yml')
K2, D2, _ = load_intrinsics('calibration_output/right_intrinsics.yml')

# Setup 3D points
objp = np.zeros((CHECKERBOARD[0]*CHECKERBOARD[1], 3), np.float32)
objp[:, :2] = np.mgrid[0:CHECKERBOARD[0], 0:CHECKERBOARD[1]].T.reshape(-1, 2) * SQUARE_SIZE

all_obj, all_l, all_r, filenames = [], [], [], []
images_l = sorted(glob.glob(f'extrinsic/left/*.{IMAGE_EXT}'))
images_r = sorted(glob.glob(f'extrinsic/right/*.{IMAGE_EXT}'))

print(f"Detecting corners in {len(images_l)} pairs...")

# --- 2. Initial Detection & Sub-pixel Refinement ---
for fl, fr in zip(images_l, images_r):
    img_l = cv2.imread(fl)
    img_r = cv2.imread(fr)
    gray_l = cv2.cvtColor(img_l, cv2.COLOR_BGR2GRAY)
    gray_r = cv2.cvtColor(img_r, cv2.COLOR_BGR2GRAY)

    ret_l, corn_l = cv2.findChessboardCorners(gray_l, CHECKERBOARD, 
        cv2.CALIB_CB_ADAPTIVE_THRESH + cv2.CALIB_CB_NORMALIZE_IMAGE)
    ret_r, corn_r = cv2.findChessboardCorners(gray_r, CHECKERBOARD, 
        cv2.CALIB_CB_ADAPTIVE_THRESH + cv2.CALIB_CB_NORMALIZE_IMAGE)

    if ret_l and ret_r:
        term = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 100, 0.0001)
        corn_l = cv2.cornerSubPix(gray_l, corn_l, (11, 11), (-1, -1), term)
        corn_r = cv2.cornerSubPix(gray_r, corn_r, (11, 11), (-1, -1), term)
        
        all_obj.append(objp)
        all_l.append(corn_l)
        all_r.append(corn_r)
        filenames.append(os.path.basename(fl))

# --- 3. Pass 1: Global Calibration & Outlier Detection ---
flags = cv2.CALIB_FIX_INTRINSIC + cv2.CALIB_RATIONAL_MODEL
ret, K1, D1, K2, D2, R, T, E, F = cv2.stereoCalibrate(
    all_obj, all_l, all_r, K1, D1, K2, D2, size, flags=flags)

# Calculate error per image pair to find "bad" data
errors = []
for i in range(len(all_obj)):
    # Project points using current R and T to see which pair deviates most
    # We use a simple vertical disparity check as a proxy for error
    undist_l = cv2.undistortPoints(all_l[i], K1, D1, P=K1)
    undist_r = cv2.undistortPoints(all_r[i], K2, D2, P=K2)
    v_error = np.mean(np.abs(undist_l[:,0,1] - undist_r[:,0,1]))
    errors.append(v_error)

# Filter: Keep pairs with error below mean
mean_err = np.mean(errors)
idx_to_keep = [i for i, e in enumerate(errors) if e <= mean_err * 1.2]

print(f"Discarded {len(all_obj) - len(idx_to_keep)} noisy pairs.")
filt_obj = [all_obj[i] for i in idx_to_keep]
filt_l = [all_l[i] for i in idx_to_keep]
filt_r = [all_r[i] for i in idx_to_keep]

# --- 4. Pass 2: Final High-Precision Calibration ---
ret, K1, D1, K2, D2, R, T, E, F = cv2.stereoCalibrate(
    filt_obj, filt_l, filt_r, K1, D1, K2, D2, size, flags=flags)

print(f"Final Stereo RMS: {ret:.6f}")

# --- 5. Rectification & Debug Save ---
R1, R2, P1, P2, Q, _, _ = cv2.stereoRectify(K1, D1, K2, D2, size, R, T)
m1x, m1y = cv2.initUndistortRectifyMap(K1, D1, R1, P1, size, cv2.CV_32FC1)
m2x, m2y = cv2.initUndistortRectifyMap(K2, D2, R2, P2, size, cv2.CV_32FC1)

for i in range(len(filt_l)):
    img_l = cv2.remap(cv2.imread(images_l[idx_to_keep[i]]), m1x, m1y, cv2.INTER_LINEAR)
    img_r = cv2.remap(cv2.imread(images_r[idx_to_keep[i]]), m2x, m2y, cv2.INTER_LINEAR)
    canvas = np.hstack((img_l, img_r))
    # Draw scanlines every 30 pixels
    for y in range(0, canvas.shape[0], 30):
        cv2.line(canvas, (0, y), (canvas.shape[1], y), (0, 255, 0), 1)
    cv2.imwrite(f"{OUT_DIR}/refined_{i:02d}.png", canvas)

# --- 6. Save Parameters ---
fs = cv2.FileStorage("stereo_params_refined.yml", cv2.FILE_STORAGE_WRITE)
data = {"K1": K1, "D1": D1, "K2": K2, "D2": D2, "R": R, "T": T, "R1": R1, "R2": R2, "P1": P1, "P2": P2, "Q": Q, "RMS": ret}
for k, v in data.items(): fs.write(k, v)
fs.release()

print("Refined calibration saved to 'stereo_params_refined.yml'")