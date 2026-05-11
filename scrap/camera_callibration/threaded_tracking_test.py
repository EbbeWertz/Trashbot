import cv2, json, base64, asyncio, time, threading
import numpy as np
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
from picamera2 import Picamera2

app = FastAPI()

# --- LOAD CALIBRATION ---
with open("stereo_params_640.json", "r") as f:
    calib = json.load(f)

mtxL, distL = np.array(calib["camera_matrix_l"]), np.array(calib["dist_l"])
mtxR, distR = np.array(calib["camera_matrix_r"]), np.array(calib["dist_r"])
R, T = np.array(calib["R"]), np.array(calib["T"])
W, H = calib["resolution"]


R0, R1, P0, P1, Q, _, _ = cv2.stereoRectify(mtxL, distL, mtxR, distR, (W, H), R, T, alpha=0)

class CameraStream:
    def __init__(self, index):
        self.picam = Picamera2(index)
        config = self.picam.create_preview_configuration(main={"format": "RGB888", "size": (640, 360)})
        self.picam.configure(config)
        self.picam.set_controls({"FrameRate": 120.0, "ExposureTime": 8000}) # Short exposure to reduce motion blur
        self.frame = None
        self.running = False

    def start(self):
        self.picam.start()
        self.running = True
        self.thread = threading.Thread(target=self.update, daemon=True)
        self.thread.start()

    def update(self):
        while self.running:
            self.frame = self.picam.capture_array()

    def stop(self):
        self.running = False
        self.picam.stop()

camL = CameraStream(0)
camR = CameraStream(1)
camL.start()
camR.start()

# Pre-allocate kernels for morphology
kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))

def find_ball_high_quality(img):
    """Balanced tracking: High precision with low latency."""
    if img is None: return None
    
    # 1. Smoothing: Gaussian blur removes high-frequency noise/sensor grain
    blurred = cv2.GaussianBlur(img, (5, 5), 0)
    hsv = cv2.cvtColor(blurred, cv2.COLOR_RGB2HSV)
    
    # 2. Thresholding
    mask = cv2.inRange(hsv, np.array([35, 70, 50]), np.array([90, 255, 255]))
    
    # 3. Morphology: Close small holes and remove tiny "salt and pepper" noise
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    
    # 4. Contour Analysis
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if cnts:
        c = max(cnts, key=cv2.contourArea)
        area = cv2.contourArea(c)
        if area > 15:
            # MinEnclosingCircle is more stable than Moments for high-speed projectiles
            ((x, y), radius) = cv2.minEnclosingCircle(c)
            return (int(x), int(y))
    return None

@app.websocket("/ws_track")
async def track_websocket(websocket: WebSocket):
    await websocket.accept()
    start_time = time.time()
    batch = []
    last_send_time = time.time()
    frame_count = 0
    SMOOTHING_ALPHA = 0.3 
    last_z = None
    try:
        while True:
            rawL, rawR = camL.frame, camR.frame
            if rawL is None or rawR is None:
                await asyncio.sleep(0.001)
                continue

            t = time.time() - start_time
            
            # Tracking with restored quality
            pL = find_ball_high_quality(rawL)
            pR = find_ball_high_quality(rawR)

            point_data = {"t": round(t, 4)}
            if pL and pR:
                # Precise Point Rectification
                ptsL = cv2.undistortPoints(np.array([[pL]], dtype=np.float32), mtxL, distL, R=R0, P=P0)
                ptsR = cv2.undistortPoints(np.array([[pR]], dtype=np.float32), mtxR, distR, R=R1, P=P1)
                uxL, uyL = ptsL[0][0]
                uxR, _ = ptsR[0][0]
                
                disp = uxL - uxR
                
                if disp > 0.5:
                    vec = np.array([uxL, uyL, disp, 1.0])
                    coords = Q @ vec
                    raw_z = float(coords[2] / coords[3])
                    
                    # --- EXPONENTIAL MOVING AVERAGE ---
                    if last_z is None:
                        last_z = raw_z
                    else:
                        # EMA Formula: Z_smooth = (α * Z_raw) + ((1 - α) * Z_prev)
                        last_z = (SMOOTHING_ALPHA * raw_z) + ((1 - SMOOTHING_ALPHA) * last_z)
                    
                    point_data["z"] = round(last_z, 1)
                
                point_data["xy"] = [round((pL[0]+pR[0])/2 - 320, 1), round((pL[1]+pR[1])/2 - 180, 1)]
            
            batch.append(point_data)
            frame_count += 1

            now = time.time()
            if now - last_send_time > 0.033: # Flush at 30Hz
                payload = {"pts": batch}
                
                if frame_count % 10 == 0: # Preview at ~12fps
                    # Slightly better preview quality (320px)
                    small = cv2.resize(rawL, (320, 180), interpolation=cv2.INTER_LINEAR)
                    _, buf = cv2.imencode('.jpg', small, [cv2.IMWRITE_JPEG_QUALITY, 40])
                    payload["img"] = base64.b64encode(buf).decode('utf-8')
                
                try:
                    await asyncio.wait_for(websocket.send_json(payload), timeout=0.01)
                    batch = []
                    last_send_time = now
                except:
                    batch = []
                    last_send_time = now

            await asyncio.sleep(0)

    except Exception as e:
        print(f"WS Error: {e}")

@app.get("/")
async def get_page():
    return HTMLResponse(html_content)

html_content = """
<!DOCTYPE html>
<html>
<head>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <style>
        body { background: #111; color: #fff; margin: 0; font-family: sans-serif; display: flex; height: 100vh; overflow: hidden; }
        #sidebar { width: 320px; padding: 15px; border-right: 1px solid #333; background: #000;}
        #visuals { flex-grow: 1; display: flex; flex-direction: column; }
        .graph { flex: 1; }
        img { width: 100%; border-radius: 4px; border: 1px solid #444; }
        .stat { font-family: monospace; font-size: 1.4em; color: #0f0; margin: 15px 0; }
    </style>
</head>
<body>
    <div id="sidebar">
        <h3>HD_TRACK_V6 (120Hz)</h3>
        <img id="view" src="">
        <div class="stat">Z: <span id="z_val">---</span> mm</div>
        <button onclick="location.reload()" style="width:100%; padding:10px; cursor:pointer;">RESET CHARTS</button>
    </div>
    <div id="visuals">
        <div id="h_g" class="graph"></div>
        <div id="d_g" class="graph"></div>
    </div>
    <script>
        const ws = new WebSocket("ws://" + window.location.host + "/ws_track");
        const MAX_POINTS = 500;
        
        const layout = {
            paper_bgcolor: '#111', plot_bgcolor: '#000',
            font: {color: '#fff', size: 10},
            margin: {t:40, r:20, b:40, l:60}
        };

        Plotly.newPlot('h_g', [{x:[], y:[], mode:'lines+markers', marker:{size:3}, line:{color:'#0ff', width:1}}], 
            {...layout, title:'HEIGHT (Z) vs TIME', yaxis:{range:[0, 2000], autorange:false}}, {displayModeBar:false});
        
        Plotly.newPlot('d_g', [{x:[], y:[], mode:'markers', marker:{color:'#fff', size:3}}], 
            {...layout, title:'DIRECTION (AVG XY)', xaxis:{range:[-320,320]}, yaxis:{range:[-180,180]}}, {displayModeBar:false});

        ws.onmessage = (e) => {
            const data = JSON.parse(e.data);
            if (data.img) document.getElementById('view').src = "data:image/jpeg;base64," + data.img;
            
            let t_arr = [], z_arr = [], x_arr = [], y_arr = [];
            data.pts.forEach(p => {
                if (p.z) { t_arr.push(p.t); z_arr.push(p.z); }
                if (p.xy) { x_arr.push(p.xy[0]); y_arr.push(p.xy[1]); }
            });

            if (t_arr.length) {
                Plotly.extendTraces('h_g', {x:[t_arr], y:[z_arr]}, [0], MAX_POINTS);
                document.getElementById('z_val').innerText = z_arr[z_arr.length-1].toFixed(0);
            }
            if (x_arr.length) Plotly.extendTraces('d_g', {x:[x_arr], y:[y_arr]}, [0], MAX_POINTS);
        };
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="error")