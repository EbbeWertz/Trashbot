import time, cv2, threading, numpy as np
import asyncio, json
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
from picamera2 import Picamera2

app = FastAPI()

class UltraController:
    def __init__(self):
        self.capture_size = (2304, 1296)
        self.bg_size = (640, 360) 
        self.hsv_lower = np.array([35, 70, 50])  
        self.hsv_upper = np.array([90, 255, 255]) 
        
        self.cam = Picamera2(0)
        config = self.cam.create_video_configuration(main={"format": "RGB888", "size": self.capture_size})
        config["sensor_mode"] = 4
        config["queue_rate_limit"] = 0 
        self.cam.configure(config)
        
        # Initial Hardware State
        self.exposure = 8000
        self.gain = 8.0
        self.stream_fps = 24
        self.new_params = False # Reset to False
        
        self.cam.start()
        self.lock = threading.Lock()
        self.bg_data = None
        self.roi_data = None
        self.roi_meta = {"x": 0, "y": 0, "w": 0, "h": 0}
        self.smoothed_fps = 0.0
        self.tracking_active = False
        self.last_cx, self.last_cy = 320, 180

    def run_loop(self):
        last_time = time.time()
        while True:
            # CHECK FOR PARAMETER UPDATES HERE
            if self.new_params:
                try:
                    self.cam.set_controls({
                        "ExposureTime": self.exposure, 
                        "AnalogueGain": self.gain,
                        "FrameRate": 60.0
                    })
                    self.new_params = False
                except Exception as e:
                    print(f"Camera update failed: {e}")

            raw = self.cam.capture_array()
            
            now = time.time()
            dt = now - last_time
            if dt > 0:
                self.smoothed_fps = (0.1 * (1.0/dt)) + (0.9 * self.smoothed_fps)
            last_time = now

            # Use current bg_size (it might have changed from the UI)
            curr_bg_size = self.bg_size
            bg = cv2.resize(raw, curr_bg_size, interpolation=cv2.INTER_NEAREST)
            
            # Tracking logic
            result = None
            if self.tracking_active:
                win = int(curr_bg_size[0] * 0.15)
                y1, y2 = max(0, self.last_cy-win), min(curr_bg_size[1], self.last_cy+win)
                x1, x2 = max(0, self.last_cx-win), min(curr_bg_size[0], self.last_cx+win)
                
                # Check if window is valid
                if y2 > y1 and x2 > x1:
                    hsv = cv2.cvtColor(bg[y1:y2, x1:x2], cv2.COLOR_RGB2HSV)
                    mask = cv2.inRange(hsv, self.hsv_lower, self.hsv_upper)
                    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    if cnts:
                        c = max(cnts, key=cv2.contourArea)
                        if cv2.contourArea(c) > 10:
                            ((x, y), r) = cv2.minEnclosingCircle(c)
                            result = (x + x1, y + y1, r)

            if result is None:
                hsv = cv2.cvtColor(bg, cv2.COLOR_RGB2HSV)
                mask = cv2.inRange(hsv, self.hsv_lower, self.hsv_upper)
                cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                if cnts:
                    c = max(cnts, key=cv2.contourArea)
                    if cv2.contourArea(c) > 10:
                        ((x, y), r) = cv2.minEnclosingCircle(c)
                        result = (x, y, r)

            roi_buf = None
            if result:
                x, y, radius = result
                self.last_cx, self.last_cy = int(x), int(y)
                self.tracking_active = True
                scale_x, scale_y = 2304/curr_bg_size[0], 1296/curr_bg_size[1]
                cx, cy = int(x * scale_x), int(y * scale_y)
                r_px = int(radius * scale_x * 1.6) + 30
                y1, y2, x1, x2 = max(0, cy-r_px), min(1296, cy+r_px), max(0, cx-r_px), min(2304, cx+r_px)
                side = min(y2-y1, x2-x1)
                if side > 10:
                    _, r_buf = cv2.imencode('.jpg', raw[y1:y1+side, x1:x1+side], [cv2.IMWRITE_JPEG_QUALITY, 85])
                    roi_buf = r_buf.tobytes()
                    with self.lock:
                        self.roi_meta = {"x": (x1/2304)*100, "y": (y1/1296)*100, "w": (side/2304)*100, "h": (side/1296)*100}
            else: 
                self.tracking_active = False

            cv2.putText(bg, f"Hardware: {int(self.smoothed_fps)} FPS", (20, 40), 0, 0.7, (0, 255, 0), 2)
            _, b_buf = cv2.imencode('.jpg', bg, [cv2.IMWRITE_JPEG_QUALITY, 50])
            with self.lock:
                self.bg_data = b_buf.tobytes()
                self.roi_data = roi_buf

streamer = UltraController()

@app.on_event("startup")
async def start_logic():
    threading.Thread(target=streamer.run_loop, daemon=True).start()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            # 1. Listen for data (Non-blocking as possible)
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=0.01)
                m = json.loads(data)
                streamer.exposure = int(m['exp'])
                streamer.gain = float(m['gain'])
                streamer.stream_fps = int(m['fps'])
                res_val = int(m['res'])
                streamer.bg_size = (res_val, int(res_val * 9/16))
                streamer.new_params = True
            except asyncio.TimeoutError:
                pass 

            # 2. Send data
            with streamer.lock:
                if streamer.bg_data:
                    pkg = {
                        "meta": streamer.roi_meta, 
                        "bg": "data:image/jpeg;base64," + cv2.base64.b64encode(streamer.bg_data).decode(),
                        "roi": "data:image/jpeg;base64," + cv2.base64.b64encode(streamer.roi_data).decode() if streamer.roi_data else ""
                    }
                    await websocket.send_json(pkg)
            
            # Dynamic sleep based on stream_fps
            await asyncio.sleep(1.0 / streamer.stream_fps)
    except Exception as e:
        print(f"WebSocket Error: {e}")

@app.get("/")
async def get():
    return HTMLResponse("""
        <body style="background:#000; color:#eee; font-family:sans-serif; margin:0; overflow:hidden;">
            <div style="background:#1a1a1a; padding:10px; display:flex; flex-wrap:wrap; justify-content:center; gap:20px; font-size:13px; border-bottom:1px solid #333;">
                <span>Exp: <input type="range" id="exp" min="500" max="16000" value="8000"></span>
                <span>Gain: <input type="range" id="gain" min="1" max="16" step="0.5" value="8"></span>
                <span>Stream FPS: <input type="range" id="fps" min="5" max="60" value="24"> <b id="fps_v">24</b></span>
                <span>Preview Res: <select id="res"><option value="320">320p</option><option value="640" selected>640p</option><option value="960">960p</option></select></span>
            </div>
            <div id="container" style="position:relative; width:98vw; aspect-ratio: 16/9; margin: 10px auto; background:#111;">
                <img id="bg" style="width:100%; height:100%; image-rendering:pixelated; position:absolute; filter: brightness(0.7);">
                <img id="fovea" style="position:absolute; object-fit:cover; display:none; pointer-events:none; -webkit-mask-image: radial-gradient(circle, black 35%, transparent 75%); mask-image: radial-gradient(circle, black 35%, transparent 75%);">
            </div>
            <script>
                const bg = document.getElementById('bg'); const fov = document.getElementById('fovea');
                const ws = new WebSocket(`ws://${location.host}/ws`);
                
                const getParams = () => ({
                    exp: document.getElementById('exp').value,
                    gain: document.getElementById('gain').value,
                    fps: document.getElementById('fps').value,
                    res: document.getElementById('res').value
                });

                const sendParams = () => {
                    document.getElementById('fps_v').innerText = document.getElementById('fps').value;
                    if (ws.readyState === WebSocket.OPEN) {
                        ws.send(JSON.stringify(getParams()));
                    }
                };

                ['exp','gain','fps','res'].forEach(id => {
                    document.getElementById(id).addEventListener('input', sendParams);
                });

                ws.onmessage = (e) => {
                    const d = JSON.parse(e.data); 
                    bg.src = d.bg;
                    if (d.roi) { 
                        fov.src = d.roi; 
                        fov.style.display = 'block'; 
                        fov.style.left = d.meta.x + '%'; 
                        fov.style.top = d.meta.y + '%'; 
                        fov.style.width = d.meta.w + '%'; 
                        fov.style.height = d.meta.h + '%';
                    } else { 
                        fov.style.display = 'none'; 
                    }
                };
            </script>
        </body>
    """)

if __name__ == "__main__":
    import uvicorn; import base64 as b64; cv2.base64 = b64
    uvicorn.run(app, host="0.0.0.0", port=8000)