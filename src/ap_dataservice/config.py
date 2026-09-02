"""Application configuration read from environment variables."""

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings.

    Values are read from environment variables, and locally from a .env file.
    A missing required value or a wrong type stops the application from starting,
    and so does a set of pagination bounds that contradict each other - a type
    alone does not tell a working configuration from an unusable one.
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

    # Whether the writing half of the resource is served at all. The public
    # instance publishes its API key, so anybody could POST a story into the
    # data a visitor is looking at - and an edited title, unlike a deleted row,
    # leaves nothing behind to notice. False by default: a deployment that
    # wants writes has to say so, rather than a deployment that forgets to
    # think about it ending up open.
    enable_write_endpoints: bool = False

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

    @model_validator(mode="after")
    def _check_pagination_bounds(self) -> "Settings":
        """Rejects pagination bounds that describe a service nobody can use.

        Each bound has to be positive, and the default page size has to fit
        under the maximum. Otherwise the values pass validation and the service
        starts, only to answer every unparameterised listing with a 422 - a
        deployment mistake that surfaces as a runtime one, far from its cause.
        """
        for name in ("default_page_size", "max_page_size", "max_offset"):
            value: int = getattr(self, name)
            if value <= 0:
                raise ValueError(f"{name} must be greater than 0 (got {value})")

        if self.default_page_size > self.max_page_size:
            raise ValueError(
                f"default_page_size ({self.default_page_size}) must not exceed "
                f"max_page_size ({self.max_page_size})"
            )

        return self

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
