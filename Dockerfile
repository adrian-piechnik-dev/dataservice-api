# syntax=docker/dockerfile:1

FROM python:3.13-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

# Building the package needs only the manifest and the sources: setuptools packs
# src/ alone (packages.find where=["src"]), so neither alembic.ini nor migrations/
# is needed here - both go into the runtime image instead.
COPY pyproject.toml ./
COPY src/ ./src/

# A non-editable install without [dev]: only runtime dependencies reach the image.
RUN pip install --prefix=/install .


FROM python:3.13-slim AS runtime

ENV PYTHONUNBUFFERED=1

WORKDIR /app

# The package with its dependencies and entry points (uvicorn, alembic).
COPY --from=builder /install /usr/local

# Migrations ship in the image but do NOT run on startup - the container assumes
# the schema is already there. Migrating is a separate step (docker compose run
# app alembic upgrade head / CI-CD / an init container), because with N replicas
# a parallel `upgrade head` would race over the alembic_version table.
COPY alembic.ini ./
COPY migrations/ ./migrations/

RUN useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "ap_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
