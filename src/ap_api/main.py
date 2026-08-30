"""Application factory: the finished layers assembled into one HTTP service.

The module holds no logic and no queries - it only wires up what was built
below it: metadata comes from the settings, routes from the resource router.
Changing how the API behaves therefore never means editing this file.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from ap_api.config import get_settings
from ap_api.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: does nothing on startup and nothing on shutdown.

    The schema is created by migrations, not by the start of a web process.
    With several application instances each of them would try to alter the
    schema at once, and a deployment would have no way back - which is why
    that responsibility belongs to Alembic.
    """
    yield


def create_app() -> FastAPI:
    """Builds the application from the settings and the resource router.

    A factory rather than a bare module-level instance: tests assemble their
    own application and so inherit no state from the shared one.

    Metadata comes from the settings, so the title and version shown in /docs
    and openapi.json change through the environment, without touching code.
    """
    settings = get_settings()
    application = FastAPI(
        title=settings.app_title,
        description=settings.app_description,
        version=settings.app_version,
        lifespan=lifespan,
    )
    application.include_router(router)
    return application


# Entry point for the server: uvicorn ap_api.main:app
app = create_app()
