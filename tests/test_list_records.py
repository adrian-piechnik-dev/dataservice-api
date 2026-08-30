"""Tests for listing records: filters, pagination and ordering.

The data set is fixed and prepared by the sample_records fixture - each test
asks for a ready database and checks one aspect of the query.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ap_dataservice.repository import create_record, list_records
from ap_dataservice.schemas import RecordCreate

# Test data: two records share value=20.0 (ordering stability), and the last
# one has an empty category and value (how the filters treat NULL).
SAMPLE = [
    RecordCreate(external_id="ext-1", name="Alpha", category="A", value=10.0),
    RecordCreate(external_id="ext-2", name="Beta", category="A", value=20.0),
    RecordCreate(external_id="ext-3", name="Gamma", category="B", value=20.0),
    RecordCreate(external_id="ext-4", name="Delta", category="B", value=30.0),
    RecordCreate(external_id="ext-5", name="alpha X", category=None, value=None),
]


@pytest.fixture
async def sample_records(session: AsyncSession) -> None:
    """Fills the database with five records of known fields and commits."""
    for data in SAMPLE:
        await create_record(session, data)
    await session.commit()


async def test_no_filters_returns_all_records(
    session: AsyncSession,
    sample_records: None,
) -> None:
    """No filters means the full list and a total equal to the record count."""
    records, total = await list_records(session, limit=100, offset=0)

    assert len(records) == 5
    assert total == 5


async def test_category_filter_narrows_to_one_category(
    session: AsyncSession,
    sample_records: None,
) -> None:
    """The category filter matches by equality, so only category A returns."""
    records, total = await list_records(session, limit=100, offset=0, category="A")

    assert [record.external_id for record in records] == ["ext-1", "ext-2"]
    assert total == 2


async def test_value_min_skips_records_without_value(
    session: AsyncSession,
    sample_records: None,
) -> None:
    """Comparing with NULL is never true, so a record without value drops out."""
    records, total = await list_records(session, limit=100, offset=0, value_min=20.0)

    assert sorted(record.external_id for record in records) == ["ext-2", "ext-3", "ext-4"]
    assert total == 3


async def test_value_min_and_max_form_inclusive_range(
    session: AsyncSession,
    sample_records: None,
) -> None:
    """Both ends are inclusive, so a value exactly on the bound passes."""
    records, total = await list_records(
        session,
        limit=100,
        offset=0,
        value_min=20.0,
        value_max=20.0,
    )

    assert sorted(record.external_id for record in records) == ["ext-2", "ext-3"]
    assert total == 2


async def test_name_contains_ignores_letter_case(
    session: AsyncSession,
    sample_records: None,
) -> None:
    """ilike matches a fragment of the name regardless of letter case."""
    records, total = await list_records(
        session,
        limit=100,
        offset=0,
        name_contains="alpha",
    )

    assert sorted(record.external_id for record in records) == ["ext-1", "ext-5"]
    assert total == 2


async def test_total_counts_all_matches_not_the_page(
    session: AsyncSession,
    sample_records: None,
) -> None:
    """limit trims the list, but total stays the count of every match."""
    records, total = await list_records(
        session,
        limit=2,
        offset=0,
        order_by="value",
        descending=False,
    )

    assert len(records) == 2
    assert total == 5


async def test_ordering_by_value_puts_nulls_last(
    session: AsyncSession,
    sample_records: None,
) -> None:
    """Checks the full result order, including the record without a value.

    The direction applies only to records that have a value; NULL stays last
    both ways (the nulls_last contract in list_records), not wherever the
    database dialect would place it. A tie on value=20 is broken by ascending
    id, so in descending order the ext-2/ext-3 pair flips with the rest.
    """
    rosnaco, _ = await list_records(session, limit=100, offset=0, order_by="value")
    malejaco, _ = await list_records(
        session,
        limit=100,
        offset=0,
        order_by="value",
        descending=True,
    )

    assert [r.external_id for r in rosnaco] == [
        "ext-1",
        "ext-2",
        "ext-3",
        "ext-4",
        "ext-5",
    ]
    assert [r.external_id for r in malejaco] == [
        "ext-4",
        "ext-3",
        "ext-2",
        "ext-1",
        "ext-5",
    ]


async def test_order_of_equal_values_is_stable(
    session: AsyncSession,
    sample_records: None,
) -> None:
    """A tie on value is broken by id, so both answers keep the same order."""
    pierwsze, _ = await list_records(session, limit=100, offset=0, order_by="value")
    drugie, _ = await list_records(session, limit=100, offset=0, order_by="value")

    remis_pierwsze = [r.external_id for r in pierwsze if r.value == 20.0]
    remis_drugie = [r.external_id for r in drugie if r.value == 20.0]

    assert remis_pierwsze == ["ext-2", "ext-3"]
    assert remis_pierwsze == remis_drugie


async def test_unknown_sort_column_does_not_break_query(
    session: AsyncSession,
    sample_records: None,
) -> None:
    """An order_by outside the allow-list quietly falls back to created_at."""
    records, total = await list_records(
        session,
        limit=100,
        offset=0,
        order_by="nieistniejaca_kolumna",
    )

    assert len(records) == 5
    assert total == 5
