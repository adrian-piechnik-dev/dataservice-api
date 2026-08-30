"""Repository tests: the basic operations on a single record.

The repository does not commit by itself - the transactions are closed here
explicitly, the way the layer above does it in the application.

No assertion reaches for an ORM attribute after a commit: the values needed
(the primary key, the timestamp) are read right after create_record, once the
flush has assigned them and the object is still fresh. That keeps the tests
independent of whether the session fixture sets expire_on_commit to False.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from ap_api.repository import (
    create_record,
    delete_record,
    get_record,
    update_record,
)
from ap_api.schemas import RecordCreate, RecordUpdate


async def test_create_record_assigns_id_and_created_at(session: AsyncSession) -> None:
    """After the write the record carries a primary key and a timestamp."""
    record = await create_record(
        session,
        RecordCreate(external_id="ext-1", name="Nazwa", category="kat", value=1.5),
    )
    # The database assigns both fields on flush: id as the primary key and
    # created_at through server_default. We read them before the commit,
    # because afterwards the attribute access would depend on fixture settings.
    record_id = record.id
    created_at = record.created_at
    await session.commit()

    assert record_id is not None
    assert created_at is not None


async def test_get_record_returns_existing_record(session: AsyncSession) -> None:
    """A fetch by primary key returns the record written earlier."""
    record = await create_record(
        session,
        RecordCreate(external_id="ext-1", name="Nazwa", category="kat", value=1.5),
    )
    record_id = record.id
    await session.commit()

    found = await get_record(session, record_id)

    assert found is not None
    assert found.external_id == "ext-1"


async def test_get_record_returns_none_for_unknown_id(session: AsyncSession) -> None:
    """A missing record is None, not an exception - the HTTP layer decides."""
    assert await get_record(session, 99999) is None


async def test_update_record_leaves_omitted_fields_alone(session: AsyncSession) -> None:
    """A partial update changes only the fields passed in the request."""
    record = await create_record(
        session,
        RecordCreate(external_id="ext-1", name="Stara", category="kat"),
    )
    record_id = record.id
    await session.commit()

    await update_record(session, record, RecordUpdate(name="Nowa"))
    await session.commit()

    # expunge_all empties the session identity map, so the fetch below goes to
    # the database rather than to an object kept in memory - otherwise the test
    # would pass even if the change had never been written.
    session.expunge_all()
    reloaded = await get_record(session, record_id)

    assert reloaded is not None
    assert reloaded.name == "Nowa"
    assert reloaded.category == "kat"


async def test_update_record_explicit_none_clears_field(session: AsyncSession) -> None:
    """A field explicitly set to None gets cleared.

    This is the other side of exclude_unset: leaving a field out keeps its
    value, while an explicit None erases it.
    """
    record = await create_record(
        session,
        RecordCreate(external_id="ext-1", name="Nazwa", category="kat"),
    )
    record_id = record.id
    await session.commit()

    await update_record(session, record, RecordUpdate(category=None))
    await session.commit()

    session.expunge_all()
    reloaded = await get_record(session, record_id)

    assert reloaded is not None
    assert reloaded.category is None


async def test_delete_record_removes_the_record(session: AsyncSession) -> None:
    """After the delete and the commit the record can no longer be fetched."""
    record = await create_record(
        session,
        RecordCreate(external_id="ext-1", name="Nazwa"),
    )
    record_id = record.id
    await session.commit()

    await delete_record(session, record)
    await session.commit()

    assert await get_record(session, record_id) is None
