import numpy as np

def summarize_calib(file_path):
    try:
        data = np.load(file_path)
    except FileNotFoundError:
        print(f"Error: {file_path} not found.")
        return

    print(f"--- Calibration Summary: {file_path} ---")
    
    # 1. Intrinsics
    for side in ['l', 'r']:
        mtx = data[f'mtx_{side}']
        dist = data[f'dist_{side}']
        name = "Left" if side == 'l' else "Right"
        
        print(f"\n[{name} Camera]")
        print(f"  Focal Length:  fx={mtx[0,0]:.2f}, fy={mtx[1,1]:.2f} (px)")
        print(f"  Principal Pt:  cx={mtx[0,2]:.2f}, cy={mtx[1,2]:.2f}")
        print(f"  Distortion:    k1={dist[0][0]:.4f}, k2={dist[0][1]:.4f}, p1={dist[0][2]:.4f}, p2={dist[0][3]:.4f}")

    # 2. Extrinsics (Baseline)
    T = data['T']
    # Euclidean distance of the translation vector
    baseline_mm = np.linalg.norm(T)
    
    print("\n[Stereo Geometry]")
    print(f"  Translation (T) mm: x={T[0,0]:.3f}, y={T[1,0]:.3f}, z={T[2,0]:.3f}")
    print(f"  PHYSICAL BASELINE:  {baseline_mm:.3f} mm")
    
    # 3. Rotation
    R = data['R']
    # Convert rotation matrix to Euler angles (degrees) for human readability
    sy = np.sqrt(R[0,0] * R[0,0] + R[1,0] * R[1,0])
    singular = sy < 1e-6
    if not singular:
        x = np.arctan2(R[2,1], R[2,2])
        y = np.arctan2(-R[2,0], sy)
        z = np.arctan2(R[1,0], R[0,0])
    else:
        x = np.arctan2(-R[1,2], R[1,1])
        y = np.arctan2(-R[2,0], sy)
        z = 0
    
    print(f"  Relative Tilt:      pitch={np.degrees(x):.3f}°, yaw={np.degrees(y):.3f}°, roll={np.degrees(z):.3f}°")
    print("-" * 40)

if __name__ == "__main__":
    summarize_calib("params_1080p_Scaled.npz")