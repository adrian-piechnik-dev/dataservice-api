"""Tests of the application assembly and of the OpenAPI schema.

The schema is read through a client, from the actually served /openapi.json
path rather than from app.openapi() in memory - what counts is what a browser
sees on /docs, not an object living inside the test process.

No test calls the /records endpoints, so dependency_overrides has nothing to
replace here: /openapi.json needs neither an API key nor a database session.
The metadata create_app reads on call is swapped in with monkeypatch.
"""

from collections.abc import AsyncGenerator
from importlib.metadata import version
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from ap_dataservice.config import Settings
from ap_dataservice.main import create_app
from ap_dataservice.security import API_KEY_HEADER_NAME

# The scheme name under which FastAPI documents the guard from security.py.
API_KEY_SCHEME_NAME = "APIKeyHeader"


@pytest.fixture
def app() -> FastAPI:
    """The application assembled by the factory, just as the server does it."""
    return create_app()


@pytest.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """A client talking to the application over ASGI, without a socket."""
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as test_client:
        yield test_client


@pytest.fixture
async def openapi_schema(client: AsyncClient) -> dict[str, Any]:
    """The schema fetched from /openapi.json of a running application."""
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    return response.json()


def test_create_app_returns_fastapi_application(app: FastAPI) -> None:
    """The factory hands back a ready instance for the server to run."""
    assert isinstance(app, FastAPI)


async def test_openapi_json_is_served_and_parses(client: AsyncClient) -> None:
    """The schema path answers with 200 and returns valid JSON."""
    response = await client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert "openapi" in schema
    assert "paths" in schema


def test_schema_documents_api_key_in_header(openapi_schema: dict[str, Any]) -> None:
    """This entry is what puts the Authorize button on /docs.

    Without it the documentation page would have nowhere to take the key, and
    every request sent from /docs would come back as a 401.
    """
    schemes = openapi_schema["components"]["securitySchemes"]

    assert API_KEY_SCHEME_NAME in schemes
    assert schemes[API_KEY_SCHEME_NAME]["type"] == "apiKey"
    assert schemes[API_KEY_SCHEME_NAME]["in"] == "header"


def test_documented_header_matches_the_guard(
    openapi_schema: dict[str, Any],
) -> None:
    """The documentation and the code must name the same header.

    The name in the schema comes from APIKeyHeader in security.py, but the two
    drifting apart would surface only for a client reading /docs.
    """
    scheme = openapi_schema["components"]["securitySchemes"][API_KEY_SCHEME_NAME]

    assert scheme["name"] == API_KEY_HEADER_NAME


def test_every_records_operation_requires_a_key(
    openapi_schema: dict[str, Any],
) -> None:
    """The guard on the router really did mark every operation of the resource.

    The security requirement sits on operations rather than on paths, so we go
    one level down - to the HTTP methods of every /records path.
    """
    operations = [
        (path, method, operation)
        for path, methods in openapi_schema["paths"].items()
        if path.startswith("/records")
        for method, operation in methods.items()
    ]

    assert operations, "the schema documents no operation on /records"
    for path, method, operation in operations:
        assert operation.get("security"), f"{method.upper()} {path} is not secured"


def test_openapi_metadata_comes_from_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Title, description and version come from Settings, not from literals.

    create_app reads the settings at call time, so we replace get_settings in
    the module itself - dependency_overrides acts only on request dependencies,
    while this metadata is produced while the application is being built.
    """

    def fake_settings() -> Settings:
        return Settings(
            database_url="sqlite+aiosqlite:///:memory:",
            api_key="sekret-testowy-123",
            app_title="Tytul testowy",
            app_description="Opis testowy",
            app_version="9.9.9",
            _env_file=None,
        )

    monkeypatch.setattr("ap_dataservice.main.get_settings", fake_settings)

    info = create_app().openapi()["info"]

    assert info["title"] == "Tytul testowy"
    assert info["description"] == "Opis testowy"
    assert info["version"] == "9.9.9"


def test_default_version_matches_package_version() -> None:
    """The version in the settings and in pyproject.toml must stay in step.

    Bumping the number in the package without touching the settings would slip
    by unnoticed: openapi.json would report a version that no longer exists.
    """
    assert Settings.model_fields["app_version"].default == version("dataservice-api")
