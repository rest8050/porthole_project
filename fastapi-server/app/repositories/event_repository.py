import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

# content(BLOB)를 뺀 조회용 컬럼
COLUMNS = (
    "id, pothole_id, event_id, captured_at, lat, lon, detections, "
    "max_confidence, width, height, created_at"
)


class EventRepository:
    def __init__(self, db_path: str):
        self.db_path = db_path

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def initialize(self):
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pothole_id TEXT NOT NULL,
                    event_id TEXT NOT NULL UNIQUE,
                    captured_at TEXT NOT NULL,
                    lat REAL,
                    lon REAL,
                    detections TEXT NOT NULL,
                    max_confidence REAL NOT NULL,
                    width INTEGER NOT NULL,
                    height INTEGER NOT NULL,
                    content BLOB NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (
                        strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                    )
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS events_captured "
                "ON events(captured_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS events_pothole "
                "ON events(pothole_id)"
            )

    @staticmethod
    def to_dict(row):
        data = dict(row)
        data["detections"] = json.loads(data["detections"])
        return data

    def save(self, event: dict):
        """(신규 여부, id)를 반환합니다. 같은 event_id면 최초 값을 유지합니다."""
        keys = ", ".join(event)
        marks = ", ".join("?" * len(event))
        with self.connection() as conn:
            cursor = conn.execute(
                f"INSERT INTO events({keys}) VALUES ({marks}) "
                "ON CONFLICT(event_id) DO NOTHING",
                tuple(event.values()),
            )
            row = conn.execute(
                "SELECT id FROM events WHERE event_id = ?",
                (event["event_id"],),
            ).fetchone()
            return cursor.rowcount == 1, row["id"]

    # 포트홀은 별도 테이블 없이 관측(events)을 pothole_id로 묶어 계산합니다.
    # ponytail: 상태(수리 완료 등)처럼 포트홀 자체의 값이 생기면 potholes 테이블 추가.
    AGGREGATE = (
        "SELECT pothole_id, COUNT(*) AS observation_count, "
        "MAX(max_confidence) AS max_confidence, "
        "AVG(max_confidence) AS avg_confidence, "
        "MIN(captured_at) AS first_seen, MAX(captured_at) AS last_seen "
        "FROM events "
    )

    @staticmethod
    def add_representative(conn, pothole):
        """대표 이미지는 최고 점수 관측, 위치는 GPS가 있는 것 중 최고 점수 관측."""
        key = (pothole["pothole_id"],)
        order = " ORDER BY max_confidence DESC, id LIMIT 1"
        pothole["best_event"] = conn.execute(
            "SELECT id FROM events WHERE pothole_id = ?" + order, key
        ).fetchone()["id"]
        gps = conn.execute(
            "SELECT lat, lon FROM events "
            "WHERE pothole_id = ? AND lat IS NOT NULL" + order, key
        ).fetchone()
        pothole["lat"], pothole["lon"] = tuple(gps) if gps else (None, None)
        return pothole

    def find_potholes(self, start, end, min_confidence, limit, offset):
        """기간 조건: 기간 안에 관측이 있는 포트홀. 집계는 전체 관측 기준."""
        in_range = ["1"]
        params = [min_confidence]
        if start:
            in_range.append("captured_at >= ?")
            params.append(start)
        if end:
            in_range.append("captured_at <= ?")
            params.append(end)
        grouped = (
            self.AGGREGATE + "GROUP BY pothole_id "
            "HAVING MAX(max_confidence) >= ? "
            f"AND SUM({' AND '.join(in_range)}) > 0"
        )

        with self.connection() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM ({grouped})", params
            ).fetchone()[0]
            rows = conn.execute(
                f"{grouped} ORDER BY last_seen DESC, pothole_id "
                "LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
            # ponytail: 페이지당 최대 100개라 포트홀별 추가 조회. 느려지면 쿼리 합치기.
            items = [self.add_representative(conn, dict(row)) for row in rows]
        return total, items

    def get_pothole(self, pothole_id):
        with self.connection() as conn:
            row = conn.execute(
                self.AGGREGATE + "WHERE pothole_id = ? GROUP BY pothole_id",
                (pothole_id,),
            ).fetchone()
            if row is None:
                return None
            pothole = self.add_representative(conn, dict(row))
            # ponytail: 관측을 전부 반환. 포트홀당 수백 건이 되면 페이지 나누기.
            rows = conn.execute(
                f"SELECT {COLUMNS} FROM events WHERE pothole_id = ? "
                "ORDER BY captured_at, id",
                (pothole_id,),
            ).fetchall()
        pothole["observations"] = [self.to_dict(item) for item in rows]
        return pothole

    def summary(self, since):
        with self.connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS total, "
                "COUNT(CASE WHEN first_seen >= ? THEN 1 END) AS new_count, "
                "MAX(received) AS last_received_at FROM ("
                "SELECT MIN(captured_at) AS first_seen, "
                "MAX(created_at) AS received FROM events GROUP BY pothole_id)",
                (since,),
            ).fetchone()
        return dict(row)

    def get_image(self, key: int):
        with self.connection() as conn:
            row = conn.execute(
                "SELECT content FROM events WHERE id = ?", (key,)
            ).fetchone()
        return None if row is None else row["content"]
