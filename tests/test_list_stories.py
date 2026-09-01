"""Tests for listing stories: filters, pagination and ordering.

The data set is fixed and prepared by the sample_stories fixture - each test
asks for a ready database and checks one aspect of the query.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ap_dataservice.repository import create_story, list_stories
from ap_dataservice.schemas import StoryCreate

# One scrape run stamps every entry it read with the same moment.
SCRAPED_AT = datetime(2026, 8, 29, 8, 0, tzinfo=timezone.utc)

# Test data: one front page as the scraper saw it. Two entries share
# site="github.com" and points=128 (exact-match filtering and ordering
# stability), the hiring entry is the only one with is_hiring, and the Ask HN
# self-post carries no site at all (how the filters and nulls_last treat NULL).
SAMPLE = [
    StoryCreate(
        hn_id=38101234,
        title="Show HN: A self-hosted Postgres backup tool",
        url="https://github.com/example/pgbackup",
        site="github.com",
        author="pg_hacker",
        points=128,
        num_comments=43,
        rank=1,
        topic="databases",
        posted_at=datetime(2026, 8, 29, 6, 12, tzinfo=timezone.utc),
        scraped_at=SCRAPED_AT,
    ),
    StoryCreate(
        hn_id=38102345,
        title="Rust 1.94 released",
        url="https://blog.rust-lang.org/2026/08/28/Rust-1.94.0.html",
        site="blog.rust-lang.org",
        author="steveklabnik",
        points=256,
        num_comments=310,
        rank=2,
        topic="languages",
        posted_at=datetime(2026, 8, 29, 4, 3, tzinfo=timezone.utc),
        scraped_at=SCRAPED_AT,
    ),
    StoryCreate(
        hn_id=38103456,
        title="rust-analyzer 2026.8 brings faster type inference",
        url="https://github.com/rust-lang/rust-analyzer/releases/tag/2026-08-24",
        site="github.com",
        author="matklad",
        points=128,
        num_comments=87,
        rank=3,
        topic="languages",
        posted_at=datetime(2026, 8, 29, 2, 35, tzinfo=timezone.utc),
        scraped_at=SCRAPED_AT,
    ),
    StoryCreate(
        hn_id=38104567,
        title="Sourcegraph (YC S13) Is Hiring a Compiler Engineer",
        url="https://www.ycombinator.com/companies/sourcegraph/jobs",
        site="ycombinator.com",
        author="sqs",
        points=1,
        num_comments=0,
        rank=4,
        is_hiring=True,
        company="Sourcegraph",
        posted_at=datetime(2026, 8, 28, 14, 0, tzinfo=timezone.utc),
        scraped_at=SCRAPED_AT,
    ),
    StoryCreate(
        hn_id=38105678,
        title="Ask HN: How do you keep a monorepo fast?",
        url="https://news.ycombinator.com/item?id=38105678",
        site=None,
        author="build_eng",
        points=32,
        num_comments=21,
        rank=5,
        posted_at=datetime(2026, 8, 28, 21, 47, tzinfo=timezone.utc),
        scraped_at=SCRAPED_AT,
    ),
]


@pytest.fixture
async def sample_stories(session: AsyncSession) -> None:
    """Fills the database with five stories of known fields and commits."""
    for data in SAMPLE:
        await create_story(session, data)
    await session.commit()


async def test_no_filters_returns_all_stories(
    session: AsyncSession,
    sample_stories: None,
) -> None:
    """No filters means the full list and a total equal to the story count."""
    stories, total = await list_stories(session, limit=100, offset=0)

    assert len(stories) == 5
    assert total == 5


async def test_site_filter_narrows_to_one_host(
    session: AsyncSession,
    sample_stories: None,
) -> None:
    """The site filter matches by equality, so only github.com returns."""
    stories, total = await list_stories(
        session,
        limit=100,
        offset=0,
        site="github.com",
    )

    assert sorted(story.hn_id for story in stories) == [38101234, 38103456]
    assert total == 2


async def test_points_min_drops_stories_below_the_bound(
    session: AsyncSession,
    sample_stories: None,
) -> None:
    """The bound is inclusive, so only entries at or above it stay."""
    stories, total = await list_stories(session, limit=100, offset=0, points_min=128)

    assert sorted(story.hn_id for story in stories) == [
        38101234,
        38102345,
        38103456,
    ]
    assert total == 3


async def test_points_min_and_max_form_inclusive_range(
    session: AsyncSession,
    sample_stories: None,
) -> None:
    """Both ends are inclusive, so a score exactly on the bound passes."""
    stories, total = await list_stories(
        session,
        limit=100,
        offset=0,
        points_min=128,
        points_max=128,
    )

    assert sorted(story.hn_id for story in stories) == [38101234, 38103456]
    assert total == 2


async def test_title_contains_ignores_letter_case(
    session: AsyncSession,
    sample_stories: None,
) -> None:
    """ilike matches a fragment of the title regardless of letter case."""
    stories, total = await list_stories(
        session,
        limit=100,
        offset=0,
        title_contains="rust",
    )

    assert sorted(story.hn_id for story in stories) == [38102345, 38103456]
    assert total == 2


async def test_title_contains_treats_underscore_as_literal(
    session: AsyncSession,
    sample_stories: None,
) -> None:
    """An underscore searches for an underscore, not for any single character.

    The sample carries "rust-analyzer ..." with a hyphen. Left unescaped, the
    underscore in the query would match that hyphen and the filter would return
    a story the caller never asked for.
    """
    stories, total = await list_stories(
        session,
        limit=100,
        offset=0,
        title_contains="rust_analyzer",
    )

    assert stories == []
    assert total == 0


async def test_title_contains_treats_percent_as_literal(
    session: AsyncSession,
    sample_stories: None,
) -> None:
    """A per-cent sign searches for a per-cent sign, not for everything.

    The story is created here rather than in SAMPLE: the fixture's five entries
    are the fixed count other tests assert against.
    """
    await create_story(
        session,
        StoryCreate(
            hn_id=38106789,
            title="Bun 1.2 starts 50% faster",
            url="https://bun.sh/blog/bun-v1.2",
            site="bun.sh",
            author="jarred",
            points=412,
            num_comments=155,
            rank=6,
            posted_at=datetime(2026, 8, 28, 9, 30, tzinfo=timezone.utc),
            scraped_at=SCRAPED_AT,
        ),
    )
    await session.commit()

    stories, total = await list_stories(
        session,
        limit=100,
        offset=0,
        title_contains="%",
    )

    assert [story.hn_id for story in stories] == [38106789]
    assert total == 1


async def test_is_hiring_filter_selects_and_excludes_job_posts(
    session: AsyncSession,
    sample_stories: None,
) -> None:
    """The three states of is_hiring: only jobs, everything but jobs, and all.

    None is not "False" - it means the filter is skipped entirely, so the
    listing keeps hiring and non-hiring entries alike.
    """
    hiring, hiring_total = await list_stories(
        session,
        limit=100,
        offset=0,
        is_hiring=True,
    )
    not_hiring, not_hiring_total = await list_stories(
        session,
        limit=100,
        offset=0,
        is_hiring=False,
    )
    unfiltered, unfiltered_total = await list_stories(
        session,
        limit=100,
        offset=0,
        is_hiring=None,
    )

    assert [story.hn_id for story in hiring] == [38104567]
    assert hiring_total == 1

    assert 38104567 not in [story.hn_id for story in not_hiring]
    assert not_hiring_total == 4

    assert len(unfiltered) == 5
    assert unfiltered_total == 5


async def test_total_counts_all_matches_not_the_page(
    session: AsyncSession,
    sample_stories: None,
) -> None:
    """limit trims the list, but total stays the count of every match."""
    stories, total = await list_stories(
        session,
        limit=2,
        offset=0,
        order_by="points",
        descending=False,
    )

    assert len(stories) == 2
    assert total == 5


async def test_ordering_by_site_puts_nulls_last(
    session: AsyncSession,
    sample_stories: None,
) -> None:
    """Checks the full result order, including the story without a site.

    The direction applies only to stories that have a site; NULL stays last
    both ways (the nulls_last contract in list_stories), not wherever the
    database dialect would place it. A tie on site="github.com" is broken by
    id, so in descending order that pair flips with the rest.
    """
    rosnaco, _ = await list_stories(session, limit=100, offset=0, order_by="site")
    malejaco, _ = await list_stories(
        session,
        limit=100,
        offset=0,
        order_by="site",
        descending=True,
    )

    assert [s.hn_id for s in rosnaco] == [
        38102345,
        38101234,
        38103456,
        38104567,
        38105678,
    ]
    assert [s.hn_id for s in malejaco] == [
        38104567,
        38103456,
        38101234,
        38102345,
        38105678,
    ]
    # The entry without a site sits at the end whichever way we sort.
    assert rosnaco[-1].site is None
    assert malejaco[-1].site is None


async def test_order_of_equal_points_is_stable(
    session: AsyncSession,
    sample_stories: None,
) -> None:
    """A tie on points is broken by id, so both answers keep the same order."""
    pierwsze, _ = await list_stories(session, limit=100, offset=0, order_by="points")
    drugie, _ = await list_stories(session, limit=100, offset=0, order_by="points")

    remis_pierwsze = [s.hn_id for s in pierwsze if s.points == 128]
    remis_drugie = [s.hn_id for s in drugie if s.points == 128]

    assert remis_pierwsze == [38101234, 38103456]
    assert remis_pierwsze == remis_drugie


async def test_unknown_sort_column_does_not_break_query(
    session: AsyncSession,
    sample_stories: None,
) -> None:
    """An order_by outside the allow-list quietly falls back to scraped_at."""
    stories, total = await list_stories(
        session,
        limit=100,
        offset=0,
        order_by="nieistniejaca_kolumna",
    )

    assert len(stories) == 5
    assert total == 5
