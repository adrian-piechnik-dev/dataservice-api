"""Smoke test of the database layer: writing and reading back a record."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ap_dataservice.models import Record


async def test_record_roundtrip(session: AsyncSession) -> None:
    """A saved record reads back, and the database fills id and created_at."""
    session.add(Record(external_id="ext-1", name="Nazwa"))
    await session.commit()

    record = (await session.scalars(select(Record))).first()

    assert record is not None
    assert record.external_id == "ext-1"
    assert record.name == "Nazwa"
    assert record.id is not None
    assert record.created_at is not None
