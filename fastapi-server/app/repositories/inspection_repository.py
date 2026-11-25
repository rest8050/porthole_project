import json

NOW = "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"


class Finished(Exception):
    """종료된 점검에 새 이미지를 추가하려 함."""


class InspectionRepository:
    """events와 같은 DB를 씁니다. 확정과 events 저장이 한 트랜잭션이어야 하기 때문입니다."""

    def __init__(self, events):
        self.events = events

    def initialize(self):
        with self.events.connection() as conn:
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS inspections (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL DEFAULT 'open',
                    result TEXT,
                    created_at TEXT NOT NULL DEFAULT ({NOW}),
                    finished_at TEXT
                )
            """)
            # ponytail: 불합격/미완료 이미지도 학습용으로 남깁니다. DB가 커지면 정리 기능 추가.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS views (
                    inspection_id TEXT NOT NULL REFERENCES inspections(id),
                    view_id TEXT NOT NULL,
                    pose_id TEXT NOT NULL,
                    pan INTEGER NOT NULL,
                    tilt INTEGER NOT NULL,
                    move INTEGER NOT NULL,
                    captured_at TEXT NOT NULL,
                    lat REAL,
                    lon REAL,
                    width INTEGER NOT NULL,
                    height INTEGER NOT NULL,
                    target TEXT,
                    content BLOB NOT NULL,
                    PRIMARY KEY (inspection_id, view_id)
                )
            """)

    @staticmethod
    def _status(conn, inspection_id):
        row = conn.execute(
            "SELECT status, result FROM inspections WHERE id = ?", (inspection_id,)
        ).fetchone()
        return row and dict(row)

    @staticmethod
    def _view(conn, inspection_id, view_id):
        row = conn.execute(
            "SELECT target FROM views WHERE inspection_id = ? AND view_id = ?",
            (inspection_id, view_id),
        ).fetchone()
        return row and {"target": row["target"] and json.loads(row["target"])}

    def find_view(self, inspection_id, view_id):
        with self.events.connection() as conn:
            return self._view(conn, inspection_id, view_id)

    def add_view(self, view: dict):
        """(신규 여부, 저장된 target). 첫 view가 점검을 만듭니다."""
        key = (view["inspection_id"], view["view_id"])
        with self.events.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")  # finish와 동시에 실행되지 않게 잠급니다.
            stored = self._view(conn, *key)
            if stored:
                return False, stored["target"]
            conn.execute(
                "INSERT INTO inspections(id) VALUES (?) ON CONFLICT(id) DO NOTHING",
                key[:1],
            )
            if self._status(conn, key[0])["status"] != "open":
                raise Finished
            row = dict(view, target=view["target"] and json.dumps(view["target"]))
            conn.execute(
                f"INSERT INTO views({', '.join(row)}) "
                f"VALUES ({', '.join('?' * len(row))})",
                tuple(row.values()),
            )
        return True, view["target"]

    def finish(self, inspection_id, evaluate):
        """판정 저장과 events 반영을 한 트랜잭션으로 처리합니다. 없으면 None.

        evaluate(views) -> (result, events에 넣을 view_id 목록).
        이미 종료됐으면 최초 결과를 그대로 반환합니다.
        """
        with self.events.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            inspection = self._status(conn, inspection_id)
            if inspection is None:
                return None
            if inspection["status"] != "open":
                return json.loads(inspection["result"])

            views = [
                dict(row, target=row["target"] and json.loads(row["target"]))
                for row in conn.execute(
                    "SELECT view_id, pose_id, pan, tilt, move, target FROM views "
                    "WHERE inspection_id = ? ORDER BY rowid",
                    (inspection_id,),
                )
            ]
            result, chosen = evaluate(views)

            for view_id in chosen:
                row = conn.execute(
                    "SELECT * FROM views WHERE inspection_id = ? AND view_id = ?",
                    (inspection_id, view_id),
                ).fetchone()
                target = json.loads(row["target"])
                conn.execute(
                    "INSERT INTO events(pothole_id, event_id, captured_at, lat, lon, "
                    "detections, max_confidence, width, height, content) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        result["pothole_id"], f"{inspection_id}:{view_id}",
                        row["captured_at"], row["lat"], row["lon"],
                        json.dumps([{
                            "confidence": target["confidence"], "box": target["box"],
                        }]),
                        target["confidence"], row["width"], row["height"],
                        row["content"],
                    ),
                )

            conn.execute(
                f"UPDATE inspections SET status = ?, result = ?, finished_at = {NOW} "
                "WHERE id = ?",
                (result["verdict"], json.dumps(result), inspection_id),
            )
        return result

    def get(self, inspection_id):
        with self.events.connection() as conn:
            row = conn.execute(
                "SELECT id, status, result, created_at, finished_at, "
                "(SELECT COUNT(*) FROM views WHERE inspection_id = id) AS view_count "
                "FROM inspections WHERE id = ?",
                (inspection_id,),
            ).fetchone()
        return row and dict(row, result=row["result"] and json.loads(row["result"]))
