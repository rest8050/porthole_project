"""포트홀 1개 점검의 수집과 최종 판정. 점수는 모두 서버에서 계산합니다."""
from statistics import mean, median

from app.services.event_service import jpeg_size, utc_text

# 실차 데이터로 조정할 값
MIN_FRAMES = 3      # 자세 1개로 인정하는 최소 사진 수
MIN_POSES = 5       # 판정에 필요한 최소 자세 수
GOOD_SCORE = 0.6    # 확정 기준 점수
GOOD_POSES = 2      # 기준을 넘어야 하는 자세 수
TOP_POSES = 3       # 최종 신뢰도와 크기에 쓰는 상위 자세 수
EDGE = 0.01         # box가 화면 끝에 닿으면 잘린 것으로 봄


def to_label(box, width, height):
    """픽셀 [x1, y1, x2, y2] -> YOLO 라벨 형식 (이미지 크기 대비 0~1)."""
    x1, y1, x2, y2 = box
    return {
        "cx": (x1 + x2) / 2 / width, "cy": (y1 + y2) / 2 / height,
        "w": (x2 - x1) / width, "h": (y2 - y1) / height,
    }


def pick_target(detections, width, height, hint=None):
    """추적 대상 1개. hint(예상 중심)가 있으면 가장 가까운 것, 없으면 가장 아래(가까운) 것."""
    candidates = [
        dict(item, label=to_label(item["box"], width, height)) for item in detections
    ]
    if not candidates:
        return None
    if hint is None:
        return max(candidates, key=lambda c: c["box"][3])
    # ponytail: 위치만 비교. 대상이 사라지면 다른 포트홀을 고를 수 있음. 문제되면 거리 제한 추가.
    return min(
        candidates,
        key=lambda c: (c["label"]["cx"] - hint[0]) ** 2 + (c["label"]["cy"] - hint[1]) ** 2,
    )


def is_cut(label):
    return (
        label["cx"] - label["w"] / 2 <= EDGE or label["cx"] + label["w"] / 2 >= 1 - EDGE
        or label["cy"] - label["h"] / 2 <= EDGE or label["cy"] + label["h"] / 2 >= 1 - EDGE
    )


def evaluate(inspection_id, views, aborted):
    """(결과, 대표 view_id 목록)."""
    poses = {}
    for view in views:
        poses.setdefault(view["pose_id"], []).append(view)

    scored = []  # (자세 점수, 감지된 view 목록)
    for frames in poses.values():
        if len(frames) >= MIN_FRAMES:
            score = median(f["target"]["confidence"] if f["target"] else 0 for f in frames)
            scored.append((score, [f for f in frames if f["target"]]))
    scored.sort(key=lambda item: item[0], reverse=True)
    top = [item for item in scored[:TOP_POSES] if item[0] > 0]

    # 최고값 하나는 시도가 많을수록 우연히 높아지므로 상위 자세의 평균을 씁니다.
    best_score = scored[0][0] if scored else 0
    final = mean(s for s, _ in scored[:TOP_POSES]) if scored else 0

    if aborted or len(scored) < MIN_POSES:
        verdict = "inconclusive"
    elif final >= GOOD_SCORE and sum(s >= GOOD_SCORE for s, _ in scored) >= GOOD_POSES:
        verdict = "confirmed"
    else:
        verdict = "rejected"

    # 크기: 상위 자세에서 잘리지 않은 box의 중앙값 (모두 잘렸으면 전부 사용)
    found = [f["target"]["label"] for _, frames in top for f in frames]
    whole = [label for label in found if not is_cut(label)]
    size = None
    if found:
        used = whole or found
        w, h = median(l["w"] for l in used), median(l["h"] for l in used)
        size = {"w": w, "h": h, "area": w * h, "truncated": not whole}

    representatives = [
        max(frames, key=lambda f: f["target"]["confidence"]) for _, frames in top
    ]
    best = representatives[0] if representatives else None

    result = {
        "inspection_id": inspection_id,
        "verdict": verdict,
        "final_confidence": round(final, 4),
        "detection_score": round(best_score, 4),
        "detection_rate": round(sum(bool(v["target"]) for v in views) / len(views), 4)
        if views else 0,
        "size": size,
        "best_view": best and {
            "view_id": best["view_id"], "pan": best["pan"], "tilt": best["tilt"],
            "move": best["move"], "label": best["target"]["label"],
        },
        "pose_count": len(scored),
        "view_count": len(views),
        "pothole_id": f"ins-{inspection_id}" if verdict == "confirmed" else None,
    }
    chosen = [f["view_id"] for f in representatives] if verdict == "confirmed" else []
    return result, chosen


class InspectionService:
    def __init__(self, repository, detect_service):
        self.repository = repository
        self.detect_service = detect_service

    def add_view(self, inspection_id, view_id, pose_id, pan, tilt, move,
                 captured_at, lat, lon, hint_x, hint_y, content):
        """입력 오류는 ValueError, 종료된 점검은 repository.Finished."""
        if (lat is None) != (lon is None):
            raise ValueError("lat과 lon은 함께 보내야 합니다.")
        if (hint_x is None) != (hint_y is None):
            raise ValueError("hint_x와 hint_y는 함께 보내야 합니다.")

        stored = self.repository.find_view(inspection_id, view_id)
        if stored:  # 재전송: 다시 추론하지 않고 최초 결과 반환
            return {"target": stored["target"], "duplicate": True}

        width, height = jpeg_size(content)
        target = pick_target(
            self.detect_service.infer(content), width, height,
            None if hint_x is None else (hint_x, hint_y),
        )
        created, target = self.repository.add_view({
            "inspection_id": inspection_id, "view_id": view_id, "pose_id": pose_id,
            "pan": pan, "tilt": tilt, "move": move,
            "captured_at": utc_text(captured_at), "lat": lat, "lon": lon,
            "width": width, "height": height, "target": target, "content": content,
        })
        return {"target": target, "duplicate": not created}

    def finish(self, inspection_id, aborted):
        return self.repository.finish(
            inspection_id, lambda views: evaluate(inspection_id, views, aborted)
        )

    def get(self, inspection_id):
        return self.repository.get(inspection_id)
