from __future__ import annotations

import csv
import json
import sqlite3
from io import StringIO
from pathlib import Path
from typing import Any

from app.schemas.dashboard import AnalysisResult


class AnalysisStore:
    def __init__(self, db_path: str | Path = "data/traffic_analysis.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS analysis_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    camera_id TEXT,
                    frame_id INTEGER,
                    model_id TEXT,
                    vehicle_count INTEGER NOT NULL DEFAULT 0,
                    current_count INTEGER NOT NULL DEFAULT 0,
                    count_in INTEGER NOT NULL DEFAULT 0,
                    count_out INTEGER NOT NULL DEFAULT 0,
                    density REAL NOT NULL DEFAULT 0,
                    avg_speed REAL,
                    congestion_level TEXT,
                    detection_count INTEGER NOT NULL DEFAULT 0,
                    event_count INTEGER NOT NULL DEFAULT 0,
                    inference_ms REAL,
                    plates TEXT,
                    whitelist_pass_count INTEGER NOT NULL DEFAULT 0,
                    whitelist_block_count INTEGER NOT NULL DEFAULT 0,
                    payload_json TEXT NOT NULL
                )
                """
            )
            for statement in [
                "ALTER TABLE analysis_records ADD COLUMN plates TEXT",
                "ALTER TABLE analysis_records ADD COLUMN whitelist_pass_count INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE analysis_records ADD COLUMN whitelist_block_count INTEGER NOT NULL DEFAULT 0",
            ]:
                try:
                    conn.execute(statement)
                except sqlite3.OperationalError:
                    pass
            conn.execute("CREATE INDEX IF NOT EXISTS idx_analysis_created_at ON analysis_records(created_at DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_analysis_camera_id ON analysis_records(camera_id)")

    def save(self, result: AnalysisResult) -> int:
        stats = result.traffic_stats
        payload = result.model_dump(mode="json")
        created_at = result.timestamp or payload.get("timestamp") or ""
        plates = sorted({item.plate for item in result.detections if item.plate})
        whitelist_pass_count = len([item for item in result.detections if item.whitelist_status is True])
        whitelist_block_count = len([item for item in result.detections if item.whitelist_status is False])
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO analysis_records (
                    created_at, camera_id, frame_id, model_id, vehicle_count, current_count,
                    count_in, count_out, density, avg_speed, congestion_level, detection_count,
                    event_count, inference_ms, plates, whitelist_pass_count, whitelist_block_count, payload_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    created_at,
                    result.camera_id,
                    result.frame_id,
                    result.model_id,
                    stats.vehicle_count,
                    stats.current_count,
                    stats.count_in,
                    stats.count_out,
                    stats.density,
                    stats.avg_speed,
                    stats.congestion_level,
                    len(result.detections),
                    len(result.events),
                    result.inference_ms,
                    ",".join(plates),
                    whitelist_pass_count,
                    whitelist_block_count,
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            return int(cursor.lastrowid)

    def list_records(self, limit: int = 30, camera_id: str | None = None) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 500))
        params: list[Any] = []
        where = ""
        if camera_id:
            where = "WHERE camera_id = ?"
            params.append(camera_id)
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT id, created_at, camera_id, frame_id, model_id, vehicle_count, current_count,
                       count_in, count_out, density, avg_speed, congestion_level, detection_count,
                       event_count, inference_ms, plates, whitelist_pass_count, whitelist_block_count
                FROM analysis_records
                {where}
                ORDER BY id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def export_csv(self, limit: int = 1000) -> str:
        rows = self.list_records(limit=limit)
        output = StringIO()
        fieldnames = [
            "id",
            "created_at",
            "camera_id",
            "frame_id",
            "model_id",
            "vehicle_count",
            "current_count",
            "count_in",
            "count_out",
            "density",
            "avg_speed",
            "congestion_level",
            "detection_count",
            "event_count",
            "inference_ms",
            "plates",
            "whitelist_pass_count",
            "whitelist_block_count",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        return output.getvalue()

    def export_json(self, limit: int = 1000) -> str:
        rows = self.list_records(limit=limit)
        return json.dumps({"items": rows}, ensure_ascii=False, indent=2)
