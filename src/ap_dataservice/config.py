"""Application configuration read from environment variables."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings.

    Values are read from environment variables, and locally from a .env file.
    A missing required value or a wrong type stops the application from starting.
    """

    database_url: str
    api_key: str
    default_page_size: int = 50
    max_page_size: int = 200

    # Metadata shown in /docs and openapi.json. The title and version mirror
    # the [project] section of pyproject.toml - a test guards that the version
    # numbers stay in step, because the two are written down separately. The
    # description does not: pyproject carries a one-line package summary,
    # while /docs has room to say what the service actually serves.
    app_title: str = "dataservice-api"
    app_description: str = (
        "REST API serving Hacker News front-page stories collected by the "
        "smartscraper-ai pipeline. Async FastAPI + SQLAlchemy 2.0 over "
        "PostgreSQL, with API-key auth, filtering, pagination and Alembic "
        "migrations."
    )
    app_version: str = "0.1.0"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Returns the single, shared settings instance."""
    return Settings()
