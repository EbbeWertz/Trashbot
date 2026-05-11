import time
import cv2
import threading
import base64
import asyncio
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
from picamera2 import Picamera2

app = FastAPI()

class MaxSpeedStitcher:
    def __init__(self):
        self.cam0 = Picamera2(0)
        self.cam1 = Picamera2(1)

        # FORCE FULL FOV: 
        # We define a 'sensor' mode that uses the 2x2 binned resolution
        # For Camera Module 3, this is 2304x1296.
        # Then we set 'main' to the small size for the Python loop.
        conf0 = self.cam0.create_preview_configuration(
            main={"format": "RGB888", "size": (320, 180)},
            sensor={"output_size": (2304, 1296)} 
        )
        conf1 = self.cam1.create_preview_configuration(
            main={"format": "RGB888", "size": (320, 180)},
            sensor={"output_size": (2304, 1296)}
        )
        
        self.cam0.configure(conf0)
        self.cam1.configure(conf1)

        # ADJUST LIGHTING & SPEED
        # AnalogueGain 16.0 is the max for Module 3; this will brighten the image
        # but add 'grain' (noise).
        self.cam0.set_controls({
            "FrameRate": 120.0,
            "ExposureTime": 8000, # Max allowed for 120fps (1/125 sec)
            "AnalogueGain": 16.0  
        })
        self.cam1.set_controls({
            "FrameRate": 120.0,
            "ExposureTime": 8000,
            "AnalogueGain": 16.0
        })

        self.cam0.start()
        self.cam1.start()

        self.stitched_data = None
        self.fps = 0
        self.lock = threading.Lock()

    def update_loop(self):
        frame_count = 0
        start_time = time.time()
        
        while True:
            # High-speed capture
            f0 = self.cam0.capture_array()
            f1 = self.cam1.capture_array()

            # Optimization 3: Horizontal concatenation of small frames is fast
            combined = cv2.hconcat([f0, f1])

            # Performance Benchmarking
            frame_count += 1
            now = time.time()
            if now - start_time >= 1.0:
                self.fps = frame_count / (now - start_time)
                frame_count = 0
                start_time = now

            cv2.putText(combined, f"ISP FPS: {self.fps:.1f}", (20, 40),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

            # Optimization 4: Encode to JPEG once per frame
            _, buf = cv2.imencode('.jpg', combined, [cv2.IMWRITE_JPEG_QUALITY, 60])
            b64_frame = base64.b64encode(buf).decode('utf-8')

            with self.lock:
                self.stitched_data = b64_frame

streamer = MaxSpeedStitcher()

@app.on_event("startup")
async def startup():
    threading.Thread(target=streamer.update_loop, daemon=True).start()

@app.get("/")
async def get():
    return HTMLResponse(html_content)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            # Optimization 5: Send via WebSocket to avoid HTTP stream overhead
            with streamer.lock:
                data = streamer.stitched_data
            
            if data:
                await websocket.send_text(data)
            
            # Allow micro-sleep for event loop
            await asyncio.sleep(0.005) 
    except Exception as e:
        print(f"Connection closed: {e}")

html_content = """
<!DOCTYPE html>
<html>
    <body style="background: #000; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0;">
        <img id="stream" style="width: 90vw; border: 2px solid #333;">
        <script>
            const img = document.getElementById('stream');
            const ws = new WebSocket(`ws://${window.location.host}/ws`);
            ws.onmessage = (event) => {
                img.src = 'data:image/jpeg;base64,' + event.data;
            };
        </script>
    </body>
</html>
"""

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="error")