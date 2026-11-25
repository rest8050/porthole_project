from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import AwareDatetime

from app.services.event_service import MAX_IMAGE

router = APIRouter(prefix="/api/detect", tags=["detect"])


@router.post("", summary="이미지 YOLO 추론 (포트홀이면 저장하고 결과 반환)")
def detect(
    request: Request,
    image: Annotated[UploadFile, File()],
    event_id: Annotated[str, Form(min_length=1, max_length=200)],
    captured_at: Annotated[AwareDatetime, Form()],
    lat: Annotated[float | None, Form(ge=-90, le=90)] = None,
    lon: Annotated[float | None, Form(ge=-180, le=180)] = None,
    save: Annotated[bool, Form(description="false면 추론만 하고 저장 안 함")] = True,
):
    service = request.app.state.detect_service
    if service is None:
        raise HTTPException(503, "모델이 설정되지 않았습니다. (MODEL_PATH)")
    content = image.file.read(MAX_IMAGE + 1)
    if len(content) > MAX_IMAGE:
        raise HTTPException(413, "이미지는 10MB 이하여야 합니다.")
    try:
        return service.detect(event_id, captured_at, lat, lon, content, save)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
