import cv2
import json
import base64
import asyncio
import numpy as np
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
from picamera2 import Picamera2

app = FastAPI()

# --- CONFIGURATION ---
CHESSBOARD_SIZE = (8, 5)
SQUARE_SIZE = 30.0  # mm
TARGET_RES = (2304, 1296) # Working resolution
CRITERIA = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)

class StereoCalibrationSession:
    def __init__(self):
        self.cams = {0: None, 1: None}
        self.objpoints = []  
        self.imgpointsL = [] 
        self.imgpointsR = [] 
        self.maps0 = None
        self.maps1 = None
        self.rectified = False

    def start_cameras(self):
        for port in [0, 1]:
            cam = Picamera2(port)
            # Capture at 2x2 binned resolution for full FOV and best quality
            config = cam.create_preview_configuration(main={"format": "RGB888", "size": (2304, 1296)})
            cam.configure(config)
            # Manual Focus (approx 0.5m to 1m distance)
            cam.set_controls({"AfMode": 0, "LensPosition": 2.0}) 
            cam.start()
            self.cams[port] = cam

    def capture_and_resize(self):
        """Captures full FOV and resizes to target immediately."""
        raw0 = self.cams[0].capture_array()
        raw1 = self.cams[1].capture_array()
        # Resize to 640x360
        img0 = cv2.resize(raw0, TARGET_RES, interpolation=cv2.INTER_AREA)
        img1 = cv2.resize(raw1, TARGET_RES, interpolation=cv2.INTER_AREA)
        return img0, img1

    def process_frame(self, img0, img1, save=False):
        gray0 = cv2.cvtColor(img0, cv2.COLOR_RGB2GRAY)
        gray1 = cv2.cvtColor(img1, cv2.COLOR_RGB2GRAY)

        ret0, corn0 = cv2.findChessboardCorners(gray0, CHESSBOARD_SIZE, None)
        ret1, corn1 = cv2.findChessboardCorners(gray1, CHESSBOARD_SIZE, None)

        found_both = ret0 and ret1

        if found_both and save:
            objp = np.zeros((CHESSBOARD_SIZE[0] * CHESSBOARD_SIZE[1], 3), np.float32)
            objp[:, :2] = np.mgrid[0:CHESSBOARD_SIZE[0], 0:CHESSBOARD_SIZE[1]].T.reshape(-1, 2) * SQUARE_SIZE
            
            # Sub-pixel refinement on the downscaled image
            corn0 = cv2.cornerSubPix(gray0, corn0, (5, 5), (-1, -1), CRITERIA)
            corn1 = cv2.cornerSubPix(gray1, corn1, (5, 5), (-1, -1), CRITERIA)
            
            self.objpoints.append(objp)
            self.imgpointsL.append(corn0)
            self.imgpointsR.append(corn1)

        return found_both, corn0 if ret0 else None, corn1 if ret1 else None

    def run_calibration(self):
        if len(self.objpoints) < 10:
            return {"error": "Need at least 10 captures for stability."}

        w, h = TARGET_RES

        # 1. Intrinsics (640x360 scale)
        ret0, mtx0, dist0, _, _ = cv2.calibrateCamera(self.objpoints, self.imgpointsL, (w, h), None, None)
        ret1, mtx1, dist1, _, _ = cv2.calibrateCamera(self.objpoints, self.imgpointsR, (w, h), None, None)

        # 2. Stereo Extrinsics
        flags = cv2.CALIB_FIX_INTRINSIC
        retS, m0, d0, m1, d1, R, T, E, F = cv2.stereoCalibrate(
            self.objpoints, self.imgpointsL, self.imgpointsR,
            mtx0, dist0, mtx1, dist1, (w, h), criteria=CRITERIA, flags=flags
        )

        # 3. Rectification Maps
        R0, R1, P0, P1, Q, _, _ = cv2.stereoRectify(m0, d0, m1, d1, (w, h), R, T)
        self.maps0 = cv2.initUndistortRectifyMap(m0, d0, R0, P0, (w, h), cv2.CV_32FC1)
        self.maps1 = cv2.initUndistortRectifyMap(m1, d1, R1, P1, (w, h), cv2.CV_32FC1)
        self.rectified = True

        result = {
            "rms_error": retS,
            "resolution": TARGET_RES,
            "camera_matrix_l": m0.tolist(),
            "camera_matrix_r": m1.tolist(),
            "dist_l": d0.tolist(),
            "dist_r": d1.tolist(),
            "R": R.tolist(),
            "T": T.tolist()
        }
        with open("stereo_params_640.json", "w") as f:
            json.dump(result, f, indent=4)
        return result

session = StereoCalibrationSession()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    session.start_cameras()
    
    try:
        while True:
            try:
                msg = await asyncio.wait_for(websocket.receive_json(), timeout=0.005)
                action = msg.get("action")
                if action == "capture":
                    # Capture high res, resize to 640, then process
                    img0, img1 = session.capture_and_resize()
                    session.process_frame(img0, img1, save=True)
                elif action == "calibrate":
                    res = session.run_calibration()
                    await websocket.send_json({"type": "result", "data": res})
            except asyncio.TimeoutError:
                pass

            img0, img1 = session.capture_and_resize()
            found, c0, c1 = session.process_frame(img0, img1, save=False)

            if session.rectified:
                # Show the rectified "Stereo Test"
                rect0 = cv2.remap(img0, session.maps0[0], session.maps0[1], cv2.INTER_LINEAR)
                rect1 = cv2.remap(img1, session.maps1[0], session.maps1[1], cv2.INTER_LINEAR)
                canvas = np.hstack((rect0, rect1))
                # Draw epipolar lines
                for i in range(0, canvas.shape[0], 25):
                    cv2.line(canvas, (0, i), (canvas.shape[1], i), (0, 255, 0), 1)
            else:
                if c0 is not None: cv2.drawChessboardCorners(img0, CHESSBOARD_SIZE, c0, True)
                if c1 is not None: cv2.drawChessboardCorners(img1, CHESSBOARD_SIZE, c1, True)
                canvas = np.hstack((img0, img1))

            _, buffer = cv2.imencode('.jpg', cv2.cvtColor(canvas, cv2.COLOR_RGB2BGR))
            encoded = base64.b64encode(buffer).decode('utf-8')
            
            await websocket.send_json({
                "type": "stream", 
                "image": encoded, 
                "count": len(session.objpoints),
                "ready": found
            })
            await asyncio.sleep(0.01)
    except Exception as e:
        print(f"WS Error: {e}")

@app.get("/")
async def get_index():
    with open("page.html") as f:
        return HTMLResponse(content=f.read())

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)