# 포트홀 서버

## 실행 (저장소 루트에서)
    docker compose up -d --build

- 대시보드: http://localhost:8000
- API 명세: http://localhost:8000/docs
- 샘플 데이터 (테스트 환경에서만): python tools/send_sample.py

인증과 HTTPS가 없습니다. 기본은 이 PC에서만 접속됩니다.
믿을 수 있는 내부망의 Pi를 받으려면 BIND_ADDR 환경변수에 PC의 내부망 IP를 지정하세요.

## API
- POST /api/events : 관측 1건 저장 (multipart: image, pothole_id, event_id, captured_at, detections, lat, lon)
- GET /api/events/{id}/image : 관측 이미지
- GET /api/potholes : 포트홀 목록
- GET /api/potholes/summary?since= : 요약
- GET /api/potholes/{pothole_id} : 포트홀 상세

## 계층
routers (HTTP) → services (검증) → repositories (SQLite)
