from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Deque


@dataclass
class AlertState:
    db_id: int | None
    symbol: str
    pct_change: float
    triggered_at: datetime
    last_notified_at: datetime | None = None
    acknowledged: bool = False
    direction: str = "up"


@dataclass
class SymbolRuntime:
    symbol: str
    prices: Deque[tuple[datetime, float]]
    active_alert: AlertState | None = None
    cooldown_armed: bool = True
    last_pct_change: float | None = None
    metadata: dict = field(default_factory=dict)
