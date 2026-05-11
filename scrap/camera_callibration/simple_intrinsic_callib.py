import cv2
import json
import base64
import asyncio
import numpy as np
from pathlib import Path
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
from picamera2 import Picamera2

app = FastAPI()

# --- CONFIGURATION ---
CHESSBOARD_SIZE = (8, 5)  
SQUARE_SIZE = 27.0       

objp = np.zeros((CHESSBOARD_SIZE[0] * CHESSBOARD_SIZE[1], 3), np.float32)
objp[:, :2] = np.mgrid[0:CHESSBOARD_SIZE[0], 0:CHESSBOARD_SIZE[1]].T.reshape(-1, 2)
objp *= SQUARE_SIZE

# Define the 3D points for a cube on the center 2x2 squares
# We place it roughly in the middle of our 8x5 grid
CUBE_START = 3 
s = SQUARE_SIZE * 2 # Cube is 2 squares wide
cube_points = np.float32([
    [CUBE_START*SQUARE_SIZE, CUBE_START*SQUARE_SIZE, 0],
    [(CUBE_START+2)*SQUARE_SIZE, CUBE_START*SQUARE_SIZE, 0],
    [(CUBE_START+2)*SQUARE_SIZE, (CUBE_START+2)*SQUARE_SIZE, 0],
    [CUBE_START*SQUARE_SIZE, (CUBE_START+2)*SQUARE_SIZE, 0],
    [CUBE_START*SQUARE_SIZE, CUBE_START*SQUARE_SIZE, -s],
    [(CUBE_START+2)*SQUARE_SIZE, CUBE_START*SQUARE_SIZE, -s],
    [(CUBE_START+2)*SQUARE_SIZE, (CUBE_START+2)*SQUARE_SIZE, -s],
    [CUBE_START*SQUARE_SIZE, (CUBE_START+2)*SQUARE_SIZE, -s]
])

class CalibrationSession:
    def __init__(self):
        self.picam2 = None
        self.serial = ""
        self.objpoints = [] 
        self.imgpoints = [] 
        self.current_frame = None
        # Active Calibration Data
        self.mtx = None
        self.dist = None
        self.calibrated = False

    def start_camera(self, port, serial):
        if self.picam2:
            self.picam2.stop()
            self.picam2.close()
        self.serial = serial
        self.objpoints = []
        self.imgpoints = []
        self.calibrated = False # Reset for new session
        
        self.picam2 = Picamera2(port)
        config = self.picam2.create_preview_configuration(main={"format": "RGB888", "size": (640, 480)})
        self.picam2.configure(config)
        self.picam2.start()

    def calibrate(self):
        if len(self.objpoints) < 5:
            return {"error": "Need at least 5-10 captures."}
        
        h, w = self.current_frame.shape[:2]
        ret, mtx, dist, rvecs, tvecs = cv2.calibrateCamera(
            self.objpoints, self.imgpoints, (w, h), None, None
        )
        self.mtx = mtx
        self.dist = dist
        self.calibrated = True
        
        result = {
            "serial": self.serial,
            "camera_matrix": mtx.tolist(),
            "dist_coeff": dist.tolist(),
            "reprojection_error": float(ret)
        }
        with open(f"calib_{self.serial}.json", "w") as f:
            json.dump(result, f, indent=4)
        return result

    def draw_cube(self, img, corners):
        # Solve for the pose of the board
        ret, rvec, tvec = cv2.solvePnP(objp, corners, self.mtx, self.dist)
        if ret:
            # Project 3D points to image plane
            imgpts, _ = cv2.projectPoints(cube_points, rvec, tvec, self.mtx, self.dist)
            imgpts = np.int32(imgpts).reshape(-1, 2)
            
            # Draw ground floor in green
            img = cv2.drawContours(img, [imgpts[:4]], -1, (0, 255, 0), 3)
            # Draw pillars in blue
            for i, j in zip(range(4), range(4, 8)):
                img = cv2.line(img, tuple(imgpts[i]), tuple(imgpts[j]), (255, 0, 0), 3)
            # Draw top floor in red
            img = cv2.drawContours(img, [imgpts[4:]], -1, (0, 0, 255), 3)
        return img

session = CalibrationSession()

@app.get("/")
async def get():
    return HTMLResponse(html_content)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            try:
                msg = await asyncio.wait_for(websocket.receive_json(), timeout=0.01)
                action = msg.get("action")
                if action == "init":
                    session.start_camera(int(msg["port"]), msg["serial"])
                elif action == "finish":
                    res = session.calibrate()
                    await websocket.send_json({"type": "result", "data": res})
            except asyncio.TimeoutError:
                action = None

            if session.picam2:
                frame = session.picam2.capture_array()
                session.current_frame = frame
                gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
                ret, corners = cv2.findChessboardCorners(gray, CHESSBOARD_SIZE, None)
                
                display_frame = frame.copy()
                
                if ret:
                    # Logic for live cube overlay if already calibrated
                    if session.calibrated:
                        display_frame = session.draw_cube(display_frame, corners)
                    else:
                        cv2.drawChessboardCorners(display_frame, CHESSBOARD_SIZE, corners, ret)

                    # Handle capture command
                    if action == "capture":
                        session.objpoints.append(objp)
                        session.imgpoints.append(corners)

                _, buffer = cv2.imencode('.jpg', cv2.cvtColor(display_frame, cv2.COLOR_RGB2BGR))
                encoded = base64.b64encode(buffer).decode('utf-8')
                await websocket.send_json({
                    "type": "stream", 
                    "image": encoded, 
                    "count": len(session.objpoints),
                    "found": bool(ret),
                    "calibrated": session.calibrated
                })
            await asyncio.sleep(0.01)
    except Exception as e:
        print(f"WS Error: {e}")

# (HTML content remains largely the same, I've added a 'Status' indicator)
html_content = """
<!DOCTYPE html>
<html>
<head>
    <title>AR Calibration</title>
    <style>
        body { font-family: sans-serif; background: #1a1a1a; color: white; text-align: center; }
        .container { display: flex; flex-direction: column; align-items: center; gap: 10px; }
        #preview { width: 640px; height: 480px; border: 5px solid #444; border-radius: 8px;}
        .controls { background: #333; padding: 15px; border-radius: 10px; margin-bottom: 10px;}
        button { padding: 12px 24px; cursor: pointer; border: none; border-radius: 5px; font-weight: bold; margin: 5px;}
        .btn-cap { background: #2ecc71; color: white; }
        .btn-fin { background: #e67e22; color: white; }
        pre { text-align: left; background: #000; padding: 15px; width: 600px; border-radius: 5px; color: #0f0;}
    </style>
</head>
<body>
    <h1>Camera Calibration & AR Check</h1>
    <div class="container">
        <div class="controls">
            Port: <input type="number" id="port" value="0" style="width: 40px;">
            Serial: <input type="text" id="serial" placeholder="SN-12345">
            <button onclick="initCam()">Start Session</button>
        </div>
        
        <img id="preview" src="">
        <div id="status_bar" style="margin: 10px; font-size: 1.2em;">Captures: 0</div>
        
        <div>
            <button class="btn-cap" onclick="capture()">CAPTURE FRAME</button>
            <button class="btn-fin" onclick="finish()">RUN CALIBRATION</button>
        </div>
        
        <pre id="output"></pre>
    </div>

    <script>
        var ws = new WebSocket("ws://" + window.location.host + "/ws");
        var preview = document.getElementById('preview');
        var status_bar = document.getElementById('status_bar');

        ws.onmessage = function(event) {
            var msg = JSON.parse(event.data);
            if (msg.type === "stream") {
                preview.src = "data:image/jpeg;base64," + msg.image;
                let mode = msg.calibrated ? " [AR MODE - Check Cube]" : " [CALIBRATION MODE]";
                status_bar.innerText = "Captures: " + msg.count + mode;
                preview.style.borderColor = msg.found ? "#2ecc71" : "#e74c3c";
            } else if (msg.type === "result") {
                document.getElementById('output').innerText = JSON.stringify(msg.data, null, 2);
            }
        };

        function initCam() {
            ws.send(JSON.stringify({action: "init", port: document.getElementById('port').value, serial: document.getElementById('serial').value}));
        }
        function capture() { ws.send(JSON.stringify({action: "capture"})); }
        function finish() { ws.send(JSON.stringify({action: "finish"})); }
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)