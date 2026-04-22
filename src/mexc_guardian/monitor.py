from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

import ccxt.async_support as ccxt

from .config import Settings
from .db import (
    create_alert,
    drain_commands as drain_db_commands,
    init_db,
    queue_ack_command,
    resolve_alert,
    restore_active_alerts,
    update_alert,
    upsert_symbol_snapshot,
)
from .models import AlertState, SymbolRuntime
from .state_store import drain_commands, write_state
from .telegram_client import TelegramClient

logger = logging.getLogger(__name__)


class MonitorService:
    def __init__(self, settings: Settings, telegram: TelegramClient):
        self.settings = settings
        self.telegram = telegram
        self.window = timedelta(hours=settings.window_hours)
        self.repeat_gap = timedelta(minutes=settings.repeat_alert_minutes)
        self.symbols: dict[str, SymbolRuntime] = {}
        self.symbol_aliases: dict[str, str] = {}
        self.exchange = ccxt.mexc({"enableRateLimit": True, "options": {"defaultType": "swap"}})
        self._restored_alerts = False
        init_db(Path(self.settings.sqlite_db_path))

    async def run(self) -> None:
        logger.info("Starting monitor service")
        if self.telegram.enabled:
            asyncio.create_task(self.telegram.poll_commands(self.on_telegram_command))
        while True:
            try:
                await self.run_cycle()
            except Exception as exc:  # noqa: BLE001
                logger.exception("Monitor cycle failed: %s", exc)
            await asyncio.sleep(self.settings.poll_seconds)

    async def run_cycle(self) -> None:
        await self._discover_symbols()
        tickers = await self.exchange.fetch_tickers()
        now = datetime.now(timezone.utc)
        threshold = self.settings.percent_threshold

        for symbol, rt in self.symbols.items():
            ticker = tickers.get(symbol)
            if not ticker:
                continue
            last = ticker.get("last")
            if last is None:
                continue

            last = float(last)
            rt.prices.append((now, last))
            self._trim(rt.prices, now)

            if len(rt.prices) >= 2:
                baseline = rt.prices[0][1]
                pct = ((last - baseline) / baseline) * 100
                rt.last_pct_change = pct
            else:
                pct = rt.last_pct_change if rt.last_pct_change is not None else 0.0

            if rt.active_alert is not None:
                rt.active_alert.pct_change = pct
                await self._notify_repeat_if_due(rt.active_alert, now)
                if rt.active_alert.db_id is not None:
                    update_alert(Path(self.settings.sqlite_db_path), rt.active_alert.db_id, current_pct=pct)

            if now - rt.prices[0][0] >= self.window:
                if rt.active_alert is None:
                    if abs(pct) >= threshold and rt.cooldown_armed:
                        db_id = create_alert(
                            Path(self.settings.sqlite_db_path),
                            symbol=symbol,
                            direction="up" if pct >= 0 else "down",
                            trigger_pct=pct,
                            triggered_at=now.isoformat(),
                            last_notified_at=now.isoformat(),
                        )
                        rt.active_alert = AlertState(
                            db_id=db_id,
                            symbol=symbol,
                            pct_change=pct,
                            triggered_at=now,
                            direction="up" if pct >= 0 else "down",
                        )
                        await self._notify_trigger(rt.active_alert)
                        rt.cooldown_armed = False

                if abs(pct) < threshold:
                    if rt.active_alert and rt.active_alert.acknowledged and self.settings.retrigger_after_ack:
                        if rt.active_alert.db_id is not None:
                            resolve_alert(
                                Path(self.settings.sqlite_db_path),
                                rt.active_alert.db_id,
                                current_pct=pct,
                                reason="normalized_after_ack",
                            )
                        rt.active_alert = None
                        rt.cooldown_armed = True
                    elif rt.active_alert is None:
                        rt.cooldown_armed = True

            upsert_symbol_snapshot(
                Path(self.settings.sqlite_db_path),
                symbol=symbol,
                pct_change=rt.last_pct_change,
                active=rt.active_alert is not None,
                acknowledged=rt.active_alert.acknowledged if rt.active_alert else False,
            )

        self._process_commands()
        self._persist(now)

    async def _discover_symbols(self) -> None:
        if self.symbols:
            return
        markets = await self.exchange.load_markets()
        for symbol, m in markets.items():
            if not m.get("active", True):
                continue
            if not m.get("swap", False):
                continue
            if m.get("quote") != self.settings.quote_currency:
                continue
            self.symbols[symbol] = SymbolRuntime(symbol=symbol, prices=deque())
            self._register_symbol_aliases(symbol)
        logger.info("Discovered %s symbols", len(self.symbols))

        if not self._restored_alerts:
            self._restore_active_alerts()
            self._restored_alerts = True

    def _restore_active_alerts(self) -> None:
        rows = restore_active_alerts(Path(self.settings.sqlite_db_path))
        for row in rows:
            symbol = row["symbol"]
            rt = self.symbols.get(symbol)
            if not rt:
                continue
            triggered_at = self._parse_iso(row["triggered_at"])
            last_notified = self._parse_iso(row["last_notified_at"]) if row["last_notified_at"] else None
            rt.active_alert = AlertState(
                db_id=int(row["id"]),
                symbol=symbol,
                pct_change=float(row["current_pct"]),
                triggered_at=triggered_at,
                last_notified_at=last_notified,
                acknowledged=bool(row["acknowledged"]),
                direction=str(row["direction"]),
            )
            rt.cooldown_armed = False

    def _trim(self, price_deque: deque[tuple[datetime, float]], now: datetime) -> None:
        oldest = now - self.window
        while price_deque and price_deque[0][0] < oldest:
            price_deque.popleft()

    async def _notify_trigger(self, alert: AlertState) -> None:
        alert.last_notified_at = datetime.now(timezone.utc)
        if alert.db_id is not None:
            update_alert(
                Path(self.settings.sqlite_db_path),
                alert.db_id,
                last_notified_at=alert.last_notified_at.isoformat(),
            )
        text = (
            f"ALERT TRIGGERED\n"
            f"Symbol: {alert.symbol}\n"
            f"4h Change: {alert.pct_change:.2f}%\n"
            f"Direction: {alert.direction}\n"
            f"Threshold: {self.settings.percent_threshold:.2f}%\n"
            f"Ack: /ack {alert.symbol} or /ack"
        )
        await self.telegram.send(text)

    async def _notify_repeat_if_due(self, alert: AlertState, now: datetime) -> None:
        if alert.acknowledged:
            return
        if alert.last_notified_at is None:
            await self._notify_trigger(alert)
            return
        if now - alert.last_notified_at < self.repeat_gap:
            return
        alert.last_notified_at = now
        if alert.db_id is not None:
            update_alert(Path(self.settings.sqlite_db_path), alert.db_id, last_notified_at=now.isoformat())
        await self.telegram.send(
            f"REMINDER\n{alert.symbol} still active at {alert.pct_change:.2f}%\nAck: /ack {alert.symbol}"
        )

    def _persist(self, now: datetime) -> None:
        alerts = []
        for rt in self.symbols.values():
            if not rt.active_alert:
                continue
            a = rt.active_alert
            alerts.append(
                {
                    "id": a.db_id,
                    "symbol": a.symbol,
                    "pct_change": round(a.pct_change, 4),
                    "direction": a.direction,
                    "triggered_at": a.triggered_at.isoformat(),
                    "last_notified_at": a.last_notified_at.isoformat() if a.last_notified_at else None,
                    "acknowledged": a.acknowledged,
                }
            )
        symbols = [
            {
                "symbol": rt.symbol,
                "pct_change": round(rt.last_pct_change, 4) if rt.last_pct_change is not None else None,
                "active": rt.active_alert is not None,
                "acknowledged": rt.active_alert.acknowledged if rt.active_alert else False,
            }
            for rt in self.symbols.values()
        ]
        payload = {
            "status": "running",
            "exchange": self.settings.exchange_id,
            "market_type": self.settings.market_type,
            "window_hours": self.settings.window_hours,
            "threshold": self.settings.percent_threshold,
            "symbols_count": len(self.symbols),
            "alerts": alerts,
            "symbols": symbols,
            "now": now.isoformat(),
        }
        write_state(self.settings.state_file, payload)

    async def on_telegram_command(self, cmd: str) -> None:
        if not cmd.startswith("/ack"):
            return
        parts = cmd.split()
        symbol = parts[1].upper() if len(parts) > 1 else None
        queue_ack_command(Path(self.settings.sqlite_db_path), symbol, source="telegram")

    def _process_commands(self) -> None:
        legacy = drain_commands(self.settings.command_file)
        db_commands = drain_db_commands(Path(self.settings.sqlite_db_path))
        commands = legacy + db_commands
        for command in commands:
            if command.get("type") != "ack":
                continue
            symbol = command.get("symbol")
            if symbol:
                self._ack_symbol(str(symbol).upper())
            else:
                self._ack_all()

    def _ack_symbol(self, symbol: str) -> None:
        resolved = self._resolve_symbol(symbol)
        rt = self.symbols.get(resolved) if resolved else None
        if not rt or not rt.active_alert:
            return
        rt.active_alert.acknowledged = True
        now = datetime.now(timezone.utc).isoformat()
        if rt.active_alert.db_id is not None:
            update_alert(
                Path(self.settings.sqlite_db_path),
                rt.active_alert.db_id,
                acknowledged=True,
                acked_at=now,
                current_pct=rt.active_alert.pct_change,
            )

    def _ack_all(self) -> None:
        for rt in self.symbols.values():
            if rt.active_alert:
                rt.active_alert.acknowledged = True
                now = datetime.now(timezone.utc).isoformat()
                if rt.active_alert.db_id is not None:
                    update_alert(
                        Path(self.settings.sqlite_db_path),
                        rt.active_alert.db_id,
                        acknowledged=True,
                        acked_at=now,
                        current_pct=rt.active_alert.pct_change,
                    )

    @staticmethod
    def _parse_iso(value: str) -> datetime:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed

    def _register_symbol_aliases(self, symbol: str) -> None:
        base = symbol.upper()
        compact = base.replace("/", "").replace(":", "")
        no_settle = base.split(":", maxsplit=1)[0].replace("/", "")
        self.symbol_aliases[base] = symbol
        self.symbol_aliases[compact] = symbol
        self.symbol_aliases[no_settle] = symbol

    def _resolve_symbol(self, symbol: str) -> str | None:
        key = symbol.strip().upper()
        if not key:
            return None
        if key in self.symbols:
            return key
        return self.symbol_aliases.get(key)
