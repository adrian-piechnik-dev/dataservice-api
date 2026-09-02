"""Database access layer: the engine, the session factory and a dependency."""

from collections.abc import AsyncGenerator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ap_dataservice.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    """Returns the shared async engine, built on first use.

    Lazy on purpose: importing this module must not read the settings or open
    a connection pool, so a misconfigured environment fails at startup with a
    readable error instead of an ImportError. @lru_cache keeps one engine per
    process, so the connection pool is created exactly once.

    pool_pre_ping=True: a pooled connection is checked out with a cheap probe
    first. Managed Postgres and connection poolers drop idle connections, and
    without the probe the first request after a quiet spell would hand the
    handler a dead connection and answer 500.
    """
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Returns the session factory bound to the shared engine.

    expire_on_commit=False: objects stay usable after a commit (no extra query
    when an attribute is read, e.g. while the response is being serialised).
    """
    return async_sessionmaker(bind=get_engine(), expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: hands out a session for the length of one request.

    The session is closed automatically once the request finishes, including
    when the handler raises.
    """
    async with get_session_factory()() as session:
        yield session
