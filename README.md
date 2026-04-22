# Mexc-Gurdian

MEXC futures (USDT perpetual) monitoring service with Telegram alerts, MCP tools, and web dashboard/API.

## What this implements

- Exchange: MEXC futures (`swap`)
- Universe: all active USDT perpetual symbols
- Rule: trigger when 4h change reaches `+-10%`
- Formula: `((current - price_4h_ago) / price_4h_ago) * 100`
- Direction: both rise and drop
- Alerts: Telegram
- Repeat alerts: every 10 minutes until manual ack
- Ack methods:
  - Telegram: `/ack` (all), `/ack SYMBOL`
  - MCP: `acknowledge_alert(symbol="")`
  - Web API: `POST /api/ack`

## New in this version

- Persistent SQLite state (`./data/mexc_gurdian.db`)
- Active alerts survive service restart
- Alert history stored in SQLite
- Dashboard UI + API on port `8080`

## Startup behavior

- Startup mode is warm-up by design: monitor waits for enough live data to build a 4h rolling baseline.
- Previously active alerts are restored from SQLite immediately after symbol discovery.

## Quick start (local or VPS)

1. Copy env file:

```bash
cp .env.example .env
```

2. Set Telegram values in `.env`:

```env
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

3. Run all services:

```bash
docker compose up -d --build
```

4. Check logs:

```bash
docker compose logs -f mexc-gurdian
```

5. Open dashboard:

- `http://<server-ip>:8080`

## API endpoints

- `GET /health`
- `GET /api/alerts/active`
- `GET /api/alerts/history?limit=200`
- `POST /api/ack` with JSON body `{ "symbol": "BTC/USDT:USDT" }` or `{}` for all

## MCP tools

- `get_service_health`
- `list_active_alerts`
- `list_alert_history(limit=100)`
- `acknowledge_alert(symbol="")`
- `get_config_summary`

## Vultr deployment notes

- Recommended: Ubuntu 22.04 + Docker + Docker Compose plugin
- Ensure outbound internet access for MEXC + Telegram API
- Allow inbound TCP `8080` if you want remote dashboard access
