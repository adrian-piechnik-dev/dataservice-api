# dataservice-api

An async REST API serving Hacker News front-page stories, built on FastAPI, SQLAlchemy 2.0 (async), Alembic migrations and API-key authentication.

![CI](https://github.com/adrian-piechnik-dev/dataservice-api/actions/workflows/ci.yml/badge.svg)

## Live demo

<https://dataservice-api.onrender.com/docs>

Hosted on Render's free tier, so the instance sleeps when idle — the first
request after a pause takes up to ~60 seconds while it wakes up. The `/docs`
page itself is public, but every `/stories` call needs a valid `X-API-Key`
header, and that key is not published here.

This is an instance of the [tpl-fastapi](https://github.com/adrian-piechnik-dev/tpl-fastapi)
template, retargeted onto a real domain: the data it serves is scraped from the
Hacker News front page by [smartscraper-ai](https://github.com/adrian-piechnik-dev/smartscraper-ai).

## Features

- **Async CRUD** over a single `Story` resource: `POST`, `GET` (list and by id), `PATCH`, `DELETE`
- **Pagination** with `limit` / `offset` and a `total` count of every match, not just the page
- **Filtering** by `site`, `title_contains`, `points_min`, `points_max` and `is_hiring`
- **Stable ordering** by `scraped_at`, `posted_at`, `points`, `num_comments`, `rank`, `title`, `site` or `id`, with `descending` and NULLs last on every dialect
- **API-key authentication** through the `X-API-Key` header, applied to the whole resource router
- **Alembic migrations** wired to the application settings, with the schema baseline included
- **CSV seeding** from the scraper's output, idempotent on re-runs
- **Docker** image: multi-stage, non-root, runtime dependencies only
- **CI** on GitHub Actions: migrations and tests on a clean Ubuntu, plus a Docker image build

## The Story resource

One row is one entry as the scraper saw it on the front page:

| Field | Type | Notes |
| --- | --- | --- |
| `id` | int | Primary key of this database, not of Hacker News |
| `hn_id` | int | The Hacker News id — unique, and what makes a re-import idempotent |
| `title` | str | Entry title |
| `url` | str | Where the entry points |
| `site` | str \| None | Host badge; empty for a self-post (Ask HN and friends) |
| `author` | str | Submitter's handle |
| `points` | int | Score at the moment of the scrape |
| `num_comments` | int | Comment count at the moment of the scrape |
| `rank` | int | Position on the front page — a property of the listing, not of the entry |
| `is_hiring` | bool | Whether the entry is a job post |
| `topic` | str \| None | Short subject label derived by the scraper |
| `company` | str \| None | Company the entry is about, when there is one |
| `posted_at` | datetime | When Hacker News published the entry |
| `scraped_at` | datetime | When the scraper read it |
| `created_at` | datetime | Row audit, filled in by the database |
| `updated_at` | datetime \| None | Row audit, empty until the first update |

`points`, `num_comments` and `rank` go stale within the hour — they describe a
snapshot of the front page, which is why a re-import updates them rather than
skipping the row.

## Quick start

1. Clone the repository:

   ```bash
   git clone git@github.com:adrian-piechnik-dev/dataservice-api.git
   cd dataservice-api
   ```

2. Create and activate a virtual environment (Python 3.13 or newer):

   ```bash
   python -m venv .venv
   source .venv/bin/activate     # Linux / macOS
   .venv\Scripts\activate        # Windows (PowerShell, cmd)
   ```

   > **Git Bash on Windows:** do not run `source .venv/Scripts/activate` there.
   > It prepends Windows paths to `PATH` and shadows the Unix tools Git Bash
   > provides (`date`, `cp`, `tail` stop resolving). Skip activation and call
   > the binaries directly instead — `.venv/Scripts/python.exe -m pip ...`,
   > `.venv/Scripts/alembic.exe ...`, `.venv/Scripts/pytest.exe ...`.
   > PowerShell and cmd are unaffected.

3. Install the package with its development dependencies:

   ```bash
   pip install -e ".[dev]"
   ```

4. Create your environment file and set a real key:

   ```bash
   cp .env.example .env
   ```

   `DATABASE_URL` and `API_KEY` are required — the application refuses to start
   without them. The example ships with a local SQLite database and the
   placeholder `API_KEY=change-me`; replace it before exposing the service.

5. Create the database schema:

   ```bash
   alembic upgrade head
   ```

6. Load the demo data:

   ```bash
   python -m scripts.seed_from_csv
   ```

7. Run the development server:

   ```bash
   uvicorn ap_dataservice.main:app --reload
   ```

8. Open <http://localhost:8000/docs>. Use the **Authorize** button to send your
   `X-API-Key`; every `/stories` request is rejected with 401 without it.

## Seeding

`scripts/seed_from_csv.py` reads the CSV that smartscraper-ai produces and
writes it into whatever `DATABASE_URL` points at — the local SQLite file or the
managed PostgreSQL behind the deployed service, through the same code path:

```bash
python -m scripts.seed_from_csv [csv_path]     # default: examples/hn_demo.csv
```

`examples/hn_demo.csv` is a captured front page (30 entries) kept in the
repository, so a fresh clone has something to serve.

The seed is idempotent through `hn_id`: an entry the database already holds is
updated, not duplicated. Updating rather than skipping is deliberate — skipping
would freeze `points`, `num_comments` and `rank` on whatever the first scrape
happened to see. The script assumes the schema exists and never creates tables;
that authority belongs to Alembic alone.

## Testing

```bash
pytest -q
```

64 tests cover the settings, schemas, repository, HTTP routes, authentication
and the OpenAPI document. They run against an in-memory SQLite database created
per test, so no setup and no cleanup is needed.

## Docker

Build the image:

```bash
docker build -t dataservice-api .
```

Run the service:

```bash
docker run --rm -p 8000:8000 \
  -e DATABASE_URL="postgresql+asyncpg://user:pass@host:5432/dbname" \
  -e API_KEY="your-key" \
  dataservice-api
```

**Migrations do not run on container start.** The container assumes the schema
is already there — with several replicas a parallel `alembic upgrade head`
would race over the `alembic_version` table. Run migrations as a separate step
before the service starts:

```bash
docker run --rm \
  -e DATABASE_URL="postgresql+asyncpg://user:pass@host:5432/dbname" \
  -e API_KEY="your-key" \
  dataservice-api alembic upgrade head
```

The image packs `src/` only, so the seed script is not inside it. Seeding a
remote database runs from a checkout, with `DATABASE_URL` pointed at it.

## PostgreSQL

Point `DATABASE_URL` at `postgresql+asyncpg://user:pass@host:5432/dbname`. No
dependency change is needed — `asyncpg` already ships with the project.

**On Neon (and other hosts that require TLS)** the URL has to ask for it
explicitly, with `?ssl=require`:

```
postgresql+asyncpg://user:pass@host/dbname?ssl=require
```

The `sslmode` and `channel_binding` parameters Neon shows in its own connection
strings come from libpq; `asyncpg` does not understand them, and leaving them
in the URL fails the connection. Strip them and use `ssl=require` instead.

## Project structure

```
src/ap_dataservice/
├── __init__.py
├── config.py       # Settings read from the environment (fail-fast)
├── db.py           # Async engine, session factory, FastAPI dependency
├── main.py         # Application factory and ASGI entry point
├── models.py       # Declarative base and the Story model
├── repository.py   # Data access: CRUD, filtering, pagination, ordering
├── routes.py       # HTTP layer of the Story resource
├── schemas.py      # Pydantic request and response schemas
└── security.py     # API-key dependency

scripts/            # Operational entry points, outside the packaged code
└── seed_from_csv.py
examples/           # Input data for the seed
└── hn_demo.csv
tests/              # 64 tests, one module per layer
migrations/         # Alembic environment
└── versions/       # Schema revisions (baseline: 706bc60acdf5)
```

## Where this came from

The repository started as the `tpl-fastapi` template, whose neutral `Record`
resource was replaced by `Story` in a single vertical slice: model, schemas,
repository, routes, migration and tests. The template's own baseline revision
was deleted rather than migrated away from — an instance that never shipped a
`records` table has no reason to carry its history.

Two seams stayed as the template drew them, because they earn it. The
sortable-column allow-list is written twice, in `repository.py` and as the
`OrderBy` literal in `routes.py`, so the HTTP layer can reject an unknown
column with a 422 instead of quietly sorting by something else; a test asserts
that the two agree. And ordering is wrapped in `nulls_last()` rather than left
to the dialect, because SQLite puts NULLs first on `ASC` while PostgreSQL puts
them last — without it the same page would differ between the test suite and
production.
