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


def test_currency_defaults_are_cad() -> None:
    settings = Settings(_env_file=None, database_url="postgresql+psycopg://u:p@localhost/db")

    assert settings.fli_default_price_currency == "CAD"
    assert settings.usd_to_cad_rate == 1.37
    assert settings.fli_call_timeout_seconds == 90.0


def test_currency_settings_can_be_overridden() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://u:p@localhost/db",
        fli_default_price_currency="USD",
        fli_call_timeout_seconds=45.0,
        usd_to_cad_rate=1.41,
    )

    assert settings.fli_default_price_currency == "USD"
    assert settings.fli_call_timeout_seconds == 45.0
    assert settings.usd_to_cad_rate == 1.41
