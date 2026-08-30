"""Tests of the dependency that checks the API key.

The dependency is exercised through a real HTTP stack: a minimal application
with one protected path, called over ASGI without a network. That way we check
what the client sees - the status code, the error body and the headers - rather
than the bare return value of a function call.

The key the application expects is supplied through dependency_overrides on
get_settings, so the tests touch neither environment variables nor the settings
cache.
"""

from collections.abc import AsyncGenerator

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from ap_api.config import Settings, get_settings
from ap_api.security import (
    API_KEY_HEADER_NAME,
    INVALID_API_KEY_DETAIL,
    require_api_key,
)

VALID_API_KEY = "sekret-testowy-123"


@pytest.fixture
def app() -> FastAPI:
    """An application with a single path protected by an API key."""
    application = FastAPI()

    @application.get("/protected", dependencies=[Depends(require_api_key)])
    async def protected() -> dict[str, str]:
        return {"status": "ok"}

    def settings_override() -> Settings:
        return Settings(
            database_url="sqlite+aiosqlite:///:memory:",
            api_key=VALID_API_KEY,
            _env_file=None,
        )

    application.dependency_overrides[get_settings] = settings_override
    return application


@pytest.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """A client talking to the application straight over ASGI, no socket."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


async def test_valid_key_allows_the_request(client: AsyncClient) -> None:
    """A key matching the settings means the request is served normally."""
    response = await client.get(
        "/protected",
        headers={API_KEY_HEADER_NAME: VALID_API_KEY},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_missing_header_returns_401(client: AsyncClient) -> None:
    """Without the header the request is rejected, not served anonymously."""
    response = await client.get("/protected")

    assert response.status_code == 401
    assert response.json()["detail"] == INVALID_API_KEY_DETAIL


async def test_wrong_key_returns_401(client: AsyncClient) -> None:
    """A key other than the expected one grants no access."""
    response = await client.get(
        "/protected",
        headers={API_KEY_HEADER_NAME: "zly-klucz"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == INVALID_API_KEY_DETAIL


async def test_missing_and_wrong_key_look_the_same(client: AsyncClient) -> None:
    """The answers are indistinguishable, so neither hints at being closer."""
    missing = await client.get("/protected")
    invalid = await client.get(
        "/protected",
        headers={API_KEY_HEADER_NAME: "zly-klucz"},
    )

    assert missing.status_code == invalid.status_code
    assert missing.json() == invalid.json()


async def test_empty_header_returns_401(client: AsyncClient) -> None:
    """An empty header value is a missing key, not an accepted empty one."""
    response = await client.get("/protected", headers={API_KEY_HEADER_NAME: ""})

    assert response.status_code == 401
    assert response.json()["detail"] == INVALID_API_KEY_DETAIL


async def test_prefix_of_valid_key_is_not_enough(client: AsyncClient) -> None:
    """A matching prefix is still a wrong key - the whole value is compared."""
    response = await client.get(
        "/protected",
        headers={API_KEY_HEADER_NAME: VALID_API_KEY[:-1]},
    )

    assert response.status_code == 401


async def test_non_ascii_key_returns_401_not_server_error(
    client: AsyncClient,
) -> None:
    """Non-ASCII characters make a wrong key, not an error during comparison.

    compare_digest on strings rejects such values by raising, so this test
    guards that we compare bytes and the client gets a 401 instead of a 500.
    """
    response = await client.get(
        "/protected",
        headers={API_KEY_HEADER_NAME: "zazolc-gesla-jazn".encode("utf-8") + b"\xc5\xbc"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == INVALID_API_KEY_DETAIL


async def test_header_name_is_case_insensitive(
    client: AsyncClient,
) -> None:
    """HTTP header names are case-insensitive, so the client may spell it freely."""
    response = await client.get(
        "/protected",
        headers={API_KEY_HEADER_NAME.lower(): VALID_API_KEY},
    )

    assert response.status_code == 200


async def test_401_response_carries_no_www_authenticate(client: AsyncClient) -> None:
    """We declare no scheme from the HTTP registry - a header key is not one."""
    response = await client.get("/protected")

    assert "www-authenticate" not in response.headers
