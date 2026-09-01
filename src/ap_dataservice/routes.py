"""HTTP layer of the Story resource: requests mapped onto repository calls.

The endpoints know no SQL - each of them only reads the request parameters,
calls a function from repository.py and turns the result into a status code.
That keeps the rules "what is missing is a 404" and "a duplicate is a 409" in
one place, and leaves the data layer independent of the protocol.

The repository deliberately does not commit, and get_session only hands out
and closes the session, so the endpoints draw the transaction boundary: every
change ends with a commit, and a failed write with a rollback.
"""

from typing import Annotated, Literal

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Path,
    Query,
    Request,
    Response,
    Security,
    status,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ap_dataservice.config import Settings, get_settings
from ap_dataservice.db import get_session
from ap_dataservice.models import Story
from ap_dataservice.repository import (
    create_story,
    delete_story,
    get_story,
    list_stories,
    update_story,
)
from ap_dataservice.schemas import Page, StoryCreate, StoryRead, StoryUpdate
from ap_dataservice.security import require_api_key

# Security instead of Depends: the guard behaves the same way, but the key
# scheme reaches OpenAPI, so /docs gains an Authorize button. Declaring it on
# the router covers every path of the resource - no endpoint repeats it.
router = APIRouter(
    prefix="/stories",
    tags=["stories"],
    dependencies=[Security(require_api_key)],
)

# The integer columns are SQLAlchemy Integer, which is a 4-byte int on both
# dialects we run on. A number outside that range reaches the driver and fails
# while the parameter is being bound - an unhandled error, so a 500 for what is
# plainly a bad request. The bounds turn it into the 422 it always was.
INT32_MIN = -2_147_483_648
INT32_MAX = 2_147_483_647

# Text filters are compared against these columns, so a longer value can never
# match anything - it is rejected instead of scanned for.
SITE_MAX_LENGTH = 255
TITLE_MAX_LENGTH = 512

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

# The identifier in the path, bounded to what the id column can hold. The lower
# bound is the column minimum rather than 1: a negative id is still a story
# that does not exist, so it stays a 404 and does not turn into a 422.
StoryIdPath = Annotated[int, Path(ge=INT32_MIN, le=INT32_MAX)]

# A mirror of the SORTABLE_COLUMNS keys from repository.py. Literal rather
# than a plain str, because it gives validation on the FastAPI side (a wrong
# value is a 422, not a silent sort by scraped_at) and lists the accepted
# values in OpenAPI. A test guards that both sets agree, as they live apart.
OrderBy = Literal[
    "scraped_at",
    "posted_at",
    "points",
    "num_comments",
    "rank",
    "title",
    "site",
    "id",
]

STORY_NOT_FOUND_DETAIL = "Story not found"
DUPLICATE_HN_ID_DETAIL = "Story with this hn_id already exists"


@router.post("", status_code=status.HTTP_201_CREATED, response_model=StoryRead)
async def create_story_endpoint(
    data: StoryCreate,
    session: SessionDep,
    request: Request,
    response: Response,
) -> Story:
    """Creates a story and returns it with the new address in Location.

    hn_id is unique in the database, so a repeated scrape of an entry still
    sitting on the front page ends with an IntegrityError on write. We catch
    it here and turn it into a 409: this is a client error (the resource
    already exists), not a server failure.

    The Location address is built with url_for by route name, so changing the
    router prefix leaves no stale path behind in the code.
    """
    try:
        story = await create_story(session, data)
        await session.commit()
    except IntegrityError:
        # After a failed write the session stays in an aborted transaction -
        # without the rollback every later use of it would end in an error.
        await session.rollback()
        # from None: the original exception carries the SQL statement, which
        # has no business showing up in the log beside the response.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=DUPLICATE_HN_ID_DETAIL,
        ) from None

    response.headers["Location"] = str(
        request.url_for("get_story_endpoint", story_id=story.id)
    )
    return story


@router.get("", response_model=Page[StoryRead])
async def list_stories_endpoint(
    session: SessionDep,
    settings: SettingsDep,
    limit: Annotated[int | None, Query(ge=1)] = None,
    offset: Annotated[int, Query(ge=0, le=INT32_MAX)] = 0,
    site: Annotated[str | None, Query(max_length=SITE_MAX_LENGTH)] = None,
    title_contains: Annotated[
        str | None,
        Query(max_length=TITLE_MAX_LENGTH),
    ] = None,
    points_min: Annotated[int | None, Query(ge=INT32_MIN, le=INT32_MAX)] = None,
    points_max: Annotated[int | None, Query(ge=INT32_MIN, le=INT32_MAX)] = None,
    is_hiring: bool | None = None,
    order_by: OrderBy = "scraped_at",
    descending: bool = False,
) -> Page[StoryRead]:
    """Returns a page of stories matching the filters, with their total count.

    The page size comes from the settings rather than a value written into the
    code: a missing parameter means default_page_size, and a request above
    max_page_size is rejected. The upper bound cannot go into Query(le=...),
    because that value is fixed once, at module import - so we read it from
    the settings on every request. offset is bounded the same way and for the
    same reason: OFFSET makes the database produce and discard every row before
    it, so paging arbitrarily deep is work nobody asked for.
    """
    page_limit = settings.default_page_size if limit is None else limit
    if page_limit > settings.max_page_size:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"limit must not exceed max_page_size ({settings.max_page_size})",
        )

    if offset > settings.max_offset:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"offset must not exceed max_offset ({settings.max_offset})",
        )

    stories, total = await list_stories(
        session,
        limit=page_limit,
        offset=offset,
        site=site,
        title_contains=title_contains,
        points_min=points_min,
        points_max=points_max,
        is_hiring=is_hiring,
        order_by=order_by,
        descending=descending,
    )
    return Page[StoryRead](
        items=[StoryRead.model_validate(story) for story in stories],
        total=total,
        limit=page_limit,
        offset=offset,
    )


@router.get("/{story_id}", response_model=StoryRead)
async def get_story_endpoint(story_id: StoryIdPath, session: SessionDep) -> Story:
    """Returns a single story, or a 404 when the database holds none."""
    story = await get_story(session, story_id)
    if story is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=STORY_NOT_FOUND_DETAIL,
        )
    return story


@router.patch("/{story_id}", response_model=StoryRead)
async def update_story_endpoint(
    story_id: StoryIdPath,
    data: StoryUpdate,
    session: SessionDep,
) -> Story:
    """Applies the fields sent in the request and returns the changed story.

    Fields left out of the request body stay untouched - exclude_unset in the
    repository filters them away. Changing hn_id to one already taken ends
    with a 409, just as on creation: it is the same uniqueness conflict.
    """
    story = await get_story(session, story_id)
    if story is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=STORY_NOT_FOUND_DETAIL,
        )

    try:
        updated = await update_story(session, story, data)
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=DUPLICATE_HN_ID_DETAIL,
        ) from None

    # updated_at is filled in by the database (onupdate), so after the write
    # SQLAlchemy treats the attribute as stale and would reach for it only
    # during serialisation - already outside the async context, which fails.
    # We load it explicitly instead.
    await session.refresh(updated)
    return updated


@router.delete(
    "/{story_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_story_endpoint(story_id: StoryIdPath, session: SessionDep) -> None:
    """Deletes the story and answers with no content, or raises a 404.

    response_class=Response: a 204 response carries no body, so there is also
    nothing to declare through a content-type header.
    """
    story = await get_story(session, story_id)
    if story is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=STORY_NOT_FOUND_DETAIL,
        )

    await delete_story(session, story)
    await session.commit()
