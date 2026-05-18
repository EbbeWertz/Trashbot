import cv2
import numpy as np
import glob
import os

# --- CONFIG ---
BOARD_SIZE = (8, 5) 
SQUARE_SIZE = 28.8 # mm
EXPECTED_WIDTH = (BOARD_SIZE[0] - 1) * SQUARE_SIZE   # 201.6 mm
EXPECTED_HEIGHT = (BOARD_SIZE[1] - 1) * SQUARE_SIZE  # 115.2 mm
NPZ_PATH = "stereo_params_v2.npz"
EXTRINSIC_DIR = "./extrinsic"

def profile_dimensions():
    data = np.load(NPZ_PATH)
    R1, R2, P1, P2, Q, _, _ = cv2.stereoRectify(
        data['mtx_l'], data['dist_l'], data['mtx_r'], data['dist_r'], 
        (2304, 1296), data['R'], data['T']
    )

    left_imgs = sorted(glob.glob(os.path.join(EXTRINSIC_DIR, "left/*.png")))
    right_imgs = sorted(glob.glob(os.path.join(EXTRINSIC_DIR, "right/*.png")))

    width_records = []
    height_records = []

    print(f"{'Image':<15} | {'Width (mm)':<10} | {'Height (mm)':<10} | {'Error %'}")
    print("-" * 55)

    for lp, rp in zip(left_imgs, right_imgs):
        img_l = cv2.imread(lp, 0)
        img_r = cv2.imread(rp, 0)
        
        ret_l, c_l = cv2.findChessboardCorners(img_l, BOARD_SIZE, None)
        ret_r, c_r = cv2.findChessboardCorners(img_r, BOARD_SIZE, None)

        if ret_l and ret_r:
            crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 100, 1e-4)
            pts_l = cv2.cornerSubPix(img_l, c_l, (11, 11), (-1, -1), crit)
            pts_r = cv2.cornerSubPix(img_r, c_r, (11, 11), (-1, -1), crit)

            pts_l_rect = cv2.undistortPoints(pts_l, data['mtx_l'], data['dist_l'], R=R1, P=P1)
            pts_r_rect = cv2.undistortPoints(pts_r, data['mtx_r'], data['dist_r'], R=R2, P=P2)

            p4d = cv2.triangulatePoints(P1, P2, pts_l_rect, pts_r_rect)
            p3d = (p4d[:3] / p4d[3]).T

            # Measure Width (Top Row) and Height (Left Column)
            w = np.linalg.norm(p3d[BOARD_SIZE[0]-1] - p3d[0])
            h = np.linalg.norm(p3d[(BOARD_SIZE[1]-1)*BOARD_SIZE[0]] - p3d[0])
            
            error_pct = ((w / EXPECTED_WIDTH) - 1) * 100
            width_records.append(w)
            height_records.append(h)
            
            print(f"{os.path.basename(lp):<15} | {w:<10.2f} | {h:<10.2f} | {error_pct:+.2f}%")

    avg_w = np.mean(width_records)
    correction_factor = EXPECTED_WIDTH / avg_w

    print("\n" + "="*30)
    print(f"FINAL ANALYSIS")
    print(f"Avg Measured Width:  {avg_w:.2f} mm")
    print(f"Expected Width:      {EXPECTED_WIDTH:.2f} mm")
    print(f"SCALE CORRECTION:    {correction_factor:.4f}")
    print("="*30)
    print("TIP: If correction is consistent (e.g. always 0.85),")
    print("multiply your Baseline (T) in the NPZ by this factor.")

if __name__ == "__main__":
    profile_dimensions()