from app.admin.telegram_admin import is_authorized_admin
from app.config import Settings


def test_admin_permission_uses_configured_chat_id_only() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://u:p@localhost/db",
        telegram_admin_chat_id="12345",
    )

    assert is_authorized_admin(12345, settings)
    assert not is_authorized_admin(67890, settings)
    assert not is_authorized_admin(None, settings)
