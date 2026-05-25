from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    telegram_bot_token: str = Field("", alias="TELEGRAM_BOT_TOKEN")
    telegram_channel_id: str = Field("", alias="TELEGRAM_CHANNEL_ID")
    telegram_admin_chat_id: str = Field("", alias="TELEGRAM_ADMIN_CHAT_ID")
    database_url: str = Field("", alias="DATABASE_URL")
    feedback_form_url: str = Field("", alias="FEEDBACK_FORM_URL")
    app_timezone: str = Field("America/Toronto", alias="APP_TIMEZONE")
    dry_run: bool = Field(True, alias="DRY_RUN")
    fli_request_delay_seconds: float = Field(0.0, alias="FLI_REQUEST_DELAY_SECONDS")
    fli_max_retries: int = Field(0, alias="FLI_MAX_RETRIES")
    discovery_candidates_per_category: int = Field(10, alias="DISCOVERY_CANDIDATES_PER_CATEGORY")
    discovery_category_workers: int = Field(3, alias="DISCOVERY_CATEGORY_WORKERS")
    discovery_interval_hours: int = Field(1, alias="DISCOVERY_INTERVAL_HOURS")
    exact_search_delay_seconds: float = Field(0.0, alias="EXACT_SEARCH_DELAY_SECONDS")
    report_max_deal_age_hours: int = Field(2, alias="REPORT_MAX_DEAL_AGE_HOURS")
    market_baseline_days: int = Field(90, alias="MARKET_BASELINE_DAYS")
    price_history_days: int = Field(90, alias="PRICE_HISTORY_DAYS")
    raw_result_retention_days: int = Field(14, alias="RAW_RESULT_RETENTION_DAYS")
    log_level: str = Field("INFO", alias="LOG_LEVEL")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
