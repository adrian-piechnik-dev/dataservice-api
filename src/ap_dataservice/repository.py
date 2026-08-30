"""Data access layer: operations on stories, with no knowledge of HTTP.

Plain functions rather than methods on a class - the session is an explicit
first argument, so the dependency is visible in the signature and easy to
swap out in tests.

None of these functions commits: the transaction boundary is drawn one layer
up (a dependency or a handler), which lets several operations reach the
database as a single whole. We use flush so that the database assigns keys
and reports constraint violations already before the commit.
"""

from collections.abc import Sequence

from sqlalchemy import func, nulls_last, select
from sqlalchemy.ext.asyncio import AsyncSession

from ap_dataservice.models import Story
from ap_dataservice.schemas import StoryCreate, StoryUpdate

# Allow-list of sortable columns. order_by arrives from outside (a URL
# parameter), so it must never reach getattr(Story, ...) - a client could
# otherwise point at any attribute of the model, including a non-column one.
# created_at and updated_at stay out on purpose: they audit the row in this
# database, not the entry on Hacker News, so they are nothing to sort a
# listing by.
SORTABLE_COLUMNS = {
    "scraped_at": Story.scraped_at,
    "posted_at": Story.posted_at,
    "points": Story.points,
    "num_comments": Story.num_comments,
    "rank": Story.rank,
    "title": Story.title,
    "site": Story.site,
    "id": Story.id,
}

# Used when order_by matches no key of SORTABLE_COLUMNS.
DEFAULT_ORDER_BY = "scraped_at"


async def create_story(session: AsyncSession, data: StoryCreate) -> Story:
    """Creates a story from the input data and returns it with an id assigned.

    After the flush the object has its primary key, but the transaction stays
    open.
    """
    story = Story(
        hn_id=data.hn_id,
        title=data.title,
        url=data.url,
        site=data.site,
        author=data.author,
        points=data.points,
        num_comments=data.num_comments,
        rank=data.rank,
        is_hiring=data.is_hiring,
        topic=data.topic,
        company=data.company,
        posted_at=data.posted_at,
        scraped_at=data.scraped_at,
    )
    session.add(story)
    await session.flush()
    return story


async def get_story(session: AsyncSession, story_id: int) -> Story | None:
    """Returns the story with the given primary key, or None when it is absent.

    session.get looks in the session identity map first, so fetching the same
    story again issues no further query.
    """
    return await session.get(Story, story_id)


async def update_story(
    session: AsyncSession,
    story: Story,
    data: StoryUpdate,
) -> Story:
    """Applies to the story only the fields actually sent in the request.

    exclude_unset=True tells a field left out (kept unchanged) apart from one
    explicitly set to None (the value is cleared).
    """
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(story, field, value)
    await session.flush()
    return story


async def delete_story(session: AsyncSession, story: Story) -> None:
    """Removes the story from the session and sends the DELETE through flush."""
    await session.delete(story)
    await session.flush()


async def list_stories(
    session: AsyncSession,
    *,
    limit: int,
    offset: int,
    site: str | None = None,
    title_contains: str | None = None,
    points_min: int | None = None,
    points_max: int | None = None,
    is_hiring: bool | None = None,
    order_by: str = DEFAULT_ORDER_BY,
    descending: bool = False,
) -> tuple[Sequence[Story], int]:
    """Returns one page of stories and the total number matching the filters.

    Filters left as None are skipped, so a missing parameter means "do not
    narrow", not "compare against NULL". That holds for is_hiring too: None
    lists hiring and non-hiring entries alike, while False narrows to the
    entries that are not job posts. The conditions are joined with AND.

    total comes from a separate query, under the same conditions but without
    the limit and offset - that is how the client knows how many pages remain.

    An order_by outside SORTABLE_COLUMNS quietly falls back to scraped_at;
    validating the accepted values belongs to the HTTP layer.
    """
    conditions = []
    if site is not None:
        conditions.append(Story.site == site)
    if title_contains is not None:
        conditions.append(Story.title.ilike(f"%{title_contains}%"))
    if points_min is not None:
        conditions.append(Story.points >= points_min)
    if points_max is not None:
        conditions.append(Story.points <= points_max)
    if is_hiring is not None:
        conditions.append(Story.is_hiring.is_(is_hiring))

    count_query = select(func.count()).select_from(Story).where(*conditions)
    # COUNT always returns a row; the "or 0" is here purely for typing, since
    # scalar declares its result as optional.
    total = await session.scalar(count_query) or 0

    order_column = SORTABLE_COLUMNS.get(order_by, SORTABLE_COLUMNS[DEFAULT_ORDER_BY])
    # Story.id breaks ties: with equal values in the leading column the
    # database could return stories in any order, so the same story would land
    # on two pages one time and on none the next.
    # nulls_last: without it the place of NULL depends on the dialect (SQLite
    # puts them first on ASC, PostgreSQL last), so one and the same page of
    # results would look different in tests and in production. Story.id is not
    # nullable, so the tie-breaker needs no wrapping.
    if descending:
        order_clauses = (nulls_last(order_column.desc()), Story.id.desc())
    else:
        order_clauses = (nulls_last(order_column.asc()), Story.id.asc())
    query = (
        select(Story)
        .where(*conditions)
        .order_by(*order_clauses)
        .offset(offset)
        .limit(limit)
    )
    stories = (await session.scalars(query)).all()

    return stories, total
