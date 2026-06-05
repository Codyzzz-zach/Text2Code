"""ObjectStore — SQLite-backed storage for validated T2C ontology objects."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from pydantic import BaseModel

from t2c.ontology import (
    Block,
    Claim,
    Document,
    Entity,
    Event,
    IgnoreSegment,
    Relation,
    Residual,
    Segment,
)

_TYPE_MAP: dict[str, type[BaseModel]] = {
    "Document": Document,
    "Block": Block,
    "Segment": Segment,
    "Entity": Entity,
    "Event": Event,
    "Claim": Claim,
    "Relation": Relation,
    "Residual": Residual,
    "IgnoreSegment": IgnoreSegment,
}


class ObjectStore:
    """SQLite-backed store for T2C ontology objects with optional validation gate."""

    def __init__(self, db_path: Path | str = ":memory:", raw_text_store: dict[str, str] | None = None) -> None:
        import sqlite3

        self._conn = sqlite3.connect(str(db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._create_tables()
        self._raw_text_store: dict[str, str] = raw_text_store or {}

    def set_raw_text(self, doc_id: str, text: str) -> None:
        """Register raw text for a document (used for evidence validation)."""
        self._raw_text_store[doc_id] = text

    def _create_tables(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS objects (
                type TEXT NOT NULL,
                id TEXT NOT NULL,
                data TEXT NOT NULL,
                PRIMARY KEY (type, id)
            );
            CREATE INDEX IF NOT EXISTS idx_objects_type ON objects(type);
        """)

    def _build_id_index(self) -> dict[str, set[str]]:
        """Build {type_name: set(ids)} from objects already in the store."""
        idx: dict[str, set[str]] = {}
        rows = self._conn.execute("SELECT type, id FROM objects").fetchall()
        for type_name, obj_id in rows:
            idx.setdefault(type_name, set()).add(obj_id)
        return idx

    # ── Save (no validation — use for internal/test) ──

    def save(self, obj: BaseModel) -> None:
        """Save a Pydantic model object to the store without validation.

        Use save_validated() or save_validated_batch() to enforce validation.
        """
        type_name = type(obj).__name__
        obj_id = getattr(obj, "id", None) or ""
        data = obj.model_dump_json()
        self._conn.execute(
            "INSERT OR REPLACE INTO objects (type, id, data) VALUES (?, ?, ?)",
            (type_name, obj_id, data),
        )
        self._conn.commit()

    # ── Save with validation gate ──

    def save_validated(self, obj: BaseModel) -> tuple[bool, list[str]]:
        """Validate then save a single object. Returns (success, errors)."""
        success, errors = self._validate_single(obj)
        if success:
            self.save(obj)
        return success, errors

    def save_validated_batch(self, objects: list[BaseModel]) -> tuple[int, list[str]]:
        """Validate and save a batch of objects. Returns (saved_count, all_errors).

        Objects that fail validation are skipped; valid ones are saved.
        All objects are validated together so cross-references within the batch resolve.
        """
        from t2c.validator import Validator

        # Build validation context from store + batch
        store_index = self._build_id_index()
        batch_dicts: list[dict] = []
        for obj in objects:
            batch_dicts.append({"type": type(obj).__name__, "data": obj.model_dump()})

        # Merge store IDs as external index for cross-reference resolution
        validator = Validator(
            raw_text_store=self._raw_text_store,
            external_index=store_index,
        )
        result = validator.validate_objects(batch_dicts)

        if result.valid:
            for obj in objects:
                self.save(obj)
            return len(objects), []

        # Partial save: figure out which objects have errors and skip them
        error_ids: set[str] = set()
        for err in result.errors:
            # Extract object ID from error messages like "Reference error in Entity (ent1):"
            for obj in objects:
                obj_id = getattr(obj, "id", "")
                if obj_id and obj_id in err:
                    error_ids.add(obj_id)

        saved = 0
        for obj in objects:
            obj_id = getattr(obj, "id", "")
            if obj_id not in error_ids:
                self.save(obj)
                saved += 1

        return saved, result.errors

    def _validate_single(self, obj: BaseModel) -> tuple[bool, list[str]]:
        """Validate a single object against store context."""
        from t2c.validator import Validator

        store_index = self._build_id_index()
        validator = Validator(
            raw_text_store=self._raw_text_store,
            external_index=store_index,
        )
        obj_dict = {"type": type(obj).__name__, "data": obj.model_dump()}
        result = validator.validate_objects([obj_dict])
        return result.valid, result.errors

    # ── Query ──

    def load(self, type_name: str, obj_id: str) -> BaseModel | None:
        row = self._conn.execute(
            "SELECT data FROM objects WHERE type=? AND id=?",
            (type_name, obj_id),
        ).fetchone()
        if row is None:
            return None
        model_cls = _TYPE_MAP.get(type_name)
        if model_cls is None:
            return None
        return model_cls.model_validate_json(row[0])

    def load_all(self, type_name: str) -> list[BaseModel]:
        rows = self._conn.execute(
            "SELECT data FROM objects WHERE type=?",
            (type_name,),
        ).fetchall()
        model_cls = _TYPE_MAP.get(type_name)
        if model_cls is None:
            return []
        return [model_cls.model_validate_json(r[0]) for r in rows]

    def query(
        self,
        type_name: str | None = None,
        **filters: Any,
    ) -> Iterator[BaseModel]:
        """Query objects by type and/or field filters."""
        if type_name is not None:
            rows = self._conn.execute(
                "SELECT data FROM objects WHERE type=?",
                (type_name,),
            ).fetchall()
            model_cls = _TYPE_MAP.get(type_name)
            if model_cls is None:
                return
            for row in rows:
                obj = model_cls.model_validate_json(row[0])
                if all(getattr(obj, k, None) == v for k, v in filters.items()):
                    yield obj
        else:
            rows = self._conn.execute("SELECT type, data FROM objects").fetchall()
            for t, data in rows:
                model_cls = _TYPE_MAP.get(t)
                if model_cls is None:
                    continue
                obj = model_cls.model_validate_json(data)
                if all(getattr(obj, k, None) == v for k, v in filters.items()):
                    yield obj

    def count(self, type_name: str | None = None) -> int:
        if type_name:
            row = self._conn.execute("SELECT COUNT(*) FROM objects WHERE type=?", (type_name,)).fetchone()
        else:
            row = self._conn.execute("SELECT COUNT(*) FROM objects").fetchone()
        return row[0] if row else 0

    def delete(self, type_name: str, obj_id: str) -> bool:
        cursor = self._conn.execute(
            "DELETE FROM objects WHERE type=? AND id=?",
            (type_name, obj_id),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def list_ids(self, type_name: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT id FROM objects WHERE type=?",
            (type_name,),
        ).fetchall()
        return [r[0] for r in rows]

    # ── Backward-compat aliases (old per-type table API) ──

    def get(self, object_type: str, object_id: str) -> dict | None:
        """Compat: return object as dict (old API). Prefer load() for typed access."""
        row = self._conn.execute(
            "SELECT data FROM objects WHERE type=? AND id=?",
            (object_type, object_id),
        ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    def get_segments_by_doc(self, doc_id: str) -> list[dict]:
        """Compat: return segments for a doc as dicts, ordered by block_index."""
        rows = self._conn.execute(
            "SELECT data FROM objects WHERE type='Segment'"
        ).fetchall()
        results = []
        for row in rows:
            data = json.loads(row[0])
            if data.get("doc_id") == doc_id:
                results.append(data)
        results.sort(key=lambda d: (d.get("block_index", 0), d.get("id", "")))
        return results

    def get_semantic_objects_for_segment(self, segment_id: str) -> list[dict]:
        """Compat: return all Entity/Event/Claim/Relation dicts referencing this segment."""
        results: list[dict] = []
        for type_name in ("Entity", "Event", "Claim", "Relation"):
            rows = self._conn.execute(
                "SELECT data FROM objects WHERE type=?", (type_name,)
            ).fetchall()
            for row in rows:
                data = json.loads(row[0])
                seg_ids = data.get("source_segment_ids", [])
                if segment_id in seg_ids:
                    results.append(data)
        return results

    def get_residuals_for_segment(self, segment_id: str) -> list[dict]:
        """Compat: return Residual dicts for a given segment_id."""
        rows = self._conn.execute(
            "SELECT data FROM objects WHERE type='Residual'"
        ).fetchall()
        return [json.loads(r[0]) for r in rows
                if json.loads(r[0]).get("segment_id") == segment_id]

    def get_ignore_markers(self, doc_id: str) -> list[dict]:
        """Compat: return IgnoreSegment dicts for a given doc_id."""
        rows = self._conn.execute(
            "SELECT data FROM objects WHERE type='IgnoreSegment'"
        ).fetchall()
        results = []
        for row in rows:
            data = json.loads(row[0])
            seg = self.get("Segment", data.get("segment_id", ""))
            if seg and seg.get("doc_id") == doc_id:
                results.append(data)
        return results

    def save_parsed(self, objects: list[dict]) -> None:
        """Compat: save parsed {type, data} dicts (from T2CParser)."""
        from t2c.schema import SchemaValidator
        sv = SchemaValidator()
        models, _ = sv.validate_and_construct(objects)
        for model in models:
            self.save(model)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> ObjectStore:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
