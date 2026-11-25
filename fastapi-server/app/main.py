import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.repositories.event_repository import EventRepository
from app.routers.event_router import router as event_router, pothole_router
from app.services.event_service import EventService

INDEX_FILE = Path(__file__).resolve().parent / "index.html"


def create_app(db_path: str | None = None) -> FastAPI:
    repository = EventRepository(
        db_path or os.getenv("DB_PATH", "./data/server.db")
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        repository.initialize()
        app.state.event_service = EventService(repository)
        yield

    application = FastAPI(
        title="Pothole Server",
        version="2.0.0",
        lifespan=lifespan,
    )

    application.include_router(event_router)
    application.include_router(pothole_router)

    @application.get("/", response_class=FileResponse, include_in_schema=False)
    def home():
        return FileResponse(
            INDEX_FILE,
            media_type="text/html",
            headers={"Cache-Control": "no-cache"},
        )

    return application


app = create_app()
