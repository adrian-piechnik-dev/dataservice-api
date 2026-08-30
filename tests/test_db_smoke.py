"""Smoke test of the database layer: writing and reading back a story."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ap_dataservice.models import Story


async def test_story_roundtrip(session: AsyncSession) -> None:
    """A saved story reads back, and the database fills id and created_at."""
    session.add(
        Story(
            hn_id=38101234,
            title="Show HN: A self-hosted Postgres backup tool",
            url="https://github.com/example/pgbackup",
            site="github.com",
            author="pg_hacker",
            rank=1,
            posted_at=datetime(2026, 8, 29, 6, 12, tzinfo=timezone.utc),
            scraped_at=datetime(2026, 8, 29, 8, 0, tzinfo=timezone.utc),
        )
    )
    await session.commit()

    story = (await session.scalars(select(Story))).first()

    assert story is not None
    assert story.hn_id == 38101234
    assert story.title == "Show HN: A self-hosted Postgres backup tool"
    # The counters were left out of the insert, so the column defaults filled
    # them in: a freshly scraped entry starts at zero, not at NULL.
    assert story.points == 0
    assert story.num_comments == 0
    assert story.is_hiring is False
    assert story.id is not None
    assert story.created_at is not None
