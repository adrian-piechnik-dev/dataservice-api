"""Data access layer: operations on records, with no knowledge of HTTP.

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

from ap_dataservice.models import Record
from ap_dataservice.schemas import RecordCreate, RecordUpdate

# Allow-list of sortable columns. order_by arrives from outside (a URL
# parameter), so it must never reach getattr(Record, ...) - a client could
# otherwise point at any attribute of the model, including a non-column one.
SORTABLE_COLUMNS = {
    "created_at": Record.created_at,
    "name": Record.name,
    "value": Record.value,
    "id": Record.id,
}

# Used when order_by matches no key of SORTABLE_COLUMNS.
DEFAULT_ORDER_BY = "created_at"


async def create_record(session: AsyncSession, data: RecordCreate) -> Record:
    """Creates a record from the input data and returns it with an id assigned.

    After the flush the object has its primary key, but the transaction stays
    open.
    """
    record = Record(
        external_id=data.external_id,
        name=data.name,
        category=data.category,
        value=data.value,
    )
    session.add(record)
    await session.flush()
    return record


async def get_record(session: AsyncSession, record_id: int) -> Record | None:
    """Returns the record with the given primary key, or None when it is absent.

    session.get looks in the session identity map first, so fetching the same
    record again issues no further query.
    """
    return await session.get(Record, record_id)


async def update_record(
    session: AsyncSession,
    record: Record,
    data: RecordUpdate,
) -> Record:
    """Applies to the record only the fields actually sent in the request.

    exclude_unset=True tells a field left out (kept unchanged) apart from one
    explicitly set to None (the value is cleared).
    """
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(record, field, value)
    await session.flush()
    return record


async def delete_record(session: AsyncSession, record: Record) -> None:
    """Removes the record from the session and sends the DELETE through flush."""
    await session.delete(record)
    await session.flush()


async def list_records(
    session: AsyncSession,
    *,
    limit: int,
    offset: int,
    category: str | None = None,
    name_contains: str | None = None,
    value_min: float | None = None,
    value_max: float | None = None,
    order_by: str = DEFAULT_ORDER_BY,
    descending: bool = False,
) -> tuple[Sequence[Record], int]:
    """Returns one page of records and the total number matching the filters.

    Filters left as None are skipped, so a missing parameter means "do not
    narrow", not "compare against NULL". The conditions are joined with AND.

    total comes from a separate query, under the same conditions but without
    the limit and offset - that is how the client knows how many pages remain.

    An order_by outside SORTABLE_COLUMNS quietly falls back to created_at;
    validating the accepted values belongs to the HTTP layer.
    """
    conditions = []
    if category is not None:
        conditions.append(Record.category == category)
    if name_contains is not None:
        conditions.append(Record.name.ilike(f"%{name_contains}%"))
    if value_min is not None:
        conditions.append(Record.value >= value_min)
    if value_max is not None:
        conditions.append(Record.value <= value_max)

    count_query = select(func.count()).select_from(Record).where(*conditions)
    # COUNT always returns a row; the "or 0" is here purely for typing, since
    # scalar declares its result as optional.
    total = await session.scalar(count_query) or 0

    order_column = SORTABLE_COLUMNS.get(order_by, SORTABLE_COLUMNS[DEFAULT_ORDER_BY])
    # Record.id breaks ties: with equal values in the leading column the
    # database could return records in any order, so the same record would land
    # on two pages one time and on none the next.
    # nulls_last: without it the place of NULL depends on the dialect (SQLite
    # puts them first on ASC, PostgreSQL last), so one and the same page of
    # results would look different in tests and in production. Record.id is not
    # nullable, so the tie-breaker needs no wrapping.
    if descending:
        order_clauses = (nulls_last(order_column.desc()), Record.id.desc())
    else:
        order_clauses = (nulls_last(order_column.asc()), Record.id.asc())
    query = (
        select(Record)
        .where(*conditions)
        .order_by(*order_clauses)
        .offset(offset)
        .limit(limit)
    )
    records = (await session.scalars(query)).all()

    return records, total
