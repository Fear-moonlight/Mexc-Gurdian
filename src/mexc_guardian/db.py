from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path) -> None:
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS alerts (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              symbol TEXT NOT NULL,
              status TEXT NOT NULL,
              direction TEXT NOT NULL,
              trigger_pct REAL NOT NULL,
              current_pct REAL NOT NULL,
              triggered_at TEXT NOT NULL,
              last_notified_at TEXT,
              acknowledged INTEGER NOT NULL DEFAULT 0,
              acked_at TEXT,
              resolved_at TEXT,
              resolved_reason TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_alerts_symbol ON alerts(symbol);
            CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status);
            CREATE INDEX IF NOT EXISTS idx_alerts_triggered ON alerts(triggered_at DESC);

            CREATE TABLE IF NOT EXISTS commands (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              type TEXT NOT NULL,
              symbol TEXT,
              status TEXT NOT NULL DEFAULT 'queued',
              source TEXT,
              created_at TEXT NOT NULL,
              processed_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_commands_status ON commands(status, id);

            CREATE TABLE IF NOT EXISTS symbol_snapshots (
              symbol TEXT PRIMARY KEY,
              pct_change REAL,
              active INTEGER NOT NULL,
              acknowledged INTEGER NOT NULL,
              updated_at TEXT NOT NULL
            );
            """
        )


def queue_ack_command(db_path: Path, symbol: str | None, source: str = "unknown") -> None:
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO commands(type, symbol, source, created_at)
            VALUES('ack', ?, ?, ?)
            """,
            (symbol, source, utc_now_iso()),
        )


def drain_commands(db_path: Path) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, type, symbol, source, created_at FROM commands WHERE status = 'queued' ORDER BY id ASC"
        ).fetchall()
        ids = [r["id"] for r in rows]
        if ids:
            now = utc_now_iso()
            conn.executemany(
                "UPDATE commands SET status = 'processed', processed_at = ? WHERE id = ?",
                [(now, i) for i in ids],
            )
    return [dict(r) for r in rows]


def create_alert(
    db_path: Path,
    symbol: str,
    direction: str,
    trigger_pct: float,
    triggered_at: str,
    last_notified_at: str | None,
) -> int:
    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO alerts(
              symbol, status, direction, trigger_pct, current_pct,
              triggered_at, last_notified_at, acknowledged
            ) VALUES (?, 'active', ?, ?, ?, ?, ?, 0)
            """,
            (symbol, direction, trigger_pct, trigger_pct, triggered_at, last_notified_at),
        )
        return int(cur.lastrowid)


def update_alert(
    db_path: Path,
    alert_id: int,
    *,
    current_pct: float | None = None,
    last_notified_at: str | None = None,
    acknowledged: bool | None = None,
    acked_at: str | None = None,
) -> None:
    sets: list[str] = []
    vals: list[Any] = []
    if current_pct is not None:
        sets.append("current_pct = ?")
        vals.append(current_pct)
    if last_notified_at is not None:
        sets.append("last_notified_at = ?")
        vals.append(last_notified_at)
    if acknowledged is not None:
        sets.append("acknowledged = ?")
        vals.append(1 if acknowledged else 0)
    if acked_at is not None:
        sets.append("acked_at = ?")
        vals.append(acked_at)
    if not sets:
        return
    vals.append(alert_id)
    with _connect(db_path) as conn:
        conn.execute(f"UPDATE alerts SET {', '.join(sets)} WHERE id = ?", vals)


def resolve_alert(db_path: Path, alert_id: int, current_pct: float, reason: str) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            """
            UPDATE alerts
            SET status = 'resolved', current_pct = ?, resolved_at = ?, resolved_reason = ?
            WHERE id = ?
            """,
            (current_pct, utc_now_iso(), reason, alert_id),
        )


def upsert_symbol_snapshot(
    db_path: Path,
    symbol: str,
    pct_change: float | None,
    active: bool,
    acknowledged: bool,
) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO symbol_snapshots(symbol, pct_change, active, acknowledged, updated_at)
            VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
              pct_change = excluded.pct_change,
              active = excluded.active,
              acknowledged = excluded.acknowledged,
              updated_at = excluded.updated_at
            """,
            (symbol, pct_change, 1 if active else 0, 1 if acknowledged else 0, utc_now_iso()),
        )


def get_active_alerts(db_path: Path) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, symbol, direction, trigger_pct, current_pct, triggered_at,
                   last_notified_at, acknowledged, acked_at
            FROM alerts
            WHERE status = 'active'
            ORDER BY triggered_at DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def get_alert_history(db_path: Path, limit: int = 200) -> list[dict[str, Any]]:
    safe_limit = max(1, min(limit, 1000))
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, symbol, status, direction, trigger_pct, current_pct,
                   triggered_at, last_notified_at, acknowledged, acked_at,
                   resolved_at, resolved_reason
            FROM alerts
            ORDER BY triggered_at DESC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def restore_active_alerts(db_path: Path) -> list[dict[str, Any]]:
    return get_active_alerts(db_path)


def count_active_alerts(db_path: Path) -> int:
    with _connect(db_path) as conn:
        row = conn.execute("SELECT COUNT(1) AS c FROM alerts WHERE status = 'active'").fetchone()
    return int(row["c"] if row else 0)
