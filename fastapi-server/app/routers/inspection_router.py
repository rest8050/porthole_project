from typing import Annotated

from fastapi import (
    APIRouter, Depends, File, Form, HTTPException, Path, Request, UploadFile,
)
from pydantic import AwareDatetime, BaseModel, ConfigDict

from app.repositories.inspection_repository import Finished
from app.services.event_service import MAX_IMAGE
from app.services.inspection_service import InspectionService

router = APIRouter(prefix="/api/inspections", tags=["inspections"])

ID = r"^[A-Za-z0-9_-]{1,64}$"
InspectionId = Annotated[str, Path(pattern=ID)]


def get_service(request: Request) -> InspectionService:
    return request.app.state.inspection_service


Service = Annotated[InspectionService, Depends(get_service)]


class FinishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    aborted: bool = False


def found(value):
    if value is None:
        raise HTTPException(404, "점검이 없습니다.")
    return value


@router.post("/{inspection_id}/views", summary="점검 이미지 1장 추론·저장")
def add_view(
    inspection_id: InspectionId,
    service: Service,
    image: Annotated[UploadFile, File()],
    view_id: Annotated[str, Form(pattern=ID)],
    pose_id: Annotated[str, Form(pattern=ID)],
    pan: Annotated[int, Form(ge=0, le=180)],
    tilt: Annotated[int, Form(ge=0, le=180)],
    captured_at: Annotated[AwareDatetime, Form()],
    move: Annotated[int, Form(ge=-100, le=100)] = 0,
    hint_x: Annotated[float | None, Form(ge=-1, le=2)] = None,
    hint_y: Annotated[float | None, Form(ge=-1, le=2)] = None,
    lat: Annotated[float | None, Form(ge=-90, le=90)] = None,
    lon: Annotated[float | None, Form(ge=-180, le=180)] = None,
):
    if service.detect_service is None:
        raise HTTPException(503, "모델이 설정되지 않았습니다. (MODEL_PATH)")
    content = image.file.read(MAX_IMAGE + 1)
    if len(content) > MAX_IMAGE:
        raise HTTPException(413, "이미지는 10MB 이하여야 합니다.")
    try:
        return service.add_view(
            inspection_id, view_id, pose_id, pan, tilt, move,
            captured_at, lat, lon, hint_x, hint_y, content,
        )
    except Finished as exc:
        raise HTTPException(409, "이미 종료된 점검입니다.") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/{inspection_id}/finish", summary="최종 계산과 확정 (한 트랜잭션)")
def finish(inspection_id: InspectionId, service: Service, body: FinishRequest):
    return found(service.finish(inspection_id, body.aborted))


@router.get("/{inspection_id}", summary="점검 상태와 결과")
def get_inspection(inspection_id: InspectionId, service: Service):
    return found(service.get(inspection_id))
