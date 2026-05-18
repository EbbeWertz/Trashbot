#!/usr/bin/env python3
import cv2
import numpy as np
import os
import glob

# ============================================================
# CONFIG
# ============================================================
DATASET_DIR = "."
LEFT_INTRINSIC_DIR = os.path.join(DATASET_DIR, "left")
RIGHT_INTRINSIC_DIR = os.path.join(DATASET_DIR, "right")
OUTPUT_DIR = "calibration_output"
DEBUG_VIZ_DIR = os.path.join(OUTPUT_DIR, "debug_viz")

BOARD_SIZE = (8, 5)
SQUARE_SIZE = 28.714  # mm

# Thresholds
MIN_SHARPNESS = 15.0 # Relaxed
MIN_BOARD_COVERAGE = 0.00001 # Significantly lowered to prevent false rejects
CALIB_CRITERIA = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 200, 1e-9)

# ============================================================
# UTILITIES
# ============================================================
def ensure_dir(path):
    os.makedirs(path, exist_ok=True)

def list_images(folder):
    exts = ["*.png", "*.jpg", "*.jpeg", "*.bmp", "*.tif"]
    files = []
    for ext in exts:
        files.extend(glob.glob(os.path.join(folder, ext)))
    return sorted(files)

# ============================================================
# PROCESSING
# ============================================================
def process_intrinsic(image_dir, camera_name):
    print(f"\n--- PROCESSING {camera_name} ---")
    image_paths = list_images(image_dir)
   
    objp = np.zeros((BOARD_SIZE[0] * BOARD_SIZE[1], 3), np.float32)
    objp[:, :2] = np.mgrid[0:BOARD_SIZE[0], 0:BOARD_SIZE[1]].T.reshape(-1, 2) * SQUARE_SIZE

    valid_objpoints = []
    valid_imgpoints = []
    processed_data = [] # Store images and corner data for later viz
    image_shape = None

    for path in image_paths:
        img = cv2.imread(path)
        if img is None: continue
        if image_shape is None: image_shape = img.shape[:2][::-1]

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        found, corners = cv2.findChessboardCorners(gray, BOARD_SIZE,
                         cv2.CALIB_CB_ADAPTIVE_THRESH + cv2.CALIB_CB_NORMALIZE_IMAGE)

        status = "REJECT_NOT_FOUND"
        if found:
            cv2.cornerSubPix(gray, corners, (5, 5), (-1, -1),
                             (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.1))
           
            # Area calculation
            area = cv2.contourArea(corners)
            coverage = area / (img.shape[0] * img.shape[1])
           
            if coverage < MIN_BOARD_COVERAGE:
                status = f"REJECT_SMALL_{coverage:.5f}"
            else:
                status = "OK"
                valid_objpoints.append(objp)
                valid_imgpoints.append(corners)

        processed_data.append({
            "path": path,
            "img": img,
            "corners": corners if found else None,
            "status": status,
            "found": found
        })
        print(f"[{status}] {os.path.basename(path)}")

    if len(valid_objpoints) < 5:
        print(f"Error: Not enough points for {camera_name}")
        return

    # Run Calibration
    flags = cv2.CALIB_RATIONAL_MODEL + cv2.CALIB_ZERO_TANGENT_DIST
    rms, K, D, _, _ = cv2.calibrateCamera(
        valid_objpoints, valid_imgpoints, image_shape, None, None,
        flags=flags, criteria=CALIB_CRITERIA
    )

    # Save Visual Debug Gallery
    cam_viz_dir = os.path.join(DEBUG_VIZ_DIR, camera_name)
    ensure_dir(cam_viz_dir)
   
    print(f"Generating debug images for {camera_name}...")
    for data in processed_data:
        # Left side: Detection
        canvas_l = data["img"].copy()
        if data["found"]:
            cv2.drawChessboardCorners(canvas_l, BOARD_SIZE, data["corners"], data["found"])
       
        # Right side: Undistortion (Only if calibration succeeded)
        canvas_r = cv2.undistort(data["img"], K, D)
       
        # Add text overlay
        cv2.putText(canvas_l, f"Status: {data['status']}", (30, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 255), 3)

        # Stack and Save
        hstack = np.hstack((canvas_l, canvas_r))
        fname = f"{data['status']}_{os.path.basename(data['path'])}"
        cv2.imwrite(os.path.join(cam_viz_dir, fname), hstack)

        params_file = os.path.join(OUTPUT_DIR, f"{camera_name.lower()}_intrinsics.yml")
        fs = cv2.FileStorage(params_file, cv2.FILE_STORAGE_WRITE)
        fs.write("image_width", image_shape[0])
        fs.write("image_height", image_shape[1])
        fs.write("camera_matrix", K)
        fs.write("distortion_coefficients", D)
        fs.write("rms_error", rms)
        fs.release()

        print(f"Saved calibration parameters to: {params_file}")

    return rms

def main():
    ensure_dir(OUTPUT_DIR)
    ensure_dir(DEBUG_VIZ_DIR)
   
    rms_l = process_intrinsic(LEFT_INTRINSIC_DIR, "LEFT")
    rms_r = process_intrinsic(RIGHT_INTRINSIC_DIR, "RIGHT")

    print(f"\nDone! Inspect results in: {DEBUG_VIZ_DIR}")
    if rms_l: print(f"Left RMS: {rms_l:.4f}")
    if rms_r: print(f"Right RMS: {rms_r:.4f}")

if __name__ == "__main__":
    main()