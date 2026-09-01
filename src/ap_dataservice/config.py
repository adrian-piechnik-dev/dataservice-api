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

    # Upper bound for offset. Paging past this point makes the database build
    # and throw away the whole prefix on every request, and the data set is one
    # Hacker News front page per scrape - a client that far in should be
    # filtering or sorting, not turning pages.
    max_offset: int = 100_000

    # Host names the service answers to, checked by TrustedHostMiddleware. A
    # comma-separated string rather than a list: every other field here is a
    # scalar, and pydantic-settings would read a list from the environment as
    # JSON, which turns a missing bracket into a service that will not start.
    # Read it through allowed_hosts_list, never by splitting at the call site.
    allowed_hosts: str = "localhost,127.0.0.1,*.onrender.com"

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

    @property
    def allowed_hosts_list(self) -> list[str]:
        """The allowed_hosts string as the list the middleware expects.

        Blank entries are dropped, so a trailing comma or a stray space in the
        environment does not turn into a host pattern matching nothing.
        """
        return [host.strip() for host in self.allowed_hosts.split(",") if host.strip()]


@lru_cache
def get_settings() -> Settings:
    """Returns the single, shared settings instance."""
    return Settings()
