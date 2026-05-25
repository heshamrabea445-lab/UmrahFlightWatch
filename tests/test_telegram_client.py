import httpx
import pytest

from app.config import Settings
from app.services.telegram_client import TelegramClient


def test_telegram_send_failure_reports_api_body_without_token(monkeypatch: pytest.MonkeyPatch):
    def fake_post(*args, **kwargs):
        return httpx.Response(
            400,
            json={
                "ok": False,
                "description": "Bad Request: can't parse entities",
            },
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    client = TelegramClient(
        Settings(
            database_url="postgresql+psycopg://u:p@localhost/db",
            dry_run=False,
            telegram_bot_token="secret-token",
            telegram_channel_id="@channel",
        )
    )

    with pytest.raises(RuntimeError) as exc_info:
        client.post_weekly_report("broken")

    message = str(exc_info.value)
    assert "can't parse entities" in message
    assert "secret-token" not in message
