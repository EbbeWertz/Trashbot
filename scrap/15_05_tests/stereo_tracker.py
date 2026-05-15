import io
import uvicorn
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from picamera2 import Picamera2

app = FastAPI()

# Initialize Picamera2
# This setup assumes a standard Raspberry Pi Camera (v2, v3, or HQ)
picam2 = Picamera2()
config = picam2.create_video_configuration(main={"format": "RGB888", "size": (640, 480)})
picam2.configure(config)
picam2.start()

def generate_frames():
    """Continuously capture frames from the camera and yield them as MJPEG."""
    while True:
        # Capture a single frame into a bytes buffer as a JPEG
        request = picam2.capture_file("buffer.jpg", format="jpeg", display=False)
        
        with open("buffer.jpg", "rb") as f:
            frame = f.read()
            
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

@app.get("/")
async def index():
    """Returns a simple HTML page that displays the video stream."""
    return StreamingResponse(
        content="""
        <html>
          <head><title>PiCamera2 Stream</title></head>
          <body style="background: #111; color: white; text-align: center;">
            <h1>Raspberry Pi Live Stream</h1>
            <img src="/video_feed" width="640" height="480" style="border: 5px solid #333;">
          </body>
        </html>
        """,
        media_type="text/html"
    )

@app.get("/video_feed")
async def video_feed():
    """Route that serves the MJPEG stream."""
    return StreamingResponse(
        generate_frames(), 
        media_type="multipart/x-mixed-replace; boundary=frame"
    )

if __name__ == "__main__":
    # Run the server on all network interfaces at port 8000
    uvicorn.run(app, host="0.0.0.0", port=8000)