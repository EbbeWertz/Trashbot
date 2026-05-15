import time, cv2, threading, numpy as np
import asyncio, json, base64
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
from picamera2 import Picamera2

# --- CONFIGURATION ---
NPZ_PATH = "stereo_calibration.npz"

app = FastAPI()

class StereoFoveatedController:
    def __init__(self):
        # 1. Load Calibration
        try:
            data = np.load(NPZ_PATH)
            self.mtx_l = np.array(data['mtx_l'])
            self.mtx_r = np.array(data['mtx_r'])
            self.f_px = float(self.mtx_l[0, 0])
            self.baseline = float(np.linalg.norm(data['T']))
        except:
            self.mtx_l = np.array([[1000, 0, 1152], [0, 1000, 648], [0, 0, 1]])
            self.f_px, self.baseline = 1000.0, 60.0 

        self.capture_size = (2304, 1296)
        self.bg_size = (640, 360) 
        self.hsv_lower = np.array([35, 70, 50])  
        self.hsv_upper = np.array([90, 255, 255]) 
        
        # 2. Initialize Dual Cameras with Hardware Lock
        self.cam_l = Picamera2(0)
        self.cam_r = Picamera2(1)
        
        for cam in [self.cam_l, self.cam_r]:
            config = cam.create_video_configuration(main={"format": "RGB888", "size": self.capture_size})
            config["sensor_mode"] = 4
            cam.configure(config)
            # Apply fixed focus/calibration controls
            cam.set_controls({
                "AfMode": 0, 
                "LensPosition": 0.0, 
                "Sharpness": 1.0,
                "FrameRate": 60.0
            })
            cam.start()

        self.lock = threading.Lock()
        self.bg_data = None
        self.roi_data = None
        self.roi_meta = {"x": 0, "y": 0, "w": 0, "h": 0}
        self.coords_3d = {"x": 0, "y": 0, "z": 0, "d": 0, "t": 0}
        self.start_time = time.time()

    def get_object_point(self, frame, search_roi=None):
        if frame is None: return None, None
        if search_roi:
            x1, y1, x2, y2 = search_roi
            y1, y2, x1, x2 = int(y1), int(y2), int(x1), int(x2)
            work_img = frame[y1:y2, x1:x2]
        else:
            work_img, x1, y1 = frame, 0, 0

        if work_img.size == 0: return None, None
        hsv = cv2.cvtColor(work_img, cv2.COLOR_RGB2HSV)
        mask = cv2.inRange(hsv, self.hsv_lower, self.hsv_upper)
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        if cnts:
            c = max(cnts, key=cv2.contourArea)
            if cv2.contourArea(c) > 15:
                M = cv2.moments(c)
                if M["m00"] != 0:
                    return (int(M["m10"]/M["m00"])+x1, int(M["m01"]/M["m00"])+y1), cv2.boundingRect(c)
        return None, None

    def run_loop(self):
        while True:
            # High-speed capture request
            raw_l = self.cam_l.capture_array()
            raw_r = self.cam_r.capture_array()

            p_l, bbox = self.get_object_point(raw_l)
            r_buf_bytes = None

            if p_l:
                # Optimized search window on right cam
                search_y1, search_y2 = max(0, p_l[1]-40), min(1296, p_l[1]+40)
                p_r, _ = self.get_object_point(raw_r, (0, search_y1, 2304, search_y2))
                
                if p_r:
                    # Triangulation
                    disp = max(0.1, abs(p_l[0] - p_r[0]))
                    z = (self.f_px * self.baseline) / disp
                    x = (p_l[0] - self.mtx_l[0, 2]) * z / self.f_px
                    y = (p_l[1] - self.mtx_l[1, 2]) * z / self.f_px
                    with self.lock:
                        self.coords_3d = {"x":round(x,1), "y":round(y,1), "z":round(z,1), "t":round(time.time()-self.start_time, 2)}

                # ROI Slice for Fovea
                bx, by, bw, bh = bbox
                y1, y2, x1, x2 = max(0, by-50), min(1296, by+bh+50), max(0, bx-50), min(2304, bx+bw+50)
                side = min(y2-y1, x2-x1)
                if side > 10:
                    _, rb = cv2.imencode('.jpg', raw_l[y1:y1+side, x1:x1+side], [cv2.IMWRITE_JPEG_QUALITY, 70])
                    r_buf_bytes = rb.tobytes()
                    with self.lock:
                        self.roi_meta = {"x":(x1/2304)*100, "y":(y1/1296)*100, "w":(side/2304)*100, "h":(side/1296)*100}

            # Faster resize (NEAREST) for preview
            bg_small = cv2.resize(raw_l, self.bg_size, interpolation=cv2.INTER_NEAREST)
            _, bb = cv2.imencode('.jpg', bg_small, [cv2.IMWRITE_JPEG_QUALITY, 40])
            
            with self.lock:
                self.bg_data = bb.tobytes()
                self.roi_data = r_buf_bytes

streamer = StereoFoveatedController()

@app.on_event("startup")
async def start_logic():
    threading.Thread(target=streamer.run_loop, daemon=True).start()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            with streamer.lock:
                if streamer.bg_data:
                    pkg = {
                        "meta": streamer.roi_meta, "coords": streamer.coords_3d,
                        "bg": "data:image/jpeg;base64," + base64.b64encode(streamer.bg_data).decode(),
                        "roi": "data:image/jpeg;base64," + (base64.b64encode(streamer.roi_data).decode() if streamer.roi_data else "")
                    }
                    await websocket.send_json(pkg)
            await asyncio.sleep(0.01) # Approx 100Hz UI refresh
    except: pass

@app.get("/")
async def get():
    return HTMLResponse("""
    <html>
    <head>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <style>
            body { background:#000; color:#eee; font-family:monospace; margin:0; display:flex; flex-direction:column; height:100vh; overflow:hidden; }
            #top { height: 40%; position:relative; background:#000; display:flex; justify-content:center; border-bottom:1px solid #333; }
            #bottom { height: 60%; display:flex; flex-direction:column; gap:2px; padding:5px; background:#111; }
            .chart-row { flex:1; display:flex; gap:5px; }
            .chart-container { flex:1; background:#1a1a1a; border-radius:4px; padding:2px; position:relative; }
            #bg { height:100%; object-fit:contain; }
            #fovea { position:absolute; border: 1px solid #0f0; border-radius:50%; pointer-events:none; }
            .stat { position:absolute; top:5px; left:5px; background:rgba(0,0,0,0.8); padding:5px; font-size:10px; z-index:10; border:1px solid #444; }
        </style>
    </head>
    <body>
        <div id="top">
            <div class="stat" id="stat">INIT...</div>
            <img id="bg"><img id="fovea">
        </div>
        <div id="bottom">
            <div class="chart-row"><div class="chart-container"><canvas id="c_x"></canvas></div></div>
            <div class="chart-row"><div class="chart-container"><canvas id="c_y"></canvas></div></div>
            <div class="chart-row"><div class="chart-container"><canvas id="c_z"></canvas></div></div>
        </div>
        <script>
            const ws = new WebSocket(`ws://${location.host}/ws`);
            const createChart = (id, label, color, minV, maxV) => new Chart(document.getElementById(id), {
                type: 'line',
                data: { datasets: [{ label: label, data: [], borderColor: color, borderWidth: 1, pointRadius: 0, fill: false, tension: 0.1 }] },
                options: { 
                    responsive: true, maintainAspectRatio: false, animation: false,
                    scales: { 
                        x: { type: 'linear', display: false }, 
                        y: { min: minV, max: maxV, grid: {color:'#222'}, ticks: {font:{size:8}, color:color} } 
                    },
                    plugins: { legend: { display:false } }
                }
            });

            const chartX = createChart('c_x', 'X', '#0f0', -1000, 1000);
            const chartY = createChart('c_y', 'Y', '#0cf', -1000, 1000);
            const chartZ = createChart('c_z', 'Z', '#f36', 0, 1500);

            ws.onmessage = (e) => {
                const d = JSON.parse(e.data);
                document.getElementById('bg').src = d.bg;
                if(d.roi) {
                    const f = document.getElementById('fovea');
                    f.src = d.roi; f.style.display='block';
                    f.style.left=d.meta.x+'%'; f.style.top=d.meta.y+'%';
                    f.style.width=d.meta.w+'%'; f.style.height=d.meta.h+'%';
                }
                const {x, y, z, t} = d.coords;
                document.getElementById('stat').innerText = `T: ${t}s | X: ${x} | Y: ${y} | Z: ${z}`;

                const up = (chart, val) => {
                    chart.data.datasets[0].data.push({x: t, y: val});
                    if(chart.data.datasets[0].data.length > 150) chart.data.datasets[0].data.shift();
                    chart.update('none');
                };
                up(chartX, x); up(chartY, -y); up(chartZ, z);
            };
        </script>
    </body>
    </html>
    """)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")