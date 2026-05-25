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
    fli_request_delay_seconds: float = Field(3.0, alias="FLI_REQUEST_DELAY_SECONDS")
    fli_max_retries: int = Field(1, alias="FLI_MAX_RETRIES")
    fli_timeout_seconds: float = Field(60.0, alias="FLI_TIMEOUT_SECONDS")
    discovery_candidates_per_category: int = Field(10, alias="DISCOVERY_CANDIDATES_PER_CATEGORY")
    discovery_category_workers: int = Field(3, alias="DISCOVERY_CATEGORY_WORKERS")
    discovery_interval_hours: int = Field(1, alias="DISCOVERY_INTERVAL_HOURS")
    exact_search_delay_seconds: float = Field(1.0, alias="EXACT_SEARCH_DELAY_SECONDS")
    exact_search_top_n: int = Field(3, alias="EXACT_SEARCH_TOP_N")
    best_value_exact_sort: str = Field("TOP_FLIGHTS", alias="BEST_VALUE_EXACT_SORT")
    best_value_max_price_premium_cad: int = Field(
        300,
        alias="BEST_VALUE_MAX_PRICE_PREMIUM_CAD",
    )
    best_value_max_price_premium_ratio: float = Field(
        1.25,
        alias="BEST_VALUE_MAX_PRICE_PREMIUM_RATIO",
    )
    report_max_deal_age_hours: int = Field(2, alias="REPORT_MAX_DEAL_AGE_HOURS")
    market_baseline_days: int = Field(90, alias="MARKET_BASELINE_DAYS")
    market_min_history_rows: int = Field(20, alias="MARKET_MIN_HISTORY_ROWS")
    flash_alert_median_ratio: float = Field(0.70, alias="FLASH_ALERT_MEDIAN_RATIO")
    flash_alert_absolute_fallback_cad: int = Field(
        750,
        alias="FLASH_ALERT_ABSOLUTE_FALLBACK_CAD",
    )
    suspicious_price_average_ratio: float = Field(
        0.20,
        alias="SUSPICIOUS_PRICE_AVERAGE_RATIO",
    )
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
