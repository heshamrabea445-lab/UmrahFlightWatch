from app.config import Settings


def test_exact_search_delay_default_is_zero() -> None:
    settings = Settings(_env_file=None, database_url="postgresql+psycopg://u:p@localhost/db")

    assert settings.exact_search_delay_seconds == 0.0


def test_exact_search_delay_can_be_overridden() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://u:p@localhost/db",
        exact_search_delay_seconds=3.0,
    )

    assert settings.exact_search_delay_seconds == 3.0
