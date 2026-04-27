import asyncio
import json
import time
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from hardware.TrashbotHardware import TrashbotHardware
from control.ManualMotorController import ManualMotorController

app = FastAPI()
hw = TrashbotHardware()
controller = ManualMotorController(hw)

# Track start time for real uptime calculation
START_TIME = time.time()

@app.get("/")
async def get_index():
    # Ensure your HTML file is in a folder named 'templates'
    with open("templates/index.html") as f:
        return HTMLResponse(content=f.read())

@app.on_event("startup")
async def startup_event():
    # Start the background loop that calculates PID/Motor outputs
    asyncio.create_task(controller.update_loop())

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    
    try:
        while True:
            # 1. Non-blocking check for incoming control data
            try:
                raw_data = await asyncio.wait_for(websocket.receive_text(), timeout=0.01)
                data = json.loads(raw_data)
                
                msg_type = data.get('type')
                if msg_type == 'drive':
                    controller.set_targets(data['l'], data['r'])
                elif msg_type == 'zero_imu':
                    hw.imu.zero()
                elif msg_type == 'abort':
                    controller.set_targets(0, 0)
                    hw.stop()
            except asyncio.TimeoutError:
                pass 

            # 2. Calculate real-time uptime
            uptime_sec = int(time.time() - START_TIME)
            uptime_str = f"{uptime_sec // 3600:02d}h {(uptime_sec % 3600) // 60:02d}m {uptime_sec % 60:02d}s"

            # 3. Construct and send telemetry payload
            payload = {
                "rpm_l": round(hw.left_motor.get_rpm(), 1),
                "rpm_r": round(hw.right_motor.get_rpm(), 1),
                "tilt": hw.imu.get_tilt(),
                "uptime": uptime_str,
                "ssid": "GROEP6_BOT_AP"
            }
            await websocket.send_json(payload)
            
            # Sync rate: 20Hz (matches typical frontend refresh rates)
            await asyncio.sleep(0.05) 
            
    except WebSocketDisconnect:
        # Emergency stop if connection is lost
        controller.set_targets(0, 0)
        hw.stop()
        print("Client disconnected: Motors Halted.")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)