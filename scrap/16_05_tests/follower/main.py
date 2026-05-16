"""
main.py — FastAPI server for the stereo robot tracker.
Run: uvicorn main:app --host 0.0.0.0 --port 8000
"""

import asyncio
import json
import sys
from pathlib import Path

import yaml
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from concurrent.futures import ThreadPoolExecutor

from RobotSystem import RobotSystem

# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

CONFIG_PATH = Path("config.yml")


def load_config(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


cfg = load_config(CONFIG_PATH)
bot = RobotSystem(cfg)
executor = ThreadPoolExecutor(max_workers=2)

app = FastAPI()


@app.on_event("startup")
async def startup():
    bot.start()


@app.on_event("shutdown")
async def shutdown():
    bot.stop()


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------

@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    loop = asyncio.get_event_loop()
    try:
        while True:
            # Non-blocking receive — process commands from the browser
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=0.01)
                msg = json.loads(raw)
                action = msg.get("action")

                if action == "set_auto":
                    with bot.lock:
                        bot.state["auto_follow"] = bool(msg["enabled"])
                    if not msg["enabled"]:
                        await loop.run_in_executor(executor, bot.motors.stop)

                elif action == "select_color":
                    bot.sample_color(float(msg["x"]), float(msg["y"]))

                elif action == "set_margins":
                    bot.set_margins(int(msg["h"]), int(msg["sv"]))

                elif action == "test_motor":
                    side = msg.get("side", "A")
                    result = await loop.run_in_executor(
                        executor, lambda: bot.test_motor(side, 1.0)
                    )
                    await websocket.send_json({"event": "test_result",
                                               "side": side, "log": result})
                    continue

                elif action == "drive":
                    meters = float(msg.get("meters", 0))
                    loop.run_in_executor(executor,
                                         lambda m=meters: bot.execute_drive(m))

                elif action == "spin":
                    degrees = float(msg.get("degrees", 0))
                    loop.run_in_executor(executor,
                                         lambda d=degrees: bot.execute_spin(d))

                elif action == "stop":
                    await loop.run_in_executor(executor, bot.motors.stop)

            except asyncio.TimeoutError:
                pass

            # Push telemetry frame to browser
            with bot.lock:
                s = bot.state
                color_state = bot.vision.get_color_state()
                payload = {
                    "event":      "frame",
                    "l":          s["encoded_l"],
                    "r":          s["encoded_r"],
                    "pos":        s["pos"],
                    "found":      s["found"],
                    "fps":        s["fps"],
                    "load":       s["load_pct"],
                    "auto":       s["auto_follow"],
                    "color":      color_state,
                }

            await websocket.send_json(payload)
            stream_fps = float(cfg.get("stream", {}).get("target_fps", 55))
            await asyncio.sleep(1 / min(stream_fps, 30))  # Cap UI at 30 fps

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[WS] error: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Web UI
# ---------------------------------------------------------------------------

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>RobotTracker</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  :root {
    --bg:       #0b0b0f;
    --surface:  #13131a;
    --border:   #252535;
    --green:    #39ff6a;
    --yellow:   #ffc130;
    --red:      #ff4455;
    --blue:     #4fa8ff;
    --text:     #d8dae0;
    --muted:    #555570;
  }

  body {
    background: var(--bg);
    color: var(--text);
    font-family: 'Consolas', 'Menlo', monospace;
    font-size: 13px;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
  }

  /* ── Top bar ────────────────────────────────────────────── */
  header {
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    padding: 8px 16px;
    display: flex;
    align-items: center;
    gap: 18px;
    flex-wrap: wrap;
  }

  header h1 { font-size: 14px; color: var(--green); letter-spacing: 1px; }

  .badge {
    font-size: 11px;
    padding: 3px 10px;
    border-radius: 20px;
    background: var(--border);
    color: var(--text);
    white-space: nowrap;
  }

  .badge.good  { color: var(--green); }
  .badge.warn  { color: var(--yellow); }
  .badge.bad   { color: var(--red); }
  .badge.blue  { color: var(--blue); }

  /* ── Main grid ──────────────────────────────────────────── */
  main {
    flex: 1;
    display: grid;
    grid-template-columns: 1fr 260px;
    gap: 0;
    overflow: hidden;
  }

  /* ── Camera area ────────────────────────────────────────── */
  #cameras {
    display: flex;
    flex-direction: column;
    gap: 0;
    padding: 10px;
    gap: 8px;
  }

  .cam-row {
    display: flex;
    gap: 8px;
  }

  .cam-wrap {
    flex: 1;
    position: relative;
    background: #000;
    border: 1px solid var(--border);
    border-radius: 4px;
    overflow: hidden;
  }

  .cam-wrap img {
    width: 100%;
    display: block;
    cursor: crosshair;
  }

  .cam-label {
    position: absolute;
    top: 6px; left: 8px;
    font-size: 10px;
    color: var(--muted);
    pointer-events: none;
  }

  /* ── Sidebar ────────────────────────────────────────────── */
  aside {
    background: var(--surface);
    border-left: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    overflow-y: auto;
  }

  .panel {
    border-bottom: 1px solid var(--border);
    padding: 12px 14px;
  }

  .panel h2 {
    font-size: 10px;
    letter-spacing: 1.5px;
    color: var(--muted);
    text-transform: uppercase;
    margin-bottom: 10px;
  }

  /* ── 3-D position display ───────────────────────────────── */
  .pos-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 6px;
    text-align: center;
  }

  .pos-cell { background: var(--bg); border: 1px solid var(--border); border-radius: 4px; padding: 6px 4px; }
  .pos-cell .lbl { font-size: 10px; color: var(--muted); }
  .pos-cell .val { font-size: 18px; font-weight: bold; margin-top: 2px; }

  /* ── Colour swatch ──────────────────────────────────────── */
  #color-swatch {
    width: 100%;
    height: 28px;
    border-radius: 4px;
    border: 1px solid var(--border);
    margin-bottom: 8px;
  }

  /* ── Sliders ────────────────────────────────────────────── */
  .slider-row {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 6px;
  }

  .slider-row label { width: 56px; color: var(--muted); font-size: 11px; }
  .slider-row input[type=range] { flex: 1; accent-color: var(--green); }
  .slider-row .sv  { width: 30px; text-align: right; color: var(--text); }

  /* ── Buttons ────────────────────────────────────────────── */
  .btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    border: 1px solid var(--border);
    background: var(--bg);
    color: var(--text);
    border-radius: 4px;
    padding: 7px 12px;
    font-size: 12px;
    font-family: inherit;
    cursor: pointer;
    transition: background 0.15s, color 0.15s, border-color 0.15s;
    width: 100%;
    margin-bottom: 6px;
  }
  .btn:hover { border-color: var(--green); color: var(--green); }

  .btn.active  { background: var(--green);  border-color: var(--green);  color: #000; font-weight: bold; }
  .btn.danger  { border-color: var(--red);  color: var(--red); }
  .btn.danger:hover { background: var(--red); color: #fff; }
  .btn.warning { border-color: var(--yellow); color: var(--yellow); }
  .btn.warning:hover { background: var(--yellow); color: #000; }

  .btn-row { display: flex; gap: 6px; }
  .btn-row .btn { margin-bottom: 0; }

  /* ── Manual drive ───────────────────────────────────────── */
  .drive-row { display: flex; gap: 6px; margin-bottom: 6px; }
  .drive-row input[type=number] {
    flex: 1;
    background: var(--bg);
    border: 1px solid var(--border);
    color: var(--text);
    border-radius: 4px;
    padding: 6px 8px;
    font-family: inherit;
    font-size: 12px;
  }
  .drive-row input[type=number]:focus { outline: none; border-color: var(--blue); }

  /* ── Motor test log ─────────────────────────────────────── */
  #test-log {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 8px;
    font-size: 11px;
    max-height: 130px;
    overflow-y: auto;
    color: var(--muted);
    white-space: pre;
    line-height: 1.6;
  }

  /* ── Status bar ─────────────────────────────────────────── */
  footer {
    background: var(--surface);
    border-top: 1px solid var(--border);
    padding: 4px 14px;
    font-size: 11px;
    color: var(--muted);
    display: flex;
    gap: 20px;
  }

  #ws-status { color: var(--red); }
  #ws-status.ok { color: var(--green); }
</style>
</head>
<body>

<header>
  <h1>&#9671; ROBOT TRACKER</h1>
  <span class="badge blue" id="fps-badge">FPS: —</span>
  <span class="badge" id="load-badge">Load: —</span>
  <span class="badge" id="found-badge">NO TARGET</span>
  <span class="badge" id="auto-badge">MANUAL</span>
</header>

<main>
  <!-- Camera feeds -->
  <div id="cameras">
    <div class="cam-row">
      <div class="cam-wrap">
        <span class="cam-label">LEFT</span>
        <img id="img-l" src="" alt="left camera" onclick="pickColor(event, 'l')">
      </div>
      <div class="cam-wrap">
        <span class="cam-label">RIGHT</span>
        <img id="img-r" src="" alt="right camera">
      </div>
    </div>
  </div>

  <!-- Sidebar -->
  <aside>

    <!-- 3-D Position -->
    <div class="panel">
      <h2>3-D Position (mm)</h2>
      <div class="pos-grid">
        <div class="pos-cell"><div class="lbl">X</div><div class="val" id="pos-x">0</div></div>
        <div class="pos-cell"><div class="lbl">Y</div><div class="val" id="pos-y">0</div></div>
        <div class="pos-cell"><div class="lbl">Z</div><div class="val" id="pos-z">0</div></div>
      </div>
    </div>

    <!-- Auto Follow -->
    <div class="panel">
      <h2>Tracking</h2>
      <button class="btn" id="btn-auto" onclick="toggleAuto()">
        &#9654; ENABLE AUTO-FOLLOW
      </button>
      <button class="btn danger" onclick="sendAction('stop')">&#9632; STOP MOTORS</button>
    </div>

    <!-- Colour Picker -->
    <div class="panel">
      <h2>Colour Target</h2>
      <div id="color-swatch"></div>
      <div class="slider-row">
        <label>H±</label>
        <input type="range" id="sl-h" min="1" max="50" value="15" oninput="syncMargins()">
        <span class="sv" id="sv-h">15</span>
      </div>
      <div class="slider-row">
        <label>S/V±</label>
        <input type="range" id="sl-sv" min="5" max="150" value="60" oninput="syncMargins()">
        <span class="sv" id="sv-sv">60</span>
      </div>
      <div style="font-size:10px; color:var(--muted); margin-top:4px;">
        Click the left camera image to sample a colour.
      </div>
    </div>

    <!-- Manual Drive -->
    <div class="panel">
      <h2>Manual Drive</h2>
      <div class="drive-row">
        <input type="number" id="in-meters" placeholder="metres" step="0.1" value="0.5">
        <button class="btn" style="width:auto; padding:6px 10px;" onclick="manualDrive()">Drive</button>
      </div>
      <div class="drive-row">
        <input type="number" id="in-degrees" placeholder="degrees" step="15" value="90">
        <button class="btn" style="width:auto; padding:6px 10px;" onclick="manualSpin()">Spin</button>
      </div>
    </div>

    <!-- Motor Tests -->
    <div class="panel">
      <h2>Motor Tests</h2>
      <div class="btn-row" style="margin-bottom:8px;">
        <button class="btn warning" onclick="testMotor('A')">Test Left (A)</button>
        <button class="btn warning" onclick="testMotor('B')">Test Right (B)</button>
      </div>
      <div id="test-log">Ready.</div>
    </div>

  </aside>
</main>

<footer>
  <span id="ws-status">● DISCONNECTED</span>
  <span id="footer-pos">X: 0 | Y: 0 | Z: 0 mm</span>
</footer>

<script>
  // ── WebSocket ──────────────────────────────────────────────────
  let ws = null;
  let autoFollow = false;

  function connect() {
    ws = new WebSocket(`ws://${location.host}/ws`);

    ws.onopen = () => {
      document.getElementById('ws-status').textContent = '● CONNECTED';
      document.getElementById('ws-status').classList.add('ok');
    };

    ws.onclose = () => {
      document.getElementById('ws-status').textContent = '● DISCONNECTED';
      document.getElementById('ws-status').classList.remove('ok');
      setTimeout(connect, 2000);
    };

    ws.onmessage = (e) => {
      const d = JSON.parse(e.data);

      if (d.event === 'frame') {
        handleFrame(d);
      } else if (d.event === 'test_result') {
        handleTestResult(d);
      }
    };

    ws.onerror = () => ws.close();
  }

  function sendAction(action, extra = {}) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ action, ...extra }));
    }
  }

  // ── Frame handler ──────────────────────────────────────────────
  function handleFrame(d) {
    if (d.l) document.getElementById('img-l').src = 'data:image/jpeg;base64,' + d.l;
    if (d.r) document.getElementById('img-r').src = 'data:image/jpeg;base64,' + d.r;

    // 3-D position
    const [x, y, z] = d.pos || [0, 0, 0];
    document.getElementById('pos-x').textContent = Math.round(x);
    document.getElementById('pos-y').textContent = Math.round(y);
    document.getElementById('pos-z').textContent = Math.round(z);
    document.getElementById('footer-pos').textContent =
      `X: ${Math.round(x)} | Y: ${Math.round(y)} | Z: ${Math.round(z)} mm`;

    // Target badge
    const foundBadge = document.getElementById('found-badge');
    if (d.found) {
      foundBadge.textContent = '● TARGET LOCKED';
      foundBadge.className = 'badge good';
    } else {
      foundBadge.textContent = 'NO TARGET';
      foundBadge.className = 'badge';
    }

    // FPS / Load
    const fpsBadge  = document.getElementById('fps-badge');
    const loadBadge = document.getElementById('load-badge');
    fpsBadge.textContent = `FPS: ${d.fps}`;
    loadBadge.textContent = `Load: ${d.load}%`;
    loadBadge.className = 'badge ' + (d.load > 85 ? 'bad' : d.load > 60 ? 'warn' : 'good');

    // Colour swatch
    if (d.color) {
      const [h, s, v] = d.color.center;
      // Convert HSV (OpenCV scale: H 0-180, S/V 0-255) to CSS hsl
      const hDeg  = Math.round(h * 2);
      const sPct  = Math.round((s / 255) * 100);
      const vPct  = Math.round((v / 255) * 100);
      // Approximate CSS hsl from HSV
      const lPct  = Math.round(vPct * (1 - sPct / 200));
      document.getElementById('color-swatch').style.background =
        `hsl(${hDeg}, ${sPct}%, ${Math.max(lPct, 20)}%)`;
    }
  }

  // ── Motor test ─────────────────────────────────────────────────
  function testMotor(side) {
    const log = document.getElementById('test-log');
    log.textContent = `Running Motor ${side} test…`;
    sendAction('test_motor', { side });
  }

  function handleTestResult(d) {
    const log = document.getElementById('test-log');
    let lines = [`Motor ${d.side} test result:`];
    for (const entry of d.log) {
      if (entry.summary) {
        lines.push(`  ΔA: ${entry.delta_a} ticks | ΔB: ${entry.delta_b} ticks`);
      } else {
        lines.push(`  t=${entry.t}s  A: ${entry.rev_s_a} r/s  B: ${entry.rev_s_b} r/s`);
      }
    }
    log.textContent = lines.join('\n');
  }

  // ── Auto-follow toggle ─────────────────────────────────────────
  function toggleAuto() {
    autoFollow = !autoFollow;
    const btn = document.getElementById('btn-auto');
    const badge = document.getElementById('auto-badge');
    if (autoFollow) {
      btn.textContent = '⏸ DISABLE AUTO-FOLLOW';
      btn.classList.add('active');
      badge.textContent = 'AUTO';
      badge.className = 'badge good';
    } else {
      btn.textContent = '▶ ENABLE AUTO-FOLLOW';
      btn.classList.remove('active');
      badge.textContent = 'MANUAL';
      badge.className = 'badge';
    }
    sendAction('set_auto', { enabled: autoFollow });
  }

  // ── Colour picking ─────────────────────────────────────────────
  function pickColor(event, side) {
    // Only allow sampling when auto-follow is OFF
    if (autoFollow) return;
    const rect = event.target.getBoundingClientRect();
    const x = (event.clientX - rect.left) / rect.width;
    const y = (event.clientY - rect.top)  / rect.height;
    sendAction('select_color', { x, y });
  }

  // ── Margin sliders ─────────────────────────────────────────────
  function syncMargins() {
    const h  = document.getElementById('sl-h').value;
    const sv = document.getElementById('sl-sv').value;
    document.getElementById('sv-h').textContent  = h;
    document.getElementById('sv-sv').textContent = sv;
    sendAction('set_margins', { h: parseInt(h), sv: parseInt(sv) });
  }

  // ── Manual drive ───────────────────────────────────────────────
  function manualDrive() {
    const m = parseFloat(document.getElementById('in-meters').value);
    if (!isNaN(m)) sendAction('drive', { meters: m });
  }

  function manualSpin() {
    const d = parseFloat(document.getElementById('in-degrees').value);
    if (!isNaN(d)) sendAction('spin', { degrees: d });
  }

  // ── Boot ───────────────────────────────────────────────────────
  connect();
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(HTML)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)