"""ORM models: the declarative base and the Hacker News story resource."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Column widths, kept here as the single source of truth. The same numbers bound
# three separate things - the column, the input schema and the length of a text
# filter - and only the first one of those is checked by the database. Written
# down three times they drift apart quietly: a column widened here would leave a
# schema that still rejects the values the column now accepts.
TITLE_MAX_LENGTH = 512
URL_MAX_LENGTH = 2048
SITE_MAX_LENGTH = 255
AUTHOR_MAX_LENGTH = 255
TOPIC_MAX_LENGTH = 255
COMPANY_MAX_LENGTH = 255


class Base(DeclarativeBase):
    """Shared declarative base for the models (SQLAlchemy 2.0 style)."""


class Story(Base):
    """Story - one Hacker News entry, as the P1 scraper produces it."""

    __tablename__ = "stories"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Identifier assigned by Hacker News - unique, because it is what tells us
    # whether a story already exists (a scrape may run more than once, and the
    # same entry stays on the front page across runs).
    hn_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)

    title: Mapped[str] = mapped_column(String(TITLE_MAX_LENGTH), index=True)
    url: Mapped[str] = mapped_column(String(URL_MAX_LENGTH))

    # Host the entry points at. Empty for a self-post (Ask HN, Show HN without
    # a link), where the story is the discussion itself.
    site: Mapped[str | None] = mapped_column(
        String(SITE_MAX_LENGTH),
        nullable=True,
        index=True,
    )

    author: Mapped[str] = mapped_column(String(AUTHOR_MAX_LENGTH))

    points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    num_comments: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Position on the front page at the moment of the scrape - a property of
    # the listing, not of the entry, so it changes between runs.
    rank: Mapped[int] = mapped_column(Integer, nullable=False)

    is_hiring: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    topic: Mapped[str | None] = mapped_column(String(TOPIC_MAX_LENGTH), nullable=True)
    company: Mapped[str | None] = mapped_column(
        String(COMPANY_MAX_LENGTH), nullable=True
    )

    # Both stamps come from the scraper, not from this database: posted_at is
    # when Hacker News published the entry, scraped_at when P1 read it.
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scraped_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    # Row audit, separate from the source stamps above: the database supplies
    # the time (server_default), so it is consistent whatever the app process
    # clock says. timezone=True: timestamptz on Postgres.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Empty until the first modification; set on every UPDATE afterwards.
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        onupdate=func.now(),
    )

    def __repr__(self) -> str:
        """Concise diagnostic representation (id and source identifier)."""
        return f"<Story id={self.id} hn_id={self.hn_id!r}>"
