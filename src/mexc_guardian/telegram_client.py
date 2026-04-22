from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Callable

import aiohttp

logger = logging.getLogger(__name__)


@dataclass
class TelegramConfig:
    token: str
    chat_id: str
    poll_seconds: int = 5


class TelegramClient:
    def __init__(self, cfg: TelegramConfig):
        self.cfg = cfg
        self.base_url = f"https://api.telegram.org/bot{cfg.token}"
        self._offset = 0

    @property
    def enabled(self) -> bool:
        return bool(self.cfg.token and self.cfg.chat_id)

    async def send(self, text: str) -> None:
        if not self.enabled:
            logger.warning("Telegram is not enabled. Skipping alert: %s", text)
            return
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/sendMessage",
                json={"chat_id": self.cfg.chat_id, "text": text},
                timeout=20,
            ) as r:
                if r.status >= 300:
                    body = await r.text()
                    logger.error("Telegram send failed (%s): %s", r.status, body)

    async def poll_commands(self, on_command: Callable[[str], asyncio.Future]) -> None:
        if not self.enabled:
            return
        while True:
            try:
                await self._poll_once(on_command)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Telegram polling error: %s", exc)
            await asyncio.sleep(self.cfg.poll_seconds)

    async def _poll_once(self, on_command: Callable[[str], asyncio.Future]) -> None:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.base_url}/getUpdates",
                params={"timeout": 0, "offset": self._offset + 1},
                timeout=20,
            ) as r:
                if r.status >= 300:
                    return
                data = await r.json()
        for item in data.get("result", []):
            self._offset = max(self._offset, item.get("update_id", 0))
            message = item.get("message") or {}
            text = (message.get("text") or "").strip()
            if not text.startswith("/"):
                continue
            await on_command(text)
