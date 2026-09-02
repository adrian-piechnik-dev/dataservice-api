"""Tests of the Pydantic schema contract (HTTP layer input and output)."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from ap_dataservice.models import TITLE_MAX_LENGTH
from ap_dataservice.schemas import StoryCreate, StoryRead, StoryUpdate

POSTED_AT = datetime(2026, 8, 29, 6, 12, tzinfo=timezone.utc)
SCRAPED_AT = datetime(2026, 8, 29, 8, 0, tzinfo=timezone.utc)


def test_create_rejects_empty_title() -> None:
    with pytest.raises(ValidationError):
        StoryCreate(
            hn_id=38101234,
            title="",
            url="https://github.com/example/pgbackup",
            author="pg_hacker",
            rank=1,
            posted_at=POSTED_AT,
            scraped_at=SCRAPED_AT,
        )


def test_create_rejects_overlong_title() -> None:
    """The upper bound is the column width, so the limit is in the contract.

    Without it the payload validates and only the INSERT refuses it, which the
    client sees as a server failure rather than as a bad request.
    """
    with pytest.raises(ValidationError):
        StoryCreate(
            hn_id=38101234,
            title="a" * (TITLE_MAX_LENGTH + 1),
            url="https://github.com/example/pgbackup",
            author="pg_hacker",
            rank=1,
            posted_at=POSTED_AT,
            scraped_at=SCRAPED_AT,
        )


def test_create_rejects_unknown_field() -> None:
    """extra="forbid" - an unknown field is an error, not silent data loss."""
    with pytest.raises(ValidationError):
        StoryCreate(
            hn_id=38101234,
            title="Show HN: A self-hosted Postgres backup tool",
            url="https://github.com/example/pgbackup",
            author="pg_hacker",
            rank=1,
            posted_at=POSTED_AT,
            scraped_at=SCRAPED_AT,
            unknown="x",
        )


def test_create_requires_the_scraper_timestamps() -> None:
    """posted_at and scraped_at have no default - the scraper supplies both."""
    with pytest.raises(ValidationError):
        StoryCreate(
            hn_id=38101234,
            title="Show HN: A self-hosted Postgres backup tool",
            url="https://github.com/example/pgbackup",
            author="pg_hacker",
            rank=1,
        )


def test_create_accepts_valid_payload() -> None:
    payload = StoryCreate(
        hn_id=38101234,
        title="Show HN: A self-hosted Postgres backup tool",
        url="https://github.com/example/pgbackup",
        site="github.com",
        author="pg_hacker",
        points=128,
        num_comments=43,
        rank=1,
        topic="databases",
        posted_at=POSTED_AT,
        scraped_at=SCRAPED_AT,
    )

    assert payload.hn_id == 38101234
    assert payload.title == "Show HN: A self-hosted Postgres backup tool"
    assert payload.site == "github.com"
    assert payload.points == 128
    assert payload.rank == 1
    # The counters and the job-post flag default for an entry that carries
    # none of them, so a minimal payload still describes a complete story.
    assert payload.is_hiring is False
    assert payload.company is None


def test_update_without_arguments_dumps_empty_dict() -> None:
    """An empty PATCH sets no field at all."""
    update = StoryUpdate()

    assert update.model_dump(exclude_unset=True) == {}


def test_update_dumps_only_set_fields() -> None:
    update = StoryUpdate(points=256)

    assert update.model_dump(exclude_unset=True) == {"points": 256}


def test_read_builds_from_orm_like_object() -> None:
    """from_attributes=True - the schema reads attributes, not dict keys."""
    obj = SimpleNamespace(
        id=1,
        hn_id=38101234,
        title="Show HN: A self-hosted Postgres backup tool",
        url="https://github.com/example/pgbackup",
        site="github.com",
        author="pg_hacker",
        points=128,
        num_comments=43,
        rank=1,
        is_hiring=False,
        topic="databases",
        company=None,
        posted_at=POSTED_AT,
        scraped_at=SCRAPED_AT,
        created_at=datetime(2026, 8, 29, 8, 0, 5, tzinfo=timezone.utc),
        updated_at=None,
    )

    read = StoryRead.model_validate(obj)

    assert read.id == 1
    assert read.hn_id == 38101234
