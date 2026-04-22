from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def write_state(path: Path, payload: dict[str, Any]) -> None:
    ensure_parent(path)
    payload = {**payload, "updated_at": _iso_now()}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def read_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"status": "starting", "alerts": [], "symbols": []}
    return json.loads(path.read_text(encoding="utf-8"))


def enqueue_command(path: Path, command: dict[str, Any]) -> None:
    ensure_parent(path)
    command = {**command, "queued_at": _iso_now()}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(command) + "\n")


def drain_commands(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("", encoding="utf-8")
    out: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
