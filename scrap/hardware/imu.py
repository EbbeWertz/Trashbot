import asyncio
import time
import math
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import socketio
from mpu6050 import mpu6050

# Initialize MPU6050
sensor = mpu6050(0x68)

# Setup Socket.IO server
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
app = FastAPI()
combined_app = socketio.ASGIApp(sio, app)

# Global State for Fusion
state = {
    "roll": 0.0,
    "pitch": 0.0,
    "gyro_roll_drift": 0.0,
    "last_time": time.time()
}

@app.get("/")
async def get_index():
    with open("templates/imu.html") as f:
        return HTMLResponse(content=f.read())

async def imu_loop():
    """Background task to read sensor data"""
    while True:
        now = time.time()
        dt = now - state["last_time"]
        state["last_time"] = now

        # Read raw data
        accel = sensor.get_accel_data()
        gyro = sensor.get_gyro_data()

        # 1. Accelerometer Angles
        accel_roll = math.atan2(accel['y'], accel['z']) * 57.2958
        accel_pitch = math.atan2(-accel['x'], math.sqrt(accel['y']**2 + accel['z']**2)) * 57.2958

        # 2. Integrated Gyro (The Drift tracker)
        state["gyro_roll_drift"] += gyro['x'] * dt

        # 3. Complementary Filter
        state["roll"] = 0.96 * (state["roll"] + gyro['x'] * dt) + 0.04 * accel_roll
        state["pitch"] = 0.96 * (state["pitch"] + gyro['y'] * dt) + 0.04 * accel_pitch

        # Broadcast to web clients
        await sio.emit('imu_data', {
            'accel': accel,
            'gyro': gyro,
            'filtered': {'roll': round(state["roll"], 2), 'pitch': round(state["pitch"], 2)},
            'drift_roll': round(state["gyro_roll_drift"], 2)
        })

        # Control sample rate (~50Hz)
        await asyncio.sleep(0.02)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(imu_loop())

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(combined_app, host="0.0.0.0", port=5000)