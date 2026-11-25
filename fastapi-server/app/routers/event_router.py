from typing import Annotated

from fastapi import (
    APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile,
)
from fastapi.responses import Response
from pydantic import AwareDatetime

from app.services.event_service import MAX_IMAGE, EventService

router = APIRouter(prefix="/api/events", tags=["events"])
pothole_router = APIRouter(prefix="/api/potholes", tags=["potholes"])

# URL 경로에 쓰므로 문자를 제한합니다.
POTHOLE_ID = r"^[A-Za-z0-9_-]{1,100}$"


def get_service(request: Request) -> EventService:
    return request.app.state.event_service


Service = Annotated[EventService, Depends(get_service)]


def found(value):
    if value is None:
        raise HTTPException(404, "데이터가 없습니다.")
    return value


@router.post("", summary="포트홀 관측 1건 저장 (이미지 + 정보)")
def create(
    service: Service,
    image: Annotated[UploadFile, File()],
    pothole_id: Annotated[str, Form(pattern=POTHOLE_ID)],
    event_id: Annotated[str, Form(min_length=1, max_length=200)],
    captured_at: Annotated[AwareDatetime, Form()],
    detections: Annotated[str, Form(
        max_length=20_000,
        description='[{"confidence": 0.9, "box": [x1, y1, x2, y2]}]',
    )],
    lat: Annotated[float | None, Form(ge=-90, le=90)] = None,
    lon: Annotated[float | None, Form(ge=-180, le=180)] = None,
):
    content = image.file.read(MAX_IMAGE + 1)
    if len(content) > MAX_IMAGE:
        raise HTTPException(413, "이미지는 10MB 이하여야 합니다.")
    try:
        return service.save(
            pothole_id, event_id, captured_at, detections,
            lat, lon, content
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/{key}/image", summary="관측 이미지")
def image(key: int, service: Service):
    return Response(
        content=found(service.get_image(key)),
        media_type="image/jpeg",
        headers={"X-Content-Type-Options": "nosniff"},
    )


@pothole_router.get("", summary="포트홀 목록 (최근 관측순)")
def list_potholes(
    service: Service,
    start: AwareDatetime | None = None,
    end: AwareDatetime | None = None,
    min_confidence: float = Query(default=0, ge=0, le=1),
    limit: int = Query(default=24, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return service.find_potholes(start, end, min_confidence, limit, offset)


@pothole_router.get("/summary", summary="전체 수, since 이후 새 포트홀 수, 마지막 수신")
def summary(service: Service, since: AwareDatetime):
    return service.summary(since)


@pothole_router.get("/{pothole_id}", summary="포트홀 상세와 전체 관측")
def pothole_detail(pothole_id: str, service: Service):
    return found(service.get_pothole(pothole_id))
