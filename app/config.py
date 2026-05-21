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
    base_currency: str = Field("CAD", alias="BASE_CURRENCY")
    dry_run: bool = Field(True, alias="DRY_RUN")
    flight_provider: str = Field("fli", alias="FLIGHT_PROVIDER")
    fli_request_delay_seconds: float = Field(3.0, alias="FLI_REQUEST_DELAY_SECONDS")
    fli_max_retries: int = Field(1, alias="FLI_MAX_RETRIES")
    fli_timeout_seconds: float = Field(60.0, alias="FLI_TIMEOUT_SECONDS")
    price_history_days: int = Field(90, alias="PRICE_HISTORY_DAYS")
    raw_result_retention_days: int = Field(14, alias="RAW_RESULT_RETENTION_DAYS")
    log_level: str = Field("INFO", alias="LOG_LEVEL")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @property
    def provider_source(self) -> str:
        return self.flight_provider.lower().strip()


@lru_cache
def get_settings() -> Settings:
    return Settings()
