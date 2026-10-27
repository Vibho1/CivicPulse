"""SQLite persistence. Deliberately simple: one file, JSON columns for nested data.

The schema is small enough that swapping to Firestore/Postgres later means
re-implementing this module only.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterable
from pathlib import Path
from typing import Any

JSON_FIELDS = {
    "hazards_json",
    "evidence_json",
    "raw_extraction_json",
    "score_breakdown_json",
    "verification_json",
    "payload_json",
    "raw_json",
    "context_json",
    "exif_gps_json",
    "before_photo_paths_json",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS clusters (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    category TEXT NOT NULL,
    status TEXT NOT NULL,
    lat REAL NOT NULL,
    lng REAL NOT NULL,
    ward TEXT NOT NULL,
    zone TEXT,
    title TEXT NOT NULL,
    description TEXT,
    landmark TEXT,
    agency TEXT NOT NULL,
    agency_reason TEXT,
    report_count INTEGER NOT NULL DEFAULT 1,
    max_severity INTEGER NOT NULL DEFAULT 1,
    impact_score REAL NOT NULL DEFAULT 0,
    score_breakdown_json TEXT,
    sla_hours INTEGER NOT NULL,
    sla_due_at TEXT NOT NULL,
    repeat_failure INTEGER NOT NULL DEFAULT 0,
    previous_cluster_id TEXT,
    resolved_at TEXT,
    resolved_by TEXT,
    resolution_note TEXT,
    after_photo_path TEXT,
    verification_verdict TEXT,
    verified_at TEXT,
    primary_photo_path TEXT,
    hazards_json TEXT,
    context_json TEXT,
    closure_count INTEGER NOT NULL DEFAULT 0,
    first_report_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_clusters_latlng ON clusters(lat, lng);
CREATE INDEX IF NOT EXISTS idx_clusters_status ON clusters(status);
CREATE INDEX IF NOT EXISTS idx_clusters_ward ON clusters(ward);

CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY,
    cluster_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    lat REAL NOT NULL,
    lng REAL NOT NULL,
    accuracy REAL,
    reporter_id TEXT,
    text TEXT,
    transcript TEXT,
    transcript_english TEXT,
    language TEXT,
    category TEXT NOT NULL,
    severity INTEGER NOT NULL,
    title TEXT,
    description TEXT,
    landmark TEXT,
    size_estimate TEXT,
    hazards_json TEXT,
    evidence_json TEXT,
    agency TEXT,
    agency_reason TEXT,
    audio_path TEXT,
    photo_path TEXT,
    ai_mode TEXT,
    confidence REAL,
    raw_extraction_json TEXT,
    ward TEXT,
    exif_gps_json TEXT,
    is_corroboration INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(cluster_id) REFERENCES clusters(id)
);
CREATE INDEX IF NOT EXISTS idx_reports_cluster ON reports(cluster_id);

CREATE TABLE IF NOT EXISTS verifications (
    id TEXT PRIMARY KEY,
    cluster_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    kind TEXT NOT NULL,
    actor TEXT,
    photo_path TEXT,
    before_photo_paths_json TEXT,
    verdict TEXT NOT NULL,
    same_location INTEGER,
    issue_resolved INTEGER,
    fix_quality TEXT,
    same_location_confidence REAL,
    resolution_confidence REAL,
    explanation TEXT,
    raw_json TEXT,
    ai_mode TEXT,
    note TEXT,
    FOREIGN KEY(cluster_id) REFERENCES clusters(id)
);
CREATE INDEX IF NOT EXISTS idx_verifications_cluster ON verifications(cluster_id);

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    cluster_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    type TEXT NOT NULL,
    actor TEXT,
    note TEXT,
    payload_json TEXT,
    FOREIGN KEY(cluster_id) REFERENCES clusters(id)
);
CREATE INDEX IF NOT EXISTS idx_events_cluster ON events(cluster_id);
"""


def _encode(row: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for k, v in row.items():
        if k in JSON_FIELDS and not isinstance(v, (str, type(None))):
            v = json.dumps(v, ensure_ascii=False, default=str)
        elif isinstance(v, bool):
            v = int(v)
        out[k] = v
    return out


def _decode(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    d = dict(row)
    for k in JSON_FIELDS:
        if k in d and isinstance(d[k], str):
            try:
                d[k] = json.loads(d[k])
            except json.JSONDecodeError:
                pass
    return d


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self._lock = threading.RLock()
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        with self._lock, self.conn:
            if self.path != ":memory:":
                self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA foreign_keys=ON")
            self.conn.executescript(SCHEMA)

    # ----------------------------------------------------------- primitives
    def _insert(self, table: str, row: dict[str, Any]) -> None:
        row = _encode(row)
        cols = ", ".join(row.keys())
        marks = ", ".join("?" for _ in row)
        with self._lock, self.conn:
            self.conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", list(row.values()))

    def _update(self, table: str, id_: str, fields: dict[str, Any]) -> None:
        if not fields:
            return
        fields = _encode(fields)
        sets = ", ".join(f"{k} = ?" for k in fields)
        with self._lock, self.conn:
            self.conn.execute(f"UPDATE {table} SET {sets} WHERE id = ?", [*fields.values(), id_])

    def _one(self, sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
        with self._lock:
            return _decode(self.conn.execute(sql, list(params)).fetchone())

    def _all(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [_decode(r) for r in self.conn.execute(sql, list(params)).fetchall()]  # type: ignore[misc]

    # -------------------------------------------------------------- clusters
    def insert_cluster(self, c: dict[str, Any]) -> None:
        self._insert("clusters", c)

    def update_cluster(self, id_: str, **fields: Any) -> None:
        self._update("clusters", id_, fields)

    def get_cluster(self, id_: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM clusters WHERE id = ?", [id_])

    def clusters_in_bbox(self, min_lat: float, max_lat: float, min_lng: float, max_lng: float) -> list[dict[str, Any]]:
        return self._all(
            "SELECT * FROM clusters WHERE lat BETWEEN ? AND ? AND lng BETWEEN ? AND ?",
            [min_lat, max_lat, min_lng, max_lng],
        )

    def list_clusters(
        self,
        status: str | None = None,
        ward: str | None = None,
        category: str | None = None,
        agency: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        where, params = [], []
        if status:
            statuses = status.split(",")
            where.append(f"status IN ({', '.join('?' for _ in statuses)})")
            params.extend(statuses)
        if ward:
            where.append("ward = ?")
            params.append(ward)
        if category:
            where.append("category = ?")
            params.append(category)
        if agency:
            where.append("agency = ?")
            params.append(agency)
        sql = "SELECT * FROM clusters"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY impact_score DESC, updated_at DESC LIMIT ?"
        params.append(limit)
        return self._all(sql, params)

    def all_clusters(self) -> list[dict[str, Any]]:
        return self._all("SELECT * FROM clusters")

    # --------------------------------------------------------------- reports
    def insert_report(self, r: dict[str, Any]) -> None:
        self._insert("reports", r)

    def get_report(self, id_: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM reports WHERE id = ?", [id_])

    def reports_for_cluster(self, cluster_id: str) -> list[dict[str, Any]]:
        return self._all("SELECT * FROM reports WHERE cluster_id = ? ORDER BY created_at ASC", [cluster_id])

    def recent_reports(self, limit: int = 20) -> list[dict[str, Any]]:
        return self._all("SELECT * FROM reports ORDER BY created_at DESC LIMIT ?", [limit])

    # --------------------------------------------------------- verifications
    def insert_verification(self, v: dict[str, Any]) -> None:
        self._insert("verifications", v)

    def verifications_for_cluster(self, cluster_id: str) -> list[dict[str, Any]]:
        return self._all("SELECT * FROM verifications WHERE cluster_id = ? ORDER BY created_at ASC", [cluster_id])

    # ---------------------------------------------------------------- events
    def insert_event(self, e: dict[str, Any]) -> None:
        self._insert("events", e)

    def events_for_cluster(self, cluster_id: str) -> list[dict[str, Any]]:
        return self._all("SELECT * FROM events WHERE cluster_id = ? ORDER BY created_at ASC", [cluster_id])

    # ----------------------------------------------------------------- stats
    def counts(self) -> dict[str, int]:
        rows = self._all("SELECT status, COUNT(*) AS n FROM clusters GROUP BY status")
        out = {r["status"]: r["n"] for r in rows}
        out["reports"] = self._one("SELECT COUNT(*) AS n FROM reports")["n"]  # type: ignore[index]
        return out

    def reset(self) -> None:
        with self._lock, self.conn:
            for t in ("events", "verifications", "reports", "clusters"):
                self.conn.execute(f"DELETE FROM {t}")

    def close(self) -> None:
        with self._lock:
            self.conn.close()
