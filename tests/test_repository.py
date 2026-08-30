"""Repository tests: the basic operations on a single story.

The repository does not commit by itself - the transactions are closed here
explicitly, the way the layer above does it in the application.

No assertion reaches for an ORM attribute after a commit: the values needed
(the primary key, the timestamp) are read right after create_story, once the
flush has assigned them and the object is still fresh. That keeps the tests
independent of whether the session fixture sets expire_on_commit to False.
"""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ap_dataservice.repository import (
    create_story,
    delete_story,
    get_story,
    update_story,
)
from ap_dataservice.schemas import StoryCreate, StoryUpdate


def _story(**overrides: Any) -> StoryCreate:
    """A complete story payload, with the fields a test cares about replaced."""
    fields: dict[str, Any] = {
        "hn_id": 38101234,
        "title": "Show HN: A self-hosted Postgres backup tool",
        "url": "https://github.com/example/pgbackup",
        "site": "github.com",
        "author": "pg_hacker",
        "points": 128,
        "num_comments": 43,
        "rank": 1,
        "topic": "databases",
        "posted_at": datetime(2026, 8, 29, 6, 12, tzinfo=timezone.utc),
        "scraped_at": datetime(2026, 8, 29, 8, 0, tzinfo=timezone.utc),
    }
    fields.update(overrides)
    return StoryCreate(**fields)


async def test_create_story_assigns_id_and_created_at(session: AsyncSession) -> None:
    """After the write the story carries a primary key and a timestamp."""
    story = await create_story(session, _story())
    # The database assigns both fields on flush: id as the primary key and
    # created_at through server_default. We read them before the commit,
    # because afterwards the attribute access would depend on fixture settings.
    story_id = story.id
    created_at = story.created_at
    await session.commit()

    assert story_id is not None
    assert created_at is not None


async def test_get_story_returns_existing_story(session: AsyncSession) -> None:
    """A fetch by primary key returns the story written earlier."""
    story = await create_story(session, _story())
    story_id = story.id
    await session.commit()

    found = await get_story(session, story_id)

    assert found is not None
    assert found.hn_id == 38101234


async def test_get_story_returns_none_for_unknown_id(session: AsyncSession) -> None:
    """A missing story is None, not an exception - the HTTP layer decides."""
    assert await get_story(session, 99999) is None


async def test_update_story_leaves_omitted_fields_alone(session: AsyncSession) -> None:
    """A partial update changes only the fields passed in the request."""
    story = await create_story(session, _story(points=128))
    story_id = story.id
    await session.commit()

    # A later scrape sees the same entry with a higher score and nothing else
    # changed - exactly the shape of the update the importer sends.
    await update_story(session, story, StoryUpdate(points=256))
    await session.commit()

    # expunge_all empties the session identity map, so the fetch below goes to
    # the database rather than to an object kept in memory - otherwise the test
    # would pass even if the change had never been written.
    session.expunge_all()
    reloaded = await get_story(session, story_id)

    assert reloaded is not None
    assert reloaded.points == 256
    assert reloaded.site == "github.com"
    assert reloaded.title == "Show HN: A self-hosted Postgres backup tool"


async def test_update_story_explicit_none_clears_field(session: AsyncSession) -> None:
    """A field explicitly set to None gets cleared.

    This is the other side of exclude_unset: leaving a field out keeps its
    value, while an explicit None erases it.
    """
    story = await create_story(session, _story(site="github.com"))
    story_id = story.id
    await session.commit()

    await update_story(session, story, StoryUpdate(site=None))
    await session.commit()

    session.expunge_all()
    reloaded = await get_story(session, story_id)

    assert reloaded is not None
    assert reloaded.site is None


async def test_delete_story_removes_the_story(session: AsyncSession) -> None:
    """After the delete and the commit the story can no longer be fetched."""
    story = await create_story(session, _story())
    story_id = story.id
    await session.commit()

    await delete_story(session, story)
    await session.commit()

    assert await get_story(session, story_id) is None
