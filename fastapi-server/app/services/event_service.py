import io
import json
import warnings
from datetime import datetime, timezone

from PIL import Image
from pydantic import TypeAdapter

from app.schemas import Detection

DETECTIONS = TypeAdapter(list[Detection])
MAX_IMAGE = 10 * 1024 * 1024
MAX_PIXELS = 20_000_000


def utc_text(value: datetime) -> str:
    # 자릿수가 고정돼 문자열 비교가 시간 순서와 같습니다.
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def jpeg_size(content: bytes) -> tuple[int, int]:
    """JPEG인지, 끝까지 해석되는지 검사하고 (너비, 높이)를 반환합니다."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content), formats=["JPEG"]) as image:
                if image.width * image.height > MAX_PIXELS:
                    raise ValueError("이미지는 2천만 픽셀 이하여야 합니다.")
                image.load()
                return image.size
    except (
        OSError,
        SyntaxError,
        # ultralytics가 Image.open을 바꿔, 읽지 못하면 pi_heif를 불러오려 합니다.
        ImportError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise ValueError("유효하지 않거나 너무 큰 JPEG 이미지입니다.") from exc


class EventService:
    def __init__(self, repository):
        self.repository = repository

    def save(self, pothole_id, event_id, captured_at, detections_json, lat, lon, content):
        """입력 오류는 ValueError (pydantic ValidationError 포함)."""
        if (lat is None) != (lon is None):
            raise ValueError("lat과 lon은 함께 보내야 합니다.")

        detections = DETECTIONS.validate_json(detections_json)
        if not 1 <= len(detections) <= 100:
            raise ValueError("detections는 1~100개여야 합니다.")

        width, height = jpeg_size(content)

        for item in detections:
            x1, y1, x2, y2 = item.box
            if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
                raise ValueError("box가 이미지 범위를 벗어났거나 잘못됐습니다.")

        created, key = self.repository.save({
            "pothole_id": pothole_id,
            "event_id": event_id,
            "captured_at": utc_text(captured_at),
            "lat": lat,
            "lon": lon,
            "detections": json.dumps(
                [item.model_dump() for item in detections]
            ),
            "max_confidence": max(item.confidence for item in detections),
            "width": width,
            "height": height,
            "content": content,
        })
        return {"id": key, "duplicate": not created}

    def find_potholes(self, start, end, min_confidence, limit, offset):
        total, items = self.repository.find_potholes(
            start and utc_text(start),
            end and utc_text(end),
            min_confidence,
            limit,
            offset,
        )
        return {"total": total, "items": items}

    def summary(self, since):
        return self.repository.summary(utc_text(since))

    def get_pothole(self, pothole_id):
        return self.repository.get_pothole(pothole_id)

    def get_image(self, key):
        return self.repository.get_image(key)
