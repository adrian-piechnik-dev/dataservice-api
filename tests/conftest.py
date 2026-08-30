"""Shared test fixtures: an isolated in-memory database and a session to it."""

from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from ap_api.models import Base


@pytest.fixture
async def engine() -> AsyncGenerator[AsyncEngine, None]:
    """Test engine on in-memory SQLite, with the table schema already created.

    Function scope: every test gets its own empty database, so neither data nor
    execution order carries over between tests.
    """
    # StaticPool keeps one connection and hands it out over and over. A
    # ":memory:" database exists only within its connection, so with an ordinary
    # pool every new connection would see its own empty database - without the
    # tables created above. check_same_thread=False: the same connection gets
    # served by different threads of the aiosqlite executor pool.
    test_engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    # create_all is synchronous, so we run it through run_sync on the
    # synchronous connection wrapped by the async engine.
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield test_engine

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await test_engine.dispose()


@pytest.fixture
async def session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """An open session bound to the test engine.

    expire_on_commit=False - as in the application: after a commit the objects
    stay usable without querying the database again.
    """
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as test_session:
        yield test_session
