import cv2
import numpy as np
import os
import glob

# --- CONFIG ---
BOARD_SIZE = (8, 5)
SQUARE_SIZE = 28.8 # mm
NPZ_PATH = "stereo_params_v2.npz" 
INPUT_DIR = "./extrinsic" 
OUTPUT_DIR = "./annotated_output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

def inspect_calibration():
    # 1. Load Params
    data = np.load(NPZ_PATH)
    mtx_l, dist_l = data['mtx_l'], data['dist_l']
    mtx_r, dist_r = data['mtx_r'], data['dist_r']
    R, T = data['R'], data['T']

    # 2. Get Rectification/Projection Matrices
    # We use these to transform raw pixel points into 3D space
    R1, R2, P1, P2, Q, _, _ = cv2.stereoRectify(
        mtx_l, dist_l, mtx_r, dist_r, (2304, 1296), R, T
    )

    left_imgs = sorted(glob.glob(os.path.join(INPUT_DIR, "left/*.png")))
    right_imgs = sorted(glob.glob(os.path.join(INPUT_DIR, "right/*.png")))

    for l_path, r_path in zip(left_imgs, right_imgs):
        img_l = cv2.imread(l_path)
        img_r = cv2.imread(r_path)
        gray_l = cv2.cvtColor(img_l, cv2.COLOR_BGR2GRAY)
        gray_r = cv2.cvtColor(img_r, cv2.COLOR_BGR2GRAY)

        ret_l, corners_l = cv2.findChessboardCorners(gray_l, BOARD_SIZE, None)
        ret_r, corners_r = cv2.findChessboardCorners(gray_r, BOARD_SIZE, None)

        if ret_l and ret_r:
            # Sub-pixel refinement for accuracy
            crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 100, 1e-4)
            pts_l = cv2.cornerSubPix(gray_l, corners_l, (11, 11), (-1, -1), crit)
            pts_r = cv2.cornerSubPix(gray_r, corners_r, (11, 11), (-1, -1), crit)

            # Undistort and Rectify points to the common coordinate system
            pts_l_rect = cv2.undistortPoints(pts_l, mtx_l, dist_l, R=R1, P=P1)
            pts_r_rect = cv2.undistortPoints(pts_r, mtx_r, dist_r, R=R2, P=P2)

            # Triangulate to 3D
            points_4d = cv2.triangulatePoints(P1, P2, pts_l_rect, pts_r_rect)
            points_3d = (points_4d[:3] / points_4d[3]).T / 1000.0  # Convert mm to Meters

            # Draw annotations on the Left Image
            for idx, pt in enumerate(points_3d):
                x, y, z = pt
                # Get the 2D pixel location for drawing
                px, py = pts_l[idx][0].astype(int)
                
                # Only annotate corners 0, 7, 32, 39 (the 4 edges) to keep it clean
                if idx in [0, BOARD_SIZE[0]-1, len(points_3d)-BOARD_SIZE[0], len(points_3d)-1]:
                    label = f"[{x:.3f}, {y:.3f}, {z:.3f}]m"
                    cv2.circle(img_l, (px, py), 5, (0, 255, 0), -1)
                    cv2.putText(img_l, label, (px + 10, py), 
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

            # Save result
            out_name = os.path.basename(l_path)
            cv2.imwrite(os.path.join(OUTPUT_DIR, out_name), img_l)
            print(f"Annotated {out_name}")

if __name__ == "__main__":
    inspect_calibration()