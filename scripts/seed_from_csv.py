"""Loads stories into the database from a CSV produced by the P1 scraper.

    python -m scripts.seed_from_csv [csv_path]

The connection is not the script's own: the engine and the session factory
come from ap_dataservice.db, so the target is whatever DATABASE_URL points at
- a local SQLite file or the managed PostgreSQL behind the deployed service -
and the same run works against both.

The schema is assumed to exist. Creating tables here would put a second
authority beside Alembic, and the two would drift; `alembic upgrade head` runs
first, as its own step.

Re-running is safe. An entry the database already holds is updated rather than
skipped: hn_id identifies the story, but points, comments and rank describe the
front page at the moment of the scrape and go stale within the hour. Skipping
would make the second run useless for exactly the fields that change, and would
freeze the service on whatever the first scrape happened to see. What the entry
was born with - the identifier, the URL and the publication time - is written
once and never rewritten.
"""

import asyncio
import csv
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from ap_dataservice.db import get_engine, get_session_factory
from ap_dataservice.models import Story

DEFAULT_CSV_PATH = Path("examples/hn_demo.csv")

# Fields refreshed on an entry the database already holds. hn_id stays out
# because it is what matched the row in the first place, and posted_at with
# url stay out because they describe the entry itself, not the listing: a
# later scrape of the same story reports them unchanged.
MUTABLE_FIELDS = (
    "title",
    "site",
    "author",
    "points",
    "num_comments",
    "rank",
    "is_hiring",
    "topic",
    "company",
    "scraped_at",
)

logger = logging.getLogger("seed_from_csv")


def parse_bool(value: str | None) -> bool:
    """Reads a boolean out of the CSV text form.

    bool(value) is not an option here: every non-empty string is truthy, so
    the scraper's "false" would come back as True and mark the whole front
    page as job posts.
    """
    return value is not None and value.strip().lower() == "true"


def row_to_fields(row: dict[str, str]) -> dict[str, Any]:
    """Maps one CSV row onto the Story columns.

    Everything the scraper knows beyond the four flat columns travels in
    `extra` as a JSON object, with every value written as text - hence the
    explicit int() and datetime conversions. Optional keys may be absent
    (a self-post carries no site, a story about no company carries none),
    and a missing key means None rather than an error.

    `price` is ignored: it belongs to the scraper's generic output shape and
    stays empty for Hacker News. created_at and updated_at are not set at all
    - those columns are the database's to fill.
    """
    extra = json.loads(row["extra"])
    return {
        "hn_id": int(extra["hn_id"]),
        "title": row["title"],
        "url": row["url"],
        "site": extra.get("site"),
        "author": extra["author"],
        "points": int(extra["points"]),
        "num_comments": int(extra["comments"]),
        "rank": int(extra["rank"]),
        "is_hiring": parse_bool(extra.get("is_hiring")),
        "topic": extra.get("topic"),
        "company": extra.get("company"),
        "posted_at": datetime.fromisoformat(extra["age_iso"]),
        "scraped_at": datetime.fromisoformat(row["scraped_at"]),
    }


def read_csv(csv_path: Path) -> list[dict[str, Any]]:
    """Reads the whole file into memory, one dict of Story fields per row.

    newline="": the csv module handles line ends itself, and a title carrying
    a newline inside quotes has to survive the read.
    """
    with csv_path.open(newline="", encoding="utf-8") as handle:
        return [row_to_fields(row) for row in csv.DictReader(handle)]


async def seed(csv_path: Path) -> tuple[int, int, int]:
    """Writes the file into the database and returns (read, inserted, updated).

    The stories already present are fetched in one query rather than one per
    row, so the run costs a constant number of round trips - which matters
    against a managed database an ocean away, not against a local file.

    A single transaction covers the whole file: a malformed row halfway
    through leaves the database as it was, instead of half-seeded.
    """
    rows = read_csv(csv_path)
    logger.info("read %d rows from %s", len(rows), csv_path)

    inserted = 0
    updated = 0

    factory = get_session_factory()
    async with factory() as session:
        hn_ids = [fields["hn_id"] for fields in rows]
        existing = {
            story.hn_id: story
            for story in await session.scalars(
                select(Story).where(Story.hn_id.in_(hn_ids))
            )
        }

        for fields in rows:
            story = existing.get(fields["hn_id"])
            if story is None:
                story = Story(**fields)
                session.add(story)
                # Registered right away, so a file that lists the same entry
                # twice updates the pending row instead of inserting it again
                # and hitting the unique constraint.
                existing[story.hn_id] = story
                inserted += 1
                continue

            for field in MUTABLE_FIELDS:
                setattr(story, field, fields[field])
            updated += 1

        await session.commit()

    logger.info("inserted %d, updated %d", inserted, updated)
    return len(rows), inserted, updated


def main(argv: list[str] | None = None) -> int:
    """Entry point: reads the path from the command line and runs the seed."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    args = sys.argv[1:] if argv is None else argv
    csv_path = Path(args[0]) if args else DEFAULT_CSV_PATH

    if not csv_path.is_file():
        logger.error("no such CSV file: %s", csv_path)
        return 1

    try:
        asyncio.run(_run(csv_path))
    except (KeyError, ValueError) as error:
        # A missing key or an unparsable number means the file is not the
        # scraper's output. Nothing was written - the transaction rolled back.
        logger.error("malformed CSV: %s", error)
        return 1

    return 0


async def _run(csv_path: Path) -> None:
    """Runs the seed and disposes of the engine the settings built for it."""
    try:
        await seed(csv_path)
    finally:
        await get_engine().dispose()


if __name__ == "__main__":
    raise SystemExit(main())
