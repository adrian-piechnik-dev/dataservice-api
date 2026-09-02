"""Pydantic schemas: the contract of the HTTP layer (input and output)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from ap_dataservice.models import (
    AUTHOR_MAX_LENGTH,
    COMPANY_MAX_LENGTH,
    SITE_MAX_LENGTH,
    TITLE_MAX_LENGTH,
    TOPIC_MAX_LENGTH,
    URL_MAX_LENGTH,
)


class StoryCreate(BaseModel):
    """Input payload for creating a story (POST).

    extra="forbid": an unknown field is a client error, not a value to drop
    silently.

    posted_at and scraped_at carry no default: both come from the scraper, so
    a payload without them is incomplete rather than something to stamp here.

    The text limits are the column widths from models.py, so a value too long
    for the database is a 422 here instead of a failed INSERT further down.
    """

    model_config = ConfigDict(extra="forbid")

    hn_id: int
    title: str = Field(min_length=1, max_length=TITLE_MAX_LENGTH)
    url: str = Field(min_length=1, max_length=URL_MAX_LENGTH)
    site: str | None = Field(default=None, max_length=SITE_MAX_LENGTH)
    author: str = Field(min_length=1, max_length=AUTHOR_MAX_LENGTH)
    points: int = 0
    num_comments: int = 0
    rank: int
    is_hiring: bool = False
    topic: str | None = Field(default=None, max_length=TOPIC_MAX_LENGTH)
    company: str | None = Field(default=None, max_length=COMPANY_MAX_LENGTH)
    posted_at: datetime
    scraped_at: datetime


class StoryUpdate(BaseModel):
    """Input payload for a partial story update (PATCH).

    Every field is optional - the ones left out stay unchanged. Telling
    "left out" apart from "explicitly set to None" belongs to the write layer
    (e.g. through model_dump(exclude_unset=True)).
    """

    model_config = ConfigDict(extra="forbid")

    hn_id: int | None = None
    title: str | None = Field(default=None, min_length=1, max_length=TITLE_MAX_LENGTH)
    url: str | None = Field(default=None, min_length=1, max_length=URL_MAX_LENGTH)
    site: str | None = Field(default=None, max_length=SITE_MAX_LENGTH)
    author: str | None = Field(default=None, min_length=1, max_length=AUTHOR_MAX_LENGTH)
    points: int | None = None
    num_comments: int | None = None
    rank: int | None = None
    is_hiring: bool | None = None
    topic: str | None = Field(default=None, max_length=TOPIC_MAX_LENGTH)
    company: str | None = Field(default=None, max_length=COMPANY_MAX_LENGTH)
    posted_at: datetime | None = None
    scraped_at: datetime | None = None


class StoryRead(BaseModel):
    """Story representation returned to the client.

    from_attributes=True: the schema is built straight from the ORM object.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    hn_id: int
    title: str
    url: str
    site: str | None
    author: str
    points: int
    num_comments: int
    rank: int
    is_hiring: bool
    topic: str | None
    company: str | None
    posted_at: datetime
    scraped_at: datetime
    created_at: datetime
    updated_at: datetime | None


class Page[ItemT](BaseModel):
    """A page of listed resources, generic over the item type.

    total counts every story matching the query, not the size of the current
    page - that is how the client knows whether further pages follow.
    """

    items: list[ItemT]
    total: int
    limit: int
    offset: int
