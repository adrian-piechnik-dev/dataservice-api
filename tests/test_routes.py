"""Tests of the HTTP layer of the Record resource.

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

from ap_api.config import Settings, get_settings
from ap_api.db import get_session
from ap_api.repository import DEFAULT_ORDER_BY, SORTABLE_COLUMNS
from ap_api.routes import OrderBy, router
from ap_api.security import API_KEY_HEADER_NAME

VALID_API_KEY = "sekret-testowy-123"

# Small page limits: with default_page_size=2 the default page is visibly
# shorter than the data set, and max_page_size=5 is easy to exceed in a request.
TEST_DEFAULT_PAGE_SIZE = 2
TEST_MAX_PAGE_SIZE = 5


def _test_settings() -> Settings:
    """Test settings: a known API key and small pagination limits."""
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        api_key=VALID_API_KEY,
        default_page_size=TEST_DEFAULT_PAGE_SIZE,
        max_page_size=TEST_MAX_PAGE_SIZE,
        _env_file=None,
    )


@pytest.fixture
def app(session: AsyncSession) -> FastAPI:
    """An application with just the records router, wired to the test database."""
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
    """Creates a record through the API and returns it as the response shows it."""
    payload = {"external_id": "ext-1", "name": "Nazwa", "category": "A", "value": 1.0}
    payload.update(fields)
    response = await client.post("/records", json=payload)
    assert response.status_code == 201
    return response.json()


async def test_post_creates_record_and_points_at_it_with_location(
    client: AsyncClient,
) -> None:
    """A 201 carries the created record and a working address for it."""
    response = await client.post(
        "/records",
        json={"external_id": "ext-1", "name": "Nazwa", "category": "A", "value": 1.5},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["id"] is not None
    assert body["external_id"] == "ext-1"
    assert body["created_at"] is not None

    location = response.headers["location"]
    record_id = body["id"]
    assert location.endswith(f"/records/{record_id}")
    # Location has to lead to that same resource, not merely look right.
    followed = await client.get(location)
    assert followed.status_code == 200
    assert followed.json() == body


async def test_post_with_taken_external_id_returns_409(client: AsyncClient) -> None:
    """A repeated external_id is a resource conflict, not a server failure."""
    await _create(client, external_id="ext-1")

    response = await client.post(
        "/records",
        json={"external_id": "ext-1", "name": "Inna nazwa"},
    )

    assert response.status_code == 409

    # After the rollback the session still works and the first record remains.
    listing = await client.get("/records")
    assert listing.status_code == 200
    assert listing.json()["total"] == 1


async def test_post_with_invalid_body_returns_422(client: AsyncClient) -> None:
    """The input schema rejects an empty name and unknown fields."""
    empty_name = await client.post(
        "/records",
        json={"external_id": "ext-1", "name": ""},
    )
    unknown_field = await client.post(
        "/records",
        json={"external_id": "ext-1", "name": "Nazwa", "nieznane": 1},
    )

    assert empty_name.status_code == 422
    assert unknown_field.status_code == 422


async def test_list_returns_page_shape_with_default_limit(
    client: AsyncClient,
) -> None:
    """With no parameters the page size comes from the settings; total counts all."""
    for index in range(3):
        await _create(client, external_id=f"ext-{index}", name=f"Nazwa {index}")

    response = await client.get("/records")

    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == TEST_DEFAULT_PAGE_SIZE
    assert body["total"] == 3
    assert body["limit"] == TEST_DEFAULT_PAGE_SIZE
    assert body["offset"] == 0


async def test_list_with_limit_above_maximum_returns_422(client: AsyncClient) -> None:
    """The upper page bound comes from max_page_size, not from a literal."""
    response = await client.get("/records", params={"limit": TEST_MAX_PAGE_SIZE + 1})

    assert response.status_code == 422
    assert str(TEST_MAX_PAGE_SIZE) in response.json()["detail"]


async def test_list_passes_ordering_to_the_repository(
    client: AsyncClient,
) -> None:
    """order_by and descending change the order, so they reach the query."""
    for name in ("Alpha", "Beta", "Gamma"):
        await _create(client, external_id=f"ext-{name}", name=name)

    response = await client.get(
        "/records",
        params={"order_by": "name", "descending": True, "limit": 5},
    )

    assert response.status_code == 200
    assert [item["name"] for item in response.json()["items"]] == [
        "Gamma",
        "Beta",
        "Alpha",
    ]


async def test_list_with_unknown_order_by_returns_422(client: AsyncClient) -> None:
    """A column outside the sort list is a request error, not a silent fallback."""
    response = await client.get("/records", params={"order_by": "haslo"})

    assert response.status_code == 422


async def test_get_unknown_id_returns_404(client: AsyncClient) -> None:
    """A missing record is a 404, not an empty 200."""
    response = await client.get("/records/99999")

    assert response.status_code == 404


async def test_patch_unknown_id_returns_404(client: AsyncClient) -> None:
    """Updating a record that does not exist creates nothing."""
    response = await client.patch("/records/99999", json={"name": "Nowa"})

    assert response.status_code == 404


async def test_delete_unknown_id_returns_404(client: AsyncClient) -> None:
    """Deleting a record that does not exist is an error, not a quiet success."""
    response = await client.delete("/records/99999")

    assert response.status_code == 404


async def test_patch_leaves_fields_absent_from_body_alone(client: AsyncClient) -> None:
    """A field absent from the request keeps its value instead of turning None."""
    created = await _create(client, name="Nazwa", category="A", value=1.0)
    record_id = created["id"]

    response = await client.patch(f"/records/{record_id}", json={"name": "Zmiana"})

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Zmiana"
    assert body["category"] == "A"
    assert body["value"] == 1.0


async def test_patch_to_taken_external_id_returns_409(client: AsyncClient) -> None:
    """Taking over another external_id is the same conflict as on creation."""
    await _create(client, external_id="ext-1")
    second = await _create(client, external_id="ext-2")
    record_id = second["id"]

    response = await client.patch(
        f"/records/{record_id}",
        json={"external_id": "ext-1"},
    )

    assert response.status_code == 409


async def test_delete_removes_record_and_returns_204(client: AsyncClient) -> None:
    """After the delete the response is empty and the resource is gone."""
    created = await _create(client)
    record_id = created["id"]

    response = await client.delete(f"/records/{record_id}")

    assert response.status_code == 204
    assert response.content == b""

    followed = await client.get(f"/records/{record_id}")
    assert followed.status_code == 404


async def test_request_without_key_returns_401(anonymous_client: AsyncClient) -> None:
    """The router guard rejects the request before it reaches the endpoint."""
    response = await anonymous_client.get("/records")

    assert response.status_code == 401


def test_order_by_matches_sortable_columns() -> None:
    """The Literal list and the SORTABLE_COLUMNS keys live apart - they must agree.

    Without this assertion, adding a column in the repository would slip by
    unnoticed: the HTTP layer would reject it as an unknown parameter value.
    """
    assert set(get_args(OrderBy)) == set(SORTABLE_COLUMNS)
    assert DEFAULT_ORDER_BY in get_args(OrderBy)
