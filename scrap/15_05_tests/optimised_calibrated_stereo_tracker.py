import asyncio
import base64
import time
import cv2
import numpy as np
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from picamera2 import Picamera2
from threading import Thread, Lock

# --- Calibration Data (Parsed from YML) ---
K1 = np.array([[1005.699745, 0., 1155.73808], [0., 1005.745235, 656.365347], [0., 0., 1.]])
D1 = np.array([-1.341524, 1.018328, 0., 0., -0.101967, -1.310691, 0.925111, -0.036968, 0,0,0,0,0,0])
K2 = np.array([[1007.351873, 0., 1152.24860], [0., 1007.222105, 649.429583], [0., 0., 1.]])
D2 = np.array([-1.568596, 1.159263, 0., 0., -0.190936, -1.557134, 1.111121, -0.153165, 0,0,0,0,0,0])
R1 = np.array([[0.998861, -0.011242, -0.046368], [0.010971, 0.999921, -0.006086], [0.046433, 0.005571, 0.998905]])
R2 = np.array([[0.999152, -0.007935, -0.040378], [0.008170, 0.999950, 0.005666], [0.040331, -0.005991, 0.999168]])
P1 = np.array([[1006.48367, 0., 1288.3914, 0.], [0., 1006.48367, 657.8783, 0.], [0., 0., 1., 0.]])
P2 = np.array([[1006.48367, 0., 1288.3914, -45203.3487], [0., 1006.48367, 657.8783, 0.], [0., 0., 1., 0.]])
Q = np.array([[1., 0., 0., -1288.3914], [0., 1., 0., -657.8783], [0., 0., 0., 1006.4836], [0., 0., 0.022265, 0.]])

CAMERA_MODE = "lo-res"

SENSOR_RES = (2304, 1296) if CAMERA_MODE == "hi-res" else (1536, 864)
CAM_FPS = 55.0 if CAMERA_MODE == "hi-res" else 120.0
STREAM_RES = (640, 360)
CAM_SWAP = True

app = FastAPI()

class StereoTracker:
    def __init__(self):
        self.cam_l = Picamera2(1 if CAM_SWAP else 0)
        self.cam_r = Picamera2(0 if CAM_SWAP else 1)
        self.lock = Lock()
        self.raw_frame_l = None
        self.encoded = {"l": "", "r": ""}
        self.coords_3d = [0, 0, 0]
        self.fps = 0
        self.process_load_pct = 0.0
        
        # HSV State
        self.center_hsv = np.array([60, 150, 150], dtype=np.uint8) 
        self.h_margin, self.sv_margin = 15, 60
        self.lower_color = np.array([45, 90, 90], dtype=np.uint8)
        self.upper_color = np.array([75, 255, 255], dtype=np.uint8)

    def setup(self):
        # Let the hardware ISP do the heavy lifting: configure a lores stream
        config_l = self.cam_l.create_video_configuration(
            main={"format": "RGB888", "size": SENSOR_RES},
            lores={"format": "RGB888", "size": STREAM_RES}
        )
        config_r = self.cam_r.create_video_configuration(
            main={"format": "RGB888", "size": SENSOR_RES},
            lores={"format": "RGB888", "size": STREAM_RES}
        )
        
        for cam, config in zip([self.cam_l, self.cam_r], [config_l, config_r]):
            cam.configure(config)
            cam.set_controls({
                "LensPosition": 0,
                "AfMode": 0,
                "FrameRate": CAM_FPS
            })
            cam.start()

    def _update_bounds(self):
        # 1. Cast the uint8 numpy values to standard Python ints 
        # to prevent underflow wrap-around during subtraction
        h = int(self.center_hsv[0])
        s = int(self.center_hsv[1])
        v = int(self.center_hsv[2])

        # 2. Calculate bounds and explicitly lock the array type to uint8
        self.lower_color = np.array([
            max(0, h - self.h_margin), 
            max(40, s - self.sv_margin), 
            max(40, v - self.sv_margin)
        ], dtype=np.uint8)
        
        self.upper_color = np.array([
            min(180, h + self.h_margin), 
            255, 
            255
        ], dtype=np.uint8)

    def sample_color(self, x_norm, y_norm):
        with self.lock:
            if self.raw_frame_l is None: return
            img = self.raw_frame_l.copy()
        h, w = img.shape[:2]
        px_x, px_y = int(np.clip(x_norm * w, 0, w-1)), int(np.clip(y_norm * h, 0, h-1))
        hsv_px = cv2.cvtColor(np.uint8([[img[px_y, px_x]]]), cv2.COLOR_RGB2HSV)[0][0]
        with self.lock:
            self.center_hsv = hsv_px
            self._update_bounds()

    def rectify_point(self, pt, K, D, R, P):
        """Rectifies a single (x, y) point mathematically"""
        pts_array = np.array([[pt]], dtype=np.float32)
        rectified = cv2.undistortPoints(pts_array, K, D, R=R, P=P)
        return rectified[0][0][0], rectified[0][0][1]

    def update_loop(self):
        prev_time = time.time()
        expected_frame_time = 1.0 / CAM_FPS
        
        while True:
            # 1. Capture Hardware-Downscaled Frames
            # "lores" bypasses CPU resizing entirely
            img_l_small = self.cam_l.capture_array("lores")
            img_r_small = self.cam_r.capture_array("lores")

            process_start = time.time()

            with self.lock:
                self.raw_frame_l = img_l_small.copy()
            
            # 2. Tracking on Low-Res
            targets = []
            for img in [img_l_small, img_r_small]:
                mask = cv2.inRange(cv2.cvtColor(img, cv2.COLOR_RGB2HSV), self.lower_color, self.upper_color)
                conts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                if conts:
                    c = max(conts, key=cv2.contourArea)
                    (x, y), r = cv2.minEnclosingCircle(c)
                    targets.append((x, y, r))
                else: 
                    targets.append(None)

            # 3. Point Rectification & 3D Triangulation
            if targets[0] and targets[1]:
                # Scale coordinates back up to SENSOR_RES for accurate calibration matrix math
                scale_x, scale_y = SENSOR_RES[0] / STREAM_RES[0], SENSOR_RES[1] / STREAM_RES[1]
                
                raw_x_l, raw_y_l = targets[0][0] * scale_x, targets[0][1] * scale_y
                raw_x_r, raw_y_r = targets[1][0] * scale_x, targets[1][1] * scale_y

                # Rectify ONLY the target center coordinates
                rect_x_l, rect_y_l = self.rectify_point((raw_x_l, raw_y_l), K1, D1, R1, P1)
                rect_x_r, rect_y_r = self.rectify_point((raw_x_r, raw_y_r), K2, D2, R2, P2)

                disparity = rect_x_l - rect_x_r
                
                if disparity > 0:
                    vec = np.array([rect_x_l, rect_y_l, disparity, 1.0])
                    coords = Q @ vec
                    coords /= coords[3]
                    self.coords_3d = [coords[0], -coords[1], coords[2]]

            # 4. Draw & Encode (Drawing on unrectified lores stream for visualization)
            for i, (img, target) in enumerate([(img_l_small, targets[0]), (img_r_small, targets[1])]):
                if target:
                    cv2.circle(img, (int(target[0]), int(target[1])), int(target[2]), (0, 255, 0), 4)
                
                _, buf = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 70])
                self.encoded["l" if i == 0 else "r"] = base64.b64encode(buf).decode('utf-8')

            # Performance calculations
            now = time.time()
            process_time = now - process_start
            self.process_load_pct = (process_time / expected_frame_time) * 100
            
            self.fps = 1 / (now - prev_time)
            prev_time = now

tracker = StereoTracker()

@app.on_event("startup")
async def startup():
    tracker.setup()
    Thread(target=tracker.update_loop, daemon=True).start()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_json(), timeout=0.01)
                if data.get("action") == "select_color":
                    tracker.sample_color(data["x"], data["y"])
                elif data.get("action") == "set_margins":
                    tracker.h_margin, tracker.sv_margin = int(data["h"]), int(data["sv"])
                    tracker._update_bounds()
            except asyncio.TimeoutError:
                pass
            
            await websocket.send_json({
                "l": tracker.encoded["l"], "r": tracker.encoded["r"],
                "pos": tracker.coords_3d, 
                "fps": round(tracker.fps, 1),
                "load": round(tracker.process_load_pct, 1)
            })
            await asyncio.sleep(0.04)
    except WebSocketDisconnect: pass

@app.get("/")
async def get():
    return HTMLResponse("""
    <!DOCTYPE html><html><head>
    <style>
        body { background: #0b0b0b; color: #4caf50; font-family: monospace; text-align: center; margin: 0; }
        .controls { background: #1a1a1a; padding: 10px; display: flex; justify-content: center; align-items: center; gap: 20px; border-bottom: 1px solid #333; flex-wrap: wrap;}
        .flex { display: flex; justify-content: center; padding: 10px; gap: 10px; }
        img { width: 48vw; max-width: 640px; cursor: crosshair; border: 1px solid #222; }
        #info { font-size: 20px; padding: 10px; color: #fff; }
        .metric { font-weight: bold; background: #222; padding: 5px 10px; border-radius: 4px;}
    </style></head><body>
        <div class="controls">
            <div>H-Margin: <input type="range" id="h" min="1" max="50" value="15" oninput="sync()"></div>
            <div>S/V-Margin: <input type="range" id="sv" min="5" max="150" value="60" oninput="sync()"></div>
            <span class="metric" id="fps_val">FPS: 0</span>
            <span class="metric" id="load_val">Load: 0%</span>
        </div>
        <div id="info">X: 0 | Y: 0 | Z: 0</div>
        <div class="flex">
            <img id="img_l" onclick="pick(event)">
            <img id="img_r">
        </div>
        <script>
            const ws = new WebSocket(`ws://${window.location.host}/ws`);
            function sync() {
                ws.send(JSON.stringify({action: "set_margins", h: document.getElementById('h').value, sv: document.getElementById('sv').value}));
            }
            function pick(e) {
                const rect = e.target.getBoundingClientRect();
                ws.send(JSON.stringify({action: "select_color", x: (e.clientX - rect.left)/rect.width, y: (e.clientY - rect.top)/rect.height}));
            }
            ws.onmessage = (e) => {
                const d = JSON.parse(e.data);
                document.getElementById('img_l').src = "data:image/jpeg;base64," + d.l;
                document.getElementById('img_r').src = "data:image/jpeg;base64," + d.r;
                document.getElementById('fps_val').innerText = "FPS: " + d.fps;
                document.getElementById('load_val').innerText = "Load: " + d.load + "%";
                
                // Color load metric based on usage
                const loadEl = document.getElementById('load_val');
                loadEl.style.color = d.load > 85 ? '#ff4444' : (d.load > 60 ? '#ffbb33' : '#4caf50');

                document.getElementById('info').innerText = `X: ${Math.round(d.pos[0])} | Y: ${Math.round(d.pos[1])} | Z: ${Math.round(d.pos[2])}`;
            };
        </script></body></html>
    """)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)