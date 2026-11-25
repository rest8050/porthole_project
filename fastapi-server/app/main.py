import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.repositories.event_repository import EventRepository
from app.routers.detect_router import router as detect_router
from app.routers.event_router import router as event_router, pothole_router
from app.services.detect_service import DetectService, YoloDetector
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
        # MODEL_PATH가 없으면 /api/detect만 503이고 나머지 API는 동작합니다.
        model_path = os.getenv("MODEL_PATH")
        app.state.detect_service = DetectService(
            YoloDetector(model_path, float(os.getenv("DETECT_CONF", "0.5"))),
            app.state.event_service,
        ) if model_path else None
        yield

    application = FastAPI(
        title="Pothole Server",
        version="2.0.0",
        lifespan=lifespan,
    )

    application.include_router(detect_router)
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
