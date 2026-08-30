# CLAUDE.md

Instructions for Claude Code working in this repository and in clones of it.
User-facing documentation lives in `README.md` — this file is the working contract.

## Project

Async REST API serving Hacker News front-page stories scraped by the P1
project smartscraper-ai: FastAPI, SQLAlchemy 2.0 async, Alembic, API-key auth.
The package `ap_dataservice` is split one concern per module: `config.py` (settings),
`db.py` (engine and session), `models.py` (ORM), `schemas.py` (Pydantic
contracts), `repository.py` (data access), `routes.py` (HTTP), `security.py`
(auth), `main.py` (application factory). Keep new code inside that split —
routes never write SQL, the repository never knows about HTTP.

## Commands

```bash
pip install -e ".[dev]"                          # install with dev dependencies
pytest -q                                        # run the test suite
alembic upgrade head                             # apply migrations
alembic revision --autogenerate -m "message"     # create a migration
python -m scripts.seed_from_csv                  # load examples/hn_demo.csv
uvicorn ap_dataservice.main:app --reload         # run the dev server
docker build -t dataservice-api .                # build the image
docker run --rm -p 8000:8000 -e DATABASE_URL=... -e API_KEY=... dataservice-api
```

`alembic` and `pytest` both need `DATABASE_URL` and `API_KEY` in the environment
or in `.env` — settings are validated before either command does anything.

## Architecture conventions

- **src layout**, package `ap_dataservice` under `src/`. Imports are always absolute
  (`from ap_dataservice.models import Story`).
- **Async throughout**: async endpoints, `AsyncSession`, `create_async_engine`.
  No sync database calls.
- **Settings are fail-fast**: `DATABASE_URL` and `API_KEY` are required, so a
  missing value stops startup rather than surfacing later. Read config through
  `get_settings()`, never `os.environ` directly.
- **The repository is free functions**, not a class — the session is the first
  argument, which keeps the dependency visible in the signature. Keep it that way.
- **No commits in the repository layer**: it flushes, the route commits. The
  transaction boundary belongs to the HTTP layer.
- **Auth**: `Security(require_api_key)` is declared on the router, so it covers
  every path of the resource and reaches OpenAPI. Do not repeat it per endpoint.
- **Migrations take the URL from Settings**, not from `alembic.ini` — the
  `sqlalchemy.url` line there is commented out on purpose. In `env.py` the
  interpolated section dict is overwritten; do not switch to `set_main_option`,
  which would break passwords containing `%`.
- **Line length 88.** Observed convention only — no formatter or linter is
  configured (no ruff, black, mypy, flake8 or pre-commit in this repo). Do not
  add one without being asked.
- **English everywhere**: docstrings, comments, commit messages, docs.

## Testing conventions

- Each test gets its own **in-memory SQLite** database from the `engine` and
  `session` fixtures in `conftest.py`, created and dropped per test. No shared
  state, no cleanup code.
- **One test module per layer**: `test_config`, `test_schemas`, `test_repository`,
  `test_routes`, `test_security`, `test_main`, `test_list_stories`,
  `test_db_smoke`. Put a new test where its layer already lives.
- `asyncio_mode = "auto"` is set in `pyproject.toml`, so async tests need no
  `@pytest.mark.asyncio` marker.
- Routes and auth are tested through a **real ASGI stack** (`httpx.ASGITransport`),
  asserting what the client sees: status code, body, headers.
- Dependencies are swapped with `dependency_overrides` on `get_session` and
  `get_settings` (see `test_routes.py`, `test_security.py`), not by patching
  modules. `test_main.py` is the exception: `create_app` reads settings at call
  time, so it uses `monkeypatch` on `ap_dataservice.main.get_settings`.
- 64 tests currently pass. A change that alters the count should say so.

## Boundaries

Ask before doing any of these:

- **Changing `models.py` without a migration.** A schema change means a new
  Alembic revision (`--autogenerate`, then review the generated file). Never
  edit an applied revision.
- **Adding a dependency.** `pyproject.toml` is deliberately small; justify the
  addition first.
- **Committing.** Stage explicit paths (`git add path/to/file`), never
  `git add .` or `-A`. Never commit `.env` or `*.db` — both are gitignored,
  keep it that way.
- **Force-pushing or rewriting history.** Not without an explicit request.
- **Running migrations from a container entrypoint.** The image ships them but
  does not run them: with several replicas a parallel `upgrade head` would race
  over `alembic_version`. Migration stays a separate step.
