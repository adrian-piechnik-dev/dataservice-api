"""Tests for reading the configuration from the environment."""

import pytest
from pydantic import ValidationError

from ap_dataservice.config import Settings


def _clear_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Removes variables that could leak in from the real environment."""
    for name in (
        "DATABASE_URL",
        "API_KEY",
        "DEFAULT_PAGE_SIZE",
        "MAX_PAGE_SIZE",
        "MAX_OFFSET",
        "ALLOWED_HOSTS",
        "APP_TITLE",
        "APP_DESCRIPTION",
        "APP_VERSION",
    ):
        monkeypatch.delenv(name, raising=False)


def test_reads_values_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_settings_env(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
    monkeypatch.setenv("API_KEY", "secret-123")

    settings = Settings(_env_file=None)

    assert settings.database_url == "sqlite+aiosqlite:///./test.db"
    assert settings.api_key == "secret-123"


def test_applies_defaults_for_optional_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_settings_env(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
    monkeypatch.setenv("API_KEY", "secret-123")

    settings = Settings(_env_file=None)

    assert settings.default_page_size == 50
    assert settings.max_page_size == 200


def test_applies_defaults_for_request_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    """The offset ceiling and the host allow-list ship with working defaults.

    A deployment that sets neither still refuses deep paging and still checks
    the Host header - the protection is not opt-in.
    """
    _clear_settings_env(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
    monkeypatch.setenv("API_KEY", "secret-123")

    settings = Settings(_env_file=None)

    assert settings.max_offset == 100_000
    assert settings.allowed_hosts == "localhost,127.0.0.1,*.onrender.com"
    assert settings.allowed_hosts_list == ["localhost", "127.0.0.1", "*.onrender.com"]


def test_allowed_hosts_list_splits_and_drops_blanks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Whitespace and a stray comma are the environment's doing, not a host.

    A blank entry left in the list would become a pattern matching nothing,
    which is harmless but hides a typo instead of surviving it.
    """
    _clear_settings_env(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
    monkeypatch.setenv("API_KEY", "secret-123")
    monkeypatch.setenv("ALLOWED_HOSTS", " api.example.com , localhost ,, ")

    settings = Settings(_env_file=None)

    assert settings.allowed_hosts_list == ["api.example.com", "localhost"]


def test_coerces_numeric_string_to_int(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_settings_env(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
    monkeypatch.setenv("API_KEY", "secret-123")
    monkeypatch.setenv("DEFAULT_PAGE_SIZE", "25")

    settings = Settings(_env_file=None)

    assert settings.default_page_size == 25


def test_missing_required_field_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_settings_env(monkeypatch)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_applies_defaults_for_metadata_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    """Metadata has defaults, so .env need not supply any of it."""
    _clear_settings_env(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
    monkeypatch.setenv("API_KEY", "secret-123")

    settings = Settings(_env_file=None)

    assert settings.app_title == "dataservice-api"
    assert settings.app_description == (
        "REST API serving Hacker News front-page stories collected by the "
        "smartscraper-ai pipeline. Async FastAPI + SQLAlchemy 2.0 over "
        "PostgreSQL, with API-key auth, filtering, pagination and Alembic "
        "migrations."
    )
    assert settings.app_version == "0.1.0"


def test_reads_app_title_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """The name shown in /docs comes from the environment when one is set."""
    _clear_settings_env(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
    monkeypatch.setenv("API_KEY", "secret-123")
    monkeypatch.setenv("APP_TITLE", "Inna nazwa")

    settings = Settings(_env_file=None)

    assert settings.app_title == "Inna nazwa"


def test_reads_app_description_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The API description is configurable too - deployments differ."""
    _clear_settings_env(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
    monkeypatch.setenv("API_KEY", "secret-123")
    monkeypatch.setenv("APP_DESCRIPTION", "Inny opis")

    settings = Settings(_env_file=None)

    assert settings.app_description == "Inny opis"


def test_reads_app_version_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """The version given to clients may come from the deployment."""
    _clear_settings_env(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
    monkeypatch.setenv("API_KEY", "secret-123")
    monkeypatch.setenv("APP_VERSION", "9.9.9")

    settings = Settings(_env_file=None)

    assert settings.app_version == "9.9.9"
