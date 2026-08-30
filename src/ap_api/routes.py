"""HTTP layer of the Record resource: requests mapped onto repository calls.

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
    Query,
    Request,
    Response,
    Security,
    status,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ap_api.config import Settings, get_settings
from ap_api.db import get_session
from ap_api.models import Record
from ap_api.repository import (
    create_record,
    delete_record,
    get_record,
    list_records,
    update_record,
)
from ap_api.schemas import Page, RecordCreate, RecordRead, RecordUpdate
from ap_api.security import require_api_key

# Security instead of Depends: the guard behaves the same way, but the key
# scheme reaches OpenAPI, so /docs gains an Authorize button. Declaring it on
# the router covers every path of the resource - no endpoint repeats it.
router = APIRouter(
    prefix="/records",
    tags=["records"],
    dependencies=[Security(require_api_key)],
)

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

# A mirror of the SORTABLE_COLUMNS keys from repository.py. Literal rather
# than a plain str, because it gives validation on the FastAPI side (a wrong
# value is a 422, not a silent sort by created_at) and lists the accepted
# values in OpenAPI. A test guards that both sets agree, as they live apart.
OrderBy = Literal["created_at", "name", "value", "id"]

RECORD_NOT_FOUND_DETAIL = "Record not found"
DUPLICATE_EXTERNAL_ID_DETAIL = "Record with this external_id already exists"


@router.post("", status_code=status.HTTP_201_CREATED, response_model=RecordRead)
async def create_record_endpoint(
    data: RecordCreate,
    session: SessionDep,
    request: Request,
    response: Response,
) -> Record:
    """Creates a record and returns it with the new address in Location.

    external_id is unique in the database, so a repeated import ends with an
    IntegrityError on write. We catch it here and turn it into a 409: this is
    a client error (the resource already exists), not a server failure.

    The Location address is built with url_for by route name, so changing the
    router prefix leaves no stale path behind in the code.
    """
    try:
        record = await create_record(session, data)
        await session.commit()
    except IntegrityError:
        # After a failed write the session stays in an aborted transaction -
        # without the rollback every later use of it would end in an error.
        await session.rollback()
        # from None: the original exception carries the SQL statement, which
        # has no business showing up in the log beside the client's response.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=DUPLICATE_EXTERNAL_ID_DETAIL,
        ) from None

    response.headers["Location"] = str(
        request.url_for("get_record_endpoint", record_id=record.id)
    )
    return record


@router.get("", response_model=Page[RecordRead])
async def list_records_endpoint(
    session: SessionDep,
    settings: SettingsDep,
    limit: Annotated[int | None, Query(ge=1)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    category: str | None = None,
    name_contains: str | None = None,
    value_min: float | None = None,
    value_max: float | None = None,
    order_by: OrderBy = "created_at",
    descending: bool = False,
) -> Page[RecordRead]:
    """Returns a page of records matching the filters, with their total count.

    The page size comes from the settings rather than a value written into the
    code: a missing parameter means default_page_size, and a request above
    max_page_size is rejected. The upper bound cannot go into Query(le=...),
    because that value is fixed once, at module import - so we read it from
    the settings on every request.
    """
    page_limit = settings.default_page_size if limit is None else limit
    if page_limit > settings.max_page_size:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"limit must not exceed max_page_size ({settings.max_page_size})",
        )

    records, total = await list_records(
        session,
        limit=page_limit,
        offset=offset,
        category=category,
        name_contains=name_contains,
        value_min=value_min,
        value_max=value_max,
        order_by=order_by,
        descending=descending,
    )
    return Page[RecordRead](
        items=[RecordRead.model_validate(record) for record in records],
        total=total,
        limit=page_limit,
        offset=offset,
    )


@router.get("/{record_id}", response_model=RecordRead)
async def get_record_endpoint(record_id: int, session: SessionDep) -> Record:
    """Returns a single record, or a 404 when the database holds none."""
    record = await get_record(session, record_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=RECORD_NOT_FOUND_DETAIL,
        )
    return record


@router.patch("/{record_id}", response_model=RecordRead)
async def update_record_endpoint(
    record_id: int,
    data: RecordUpdate,
    session: SessionDep,
) -> Record:
    """Applies the fields sent in the request and returns the changed record.

    Fields left out of the request body stay untouched - exclude_unset in the
    repository filters them away. Changing external_id to one already taken
    ends with a 409, just as on creation: it is the same uniqueness conflict.
    """
    record = await get_record(session, record_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=RECORD_NOT_FOUND_DETAIL,
        )

    try:
        updated = await update_record(session, record, data)
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=DUPLICATE_EXTERNAL_ID_DETAIL,
        ) from None

    # updated_at is filled in by the database (onupdate), so after the write
    # SQLAlchemy treats the attribute as stale and would reach for it only
    # during serialisation - already outside the async context, which fails.
    # We load it explicitly instead.
    await session.refresh(updated)
    return updated


@router.delete(
    "/{record_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_record_endpoint(record_id: int, session: SessionDep) -> None:
    """Deletes the record and answers with no content, or raises a 404.

    response_class=Response: a 204 response carries no body, so there is also
    nothing to declare through a content-type header.
    """
    record = await get_record(session, record_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=RECORD_NOT_FOUND_DETAIL,
        )

    await delete_record(session, record)
    await session.commit()
