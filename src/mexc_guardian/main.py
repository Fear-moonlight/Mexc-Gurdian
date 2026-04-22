from __future__ import annotations

import asyncio
import logging

from .config import settings
from .monitor import MonitorService
from .telegram_client import TelegramClient, TelegramConfig


def configure_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


async def _run() -> None:
    telegram = TelegramClient(
        TelegramConfig(
            token=settings.telegram_bot_token,
            chat_id=settings.telegram_chat_id,
            poll_seconds=settings.telegram_poll_seconds,
        )
    )
    service = MonitorService(settings, telegram)
    await service.run()


def main() -> None:
    configure_logging()
    asyncio.run(_run())


if __name__ == "__main__":
    main()
