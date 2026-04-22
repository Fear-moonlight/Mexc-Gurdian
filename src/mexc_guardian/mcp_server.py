from __future__ import annotations

from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from .config import settings
from .db import count_active_alerts, get_active_alerts, get_alert_history, init_db, queue_ack_command
from .state_store import read_state

mcp = FastMCP("mexc-gurdian")
init_db(Path(settings.sqlite_db_path))


def _state() -> dict[str, Any]:
    return read_state(Path(settings.state_file))


@mcp.tool
def get_service_health() -> dict[str, Any]:
    data = _state()
    return {
        "status": data.get("status", "unknown"),
        "updated_at": data.get("updated_at"),
        "symbols_count": data.get("symbols_count", 0),
        "active_alerts": count_active_alerts(Path(settings.sqlite_db_path)),
    }


@mcp.tool
def list_active_alerts() -> list[dict[str, Any]]:
    return get_active_alerts(Path(settings.sqlite_db_path))


@mcp.tool
def list_alert_history(limit: int = 100) -> list[dict[str, Any]]:
    return get_alert_history(Path(settings.sqlite_db_path), limit=limit)


@mcp.tool
def acknowledge_alert(symbol: str = "") -> dict[str, str]:
    normalized = symbol.strip().upper() or None
    queue_ack_command(Path(settings.sqlite_db_path), normalized, source="mcp")
    if normalized:
        return {"status": "queued", "action": f"ack {normalized}"}
    return {"status": "queued", "action": "ack all"}


@mcp.tool
def get_config_summary() -> dict[str, Any]:
    return {
        "exchange": settings.exchange_id,
        "market_type": settings.market_type,
        "quote": settings.quote_currency,
        "threshold": settings.percent_threshold,
        "window_hours": settings.window_hours,
        "repeat_alert_minutes": settings.repeat_alert_minutes,
        "manual_ack_required": settings.require_manual_ack,
        "sqlite_db_path": str(settings.sqlite_db_path),
    }


if __name__ == "__main__":
    mcp.run()
