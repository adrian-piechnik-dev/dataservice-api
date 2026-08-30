# tpl-fastapi

An async REST API template built on FastAPI, SQLAlchemy 2.0 (async), Alembic migrations and API-key authentication.

![CI](https://github.com/adrian-piechnik-dev/tpl-fastapi/actions/workflows/ci.yml/badge.svg)

## Features

- **Async CRUD** over a single `Record` resource: `POST`, `GET` (list and by id), `PATCH`, `DELETE`
- **Pagination** with `limit` / `offset` and a `total` count of every match, not just the page
- **Filtering** by `category`, `name_contains`, `value_min`, `value_max`
- **Stable ordering** by `created_at`, `name`, `value` or `id`, with `descending` and NULLs last on every dialect
- **API-key authentication** through the `X-API-Key` header, applied to the whole resource router
- **Alembic migrations** wired to the application settings, with the schema baseline included
- **Docker** image: multi-stage, non-root, runtime dependencies only
- **CI** on GitHub Actions: migrations and tests on a clean Ubuntu, plus a Docker image build

## Quick start

1. Clone the repository:

   ```bash
   git clone git@github.com:adrian-piechnik-dev/tpl-fastapi.git
   cd tpl-fastapi
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

6. Run the development server:

   ```bash
   uvicorn ap_dataservice.main:app --reload
   ```

7. Open <http://localhost:8000/docs>. Use the **Authorize** button to send your
   `X-API-Key`; every `/records` request is rejected with 401 without it.

## Testing

```bash
pytest -q
```

61 tests cover the settings, schemas, repository, HTTP routes, authentication
and the OpenAPI document. They run against an in-memory SQLite database created
per test, so no setup and no cleanup is needed.

## Docker

Build the image:

```bash
docker build -t tpl-fastapi .
```

Run the service:

```bash
docker run --rm -p 8000:8000 \
  -e DATABASE_URL="postgresql+asyncpg://user:pass@host:5432/dbname" \
  -e API_KEY="your-key" \
  tpl-fastapi
```

**Migrations do not run on container start.** The container assumes the schema
is already there — with several replicas a parallel `alembic upgrade head`
would race over the `alembic_version` table. Run migrations as a separate step
before the service starts:

```bash
docker run --rm \
  -e DATABASE_URL="postgresql+asyncpg://user:pass@host:5432/dbname" \
  -e API_KEY="your-key" \
  tpl-fastapi alembic upgrade head
```

## Project structure

```
src/ap_dataservice/
├── __init__.py
├── config.py       # Settings read from the environment (fail-fast)
├── db.py           # Async engine, session factory, FastAPI dependency
├── main.py         # Application factory and ASGI entry point
├── models.py       # Declarative base and the Record model
├── repository.py   # Data access: CRUD, filtering, pagination, ordering
├── routes.py       # HTTP layer of the Record resource
├── schemas.py      # Pydantic request and response schemas
└── security.py     # API-key dependency

tests/              # 61 tests, one module per layer
migrations/         # Alembic environment
└── versions/       # Schema revisions (baseline: a7e14c606a78)
```

## Retargeting the template

Replace `Record` in `models.py` with your own entity and mirror it in
`schemas.py`, keeping the split between input and output models. Then generate
a migration for the new shape with `alembic revision --autogenerate` and review
the result before applying it — autogenerate proposes, it does not decide.
Adjust `routes.py` and `repository.py` to the fields your
resource actually exposes, including the sortable-column allow-list, which the
HTTP layer and the repository keep in two places on purpose.

For PostgreSQL, point `DATABASE_URL` at `postgresql+asyncpg://user:pass@host:5432/dbname`.
No dependency change is needed — `asyncpg` already ships with the template.
