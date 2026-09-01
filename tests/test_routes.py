"""Tests of the HTTP layer of the Story resource.

The router is exercised through a real ASGI stack, so every test checks what
the client sees: the status code, the body and the headers. The application is
mounted locally in a fixture - the router stands on its own.

The dependencies are replaced through dependency_overrides: get_session hands
back a session bound to the in-memory test database (the fixture from
conftest.py), and get_settings returns settings with small page limits, so the
pagination tests have something to check.
"""

from collections.abc import AsyncGenerator
from typing import Any, get_args

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from ap_dataservice.config import Settings, get_settings
from ap_dataservice.db import get_session
from ap_dataservice.repository import DEFAULT_ORDER_BY, SORTABLE_COLUMNS
from ap_dataservice.routes import (
    INT32_MAX,
    INT32_MIN,
    SITE_MAX_LENGTH,
    TITLE_MAX_LENGTH,
    OrderBy,
    router,
)
from ap_dataservice.security import API_KEY_HEADER_NAME

VALID_API_KEY = "sekret-testowy-123"

# Small page limits: with default_page_size=2 the default page is visibly
# shorter than the data set, and max_page_size=5 is easy to exceed in a request.
TEST_DEFAULT_PAGE_SIZE = 2
TEST_MAX_PAGE_SIZE = 5

# Small enough to step over in a request, the same way max_page_size is.
TEST_MAX_OFFSET = 10

# The scraper timestamps, in the shape they travel over JSON.
POSTED_AT = "2026-08-29T06:12:00Z"
SCRAPED_AT = "2026-08-29T08:00:00Z"


def _test_settings() -> Settings:
    """Test settings: a known API key and small pagination limits."""
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        api_key=VALID_API_KEY,
        default_page_size=TEST_DEFAULT_PAGE_SIZE,
        max_page_size=TEST_MAX_PAGE_SIZE,
        max_offset=TEST_MAX_OFFSET,
        _env_file=None,
    )


@pytest.fixture
def app(session: AsyncSession) -> FastAPI:
    """An application with just the stories router, wired to the test database."""
    application = FastAPI()
    application.include_router(router)
    # The session is handed back directly, without a generator: closing it is
    # the fixture's job, which keeps the test and the endpoints in one
    # transaction.
    application.dependency_overrides[get_session] = lambda: session
    application.dependency_overrides[get_settings] = _test_settings
    return application


@pytest.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """A client carrying a valid API key on every request."""
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={API_KEY_HEADER_NAME: VALID_API_KEY},
    ) as authorized_client:
        yield authorized_client


@pytest.fixture
async def anonymous_client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """A client without an API key - separate, rather than dropping the header."""
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as unauthorized_client:
        yield unauthorized_client


async def _create(client: AsyncClient, **fields: Any) -> dict[str, Any]:
    """Creates a story through the API and returns it as the response shows it."""
    payload: dict[str, Any] = {
        "hn_id": 38101234,
        "title": "Show HN: A self-hosted Postgres backup tool",
        "url": "https://github.com/example/pgbackup",
        "site": "github.com",
        "author": "pg_hacker",
        "points": 128,
        "num_comments": 43,
        "rank": 1,
        "topic": "databases",
        "posted_at": POSTED_AT,
        "scraped_at": SCRAPED_AT,
    }
    payload.update(fields)
    response = await client.post("/stories", json=payload)
    assert response.status_code == 201
    return response.json()


async def test_post_creates_story_and_points_at_it_with_location(
    client: AsyncClient,
) -> None:
    """A 201 carries the created story and a working address for it."""
    response = await client.post(
        "/stories",
        json={
            "hn_id": 38101234,
            "title": "Show HN: A self-hosted Postgres backup tool",
            "url": "https://github.com/example/pgbackup",
            "site": "github.com",
            "author": "pg_hacker",
            "points": 128,
            "num_comments": 43,
            "rank": 1,
            "posted_at": POSTED_AT,
            "scraped_at": SCRAPED_AT,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["id"] is not None
    assert body["hn_id"] == 38101234
    assert body["created_at"] is not None

    location = response.headers["location"]
    story_id = body["id"]
    assert location.endswith(f"/stories/{story_id}")
    # Location has to lead to that same resource, not merely look right.
    followed = await client.get(location)
    assert followed.status_code == 200

    # SQLite has no timestamptz: it stores the datetime and drops the offset,
    # so the stamps read back from the database no longer carry the "Z" the
    # request sent, while the 201 still shows the value held in memory. That
    # is a property of the test dialect, not of the API - on PostgreSQL both
    # bodies match to the character. Every other field has to be identical.
    followed_body = followed.json()
    stamps = {"posted_at", "scraped_at"}
    assert {k: v for k, v in followed_body.items() if k not in stamps} == {
        k: v for k, v in body.items() if k not in stamps
    }
    assert followed_body["posted_at"].startswith("2026-08-29T06:12:00")
    assert followed_body["scraped_at"].startswith("2026-08-29T08:00:00")


async def test_post_with_taken_hn_id_returns_409(client: AsyncClient) -> None:
    """A repeated hn_id is a resource conflict, not a server failure.

    That is the everyday case: the same entry stays on the front page across
    scrapes, so the importer keeps offering it again.
    """
    await _create(client, hn_id=38101234)

    response = await client.post(
        "/stories",
        json={
            "hn_id": 38101234,
            "title": "Show HN: A self-hosted Postgres backup tool",
            "url": "https://github.com/example/pgbackup",
            "author": "pg_hacker",
            "rank": 7,
            "posted_at": POSTED_AT,
            "scraped_at": "2026-08-29T09:00:00Z",
        },
    )

    assert response.status_code == 409

    # After the rollback the session still works and the first story remains.
    listing = await client.get("/stories")
    assert listing.status_code == 200
    assert listing.json()["total"] == 1


async def test_post_with_invalid_body_returns_422(client: AsyncClient) -> None:
    """The input schema rejects an empty title and unknown fields."""
    empty_title = await client.post(
        "/stories",
        json={
            "hn_id": 38101234,
            "title": "",
            "url": "https://github.com/example/pgbackup",
            "author": "pg_hacker",
            "rank": 1,
            "posted_at": POSTED_AT,
            "scraped_at": SCRAPED_AT,
        },
    )
    unknown_field = await client.post(
        "/stories",
        json={
            "hn_id": 38101234,
            "title": "Show HN: A self-hosted Postgres backup tool",
            "url": "https://github.com/example/pgbackup",
            "author": "pg_hacker",
            "rank": 1,
            "posted_at": POSTED_AT,
            "scraped_at": SCRAPED_AT,
            "nieznane": 1,
        },
    )

    assert empty_title.status_code == 422
    assert unknown_field.status_code == 422


async def test_list_returns_page_shape_with_default_limit(
    client: AsyncClient,
) -> None:
    """With no parameters the page size comes from the settings; total counts all."""
    for index in range(3):
        await _create(client, hn_id=38101234 + index, rank=index + 1)

    response = await client.get("/stories")

    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == TEST_DEFAULT_PAGE_SIZE
    assert body["total"] == 3
    assert body["limit"] == TEST_DEFAULT_PAGE_SIZE
    assert body["offset"] == 0


async def test_list_with_limit_above_maximum_returns_422(client: AsyncClient) -> None:
    """The upper page bound comes from max_page_size, not from a literal."""
    response = await client.get("/stories", params={"limit": TEST_MAX_PAGE_SIZE + 1})

    assert response.status_code == 422
    assert str(TEST_MAX_PAGE_SIZE) in response.json()["detail"]


async def test_list_with_offset_above_maximum_returns_422(client: AsyncClient) -> None:
    """The offset ceiling comes from max_offset, the same way limit's does.

    OFFSET makes the database produce and discard every row before it, so an
    unbounded value is work a caller can ask for and nobody can use.
    """
    response = await client.get("/stories", params={"offset": TEST_MAX_OFFSET + 1})

    assert response.status_code == 422
    assert str(TEST_MAX_OFFSET) in response.json()["detail"]


async def test_out_of_range_integers_are_422_not_500(client: AsyncClient) -> None:
    """A number wider than the column is a bad request, not a server failure.

    Unbounded, each of these reaches the driver and fails while the parameter
    is being bound - an unhandled error the client sees as a 500.

    points_min is checked at both ends: a number too negative overflows exactly
    as a number too large does, so a bound on one side alone would leave half
    the hole open. The values on the bounds themselves must still pass, or the
    fix would have cost the caller part of the column's range.
    """
    for parameter in ("offset", "points_min", "points_max"):
        response = await client.get("/stories", params={parameter: INT32_MAX + 1})
        assert response.status_code == 422, parameter

    below_range = await client.get("/stories", params={"points_min": INT32_MIN - 1})
    assert below_range.status_code == 422

    for value in (INT32_MIN, INT32_MAX):
        on_bound = await client.get("/stories", params={"points_min": value})
        assert on_bound.status_code == 200, value


async def test_out_of_range_story_id_is_422_not_500(client: AsyncClient) -> None:
    """The identifier in the path is bounded to what the id column holds.

    A negative id stays a 404 though - it is a story that does not exist, not
    a malformed request.
    """
    too_large = await client.get(f"/stories/{INT32_MAX + 1}")
    negative = await client.get("/stories/-1")

    assert too_large.status_code == 422
    assert negative.status_code == 404


async def test_overlong_filter_values_return_422(client: AsyncClient) -> None:
    """A filter longer than its column can never match, so it is refused."""
    long_site = await client.get(
        "/stories",
        params={"site": "a" * (SITE_MAX_LENGTH + 1)},
    )
    long_title = await client.get(
        "/stories",
        params={"title_contains": "a" * (TITLE_MAX_LENGTH + 1)},
    )

    assert long_site.status_code == 422
    assert long_title.status_code == 422


async def test_title_contains_metacharacters_match_literally(
    client: AsyncClient,
) -> None:
    """Through HTTP too, '%' searches for a per-cent sign and not for anything.

    The repository escapes the pattern; this checks the parameter really gets
    there, so the guard cannot be lost between the layers.
    """
    await _create(client, hn_id=38101234, title="Bun 1.2 starts 50% faster", rank=1)
    await _create(client, hn_id=38102345, title="Rust 1.94 released", rank=2)

    response = await client.get("/stories", params={"title_contains": "%"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert [item["hn_id"] for item in body["items"]] == [38101234]


async def test_list_passes_ordering_to_the_repository(
    client: AsyncClient,
) -> None:
    """order_by and descending change the order, so they reach the query."""
    titles = (
        "Ask HN: How do you keep a monorepo fast?",
        "Rust 1.94 released",
        "Show HN: A self-hosted Postgres backup tool",
    )
    for index, title in enumerate(titles):
        await _create(client, hn_id=38101234 + index, title=title, rank=index + 1)

    response = await client.get(
        "/stories",
        params={"order_by": "title", "descending": True, "limit": 5},
    )

    assert response.status_code == 200
    assert [item["title"] for item in response.json()["items"]] == list(
        reversed(titles)
    )


async def test_list_filters_by_is_hiring(client: AsyncClient) -> None:
    """The is_hiring query parameter reaches the repository filter.

    Left out it narrows nothing, so the job post shows up beside the rest.
    """
    await _create(client, hn_id=38101234, rank=1)
    await _create(
        client,
        hn_id=38104567,
        title="Sourcegraph (YC S13) Is Hiring a Compiler Engineer",
        url="https://www.ycombinator.com/companies/sourcegraph/jobs",
        site="ycombinator.com",
        author="sqs",
        points=1,
        num_comments=0,
        rank=2,
        is_hiring=True,
        topic=None,
        company="Sourcegraph",
    )

    hiring = await client.get("/stories", params={"is_hiring": True})
    not_hiring = await client.get("/stories", params={"is_hiring": False})
    unfiltered = await client.get("/stories")

    assert hiring.status_code == 200
    assert hiring.json()["total"] == 1
    assert [item["hn_id"] for item in hiring.json()["items"]] == [38104567]

    assert not_hiring.json()["total"] == 1
    assert [item["hn_id"] for item in not_hiring.json()["items"]] == [38101234]

    assert unfiltered.json()["total"] == 2


async def test_list_with_unknown_order_by_returns_422(client: AsyncClient) -> None:
    """A column outside the sort list is a request error, not a silent fallback."""
    response = await client.get("/stories", params={"order_by": "haslo"})

    assert response.status_code == 422


async def test_get_unknown_id_returns_404(client: AsyncClient) -> None:
    """A missing story is a 404, not an empty 200."""
    response = await client.get("/stories/99999")

    assert response.status_code == 404


async def test_patch_unknown_id_returns_404(client: AsyncClient) -> None:
    """Updating a story that does not exist creates nothing."""
    response = await client.patch("/stories/99999", json={"points": 256})

    assert response.status_code == 404


async def test_delete_unknown_id_returns_404(client: AsyncClient) -> None:
    """Deleting a story that does not exist is an error, not a quiet success."""
    response = await client.delete("/stories/99999")

    assert response.status_code == 404


async def test_patch_leaves_fields_absent_from_body_alone(client: AsyncClient) -> None:
    """A field absent from the request keeps its value instead of turning None."""
    created = await _create(client, points=128, num_comments=43, site="github.com")
    story_id = created["id"]

    response = await client.patch(f"/stories/{story_id}", json={"points": 256})

    assert response.status_code == 200
    body = response.json()
    assert body["points"] == 256
    assert body["num_comments"] == 43
    assert body["site"] == "github.com"


async def test_patch_to_taken_hn_id_returns_409(client: AsyncClient) -> None:
    """Taking over another hn_id is the same conflict as on creation."""
    await _create(client, hn_id=38101234, rank=1)
    second = await _create(client, hn_id=38102345, rank=2)
    story_id = second["id"]

    response = await client.patch(
        f"/stories/{story_id}",
        json={"hn_id": 38101234},
    )

    assert response.status_code == 409


async def test_delete_removes_story_and_returns_204(client: AsyncClient) -> None:
    """After the delete the response is empty and the resource is gone."""
    created = await _create(client)
    story_id = created["id"]

    response = await client.delete(f"/stories/{story_id}")

    assert response.status_code == 204
    assert response.content == b""

    followed = await client.get(f"/stories/{story_id}")
    assert followed.status_code == 404


async def test_request_without_key_returns_401(anonymous_client: AsyncClient) -> None:
    """The router guard rejects the request before it reaches the endpoint."""
    response = await anonymous_client.get("/stories")

    assert response.status_code == 401


def test_order_by_matches_sortable_columns() -> None:
    """The Literal list and the SORTABLE_COLUMNS keys live apart - they must agree.

    Without this assertion, adding a column in the repository would slip by
    unnoticed: the HTTP layer would reject it as an unknown parameter value.
    """
    assert set(get_args(OrderBy)) == set(SORTABLE_COLUMNS)
    assert DEFAULT_ORDER_BY in get_args(OrderBy)
