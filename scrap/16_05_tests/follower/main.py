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
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=0.01)
                msg = json.loads(raw)
                action = msg.get("action")

                if action == "set_mode":
                    bot.set_mode(msg.get("mode", "off"))

                elif action == "reset_intercept":
                    bot.reset_intercept()

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
                    bot.set_mode("off")

            except asyncio.TimeoutError:
                pass

            with bot.lock:
                s = bot.state
                color_state = bot.vision.get_color_state()
                payload = {
                    "event":           "frame",
                    "l":               s["encoded_l"],
                    "r":               s["encoded_r"],
                    "pos":             s["pos"],
                    "found":           s["found"],
                    "fps":             s["fps"],
                    "load":            s["load_pct"],
                    "mode":            s["mode"],
                    "color":           color_state,
                    "intercept_telem": s.get("intercept_telem", {}),
                }

            await websocket.send_json(payload)
            stream_fps = float(cfg.get("stream", {}).get("target_fps", 55))
            await asyncio.sleep(1 / min(stream_fps, 30))

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
    --bg:      #0b0b0f;
    --surf:    #13131a;
    --bord:    #252535;
    --green:   #39ff6a;
    --yellow:  #ffc130;
    --red:     #ff4455;
    --blue:    #4fa8ff;
    --purple:  #bf7fff;
    --text:    #d8dae0;
    --muted:   #555570;
  }
  body { background:var(--bg); color:var(--text); font-family:'Consolas','Menlo',monospace;
         font-size:13px; min-height:100vh; display:flex; flex-direction:column; }

  /* header */
  header { background:var(--surf); border-bottom:1px solid var(--bord);
           padding:8px 16px; display:flex; align-items:center; gap:14px; flex-wrap:wrap; }
  header h1 { font-size:14px; color:var(--green); letter-spacing:1px; }
  .badge { font-size:11px; padding:3px 10px; border-radius:20px;
           background:var(--bord); color:var(--text); white-space:nowrap; }
  .badge.good   { color:var(--green); }
  .badge.warn   { color:var(--yellow); }
  .badge.bad    { color:var(--red); }
  .badge.blue   { color:var(--blue); }
  .badge.purple { color:var(--purple); }

  /* layout */
  main { flex:1; display:grid; grid-template-columns:1fr 270px; overflow:hidden; }

  /* cameras */
  #cameras { display:flex; flex-direction:column; padding:10px; gap:8px; }
  .cam-row { display:flex; gap:8px; }
  .cam-wrap { flex:1; position:relative; background:#000;
              border:1px solid var(--bord); border-radius:4px; overflow:hidden; }
  .cam-wrap img { width:100%; display:block; cursor:crosshair; }
  .cam-label { position:absolute; top:6px; left:8px; font-size:10px;
               color:var(--muted); pointer-events:none; }

  /* trajectory canvas */
  #traj-wrap { position:relative; border:1px solid var(--bord); border-radius:4px;
               background:#000; height:160px; }
  #traj-canvas { width:100%; height:100%; display:block; }
  #traj-label  { position:absolute; top:6px; left:8px; font-size:10px; color:var(--muted); }

  /* sidebar */
  aside { background:var(--surf); border-left:1px solid var(--bord);
          display:flex; flex-direction:column; overflow-y:auto; }
  .panel { border-bottom:1px solid var(--bord); padding:12px 14px; }
  .panel h2 { font-size:10px; letter-spacing:1.5px; color:var(--muted);
              text-transform:uppercase; margin-bottom:10px; }

  /* mode buttons */
  .mode-grid { display:grid; grid-template-columns:1fr 1fr 1fr; gap:6px; }
  .mode-btn  { border:1px solid var(--bord); background:var(--bg); color:var(--text);
               border-radius:4px; padding:8px 4px; font-size:11px; font-family:inherit;
               cursor:pointer; text-align:center; transition:all .15s; }
  .mode-btn:hover { border-color:var(--blue); color:var(--blue); }
  .mode-btn.active-off        { background:var(--bord); color:var(--text); border-color:var(--muted); }
  .mode-btn.active-follow     { background:var(--green); color:#000; border-color:var(--green); font-weight:bold; }
  .mode-btn.active-intercept  { background:var(--purple); color:#000; border-color:var(--purple); font-weight:bold; }

  /* 3D position */
  .pos-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:6px; text-align:center; }
  .pos-cell { background:var(--bg); border:1px solid var(--bord); border-radius:4px; padding:6px 4px; }
  .pos-cell .lbl { font-size:10px; color:var(--muted); }
  .pos-cell .val { font-size:18px; font-weight:bold; margin-top:2px; }

  /* intercept telemetry */
  .itelem { display:grid; grid-template-columns:1fr 1fr; gap:5px; }
  .itelem-cell { background:var(--bg); border:1px solid var(--bord);
                 border-radius:4px; padding:5px 7px; }
  .itelem-cell .lbl { font-size:9px; color:var(--muted); }
  .itelem-cell .val { font-size:13px; font-weight:bold; margin-top:1px; }
  .itelem-cell .val.good   { color:var(--green); }
  .itelem-cell .val.warn   { color:var(--yellow); }
  .itelem-cell .val.bad    { color:var(--red); }
  .itelem-cell .val.purple { color:var(--purple); }

  /* phase indicator */
  #phase-bar { border-radius:4px; padding:8px 12px; text-align:center;
               font-size:12px; font-weight:bold; letter-spacing:1px;
               margin-bottom:10px; background:var(--bord); color:var(--muted); }
  #phase-bar.observing  { background:#1a2a1a; color:var(--green); border:1px solid var(--green); }
  #phase-bar.committed  { background:#2a1a00; color:var(--yellow); border:1px solid var(--yellow); }
  #phase-bar.braking    { background:#2a0008; color:var(--red); border:1px solid var(--red); }
  #phase-bar.done       { background:#1a1a2a; color:var(--purple); border:1px solid var(--purple); }

  /* colour swatch */
  #color-swatch { width:100%; height:28px; border-radius:4px; border:1px solid var(--bord); margin-bottom:8px; }
  .slider-row { display:flex; align-items:center; gap:8px; margin-bottom:6px; }
  .slider-row label { width:56px; color:var(--muted); font-size:11px; }
  .slider-row input[type=range] { flex:1; accent-color:var(--green); }
  .slider-row .sv { width:30px; text-align:right; color:var(--text); }

  /* buttons */
  .btn { display:inline-flex; align-items:center; justify-content:center; gap:6px;
         border:1px solid var(--bord); background:var(--bg); color:var(--text);
         border-radius:4px; padding:7px 12px; font-size:12px; font-family:inherit;
         cursor:pointer; transition:all .15s; width:100%; margin-bottom:6px; }
  .btn:hover { border-color:var(--green); color:var(--green); }
  .btn.danger  { border-color:var(--red);    color:var(--red); }
  .btn.danger:hover  { background:var(--red);    color:#fff; }
  .btn.warning { border-color:var(--yellow); color:var(--yellow); }
  .btn.warning:hover { background:var(--yellow); color:#000; }
  .btn.purple  { border-color:var(--purple); color:var(--purple); }
  .btn.purple:hover  { background:var(--purple); color:#000; }
  .btn-row { display:flex; gap:6px; }
  .btn-row .btn { margin-bottom:0; }

  /* drive inputs */
  .drive-row { display:flex; gap:6px; margin-bottom:6px; }
  .drive-row input[type=number] { flex:1; background:var(--bg); border:1px solid var(--bord);
    color:var(--text); border-radius:4px; padding:6px 8px; font-family:inherit; font-size:12px; }
  .drive-row input:focus { outline:none; border-color:var(--blue); }

  /* motor log */
  #test-log { background:var(--bg); border:1px solid var(--bord); border-radius:4px;
              padding:8px; font-size:11px; max-height:120px; overflow-y:auto;
              color:var(--muted); white-space:pre; line-height:1.6; }

  /* footer */
  footer { background:var(--surf); border-top:1px solid var(--bord);
           padding:4px 14px; font-size:11px; color:var(--muted); display:flex; gap:20px; }
  #ws-status { color:var(--red); }
  #ws-status.ok { color:var(--green); }
</style>
</head>
<body>

<header>
  <h1>&#9671; ROBOT TRACKER</h1>
  <span class="badge blue"  id="fps-badge">FPS: —</span>
  <span class="badge"       id="load-badge">Load: —</span>
  <span class="badge"       id="found-badge">NO TARGET</span>
  <span class="badge"       id="mode-badge">OFF</span>
</header>

<main>
  <div id="cameras">
    <div class="cam-row">
      <div class="cam-wrap">
        <span class="cam-label">LEFT</span>
        <img id="img-l" src="" alt="left" onclick="pickColor(event)">
      </div>
      <div class="cam-wrap">
        <span class="cam-label">RIGHT</span>
        <img id="img-r" src="" alt="right">
      </div>
    </div>
    <!-- Trajectory / fit preview -->
    <div class="traj-wrap" id="traj-wrap">
      <canvas id="traj-canvas"></canvas>
      <span class="cam-label" id="traj-label">XY TRAJECTORY — INTERCEPT PREVIEW</span>
    </div>
  </div>

  <aside>

    <!-- Mode selector -->
    <div class="panel">
      <h2>Mode</h2>
      <div class="mode-grid">
        <button class="mode-btn active-off" id="btn-off"       onclick="setMode('off')">&#9632; OFF</button>
        <button class="mode-btn"            id="btn-follow"    onclick="setMode('follow')">&#9654; FOLLOW</button>
        <button class="mode-btn"            id="btn-intercept" onclick="setMode('intercept')">&#10006; INTERCEPT</button>
      </div>
    </div>

    <!-- 3-D position -->
    <div class="panel">
      <h2>3-D Position (mm)</h2>
      <div class="pos-grid">
        <div class="pos-cell"><div class="lbl">X</div><div class="val" id="pos-x">0</div></div>
        <div class="pos-cell"><div class="lbl">Y</div><div class="val" id="pos-y">0</div></div>
        <div class="pos-cell"><div class="lbl">Z</div><div class="val" id="pos-z">0</div></div>
      </div>
    </div>

    <!-- Intercept telemetry -->
    <div class="panel" id="panel-intercept">
      <h2>Intercept</h2>
      <div id="phase-bar">IDLE</div>
      <div class="itelem">
        <div class="itelem-cell"><div class="lbl">Samples</div><div class="val" id="it-samples">0</div></div>
        <div class="itelem-cell"><div class="lbl">Time to catch</div><div class="val" id="it-ttc">—</div></div>
        <div class="itelem-cell"><div class="lbl">Z fit RMS</div><div class="val" id="it-rmsz">—</div></div>
        <div class="itelem-cell"><div class="lbl">XY fit RMS</div><div class="val" id="it-rmsxy">—</div></div>
        <div class="itelem-cell"><div class="lbl">Catch X</div><div class="val" id="it-cx">—</div></div>
        <div class="itelem-cell"><div class="lbl">Catch Y</div><div class="val" id="it-cy">—</div></div>
        <div class="itelem-cell"><div class="lbl">Turn</div><div class="val" id="it-turn">—</div></div>
        <div class="itelem-cell"><div class="lbl">Heading</div><div class="val" id="it-heading">0°</div></div>
      </div>
      <button class="btn purple" style="margin-top:10px;" onclick="sendAction('reset_intercept')">
        &#8635; RE-ARM INTERCEPT
      </button>
    </div>

    <!-- Colour picker -->
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
      <div style="font-size:10px;color:var(--muted);margin-top:4px;">
        Click left camera to sample colour (when mode is OFF).
      </div>
    </div>

    <!-- Manual drive -->
    <div class="panel">
      <h2>Manual Drive</h2>
      <div class="drive-row">
        <input type="number" id="in-meters" placeholder="metres" step="0.1" value="0.5">
        <button class="btn" style="width:auto;padding:6px 10px;" onclick="manualDrive()">Drive</button>
      </div>
      <div class="drive-row">
        <input type="number" id="in-degrees" placeholder="degrees" step="15" value="90">
        <button class="btn" style="width:auto;padding:6px 10px;" onclick="manualSpin()">Spin</button>
      </div>
      <button class="btn danger" onclick="sendAction('stop')">&#9632; STOP MOTORS</button>
    </div>

    <!-- Motor tests -->
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
// ── WebSocket ──────────────────────────────────────────────────────────────
let ws = null;
let currentMode = 'off';

// Trajectory history for the canvas
const MAX_HIST = 120;
let trajHistory = [];   // [{x, y, z}]
let fitLine = null;     // {x0,y0,x1,y1} normalised 0-1 in data space
let catchPoint = null;  // {x, y} mm

function connect() {
  ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onopen  = () => { document.getElementById('ws-status').textContent = '● CONNECTED';
                        document.getElementById('ws-status').classList.add('ok'); };
  ws.onclose = () => { document.getElementById('ws-status').textContent = '● DISCONNECTED';
                        document.getElementById('ws-status').classList.remove('ok');
                        setTimeout(connect, 2000); };
  ws.onmessage = e => {
    const d = JSON.parse(e.data);
    if (d.event === 'frame')       handleFrame(d);
    else if (d.event === 'test_result') handleTestResult(d);
  };
  ws.onerror = () => ws.close();
}

function sendAction(action, extra = {}) {
  if (ws && ws.readyState === WebSocket.OPEN)
    ws.send(JSON.stringify({ action, ...extra }));
}

// ── Frame handler ──────────────────────────────────────────────────────────
function handleFrame(d) {
  if (d.l) document.getElementById('img-l').src = 'data:image/jpeg;base64,' + d.l;
  if (d.r) document.getElementById('img-r').src = 'data:image/jpeg;base64,' + d.r;

  const [x, y, z] = d.pos || [0, 0, 0];
  document.getElementById('pos-x').textContent = Math.round(x);
  document.getElementById('pos-y').textContent = Math.round(y);
  document.getElementById('pos-z').textContent = Math.round(z);
  document.getElementById('footer-pos').textContent =
    `X: ${Math.round(x)} | Y: ${Math.round(y)} | Z: ${Math.round(z)} mm`;

  const foundB = document.getElementById('found-badge');
  if (d.found) { foundB.textContent = '● TARGET LOCKED'; foundB.className = 'badge good'; }
  else         { foundB.textContent = 'NO TARGET';        foundB.className = 'badge'; }

  document.getElementById('fps-badge').textContent  = `FPS: ${d.fps}`;
  const lb = document.getElementById('load-badge');
  lb.textContent = `Load: ${d.load}%`;
  lb.className   = 'badge ' + (d.load > 85 ? 'bad' : d.load > 60 ? 'warn' : 'good');

  // Colour swatch
  if (d.color) {
    const [h, s, v] = d.color.center;
    const hDeg = Math.round(h * 2);
    const sPct = Math.round((s / 255) * 100);
    const vPct = Math.round((v / 255) * 100);
    const lPct = Math.round(vPct * (1 - sPct / 200));
    document.getElementById('color-swatch').style.background =
      `hsl(${hDeg}, ${sPct}%, ${Math.max(lPct, 20)}%)`;
  }

  // Mode sync
  if (d.mode !== currentMode) applyMode(d.mode);

  // Intercept telemetry
  const it = d.intercept_telem || {};
  updateInterceptPanel(it, d.found, d.pos);

  // Trajectory history
  if (d.found && d.pos[2] > 0) {
    trajHistory.push({ x: d.pos[0], y: d.pos[1], z: d.pos[2] });
    if (trajHistory.length > MAX_HIST) trajHistory.shift();
  }
  if (it.catch_x !== undefined && it.catch_y !== undefined && it.catch_x !== 0)
    catchPoint = { x: it.catch_x, y: it.catch_y };
  else catchPoint = null;

  drawTrajectory();
}

// ── Intercept panel ────────────────────────────────────────────────────────
function updateInterceptPanel(it, found, pos) {
  const phase = (it.phase || 'IDLE').toUpperCase();
  const bar   = document.getElementById('phase-bar');
  bar.textContent = phase;
  bar.className   = '';
  if      (phase === 'OBSERVING') bar.className = 'observing';
  else if (phase === 'COMMITTED') bar.className = 'committed';
  else if (phase === 'BRAKING')   bar.className = 'braking';
  else if (phase === 'DONE')      bar.className = 'done';

  setIVal('it-samples', it.n_samples ?? '—');
  const ttc = it.predicted_t;
  if (ttc && ttc > 0) {
    const el = document.getElementById('it-ttc');
    el.textContent = ttc.toFixed(2) + 's';
    el.className   = 'val ' + (ttc < 0.4 ? 'bad' : ttc < 1.0 ? 'warn' : 'good');
  } else { setIVal('it-ttc', '—', ''); }

  const rz  = it.fit_rms_z  ?? 0;
  const rxy = it.fit_rms_xy ?? 0;
  setIVal('it-rmsz',  rz  ? rz.toFixed(1)  + ' mm' : '—',
          rz  > 40 ? 'bad' : rz  > 20 ? 'warn' : 'good');
  setIVal('it-rmsxy', rxy ? rxy.toFixed(1) + ' mm' : '—',
          rxy > 40 ? 'bad' : rxy > 20 ? 'warn' : 'good');
  setIVal('it-cx',  it.catch_x ? Math.round(it.catch_x) + ' mm' : '—');
  setIVal('it-cy',  it.catch_y ? Math.round(it.catch_y) + ' mm' : '—');
  const td = it.turn_deg ?? 0;
  setIVal('it-turn', td ? td.toFixed(1) + '°' : '—',
          Math.abs(td) > 30 ? 'warn' : 'good');
  setIVal('it-heading', (it.heading ?? 0).toFixed(1) + '°');

  // Z height warning in position display
  if (found && pos && pos[2] > 0 && pos[2] < 200) {
    document.getElementById('pos-z').className = 'val bad';
  } else {
    document.getElementById('pos-z').className = 'val';
  }
}

function setIVal(id, txt, cls) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = txt;
  el.className   = 'val' + (cls ? ' ' + cls : '');
}

// ── Trajectory canvas ──────────────────────────────────────────────────────
function drawTrajectory() {
  const wrap   = document.getElementById('traj-wrap');
  const canvas = document.getElementById('traj-canvas');
  canvas.width  = wrap.clientWidth  || 600;
  canvas.height = wrap.clientHeight || 160;
  const W = canvas.width, H = canvas.height;
  const ctx = canvas.getContext('2d');

  ctx.fillStyle = '#000';
  ctx.fillRect(0, 0, W, H);

  if (trajHistory.length < 2) return;

  const xs  = trajHistory.map(p => p.x);
  const ys  = trajHistory.map(p => p.y);
  const zs  = trajHistory.map(p => p.z);
  const xMin = Math.min(...xs), xMax = Math.max(...xs);
  const yMin = Math.min(...ys), yMax = Math.max(...ys);
  const zMin = Math.min(...zs), zMax = Math.max(...zs);
  const PAD = 20;

  function toCanvasXY(x, y) {
    const cx = xMax === xMin ? W/2 : PAD + (x - xMin) / (xMax - xMin) * (W - 2*PAD);
    const cy = yMax === yMin ? H/2 : PAD + (1 - (y - yMin) / (yMax - yMin)) * (H - 2*PAD);
    return [cx, cy];
  }

  // Draw grid lines
  ctx.strokeStyle = '#1e1e2e';
  ctx.lineWidth   = 1;
  for (let i = 0; i <= 4; i++) {
    const gx = PAD + (i/4)*(W-2*PAD);
    const gy = PAD + (i/4)*(H-2*PAD);
    ctx.beginPath(); ctx.moveTo(gx, PAD); ctx.lineTo(gx, H-PAD); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(PAD, gy); ctx.lineTo(W-PAD, gy); ctx.stroke();
  }

  // XY trajectory path coloured by Z (height)
  const zRange = zMax - zMin || 1;
  for (let i = 1; i < trajHistory.length; i++) {
    const [x0, y0] = toCanvasXY(trajHistory[i-1].x, trajHistory[i-1].y);
    const [x1, y1] = toCanvasXY(trajHistory[i].x,   trajHistory[i].y);
    const t = (trajHistory[i].z - zMin) / zRange;  // 0=low, 1=high
    // Blue (low) → green (mid) → red (high Z = high up)
    const r = Math.round(t > 0.5 ? 255 : t * 2 * 255);
    const g = Math.round(t < 0.5 ? t * 2 * 200 : (1 - t) * 2 * 200);
    const b = Math.round(t < 0.5 ? (1 - t * 2) * 255 : 0);
    ctx.strokeStyle = `rgb(${r},${g},${b})`;
    ctx.lineWidth   = 2;
    ctx.beginPath(); ctx.moveTo(x0,y0); ctx.lineTo(x1,y1); ctx.stroke();
  }

  // Catch-point marker
  if (catchPoint) {
    const allX = [...xs, catchPoint.x], allY = [...ys, catchPoint.y];
    const [cpx, cpy] = toCanvasXY(catchPoint.x, catchPoint.y);
    ctx.beginPath();
    ctx.arc(cpx, cpy, 8, 0, 2*Math.PI);
    ctx.strokeStyle = '#bf7fff';
    ctx.lineWidth   = 2;
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(cpx-10, cpy); ctx.lineTo(cpx+10, cpy);
    ctx.moveTo(cpx, cpy-10); ctx.lineTo(cpx, cpy+10);
    ctx.strokeStyle = '#bf7fff';
    ctx.lineWidth   = 1;
    ctx.stroke();
    ctx.fillStyle   = '#bf7fff';
    ctx.font        = '10px Consolas';
    ctx.fillText(`CATCH (${Math.round(catchPoint.x)}, ${Math.round(catchPoint.y)})`, cpx+10, cpy-5);
  }

  // Current position dot
  if (trajHistory.length > 0) {
    const last = trajHistory[trajHistory.length-1];
    const [lx, ly] = toCanvasXY(last.x, last.y);
    ctx.beginPath(); ctx.arc(lx, ly, 5, 0, 2*Math.PI);
    ctx.fillStyle = '#39ff6a'; ctx.fill();
  }

  // Axis labels
  ctx.fillStyle = '#333355'; ctx.font = '9px Consolas';
  ctx.fillText(`X: ${Math.round(xMin)}…${Math.round(xMax)} mm`, PAD, H-5);
  ctx.save(); ctx.translate(9, H/2); ctx.rotate(-Math.PI/2);
  ctx.fillText(`Y: ${Math.round(yMin)}…${Math.round(yMax)} mm`, -30, 0);
  ctx.restore();
}

// ── Mode management ────────────────────────────────────────────────────────
function setMode(mode) {
  sendAction('set_mode', { mode });
  applyMode(mode);
  if (mode !== 'intercept') trajHistory = [];
}

function applyMode(mode) {
  currentMode = mode;
  ['off','follow','intercept'].forEach(m => {
    const btn = document.getElementById('btn-' + m);
    btn.className = 'mode-btn' + (m === mode ? ' active-' + m : '');
  });
  const badge = document.getElementById('mode-badge');
  const labels = { off:'OFF', follow:'FOLLOW', intercept:'INTERCEPT' };
  const classes = { off:'badge', follow:'badge good', intercept:'badge purple' };
  badge.textContent = labels[mode] || mode.toUpperCase();
  badge.className   = classes[mode] || 'badge';
}

// ── Colour picker ──────────────────────────────────────────────────────────
function pickColor(event) {
  if (currentMode !== 'off') return;
  const rect = event.target.getBoundingClientRect();
  sendAction('select_color', {
    x: (event.clientX - rect.left) / rect.width,
    y: (event.clientY - rect.top)  / rect.height,
  });
}

function syncMargins() {
  const h  = document.getElementById('sl-h').value;
  const sv = document.getElementById('sl-sv').value;
  document.getElementById('sv-h').textContent  = h;
  document.getElementById('sv-sv').textContent = sv;
  sendAction('set_margins', { h: parseInt(h), sv: parseInt(sv) });
}

// ── Motor tests ────────────────────────────────────────────────────────────
function testMotor(side) {
  document.getElementById('test-log').textContent = `Running Motor ${side} test…`;
  sendAction('test_motor', { side });
}

function handleTestResult(d) {
  const lines = [`Motor ${d.side} test:`];
  for (const e of d.log) {
    if (e.summary) lines.push(`  ΔA: ${e.delta_a} ticks | ΔB: ${e.delta_b} ticks`);
    else lines.push(`  t=${e.t}s  A:${e.rev_s_a} r/s  B:${e.rev_s_b} r/s`);
  }
  document.getElementById('test-log').textContent = lines.join('\n');
}

// ── Manual drive ───────────────────────────────────────────────────────────
function manualDrive() {
  const m = parseFloat(document.getElementById('in-meters').value);
  if (!isNaN(m)) sendAction('drive', { meters: m });
}
function manualSpin() {
  const d = parseFloat(document.getElementById('in-degrees').value);
  if (!isNaN(d)) sendAction('spin', { degrees: d });
}

connect();
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(HTML)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)