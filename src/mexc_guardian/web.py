from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .config import settings
from .db import count_active_alerts, get_active_alerts, get_alert_history, init_db, queue_ack_command
from .state_store import read_state

app = FastAPI(title="Mexc-Gurdian API", version="0.2.0")
init_db(Path(settings.sqlite_db_path))


class AckPayload(BaseModel):
    symbol: str | None = None


@app.get("/health")
def health() -> dict:
    state = read_state(Path(settings.state_file))
    return {
        "status": state.get("status", "unknown"),
        "symbols_count": state.get("symbols_count", 0),
        "active_alerts": count_active_alerts(Path(settings.sqlite_db_path)),
        "updated_at": state.get("updated_at"),
    }


@app.get("/api/alerts/active")
def api_active_alerts() -> list[dict]:
    return get_active_alerts(Path(settings.sqlite_db_path))


@app.get("/api/alerts/history")
def api_alert_history(limit: int = 200) -> list[dict]:
    return get_alert_history(Path(settings.sqlite_db_path), limit=limit)


@app.post("/api/ack")
def api_ack(payload: AckPayload) -> dict:
    normalized = payload.symbol.upper().strip() if payload.symbol else None
    queue_ack_command(Path(settings.sqlite_db_path), normalized, source="web-api")
    return {"status": "queued", "symbol": normalized}


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    return """
<!doctype html>
<html>
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Mexc-Gurdian Dashboard</title>
  <style>
    :root { --bg:#0c1222; --panel:#131d36; --line:#273760; --text:#e6ecff; --muted:#9db0db; --up:#21c77a; --down:#ff5f6d; }
    body { background: radial-gradient(circle at top, #132246 0%, var(--bg) 50%); color:var(--text); font-family: ui-sans-serif, system-ui; margin:0; }
    .wrap { max-width:1100px; margin:20px auto; padding:0 16px; }
    h1 { margin:0 0 12px; }
    .row { display:flex; gap:10px; margin:10px 0 20px; }
    button,input { border:1px solid var(--line); background:var(--panel); color:var(--text); border-radius:8px; padding:8px 10px; }
    table { width:100%; border-collapse: collapse; background: rgba(15,25,46,.75); border:1px solid var(--line); border-radius:12px; overflow:hidden; }
    th,td { text-align:left; padding:10px; border-bottom:1px solid var(--line); font-size:14px; }
    .up { color: var(--up); }
    .down { color: var(--down); }
    .muted { color: var(--muted); }
  </style>
</head>
<body>
  <div class=\"wrap\">
    <h1>Mexc-Gurdian</h1>
    <div class=\"row\">
      <button onclick=\"ackAll()\">Ack All</button>
      <input id=\"symbol\" placeholder=\"BTC/USDT:USDT\" />
      <button onclick=\"ackOne()\">Ack Symbol</button>
      <button onclick=\"load()\">Refresh</button>
    </div>

    <h2>Active Alerts</h2>
    <table id=\"active\"><thead><tr><th>Symbol</th><th>Direction</th><th>Current %</th><th>Triggered</th><th>Acknowledged</th></tr></thead><tbody></tbody></table>

    <h2>Alert History</h2>
    <table id=\"history\"><thead><tr><th>Symbol</th><th>Status</th><th>Trigger %</th><th>Current %</th><th>Triggered</th><th>Resolved</th></tr></thead><tbody></tbody></table>
  </div>

<script>
async function api(path, opt) {
  const r = await fetch(path, opt || {});
  return await r.json();
}
function td(v, cls='') { return `<td class=\"${cls}\">${v ?? ''}</td>`; }
function pctClass(v){ return Number(v) >= 0 ? 'up' : 'down'; }
async function ackAll(){ await api('/api/ack', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({})}); await load(); }
async function ackOne(){
  const symbol = document.getElementById('symbol').value.trim();
  if (!symbol) return;
  await api('/api/ack', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({symbol})});
  await load();
}
async function load(){
  const active = await api('/api/alerts/active');
  const history = await api('/api/alerts/history?limit=100');

  const aBody = document.querySelector('#active tbody');
  aBody.innerHTML = active.map(a => `<tr>${td(a.symbol)}${td(a.direction)}${td(Number(a.current_pct).toFixed(2)+'%', pctClass(a.current_pct))}${td(a.triggered_at)}${td(a.acknowledged ? 'yes' : 'no', a.acknowledged ? 'up': 'muted')}</tr>`).join('') || '<tr><td colspan=\"5\" class=\"muted\">No active alerts</td></tr>';

  const hBody = document.querySelector('#history tbody');
  hBody.innerHTML = history.map(a => `<tr>${td(a.symbol)}${td(a.status)}${td(Number(a.trigger_pct).toFixed(2)+'%', pctClass(a.trigger_pct))}${td(Number(a.current_pct).toFixed(2)+'%', pctClass(a.current_pct))}${td(a.triggered_at)}${td(a.resolved_at || '-')}</tr>`).join('');
}
load();
setInterval(load, 15000);
</script>
</body>
</html>
    """
