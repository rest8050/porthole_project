# 포트홀 서버 API 명세서

대상: `fastapi-server` (버전 2.0.0). `lead2` 서버는 포함하지 않습니다.

## 1. 공통

| 항목 | 내용 |
|---|---|
| 기본 주소 | `http://<서버 IP>:8000` (`BIND_ADDR`를 지정하지 않으면 `127.0.0.1`) |
| 인증 / HTTPS | **없음.** 믿을 수 있는 내부망에서만 사용 |
| 응답 형식 | JSON (이미지 조회와 `/`는 제외) |
| 시각 | ISO 8601. 요청에는 **시간대 필수** (예: `2026-11-25T12:00:00+09:00`) |
| 이미지 | JPEG만, 10 MiB 이하, 2천만 픽셀 이하 |
| 자동 문서 | `/docs`, `/openapi.json` (응답 필드의 상세 형식은 이 문서 참고) |

쿼리 문자열의 시간대에 `+`를 쓸 때는 `%2B`로 인코딩하거나 `Z`(UTC)를 사용합니다.

| 방식 | 경로 | 용도 | 예시 |
|---|---|---|---|
| POST | `/api/detect` | YOLO 추론, 포트홀이면 저장 | `curl -F image=@frame.jpg -F event_id=test-detect-1 -F captured_at=2026-11-25T12:00:00+09:00 http://172.16.46.41:8000/api/detect` |
| POST | `/api/events` | 추론이 끝난 관측 1건 저장 | `curl -F image=@frame.jpg -F pothole_id=test-pothole-1 -F event_id=test-event-1 -F captured_at=2026-11-25T12:00:00+09:00 --form-string 'detections=[{"confidence":0.9,"box":[1,1,50,50]}]' http://172.16.46.41:8000/api/events` |
| GET | `/api/events/{key}/image` | 관측 이미지 | `curl -o event.jpg http://172.16.46.41:8000/api/events/1/image` |
| GET | `/api/potholes` | 포트홀 목록 | `curl "http://172.16.46.41:8000/api/potholes?limit=5&min_confidence=0.5"` |
| GET | `/api/potholes/summary` | 요약 (주행 정지 신호) | `curl "http://172.16.46.41:8000/api/potholes/summary?since=2000-01-01T00:00:00Z"` |
| GET | `/api/potholes/{pothole_id}` | 포트홀 상세 | `curl http://172.16.46.41:8000/api/potholes/sample-9143102f-f70f-4b17-8b3b-7beb444157d9` |
| GET | `/` | 대시보드 (HTML) | `curl http://172.16.46.41:8000/` |

예시 사용법:

- **라즈베리파이 / Linux / Git Bash용**입니다. Windows PowerShell에서는 POST 예시의 따옴표와 `curl` 별칭 때문에 그대로 동작하지 않을 수 있습니다.
- `172.16.46.41`은 작성 당시의 서버 주소입니다. 서버 IP가 바뀌면 이 부분을 바꿉니다.
- POST 예시는 현재 폴더에 `frame.jpg`(JPEG, 가로·세로 50픽셀 이상)가 있어야 합니다.
- **POST 예시는 실제 데이터를 저장하며, 새로 저장되면 주행 중인 차가 멈춥니다.** (`/api/detect`는 포트홀을 감지했을 때만) 같은 `event_id`로 다시 실행하면 새로 저장하지 않으므로, 새 관측은 `event_id`를 바꿉니다.
- 이미지의 `1`과 상세의 `pothole_id`는 작성 당시 저장돼 있던 값입니다. 없으면 404이며, 목록 조회 결과의 `best_event`, `pothole_id`로 바꿉니다.

## 2. POST /api/detect

서버가 이미지를 추론합니다. `pothole` 클래스가 기준값(`DETECT_CONF`, 기본 0.5) 이상이면 저장하고, 결과는 **같은 요청의 응답**으로 돌려줍니다.

요청: `multipart/form-data`

| 필드 | 형식 | 필수 | 설명 |
|---|---|---|---|
| `image` | 파일 | O | JPEG |
| `event_id` | 문자열 1~200자 | O | 촬영 1건의 고유 ID (UUID 권장). 재전송할 때는 같은 값 사용 |
| `captured_at` | 시각 | O | 촬영 시각 (시간대 포함) |
| `lat` | 실수 -90~90 | X | `lon`과 함께 보내야 함 |
| `lon` | 실수 -180~180 | X | `lat`과 함께 보내야 함 |

예시 (Linux / 라즈베리파이):

```bash
curl -X POST http://<서버 IP>:8000/api/detect \
  -F image=@frame.jpg \
  -F event_id=7b1f0c52-3c1e-4f55-9a0e-2f6f1d9b8a10 \
  -F captured_at=2026-11-25T12:00:00+09:00
```

응답 200 (포트홀 감지, 저장됨):

```json
{
  "pothole": true,
  "detections": [{"confidence": 0.64, "box": [187.3, 178.7, 331.3, 266.3]}],
  "id": 7,
  "duplicate": false
}
```

응답 200 (감지 없음, 저장 안 함):

```json
{"pothole": false, "detections": [], "id": null, "duplicate": false}
```

| 필드 | 설명 |
|---|---|
| `pothole` | 이번 추론에서 포트홀을 감지했는지 |
| `detections` | 감지 목록 (점수 높은 순, 최대 100개). `box`는 `[x1, y1, x2, y2]`, 보낸 이미지의 픽셀 좌표 |
| `id` | 저장된 관측 번호. `/api/events/{id}/image`에 사용 |
| `duplicate` | 같은 `event_id`가 이미 저장돼 있었는지. `true`면 최초 저장값을 유지 |

- 저장할 때마다 `pothole_id`가 `det-...`인 **새 포트홀**이 됩니다. 같은 포트홀을 여러 번 찍으면 여러 개로 셉니다.
- `event_id`의 중복 검사는 `/api/events`와 공유합니다.
- `duplicate`가 `true`여도 `detections`는 이번에 보낸 이미지의 추론 결과입니다.
- 추론은 한 번에 1장씩 처리합니다.

## 3. POST /api/events

이미 추론한 결과를 저장합니다.

요청: `multipart/form-data`. `image`, `event_id`, `captured_at`, `lat`, `lon`은 `/api/detect`와 같고, 아래 필드가 추가로 **필수**입니다.

| 필드 | 형식 | 설명 |
|---|---|---|
| `pothole_id` | 영문, 숫자, `_`, `-`로 1~100자 | 같은 포트홀의 관측은 같은 값 |
| `detections` | JSON 문자열, 20,000자 이하 | 1~100개. `[{"confidence": 0.9, "box": [x1, y1, x2, y2]}]` |

`confidence`는 0~1이고, `box`는 이미지 범위 안에서 `x1 < x2`, `y1 < y2`여야 합니다. 정해진 두 키 외의 값은 거부합니다.

응답 200:

```json
{"id": 8, "duplicate": false}
```

같은 `event_id`를 다시 보내면 새로 저장하지 않고 기존 `id`와 `"duplicate": true`를 반환합니다.

## 4. GET /api/events/{key}/image

`key`는 관측 번호(정수)입니다. 응답은 `image/jpeg`이며, 없으면 404입니다.

## 5. GET /api/potholes

최근 관측순으로 포트홀 목록을 반환합니다.

| 쿼리 | 기본값 | 설명 |
|---|---|---|
| `start`, `end` | 없음 | 이 기간(촬영 시각, 양끝 포함)에 관측이 있는 포트홀 |
| `min_confidence` | 0 | 최고 신뢰도가 이 값 이상 (0~1) |
| `limit` | 24 | 1~100 |
| `offset` | 0 | 0 이상 |

집계 값은 기간과 관계없이 해당 포트홀의 전체 관측으로 계산합니다.

```json
{
  "total": 6,
  "items": [{
    "pothole_id": "sample-9143102f-...",
    "observation_count": 2,
    "max_confidence": 0.796,
    "avg_confidence": 0.7135,
    "first_seen": "2026-11-25T10:47:44.569111Z",
    "last_seen": "2026-11-25T10:47:44.869111Z",
    "best_event": 1,
    "lat": 37.568257,
    "lon": 126.972253
  }]
}
```

- `total`: 조건에 맞는 전체 포트홀 수
- `avg_confidence`: 관측별 최고 신뢰도의 평균
- `best_event`: 신뢰도가 가장 높은 관측 번호
- `lat`, `lon`: 위치가 있는 관측 중 신뢰도가 가장 높은 것의 위치. 없으면 `null`

## 6. GET /api/potholes/summary

| 쿼리 | 필수 | 설명 |
|---|---|---|
| `since` | O | 시각 (시간대 포함) |

```json
{"total": 6, "new_count": 6, "last_received_at": "2026-11-25T10:49:07.350Z"}
```

| 필드 | 설명 |
|---|---|
| `total` | 전체 포트홀 수 (관측 수가 아님) |
| `new_count` | 첫 촬영 시각이 `since` 이후인 포트홀 수 |
| `last_received_at` | 서버가 마지막으로 관측을 저장한 시각. 데이터가 없으면 `null`. `since`의 영향 없음 |

## 7. GET /api/potholes/{pothole_id}

목록의 항목 필드에 `observations`(촬영 시각순, 전체)가 추가됩니다. 없으면 404입니다.

`observations` 항목: `id`, `pothole_id`, `event_id`, `captured_at`, `lat`, `lon`, `detections`, `max_confidence`, `width`, `height`, `created_at`(서버 저장 시각)

## 8. 오류

| 코드 | 상황 |
|---|---|
| 400 | JPEG가 아니거나 손상됨, 픽셀 수 초과, `lat`/`lon` 중 하나만 보냄, 잘못된 `detections` 또는 `box` |
| 404 | 이미지 또는 포트홀 없음 |
| 413 | 이미지가 10 MiB 초과 |
| 422 | 필수 항목 누락, 형식이나 범위 오류 |
| 503 | `/api/detect`만 해당. 서버에 `MODEL_PATH`가 설정되지 않음 |

400, 404, 413, 503은 `{"detail": "설명"}` 형식입니다. 422의 `detail`은 배열입니다.

```json
{"detail": [{"type": "missing", "loc": ["query", "since"], "msg": "Field required", "input": null}]}
```

`MODEL_PATH`를 지정했는데 모델을 불러오지 못하면 서버가 시작되지 않습니다.

## 9. 차량 연동

| 프로그램 (라즈베리파이) | 사용하는 API | 동작 |
|---|---|---|
| `car/camera_send.py` | `POST /api/detect` | 촬영해 전송. 감지하면 5초 쉼. 응답 대기 10초 |
| `car/drive.py` | `GET /api/potholes/summary` | 0.2초 간격으로 조회. `last_received_at`이 바뀌면 정지. 통신 오류에도 정지 |

터미널 2개에서 실행합니다. 카메라 전송을 먼저 켜고 결과가 정상으로 나오는지 확인한 뒤 주행을 시작합니다.

```bash
python3 camera_send.py --server http://<서버 IP>:8000
```

```bash
python3 drive.py --server http://<서버 IP>:8000
```

주의:

- `/api/events`나 `/api/detect`로 **어느 기기가 저장해도** 차가 멈춥니다.
- 카메라 전송이 실패해도 `drive.py`는 알 수 없어 계속 직진합니다. `send failed`가 나오는지 지켜보세요.

## 10. 서버 실행

저장소 루트에서 실행합니다 (PowerShell). 모델 파일은 `runs/detect/runs/train/trial_gpu/weights/best.pt`이며 `compose.yaml`에서 연결합니다.

```powershell
$env:BIND_ADDR = "<서버 IP>"
```

```powershell
docker compose -p yolodemo up -d --build api
```

기준값을 바꾸려면 실행 전에 `$env:DETECT_CONF = "0.4"`처럼 지정합니다.
