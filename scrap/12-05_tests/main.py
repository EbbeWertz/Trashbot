import threading, asyncio, json
from fastapi import FastAPI, WebSocket, responses
from RobotSystem import RobotSystem

app = FastAPI()
bot = RobotSystem()

@app.on_event("startup")
async def startup():
    threading.Thread(target=bot.run_main_loop, daemon=True).start()

@app.get("/", response_class=responses.HTMLResponse)
async def index():
    return """
    <body style="background:#000; color:#eee; font-family:sans-serif; display:flex; margin:0;">
        <div style="flex:2; padding:10px;">
            <button id="tog" style="width:100%; padding:20px; background:red; color:#fff; border:none;">ENABLE AUTO-FOLLOW</button>
            <img id="stream" style="width:100%; margin-top:10px;">
        </div>
        <div style="flex:1; background:#111; padding:20px; text-align:center; border-left:1px solid #333;">
            <h3>Z-Depth (mm)</h3>
            <h1 id="z_txt">0</h1>
            <div style="height:300px; width:40px; background:#222; margin:auto; position:relative; border:1px solid #444;">
                <div id="dot" style="width:40px; height:5px; background:#0f0; position:absolute; bottom:50%;"></div>
            </div>
        </div>
        <script>
            const ws = new WebSocket(`ws://${location.host}/ws`);
            let auto = false;
            document.getElementById('tog').onclick = () => {
                auto = !auto;
                document.getElementById('tog').style.background = auto ? 'green' : 'red';
            };
            ws.onmessage = (e) => {
                const d = JSON.parse(e.data);
                document.getElementById('stream').src = d.img;
                document.getElementById('z_txt').innerText = Math.round(d.z);
                document.getElementById('dot').style.top = (d.y_norm * 100) + '%';
                ws.send(JSON.stringify({auto: auto}));
            };
        </script>
    </body>
    """

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            try:
                msg = await asyncio.wait_for(websocket.receive_text(), 0.01)
                data = json.loads(msg)
                bot.state["auto_follow"] = data["auto"]
            except: pass

            with bot.lock:
                if bot.state["bg_bytes"]:
                    import base64
                    encoded = base64.b64encode(bot.state["bg_bytes"]).decode()
                    await websocket.send_json({
                        "img": "data:image/jpeg;base64," + encoded,
                        "z": bot.state["telemetry"]["z"],
                        "y_norm": bot.state["telemetry"]["y_norm"]
                    })
            await asyncio.sleep(1/bot.state["fps"])
    except Exception: pass

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)