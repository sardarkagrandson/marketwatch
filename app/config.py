"""Application settings loaded from environment / .env."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "MarketWatch"
    data_dir: Path = Field(default=PROJECT_ROOT / "data")
    offline_mode: bool = False
    market_holidays: str = ""

    anthropic_api_key: str = ""
    sentiment_model: str = "claude-opus-5-5"

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    smtp_from: str = "alerts@example.com"

    quote_cache_seconds: int = 60
    history_cache_seconds: int = 900
    news_cache_seconds: int = 1800

    @property
    def resolved_data_dir(self) -> Path:
        d = self.data_dir if self.data_dir.is_absolute() else PROJECT_ROOT / self.data_dir
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.resolved_data_dir / 'marketwatch.db'}"

    @property
    def jobstore_url(self) -> str:
        return f"sqlite:///{self.resolved_data_dir / 'jobs.db'}"

    @property
    def holiday_set(self) -> set[str]:
        return {h.strip() for h in self.market_holidays.split(",") if h.strip()}

    @property
    def llm_enabled(self) -> bool:
        return bool(self.anthropic_api_key) and not self.offline_mode

    @property
    def smtp_enabled(self) -> bool:
        return bool(self.smtp_host)


@lru_cache
def get_settings() -> Settings:
    return Settings()
