import cv2, json, base64, asyncio, threading, os, shutil, time
from datetime import datetime
import numpy as np
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse, FileResponse
from picamera2 import Picamera2

app = FastAPI()

# --- CONFIG ---
#SENSOR_RES = (2304, 1296)
SENSOR_RES = (1536, 864)
PROXY_RES = (640, 360)
SESSION_DIR = f"calib_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
BOARD_SIZE = (8, 5)

# Folder Setup
FOLDERS = [
    "left", 
    "right", 
    "extrinsic/left", 
    "extrinsic/right"
]
for f in FOLDERS:
    os.makedirs(os.path.join(SESSION_DIR, f), exist_ok=True)

class CaptureSystem:
    def __init__(self):
        self.cams = {0: None, 1: None}
        self.latest_canvas = None
        self.lock = threading.Lock()
        self.running = True
        self.last_raw = (None, None)
        self.counts = {"left": 0, "right": 0, "extrinsic": 0}

    def start(self):
        for port in [0, 1]:
            cam = Picamera2(port)
            config = cam.create_preview_configuration(main={"format": "RGB888", "size": SENSOR_RES})
            cam.configure(config)
            cam.set_controls({"AfMode": 0, "LensPosition": 0.0, "Sharpness": 1.0})
            cam.start()
            self.cams[port] = cam
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        while self.running:
            raw0 = self.cams[0].capture_array()
            raw1 = self.cams[1].capture_array()
            
            p0 = cv2.cvtColor(cv2.resize(raw0, PROXY_RES), cv2.COLOR_RGB2BGR)
            p1 = cv2.cvtColor(cv2.resize(raw1, PROXY_RES), cv2.COLOR_RGB2BGR)
            
            # Simple detection overlays for visual confirmation
            for img in [p0, p1]:
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                ret, _ = cv2.findChessboardCorners(gray, BOARD_SIZE, None)
                if ret:
                    cv2.circle(img, (20, 20), 10, (0, 255, 0), -1)

            with self.lock:
                self.last_raw = (raw0, raw1)
                self.latest_canvas = np.hstack((p0, p1))

    def save_target(self, mode):
        with self.lock:
            l_rgb, r_rgb = self.last_raw
            if l_rgb is None: return
            
            self.counts[mode] += 1
            idx = self.counts[mode]
            
            if mode == "left":
                path = os.path.join(SESSION_DIR, "left", f"intr_l_{idx:03d}.png")
                cv2.imwrite(path, cv2.cvtColor(l_rgb, cv2.COLOR_RGB2BGR))
            
            elif mode == "right":
                path = os.path.join(SESSION_DIR, "right", f"intr_r_{idx:03d}.png")
                cv2.imwrite(path, cv2.cvtColor(r_rgb, cv2.COLOR_RGB2BGR))
            
            elif mode == "extrinsic":
                lp = os.path.join(SESSION_DIR, "extrinsic/left", f"ext_l_{idx:03d}.png")
                rp = os.path.join(SESSION_DIR, "extrinsic/right", f"ext_r_{idx:03d}.png")
                cv2.imwrite(lp, cv2.cvtColor(l_rgb, cv2.COLOR_RGB2BGR))
                cv2.imwrite(rp, cv2.cvtColor(r_rgb, cv2.COLOR_RGB2BGR))

sys = CaptureSystem()

@app.on_event("startup")
async def startup(): sys.start()

@app.get("/", response_class=HTMLResponse)
async def index():
    return """
    <body style="background:#111; color:#eee; font-family:sans-serif; text-align:center; padding-top:20px;">
        <div style="display:flex; justify-content:center; gap:10px; margin-bottom:15px;">
            <button onclick="cap('left')" style="background:#444; color:white; padding:15px;">CAP LEFT (L)</button>
            <button onclick="cap('right')" style="background:#444; color:white; padding:15px;">CAP RIGHT (R)</button>
            <button onclick="cap('extrinsic')" style="background:#28a745; color:white; padding:15px; font-weight:bold;">CAP STATIONARY PAIR (Space)</button>
        </div>
        <img id="stream" style="width:95vw; border:2px solid #333;">
        <div style="margin-top:15px;">
            Left: <span id="c_left">0</span> | Right: <span id="c_right">0</span> | Extrinsic Pairs: <span id="c_ext">0</span>
        </div>
        <script>
            const ws = new WebSocket(`ws://${location.host}/ws`);
            ws.onmessage = (e) => {
                const d = JSON.parse(e.data);
                document.getElementById('stream').src = "data:image/jpeg;base64," + d.img;
                document.getElementById('c_left').innerText = d.counts.left;
                document.getElementById('c_right').innerText = d.counts.right;
                document.getElementById('c_ext').innerText = d.counts.extrinsic;
            };
            const cap = (m) => ws.send(m);
            window.onkeydown = (e) => {
                if(e.code==='Space') cap('extrinsic');
                if(e.key==='l' || e.key==='L') cap('left');
                if(e.key==='r' || e.key==='R') cap('right');
            };
        </script>
    </body>
    """

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    while True:
        try:
            try:
                msg = await asyncio.wait_for(websocket.receive_text(), 0.005)
                if msg in ["left", "right", "extrinsic"]: sys.save_target(msg)
            except: pass
            
            with sys.lock:
                if sys.latest_canvas is not None:
                    _, buf = cv2.imencode('.jpg', sys.latest_canvas, [cv2.IMWRITE_JPEG_QUALITY, 70])
                    await websocket.send_json({
                        "img": base64.b64encode(buf).decode(),
                        "counts": sys.counts
                    })
            await asyncio.sleep(0.04)
        except: break

@app.get("/download")
async def download():
    shutil.make_archive("calibration_session", 'zip', SESSION_DIR)
    return FileResponse("calibration_session.zip", filename="calibration_session.zip")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
