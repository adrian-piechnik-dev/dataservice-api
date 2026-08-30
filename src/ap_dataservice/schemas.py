"""Pydantic schemas: the contract of the HTTP layer (input and output)."""

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

ItemT = TypeVar("ItemT")


class RecordCreate(BaseModel):
    """Input payload for creating a record (POST).

    extra="forbid": an unknown field is a client error, not a value to drop
    silently.
    """

    model_config = ConfigDict(extra="forbid")

    external_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    category: str | None = None
    value: float | None = None


class RecordUpdate(BaseModel):
    """Input payload for a partial record update (PATCH).

    Every field is optional - the ones left out stay unchanged. Telling
    "left out" apart from "explicitly set to None" belongs to the write layer
    (e.g. through model_dump(exclude_unset=True)).
    """

    model_config = ConfigDict(extra="forbid")

    external_id: str | None = Field(default=None, min_length=1)
    name: str | None = Field(default=None, min_length=1)
    category: str | None = None
    value: float | None = None


class RecordRead(BaseModel):
    """Record representation returned to the client.

    from_attributes=True: the schema is built straight from the ORM object.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    external_id: str
    name: str
    category: str | None
    value: float | None
    created_at: datetime
    updated_at: datetime | None


class Page(BaseModel, Generic[ItemT]):
    """A page of listed resources, generic over the item type.

    total counts every record matching the query, not the size of the current
    page - that is how the client knows whether further pages follow.
    """

    items: list[ItemT]
    total: int
    limit: int
    offset: int
