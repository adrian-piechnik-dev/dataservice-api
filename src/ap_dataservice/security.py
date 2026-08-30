"""Request authentication with an API key sent in an HTTP header."""

from secrets import compare_digest
from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader

from ap_dataservice.config import Settings, get_settings

# The header name is part of the API contract, so it lives in a single place
# (the security scheme, the docs and the tests all read it from here).
API_KEY_HEADER_NAME = "X-API-Key"

# One message for both a missing header and a wrong key. Telling those cases
# apart in the response would show the caller which half of the contract they
# already got right - a hint they do not need.
INVALID_API_KEY_DETAIL = "Invalid or missing API key"

# auto_error=False: the scheme only reads the header and documents it in
# OpenAPI. Raising on a missing header itself would make that response differ
# from the one for a wrong key - and we want a single, shared answer.
api_key_header = APIKeyHeader(name=API_KEY_HEADER_NAME, auto_error=False)


async def require_api_key(
    api_key: Annotated[str | None, Security(api_key_header)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    """FastAPI dependency: lets a request through when its API key is valid.

    The comparison goes through compare_digest, so the response time does not
    reveal how many leading characters of the key the caller guessed. It runs
    on bytes rather than text, because compare_digest rejects non-ASCII
    characters in strings - and the header comes from outside, carrying
    whatever the caller chose to send.

    The function is async, so FastAPI runs it on the event loop instead of
    handing every request over to the thread pool.
    """
    # The response carries no WWW-Authenticate header: it would name an
    # authentication scheme from the HTTP registry (Basic, Bearer), and a key
    # in a custom header is not one of them.
    if api_key is None or not compare_digest(
        api_key.encode("utf-8"),
        settings.api_key.encode("utf-8"),
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=INVALID_API_KEY_DETAIL,
        )
