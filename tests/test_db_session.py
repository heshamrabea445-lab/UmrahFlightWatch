from app.db.session import normalize_database_url


def test_normalize_database_url_uses_installed_psycopg_driver() -> None:
    url = normalize_database_url("postgresql://user:pass@example.com/db")

    assert url == "postgresql+psycopg://user:pass@example.com/db"


def test_normalize_database_url_keeps_explicit_driver() -> None:
    url = normalize_database_url("postgresql+psycopg://user:pass@example.com/db")

    assert url == "postgresql+psycopg://user:pass@example.com/db"
