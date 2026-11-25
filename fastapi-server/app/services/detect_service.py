import io
import json
import threading
import uuid

from PIL import Image

from app.services.event_service import jpeg_size

TARGET_CLASS = "pothole"


class YoloDetector:
    def __init__(self, model_path: str, conf: float):
        # 무거운 패키지는 모델을 쓸 때만 불러옵니다.
        import numpy
        from ultralytics import YOLO

        self.numpy = numpy
        self.model = YOLO(model_path)
        if TARGET_CLASS not in self.model.names.values():
            raise ValueError(f"모델에 '{TARGET_CLASS}' 클래스가 없습니다.")
        self.conf = conf

    def __call__(self, content: bytes) -> list[dict]:
        with Image.open(io.BytesIO(content)) as image:
            # 배열로 넘겨야 EXIF 회전 없이 저장 이미지와 box 좌표가 일치합니다.
            bgr = self.numpy.asarray(image.convert("RGB"))[..., ::-1].copy()
        result = self.model.predict(bgr, conf=self.conf, verbose=False)[0]
        height, width = bgr.shape[:2]
        found = []
        for cls, conf, (x1, y1, x2, y2) in zip(
            result.boxes.cls.tolist(),
            result.boxes.conf.tolist(),
            result.boxes.xyxy.tolist(),
        ):
            box = [max(x1, 0), max(y1, 0), min(x2, width), min(y2, height)]
            if result.names[int(cls)] == TARGET_CLASS and box[0] < box[2] and box[1] < box[3]:
                found.append({"confidence": min(conf, 1.0), "box": box})
        return found[:100]  # YOLO 결과는 점수 높은 순


class DetectService:
    def __init__(self, detector, events):
        self.detector = detector
        self.events = events
        # ponytail: 한 번에 1장씩 추론. 카메라가 여러 대가 되면 작업 큐로 변경.
        self.lock = threading.Lock()

    def infer(self, content: bytes) -> list[dict]:
        """검증된 JPEG만 넘기세요."""
        with self.lock:
            return self.detector(content)

    def detect(self, event_id, captured_at, lat, lon, content, save=True):
        """입력 오류는 ValueError. save이고 포트홀일 때만 저장합니다."""
        if (lat is None) != (lon is None):
            raise ValueError("lat과 lon은 함께 보내야 합니다.")
        jpeg_size(content)

        detections = self.infer(content)

        if not detections or not save:
            return {
                "pothole": bool(detections), "detections": detections,
                "id": None, "duplicate": False,
            }

        # ponytail: 저장할 때마다 새 포트홀. 같은 포트홀을 묶으려면 위치/추적 기준 필요.
        # event_id에서 만들므로 재전송해도 같은 값입니다.
        pothole_id = f"det-{uuid.uuid5(uuid.NAMESPACE_URL, event_id).hex}"
        saved = self.events.save(
            pothole_id, event_id, captured_at, json.dumps(detections),
            lat, lon, content,
        )
        return {"pothole": True, "detections": detections, **saved}
