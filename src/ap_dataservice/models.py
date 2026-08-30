"""ORM models: the declarative base and the template's single resource."""

from datetime import datetime

from sqlalchemy import DateTime, Float, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Shared declarative base for the models (SQLAlchemy 2.0 style)."""


class Record(Base):
    """Record - the neutral template resource, a starting point for a domain."""

    __tablename__ = "records"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Identifier assigned by the data source - unique, because it is what tells
    # us whether a record already exists (an import may run more than once).
    external_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)

    name: Mapped[str] = mapped_column(String(255), index=True)
    category: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)

    # The database supplies the time (server_default), so the stamp is consistent
    # whatever the app process clock says. timezone=True: timestamptz on Postgres.
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
        return f"<Record id={self.id} external_id={self.external_id!r}>"
