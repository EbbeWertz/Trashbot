import cv2, json, base64, asyncio, time
import numpy as np
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
from picamera2 import Picamera2

app = FastAPI()

# --- LOAD CALIBRATION & PRECOMPUTE Q ---
try:
    with open("stereo_params_640.json", "r") as f:
        calib = json.load(f)
except FileNotFoundError:
    print("Error: stereo_params_640.json not found.")
    exit()

mtxL, distL = np.array(calib["camera_matrix_l"]), np.array(calib["dist_l"])
mtxR, distR = np.array(calib["camera_matrix_r"]), np.array(calib["dist_r"])
R, T = np.array(calib["R"]), np.array(calib["T"])
W, H = calib["resolution"]

# Generate Rectification Transforms and the missing Q matrix
# alpha=0 zooms to remove black borders; alpha=1 keeps all pixels
R0, R1, P0, P1, Q, _, _ = cv2.stereoRectify(mtxL, distL, mtxR, distR, (W, H), R, T, alpha=0)

def find_ball_raw(img_rgb):
    """Detects ball on raw frames for maximum speed."""
    hsv = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2HSV)
    # Masking for green target
    mask = cv2.inRange(hsv, np.array([35, 70, 50]), np.array([90, 255, 255]))
    
    # Fast noise reduction
    mask = cv2.erode(mask, None, iterations=1)
    mask = cv2.dilate(mask, None, iterations=1)
    
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if cnts:
        c = max(cnts, key=cv2.contourArea)
        if cv2.contourArea(c) > 10:
            M = cv2.moments(c)
            if M["m00"] > 0:
                return (int(M["m10"] / M["m00"]), int(M["m01"] / M["m00"])), int(np.sqrt(cv2.contourArea(c)/np.pi))
    return None, 0

@app.websocket("/ws_track")
async def track_websocket(websocket: WebSocket):
    await websocket.accept()
    
    # Initialize Cameras for high framerate
    cams = [Picamera2(0), Picamera2(1)]
    for c in cams:
        config = c.create_preview_configuration(main={"format": "RGB888", "size": (640, 360)})
        c.configure(config)
        c.set_controls({"FrameRate": 60.0}) # Request 60 FPS
        c.start()

    start_time = time.time()
    frame_count = 0

    try:
        while True:
            t = time.time() - start_time
            frame_count += 1
            
            # Capture Raw Frames
            rawL = cams[0].capture_array()
            rawR = cams[1].capture_array()
            
            # Detect on Raw
            coordL, radL = find_ball_raw(rawL)
            coordR, _ = find_ball_raw(rawR)

            data_out = {"time": t, "avg_pix": None, "height_mm": None, "image": None}

            if coordL and coordR:
                # --- POINT RECTIFICATION ONLY ---
                # This maps raw pixels to the rectified 3D-ready coordinate space
                ptsL = cv2.undistortPoints(np.array([[coordL]], dtype=np.float32), mtxL, distL, R=R0, P=P0)
                ptsR = cv2.undistortPoints(np.array([[coordR]], dtype=np.float32), mtxR, distR, R=R1, P=P1)
                
                uxL, uyL = ptsL[0][0]
                uxR, uyR = ptsR[0][0]

                # Calculate Disparity in rectified space
                disparity = uxL - uxR
                
                if disparity > 0.1:
                    # Triangulate using Q
                    vec = np.array([uxL, uyL, disparity, 1.0])
                    coords_3d = Q @ vec
                    coords_3d /= coords_3d[3]
                    data_out["height_mm"] = float(coords_3d[2])

                # Ground Direction (Averaged Pixel Space for stability)
                data_out["avg_pix"] = [float((coordL[0] + coordR[0])/2 - 320), 
                                       float((coordL[1] + coordR[1])/2 - 180)]

            # --- OPTIMIZED PREVIEW ---
            # Only send image every 4th frame (~15fps) to save WebSocket bandwidth
            if frame_count % 4 == 0:
                # Resize to 320px for web display efficiency
                small = cv2.resize(rawL, (320, 180), interpolation=cv2.INTER_NEAREST)
                view_frame = cv2.cvtColor(small, cv2.COLOR_RGB2BGR)
                
                if coordL:
                    # Scale coordinates for the 320px preview
                    cv2.circle(view_frame, (int(coordL[0]/2), int(coordL[1]/2)), int(radL/2), (0, 255, 0), 2)
                
                _, buf = cv2.imencode('.jpg', view_frame, [cv2.IMWRITE_JPEG_QUALITY, 35])
                data_out["image"] = base64.b64encode(buf).decode('utf-8')

            await websocket.send_json(data_out)
            await asyncio.sleep(0) # Yield control without delay

    except Exception as e:
        print(f"Loop Error: {e}")
    finally:
        for c in cams: c.stop()

@app.get("/")
async def get_page():
    return HTMLResponse(html_content)

html_content = """
<!DOCTYPE html>
<html>
<head>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <style>
        body { background: #111; color: white; margin: 0; font-family: sans-serif; display: flex; height: 100vh; overflow: hidden;}
        #sidebar { width: 320px; padding: 15px; border-right: 1px solid #333; display: flex; flex-direction: column; }
        #visuals { flex-grow: 1; display: flex; flex-direction: column; }
        .graph { flex: 1; }
        img { width: 100%; border-radius: 8px; border: 1px solid #444; }
        .stat { font-family: monospace; font-size: 1.2em; color: #0f0; margin: 10px 0; }
    </style>
</head>
<body>
    <div id="sidebar">
        <h3>High-Speed Tracker</h3>
        <img id="view" src="">
        <div class="stat">Z: <span id="z_val">0</span> mm</div>
        <button onclick="location.reload()" style="padding:10px; cursor:pointer; background:#333; color:white; border:none;">Reset Charts</button>
    </div>
    <div id="visuals">
        <div id="height_chart" class="graph"></div>
        <div id="direction_chart" class="graph"></div>
    </div>
    <script>
        const ws = new WebSocket("ws://" + window.location.host + "/ws_track");
        const MAX_TRAIL = 100;

        Plotly.newPlot('height_chart', [{
            x: [], y: [], mode: 'markers+lines', name: 'Height', 
            marker: {color: 'cyan', size: 4}, line: {color: 'rgba(0,255,255,0.2)'}
        }], { 
            title: 'Height (Z) over Time', paper_bgcolor: '#111', plot_bgcolor: '#111', font: {color: '#fff'},
            xaxis: {title: 'Time (s)'}, yaxis: {title: 'mm', range: [0, 2000], autorange: false},
            margin: {t:40, r:20, b:40, l:60}
        });

        Plotly.newPlot('direction_chart', [{
            x: [], y: [], mode: 'markers+lines', name: '2D Path', 
            marker: {color: 'white', size: 4}, line: {color: 'rgba(255,255,255,0.2)'}
        }], { 
            title: 'Top-Down Direction (Avg Pixels)', paper_bgcolor: '#111', plot_bgcolor: '#111', font: {color: '#fff'},
            xaxis: {title: 'X', range: [-320, 320]}, yaxis: {title: 'Y', range: [-180, 180]},
            margin: {t:40, r:20, b:40, l:60}
        });

        ws.onmessage = (e) => {
            const data = JSON.parse(e.data);
            if (data.image) document.getElementById('view').src = "data:image/jpeg;base64," + data.image;
            if (data.height_mm !== null) {
                document.getElementById('z_val').innerText = data.height_mm.toFixed(0);
                Plotly.extendTraces('height_chart', { x: [[data.time]], y: [[data.height_mm]] }, [0], MAX_TRAIL);
            }
            if (data.avg_pix !== null) {
                Plotly.extendTraces('direction_chart', { x: [[data.avg_pix[0]]], y: [[data.avg_pix[1]]] }, [0], MAX_TRAIL);
            }
        };
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)