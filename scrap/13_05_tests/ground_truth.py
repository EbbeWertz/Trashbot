import cv2
import time
import threading
import numpy as np
import base64
import asyncio
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
from picamera2 import Picamera2

app = FastAPI()

class GroundTruthCamera:
    def __init__(self, index):
        self.picam = Picamera2(index)
        
        # GROUND TRUTH MODE: 2x2 Binning 
        # This provides the maximum possible FoV at 2K resolution.
        # Max FPS for this mode is typically 56-60 FPS.
        config = self.picam.create_video_configuration(
            main={"format": "YUV420", "size": (2304, 1296)},
        )
        self.picam.configure(config)
        
        self.picam.set_controls({
            "LensPosition": 2.5,
            "AfMode": 0,
            "FrameRate": 120.0 # Locked to 30 for stability in high-res
        })
        
        self.frame = None
        self.frame_count = 0
        self.new_frame_event = threading.Event()
        self.lock = threading.Lock()
        self.running = False

    def start(self):
        self.picam.start()
        self.running = True
        self.thread = threading.Thread(target=self.update, daemon=True)
        self.thread.start()

    def update(self):
        while self.running:
            raw_array = self.picam.capture_array()
            with self.lock:
                self.frame = raw_array
                self.frame_count += 1
            self.new_frame_event.set()

    def get_preview_jpeg(self):
        with self.lock:
            if self.frame is None:
                return None
            # Conversion from 2K YUV to BGR
            # We resize to the same preview size (480px width) to compare FoV fairly
            bgr = cv2.cvtColor(self.frame, cv2.COLOR_YUV420p2BGR)
            small = cv2.resize(bgr, (480, 270)) 
            _, buffer = cv2.imencode('.jpg', small, [cv2.IMWRITE_JPEG_QUALITY, 60])
            return base64.b64encode(buffer).decode('utf-8')

# Initialize Ground Truth Cameras
camL = GroundTruthCamera(0)
camR = GroundTruthCamera(1)
camL.start()
camR.start()

@app.websocket("/ws_groundtruth")
async def ground_truth_ws(websocket: WebSocket):
    await websocket.accept()
    last_fps_check = time.time()
    last_img_send = time.time()
    
    try:
        while True:
            if camL.new_frame_event.wait(timeout=0.1):
                camL.new_frame_event.clear()
                camR.new_frame_event.clear()
                
                now = time.time()
                payload = {}

                if now - last_fps_check >= 1.0:
                    payload["camL_fps"] = camL.frame_count
                    payload["camR_fps"] = camR.frame_count
                    camL.frame_count = 0
                    camR.frame_count = 0
                    last_fps_check = now

                # Preview at 10fps for Ground Truth comparison
                if now - last_img_send >= 0.1:
                    img_data = camL.get_preview_jpeg()
                    if img_data:
                        payload["img"] = img_data
                    last_img_send = now

                if payload:
                    await websocket.send_json(payload)
            
            await asyncio.sleep(0)
    except Exception:
        pass

@app.get("/")
async def get():
    return HTMLResponse("""
        <html>
            <head>
                <title>2x2 Ground Truth FoV</title>
                <style>
                    body { background:#000; color:#fff; font-family:sans-serif; text-align:center; }
                    .container { display:flex; flex-direction:column; align-items:center; padding:20px; }
                    img { width: 90%; max-width: 1000px; border: 2px solid #00ff00; }
                    .banner { background: #00ff00; color: #000; padding: 5px 20px; font-weight: bold; margin-bottom: 10px; }
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="banner">GROUND TRUTH MODE (2x2 BINNING)</div>
                    <div id="stats">L: -- FPS | R: -- FPS</div>
                    <img id="stream" src="">
                    <p>Current Resolution: 2304x1296 (Native Full Sensor)</p>
                    <p style="color: #aaa;">Compare this image to the 120FPS mode. The edges of the image should align perfectly.</p>
                </div>
                <script>
                    const ws = new WebSocket("ws://" + window.location.host + "/ws_groundtruth");
                    ws.onmessage = (event) => {
                        const data = JSON.parse(event.data);
                        if (data.camL_fps) document.getElementById('stats').innerHTML = "L: " + data.camL_fps + " FPS | R: " + data.camR_fps + " FPS";
                        if (data.img) document.getElementById('stream').src = "data:image/jpeg;base64," + data.img;
                    };
                </script>
            </body>
        </html>
    """)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)