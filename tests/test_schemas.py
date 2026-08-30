"""Tests of the Pydantic schema contract (HTTP layer input and output)."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from ap_api.schemas import RecordCreate, RecordRead, RecordUpdate


def test_create_rejects_empty_name() -> None:
    with pytest.raises(ValidationError):
        RecordCreate(external_id="ext-1", name="")


def test_create_rejects_unknown_field() -> None:
    """extra="forbid" - an unknown field is an error, not silent data loss."""
    with pytest.raises(ValidationError):
        RecordCreate(external_id="ext-1", name="Nazwa", unknown="x")


def test_create_accepts_valid_payload() -> None:
    payload = RecordCreate(
        external_id="ext-1",
        name="Nazwa",
        category="kategoria",
        value=12.5,
    )

    assert payload.external_id == "ext-1"
    assert payload.name == "Nazwa"
    assert payload.category == "kategoria"
    assert payload.value == 12.5


def test_update_without_arguments_dumps_empty_dict() -> None:
    """An empty PATCH sets no field at all."""
    update = RecordUpdate()

    assert update.model_dump(exclude_unset=True) == {}


def test_update_dumps_only_set_fields() -> None:
    update = RecordUpdate(name="nowa")

    assert update.model_dump(exclude_unset=True) == {"name": "nowa"}


def test_read_builds_from_orm_like_object() -> None:
    """from_attributes=True - the schema reads attributes, not dict keys."""
    obj = SimpleNamespace(
        id=1,
        external_id="ext-1",
        name="Nazwa",
        category=None,
        value=None,
        created_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        updated_at=None,
    )

    read = RecordRead.model_validate(obj)

    assert read.id == 1
    assert read.external_id == "ext-1"
