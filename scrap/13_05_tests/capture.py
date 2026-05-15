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

class HighSpeedCamera:
    def __init__(self, index):
        self.picam = Picamera2(index)
        
        # 1536x864 = Full FoV at 120fps via 3x3 binning
        config = self.picam.create_video_configuration(
            main={"format": "YUV420", "size": (1536, 864)},
        )
        self.picam.configure(config)
        
        self.picam.set_controls({
            "LensPosition": 2.5,
            "AfMode": 0,
            "ExposureTime": 4000,
            "FrameRate": 120.0
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
        """Converts YUV420 to a small BGR JPEG for web viewing."""
        with self.lock:
            if self.frame is None:
                return None
            # Extract the Y channel for a fast grayscale preview 
            # or convert full YUV to BGR. BGR is heavier.
            # Here we do a full BGR conversion + Resize for FOV verification
            bgr = cv2.cvtColor(self.frame, cv2.COLOR_YUV420p2BGR)
            small = cv2.resize(bgr, (480, 270)) 
            _, buffer = cv2.imencode('.jpg', small, [cv2.IMWRITE_JPEG_QUALITY, 50])
            return base64.b64encode(buffer).decode('utf-8')

# Initialize
camL = HighSpeedCamera(0)
camR = HighSpeedCamera(1)
camL.start()
camR.start()

@app.websocket("/ws_speedtest")
async def speed_test(websocket: WebSocket):
    await websocket.accept()
    last_fps_check = time.time()
    last_img_send = time.time()
    
    try:
        while True:
            # High speed logic gate
            if camL.new_frame_event.wait(timeout=0.1):
                camL.new_frame_event.clear()
                camR.new_frame_event.clear()
                
                now = time.time()
                payload = {}

                # 1. Update FPS Stats every second
                if now - last_fps_check >= 1.0:
                    payload["camL_fps"] = camL.frame_count
                    payload["camR_fps"] = camR.frame_count
                    camL.frame_count = 0
                    camR.frame_count = 0
                    last_fps_check = now

                # 2. Update Image Preview at ~15fps to verify FOV
                if now - last_img_send >= 0.066:
                    img_data = camL.get_preview_jpeg()
                    if img_data:
                        payload["img"] = img_data
                    last_img_send = now

                if payload:
                    await websocket.send_json(payload)
            
            await asyncio.sleep(0)
    except Exception as e:
        print(f"Websocket error: {e}")

@app.get("/")
async def get():
    return HTMLResponse("""
        <html>
            <head>
                <title>120FPS FOV Test</title>
                <style>
                    body { background:#111; color:#0f0; font-family:monospace; text-align:center; }
                    .container { display:flex; flex-direction:column; align-items:center; padding:20px; }
                    img { width: 80%; max-width: 800px; border: 2px solid #333; margin-top: 20px; }
                    .stats { font-size: 1.5em; margin: 20px; color: #fff; }
                </style>
            </head>
            <body>
                <div class="container">
                    <h1>DUAL CAMERA HIGH-SPEED FOV TEST</h1>
                    <div class="stats" id="stats">Waiting for hardware...</div>
                    <img id="stream" src="">
                    <p>Resolution: 1536x864 | Target: 120 FPS</p>
                </div>
                <script>
                    const ws = new WebSocket("ws://" + window.location.host + "/ws_speedtest");
                    const img = document.getElementById('stream');
                    const stats = document.getElementById('stats');
                    
                    ws.onmessage = (event) => {
                        const data = JSON.parse(event.data);
                        if (data.camL_fps) {
                            stats.innerHTML = "L: " + data.camL_fps + " FPS | R: " + data.camR_fps + " FPS";
                        }
                        if (data.img) {
                            img.src = "data:image/jpeg;base64," + data.img;
                        }
                    };
                </script>
            </body>
        </html>
    """)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)