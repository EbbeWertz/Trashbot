import cv2
import numpy as np

# 1. Load your newly saved calibration data
fs = cv2.FileStorage("final/stereo_params_refined.yml", cv2.FILE_STORAGE_READ)
K1, D1 = fs.getNode("K1").mat(), fs.getNode("D1").mat()
K2, D2 = fs.getNode("K2").mat(), fs.getNode("D2").mat()
R1, P1 = fs.getNode("R1").mat(), fs.getNode("P1").mat()
R2, P2 = fs.getNode("R2").mat(), fs.getNode("P2").mat()
Q = fs.getNode("Q").mat()
size = (int(K1[0,2]*2), int(K1[1,2]*2)) # Rough estimate of res
fs.release()

# 2. Setup SGBM (The "Dense" Matcher)
# These parameters are tuned for a 46mm baseline and 2K resolution
win_size = 5
stereo = cv2.StereoSGBM_create(
    minDisparity=0,
    numDisparities=16*10, # Must be divisible by 16. Adjust based on how close objects are.
    blockSize=win_size,
    uniquenessRatio=10,
    speckleWindowSize=100,
    speckleRange=2,
    disp12MaxDiff=1,
    P1=8 * 3 * win_size**2,
    P2=32 * 3 * win_size**2,
)

# 3. Load an image pair (Replace with your actual path)
imgL = cv2.imread('extrinsic/left/ext_r_001.png')
imgR = cv2.imread('extrinsic/right/ext_l_001.png')
h, w = imgL.shape[:2]

# 4. Rectify
map1x, map1y = cv2.initUndistortRectifyMap(K1, D1, R1, P1, (w, h), cv2.CV_32FC1)
map2x, map2y = cv2.initUndistortRectifyMap(K2, D2, R2, P2, (w, h), cv2.CV_32FC1)

rectL = cv2.remap(imgL, map1x, map1y, cv2.INTER_LINEAR)
rectR = cv2.remap(imgR, map2x, map2y, cv2.INTER_LINEAR)

# 5. Compute Disparity and 3D Coordinates
grayL = cv2.cvtColor(rectL, cv2.COLOR_BGR2GRAY)
grayR = cv2.cvtColor(rectR, cv2.COLOR_BGR2GRAY)
disparity = stereo.compute(grayL, grayR).astype(np.float32) / 16.0

# "Project to 3D" gives an (H, W, 3) array where each pixel is [X, Y, Z] in mm
points_3d = cv2.reprojectImageTo3D(disparity, Q)

# 6. Random Annotations
# Pick 5 random valid points to label
mask = disparity > disparity.min() # Ignore areas where matcher failed
coords = np.column_stack(np.where(mask))
random_indices = np.random.choice(len(coords), 5, replace=False)

for idx in random_indices:
    y, x = coords[idx]
    pt_3d = points_3d[y, x]
    
    # pt_3d[2] is the Z-distance (depth)
    text = f"Z: {pt_3d[2]/10:.1f}cm" # Convert mm to cm for readability
    cv2.circle(rectL, (x, y), 10, (0, 255, 0), -1)
    cv2.putText(rectL, text, (x + 15, y), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 0), 3)

# 7. Visualize
disp_vis = cv2.normalize(disparity, None, alpha=0, beta=255, norm_type=cv2.NORM_MINMAX, dtype=cv2.CV_8U)
disp_color = cv2.applyColorMap(disp_vis, cv2.COLORMAP_JET)

cv2.imshow("Annotated Left Image", cv2.resize(rectL, (1152, 648)))
cv2.imshow("Dense Disparity Map", cv2.resize(disp_color, (1152, 648)))
cv2.waitKey(0)