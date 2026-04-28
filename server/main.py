import asyncio
import json
import cv2
import numpy as np
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, StreamingResponse
from hardware.TrashbotHardware import TrashbotHardware
from hardware.Camera import Camera
from control.ManualMotorController import ManualMotorController
import socketio

sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
app = FastAPI()
combined_app = socketio.ASGIApp(sio, app)

hw = TrashbotHardware()
controller = ManualMotorController(hw)
hw.startCams()

UPTIME_START = datetime.now()

@app.get("/")
async def get_index():
    with open("templates/index.html") as f:
        return HTMLResponse(content=f.read())

async def uptime_loop():
    while True:
        now = str(datetime.now() - UPTIME_START).split('.')[0]
        print(f"[uptime]: {now}")
        await sio.emit('uptime_update', {
            'uptime': now
        })
        await asyncio.sleep(1)

async def camera_frames_loop(view):
    while True:
        left_frame, right_frame = hw.getCamFrames()
        frame = left_frame if view == "left" else right_frame
        _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')

@app.get("/video")
async def video_feed(view: str = "raw"):
    return StreamingResponse(camera_frames_loop(view), 
                             media_type="multipart/x-mixed-replace; boundary=frame")

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(uptime_loop())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(combined_app, host="0.0.0.0", port=8000)