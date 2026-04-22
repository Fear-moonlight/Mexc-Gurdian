from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    timezone: str = Field(default="Asia/Kuala_Lumpur", alias="TIMEZONE")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    percent_threshold: float = Field(default=10.0, alias="PERCENT_THRESHOLD")
    window_hours: int = Field(default=4, alias="WINDOW_HOURS")
    poll_seconds: int = Field(default=60, alias="POLL_SECONDS")
    repeat_alert_minutes: int = Field(default=10, alias="REPEAT_ALERT_MINUTES")
    require_manual_ack: bool = Field(default=True, alias="REQUIRE_MANUAL_ACK")
    retrigger_after_ack: bool = Field(default=True, alias="RETRIGGER_AFTER_ACK")

    exchange_id: str = Field(default="mexc", alias="EXCHANGE_ID")
    market_type: str = Field(default="futures", alias="MARKET_TYPE")
    quote_currency: str = Field(default="USDT", alias="QUOTE_CURRENCY")
    include_all_usdt_pairs: bool = Field(default=True, alias="INCLUDE_ALL_USDT_PAIRS")

    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str = Field(default="", alias="TELEGRAM_CHAT_ID")
    telegram_poll_seconds: int = Field(default=5, alias="TELEGRAM_POLL_SECONDS")

    state_file: Path = Field(default=Path("./data/state.json"), alias="STATE_FILE")
    command_file: Path = Field(default=Path("./data/commands.jsonl"), alias="COMMAND_FILE")
    sqlite_db_path: Path = Field(default=Path("./data/mexc_gurdian.db"), alias="SQLITE_DB_PATH")
    web_host: str = Field(default="0.0.0.0", alias="WEB_HOST")
    web_port: int = Field(default=8080, alias="WEB_PORT")


settings = Settings()
