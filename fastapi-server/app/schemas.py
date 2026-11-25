from pydantic import BaseModel, ConfigDict, Field


class Detection(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    confidence: float = Field(ge=0, le=1)
    box: tuple[float, float, float, float]  # x1, y1, x2, y2 (전송 이미지 픽셀)
