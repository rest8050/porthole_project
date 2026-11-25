"""점검 판정과 트랜잭션 검사 (모델 불필요): python fastapi-server/test_inspection.py"""
import io
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True

from PIL import Image

from app.repositories.event_repository import EventRepository
from app.repositories.inspection_repository import Finished, InspectionRepository
from app.services.inspection_service import InspectionService, pick_target

buffer = io.BytesIO()
Image.new("RGB", (100, 100)).save(buffer, "JPEG")
JPEG = buffer.getvalue()
NOW = datetime.now(timezone.utc)


class FakeDetect:
    confidence = 0.0

    def infer(self, content):
        if not self.confidence:
            return []
        return [{"confidence": self.confidence, "box": [20, 40, 60, 60]}]


folder = tempfile.TemporaryDirectory()
events = EventRepository(str(Path(folder.name) / "t.db"))
events.initialize()
repository = InspectionRepository(events)
repository.initialize()
fake = FakeDetect()
service = InspectionService(repository, fake)


def add(iid, pose, frame, confidence):
    fake.confidence = confidence
    return service.add_view(iid, f"{pose}-{frame}", f"p{pose}", 90, 100, 0,
                            NOW, None, None, None, None, JPEG)


def collect(iid, scores):
    for pose, score in enumerate(scores):
        for frame in range(3):
            add(iid, pose, frame, score)


def event_count():
    with events.connection() as conn:
        return conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]


# 확정: 상위 3개 평균, 크기는 YOLO 라벨 비율, events에는 포트홀 1개
collect("ok", [0.9, 0.8, 0.7, 0.2, 0.0])
result = service.finish("ok", aborted=False)
assert result["verdict"] == "confirmed", result
assert result["final_confidence"] == 0.8 and result["detection_score"] == 0.9, result
assert result["detection_rate"] == 0.8, result
assert abs(result["size"]["w"] - 0.4) < 1e-9 and abs(result["size"]["h"] - 0.2) < 1e-9
assert abs(result["size"]["area"] - 0.08) < 1e-9 and not result["size"]["truncated"]
assert event_count() == 3
total, items = events.find_potholes(None, None, 0, 10, 0)
assert total == 1 and items[0]["pothole_id"] == "ins-ok", items

# 재전송: finish는 최초 결과, events는 늘지 않음. 새 이미지는 거부, 기존 이미지는 중복
assert service.finish("ok", aborted=True) == result and event_count() == 3
assert add("ok", 0, 0, 0.1) == {"duplicate": True, "target": add("ok", 0, 0, 0.5)["target"]}
try:
    add("ok", 9, 0, 0.9)
    raise AssertionError("accepted a view after finish")
except Finished:
    pass

# 한 번 튄 값만 높으면 불합격
collect("spike", [0.95, 0.3, 0.3, 0.3, 0.3])
assert service.finish("spike", aborted=False)["verdict"] == "rejected"

# 자세 부족, 중단, 사진 수가 모자란 자세는 판정 보류
collect("few", [0.9] * 4)
add("few", 4, 0, 0.99)
result = service.finish("few", aborted=False)
assert result["verdict"] == "inconclusive" and result["pose_count"] == 4, result
collect("stop", [0.9] * 6)
assert service.finish("stop", aborted=True)["verdict"] == "inconclusive"

# 감지가 전혀 없으면 크기도 없음
collect("none", [0.0] * 5)
result = service.finish("none", aborted=False)
assert result["verdict"] == "rejected" and result["size"] is None, result
assert event_count() == 3 and service.finish("missing", False) is None

# events 저장이 중간에 실패하면 판정도 저장되지 않음
collect("atomic", [0.9] * 5)
with events.connection() as conn:
    conn.execute("CREATE TRIGGER boom BEFORE INSERT ON events "
                 "WHEN NEW.event_id = 'atomic:1-0' BEGIN SELECT RAISE(ABORT, 'boom'); END")
try:
    service.finish("atomic", aborted=False)
    raise AssertionError("expected failure")
except Exception as error:
    assert "boom" in str(error), error
assert service.get("atomic")["status"] == "open" and event_count() == 3
with events.connection() as conn:
    conn.execute("DROP TRIGGER boom")
assert service.finish("atomic", aborted=False)["verdict"] == "confirmed"
assert event_count() == 6

# 대상 선택: hint가 없으면 아래쪽, 있으면 가까운 것
two = [{"confidence": 0.9, "box": [0, 0, 10, 10]}, {"confidence": 0.6, "box": [70, 80, 90, 95]}]
assert pick_target(two, 100, 100)["confidence"] == 0.6
assert pick_target(two, 100, 100, (0.05, 0.05))["confidence"] == 0.9

folder.cleanup()
print("OK")
