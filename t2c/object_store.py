"""Object Store — SQLite-backed persistence for T2C objects."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from t2c.ontology import ONTOLOGY_CLASSES

_TABLES = {
    "Document": """CREATE TABLE IF NOT EXISTS Document (
        id TEXT PRIMARY KEY,
        source_path TEXT,
        data JSON NOT NULL
    )""",
    "Block": """CREATE TABLE IF NOT EXISTS Block (
        id TEXT PRIMARY KEY,
        doc_id TEXT NOT NULL,
        "index" INTEGER NOT NULL,
        data JSON NOT NULL
    )""",
    "Segment": """CREATE TABLE IF NOT EXISTS Segment (
        id TEXT PRIMARY KEY,
        doc_id TEXT NOT NULL,
        block_index INTEGER NOT NULL,
        data JSON NOT NULL
    )""",
    "Entity": """CREATE TABLE IF NOT EXISTS Entity (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        kind TEXT NOT NULL,
        data JSON NOT NULL
    )""",
    "Event": """CREATE TABLE IF NOT EXISTS Event (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        kind TEXT NOT NULL,
        data JSON NOT NULL
    )""",
    "Claim": """CREATE TABLE IF NOT EXISTS Claim (
        id TEXT PRIMARY KEY,
        subject TEXT NOT NULL,
        predicate TEXT NOT NULL,
        modality TEXT NOT NULL,
        polarity TEXT NOT NULL,
        confidence REAL NOT NULL DEFAULT 1.0,
        data JSON NOT NULL
    )""",
    "Relation": """CREATE TABLE IF NOT EXISTS Relation (
        id TEXT PRIMARY KEY,
        subject TEXT NOT NULL,
        predicate TEXT NOT NULL,
        object TEXT NOT NULL,
        claim_id TEXT NOT NULL,
        data JSON NOT NULL
    )""",
    "Residual": """CREATE TABLE IF NOT EXISTS Residual (
        id TEXT PRIMARY KEY,
        segment_id TEXT NOT NULL,
        category TEXT NOT NULL,
        importance TEXT NOT NULL,
        data JSON NOT NULL
    )""",
    "IgnoreSegment": """CREATE TABLE IF NOT EXISTS IgnoreSegment (
        id TEXT PRIMARY KEY,
        segment_id TEXT NOT NULL,
        data JSON NOT NULL
    )""",
    "CoverageReport": """CREATE TABLE IF NOT EXISTS CoverageReport (
        id TEXT PRIMARY KEY,
        doc_id TEXT NOT NULL,
        data JSON NOT NULL
    )""",
}

_INSERT_SQL = {
    "Document": "INSERT OR REPLACE INTO Document (id, source_path, data) VALUES (?, ?, ?)",
    "Block": 'INSERT OR REPLACE INTO Block (id, doc_id, "index", data) VALUES (?, ?, ?, ?)',
    "Segment": "INSERT OR REPLACE INTO Segment (id, doc_id, block_index, data) VALUES (?, ?, ?, ?)",
    "Entity": "INSERT OR REPLACE INTO Entity (id, name, kind, data) VALUES (?, ?, ?, ?)",
    "Event": "INSERT OR REPLACE INTO Event (id, name, kind, data) VALUES (?, ?, ?, ?)",
    "Claim": "INSERT OR REPLACE INTO Claim (id, subject, predicate, modality, polarity, confidence, data) VALUES (?, ?, ?, ?, ?, ?, ?)",
    "Relation": "INSERT OR REPLACE INTO Relation (id, subject, predicate, object, claim_id, data) VALUES (?, ?, ?, ?, ?, ?)",
    "Residual": "INSERT OR REPLACE INTO Residual (id, segment_id, category, importance, data) VALUES (?, ?, ?, ?, ?)",
    "IgnoreSegment": "INSERT OR REPLACE INTO IgnoreSegment (id, segment_id, data) VALUES (?, ?, ?)",
    "CoverageReport": "INSERT OR REPLACE INTO CoverageReport (id, doc_id, data) VALUES (?, ?, ?)",
}


class ObjectStore:
    def __init__(self, db_path: Path | str = ":memory:") -> None:
        import sqlite3
        self._conn = sqlite3.connect(str(db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._create_tables()

    def _create_tables(self) -> None:
        for ddl in _TABLES.values():
            self._conn.execute(ddl)
        self._conn.commit()

    def save(self, obj: BaseModel) -> None:
        type_name = type(obj).__name__
        data_json = obj.model_dump_json()
        obj_id = getattr(obj, "id", None)
        if obj_id is None:
            raise ValueError(f"Object of type {type_name} has no 'id' field")

        sql = _INSERT_SQL.get(type_name)
        if sql is None:
            raise ValueError(f"Unknown object type: {type_name}")

        if type_name == "Document":
            params = (obj_id, obj.source_path, data_json)
        elif type_name == "Block":
            params = (obj_id, obj.doc_id, obj.index, data_json)
        elif type_name == "Segment":
            params = (obj_id, obj.doc_id, obj.block_index, data_json)
        elif type_name == "Entity":
            params = (obj_id, obj.name, obj.kind, data_json)
        elif type_name == "Event":
            params = (obj_id, obj.name, obj.kind, data_json)
        elif type_name == "Claim":
            params = (obj_id, obj.subject, obj.predicate, obj.modality, obj.polarity, obj.confidence, data_json)
        elif type_name == "Relation":
            params = (obj_id, obj.subject, obj.predicate, obj.object, obj.claim_id, data_json)
        elif type_name == "Residual":
            params = (obj_id, obj.segment_id, obj.category, obj.importance, data_json)
        elif type_name == "IgnoreSegment":
            params = (obj_id, obj.segment_id, data_json)
        elif type_name == "CoverageReport":
            params = (obj_id, obj.doc_id, data_json)
        else:
            raise ValueError(f"No insert mapping for {type_name}")

        self._conn.execute(sql, params)
        self._conn.commit()

    def save_parsed(self, objects: list[dict]) -> None:
        """Save parsed {type, data} dicts (from T2CParser)."""
        from t2c.schema import SchemaValidator
        sv = SchemaValidator()
        models, _ = sv.validate_and_construct(objects)
        for model in models:
            self.save(model)

    def get(self, object_type: str, object_id: str) -> dict | None:
        row = self._conn.execute(
            f"SELECT data FROM {object_type} WHERE id = ?", (object_id,)
        ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    def query(self, object_type: str, **filters: Any) -> list[dict]:
        where_parts: list[str] = []
        params: list[Any] = []
        for key, value in filters.items():
            where_parts.append(f"{key} = ?")
            params.append(value)
        where = " AND ".join(where_parts) if where_parts else "1=1"
        rows = self._conn.execute(
            f"SELECT data FROM {object_type} WHERE {where}", params
        ).fetchall()
        return [json.loads(r[0]) for r in rows]

    def get_segments_by_doc(self, doc_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT data FROM Segment WHERE doc_id = ? ORDER BY block_index, id",
            (doc_id,),
        ).fetchall()
        return [json.loads(r[0]) for r in rows]

    def get_semantic_objects_for_segment(self, segment_id: str) -> list[dict]:
        results: list[dict] = []
        for type_name in ("Entity", "Event", "Claim", "Relation"):
            rows = self._conn.execute(
                f"SELECT data FROM {type_name}"
            ).fetchall()
            for row in rows:
                data = json.loads(row[0])
                seg_ids = data.get("source_segment_ids", [])
                if segment_id in seg_ids:
                    results.append(data)
        return results

    def get_residuals_for_segment(self, segment_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT data FROM Residual WHERE segment_id = ?", (segment_id,)
        ).fetchall()
        return [json.loads(r[0]) for r in rows]

    def get_ignore_markers(self, doc_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT data FROM IgnoreSegment"
        ).fetchall()
        results = []
        for row in rows:
            data = json.loads(row[0])
            seg = self.get("Segment", data.get("segment_id", ""))
            if seg and seg.get("doc_id") == doc_id:
                results.append(data)
        return results

    def close(self) -> None:
        self._conn.close()