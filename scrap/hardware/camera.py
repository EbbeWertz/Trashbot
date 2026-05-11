import cv2
import numpy as np
import asyncio
from fastapi import FastAPI, Response
from fastapi.responses import HTMLResponse, StreamingResponse
from picamera2 import Picamera2

app = FastAPI()

# 1. Setup Camera Configuration
# We use a lower resolution for high-speed processing
WIDTH, HEIGHT = 640, 480

picam_0 = Picamera2(0)
picam_1 = Picamera2(1)

# Configure Camera 0 (Left)
config0 = picam_0.create_video_configuration(main={"size": (WIDTH, HEIGHT), "format": "RGB888"})
# Configure Camera 1 (Right)
config1 = picam_1.create_video_configuration(main={"size": (WIDTH, HEIGHT), "format": "RGB888"})

# Apply configurations and start
picam_0.configure(config0)
picam_1.configure(config1)

# LOCK FOCUS: Set AF to Manual and Lens to Infinity (0.0) or close range (~5.0)
# This ensures calibration consistency
picam_0.set_controls({"AfMode": 0, "LensPosition": 0.0})
picam_1.set_controls({"AfMode": 0, "LensPosition": 0.0})


picam_0.start()
picam_1.start()


def generate_frames():
    while True:
        # Capture frames from both cameras
        # Picamera2's capture_array is optimized for numpy
        frame_l = picam_0.capture_array()
        frame_r = picam_1.capture_array()

        # SEPARABLE FRAMES:
        # You can access frame_l and frame_r independently here for processing.
        # For the web app, we stack them horizontally.
        combined = np.hstack((frame_l, frame_r))
        
        # Convert RGB to BGR for OpenCV encoding
        # combined_bgr = cv2.cvtColor(combined, cv2.COLOR_RGB2BGR)
        
        # Encode as JPG
        _, buffer = cv2.imencode('.jpg', combined, [cv2.IMWRITE_JPEG_QUALITY, 80])
        
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')

@app.get("/video")
async def video_feed():
    return StreamingResponse(generate_frames(), 
                             media_type="multipart/x-mixed-replace; boundary=frame")

@app.get("/")
async def index():
    content = """
    <html>
        <head><title>Stereo Vision</title></head>
        <body style="margin:0; background:#000; display:flex; flex-direction:column; align-items:center; color:white; font-family:sans-serif;">
            <h2>Dual Sync Cam Module 3 (Fixed Focus)</h2>
            <img src="/video" style="width:95%; border:2px solid #333;">
            <p>Left: Camera 0 | Right: Camera 1</p>
        </body>
    </html>
    """
    return HTMLResponse(content=content)

if __name__ == "__main__":
    import uvicorn
    # Use a single worker to prevent camera resource conflicts
    uvicorn.run(app, host="0.0.0.0", port=8000, workers=1)