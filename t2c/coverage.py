"""Coverage — auto-derive coverage report for a document's segments."""
from __future__ import annotations

from t2c.corpus import content_timestamp
from t2c.object_store import ObjectStore
from t2c.ontology import CoverageReport


class CoverageGenerator:
    def __init__(self, store: ObjectStore) -> None:
        self._store = store

    def generate_coverage(self, doc_id: str) -> CoverageReport:
        segments = list(self._store.query("Segment", doc_id=doc_id))
        total = len(segments)
        status_counts = {"covered": 0, "partial": 0, "raw_only": 0, "ignored": 0, "uncovered": 0}
        requires_raw_fallback: list[str] = []

        for seg in segments:
            seg_id = seg.id
            status = self._segment_status(seg_id)
            status_counts[status] += 1
            if self._requires_raw_fallback(seg_id, status):
                requires_raw_fallback.append(seg_id)

        # Deterministic timestamp (rebuild gate): reuse the document's
        # content-derived created_at rather than wall-clock time.
        docs = list(self._store.query("Document", id=doc_id))
        generated_at = docs[0].created_at if docs else content_timestamp("")

        return CoverageReport(
            id=f"{doc_id}_coverage",
            doc_id=doc_id,
            total_segments=total,
            status_counts=status_counts,
            requires_raw_fallback=requires_raw_fallback,
            generated_at=generated_at,
        )

    def _segment_status(self, segment_id: str) -> str:
        has_semantic = bool(self._get_semantic_objects_for_segment(segment_id))
        residuals = list(self._store.query("Residual", segment_id=segment_id))
        has_residual = bool(residuals)
        is_ignored = bool(list(self._store.query("IgnoreSegment", segment_id=segment_id)))

        if is_ignored:
            return "ignored"
        if has_semantic and not has_residual:
            return "covered"
        if has_semantic and has_residual:
            return "partial"
        if not has_semantic and has_residual:
            return "raw_only"
        return "uncovered"

    def _requires_raw_fallback(self, segment_id: str, status: str) -> bool:
        if status in ("partial", "raw_only", "uncovered"):
            return True

        # Check for high-importance residuals
        residuals = list(self._store.query("Residual", segment_id=segment_id))
        for r in residuals:
            if r.importance == "high":
                return True

        # Check for non-asserted claims or non-positive polarity
        semantic = self._get_semantic_objects_for_segment(segment_id)
        for obj in semantic:
            modality = getattr(obj, "modality", None)
            polarity = getattr(obj, "polarity", None)
            if modality and modality != "asserted":
                return True
            if polarity and polarity != "positive":
                return True

        return False

    def _get_semantic_objects_for_segment(self, segment_id: str) -> list:
        """Get all semantic objects (Entity/Event/Claim/Relation) referencing this segment.

        Checks both source_segment_ids (v3.2) and evidence_refs[].segment_id (v3.3).
        """
        results = []
        for type_name in ("Entity", "Event", "Claim", "Relation"):
            for obj in self._store.query(type_name):
                # v3.2: source_segment_ids
                seg_ids = getattr(obj, "source_segment_ids", [])
                if segment_id in seg_ids:
                    results.append(obj)
                    continue
                # v3.3: evidence_refs[].segment_id
                erefs = getattr(obj, "evidence_refs", []) or []
                for eref in erefs:
                    if getattr(eref, "segment_id", None) == segment_id:
                        results.append(obj)
                        break
        return results

    def coverage_by_symbol(
        self,
        doc_id: str,
        symbol_map: dict[str, str] | None = None,
    ) -> dict[str, dict]:
        """Generate coverage report keyed by segment symbol name.

        symbol_map: {segment_id: symbol_name} from text.py parse.
        Returns {symbol_name: {"status": str, "raw_fallback": bool, "id": str}}.
        """
        segments = list(self._store.query("Segment", doc_id=doc_id))
        sym_map = symbol_map or {}
        result: dict[str, dict] = {}
        for seg in segments:
            sym = sym_map.get(seg.id, seg.id)
            status = self._segment_status(seg.id)
            result[sym] = {
                "status": status,
                "raw_fallback": self._requires_raw_fallback(seg.id, status),
                "id": seg.id,
            }
        return result

    @staticmethod
    def coverage_from_parsed_objects(
        objects: list[dict],
        segments: list,
    ) -> dict[str, dict]:
        """Derive coverage directly from parsed v3.3 objects.

        objects: parsed v3.3 objects (with symbol and __symbol_refs__)
        segments: Segment Pydantic models
        Returns {segment_id: {"status": str, "symbol": str | None, ...}}
        """
        # Build map of segment_id → referenced_by objects
        ref_map: dict[str, list] = {s.id: [] for s in segments}
        # Also track residuals and ignores
        residual_seg_ids: set[str] = set()
        ignore_seg_ids: set[str] = set()

        for obj in objects:
            type_name = obj.get("type", "")
            data = obj.get("data", {})

            if type_name == "Residual":
                sid = data.get("segment_id")
                if sid:
                    residual_seg_ids.add(sid)
                continue
            if type_name == "IgnoreSegment":
                sid = data.get("segment_id")
                if sid:
                    ignore_seg_ids.add(sid)
                continue

            # Semantic objects: check evidence_refs and source_segment_ids
            for eref in data.get("evidence_refs", []):
                eref_data = eref.get("data", eref)
                sid = eref_data.get("segment_id") or eref_data.get("segment")
                if sid and sid in ref_map:
                    ref_map[sid].append(obj)

            for sid in data.get("source_segment_ids", []):
                if sid in ref_map:
                    ref_map[sid].append(obj)

        # Determine status for each segment
        result: dict[str, dict] = {}
        for seg in segments:
            sid = seg.id
            is_ignored = sid in ignore_seg_ids
            has_semantic = len(ref_map.get(sid, [])) > 0
            has_residual = sid in residual_seg_ids

            if is_ignored:
                status = "ignored"
            elif has_semantic and not has_residual:
                status = "covered"
            elif has_semantic and has_residual:
                status = "partial"
            elif not has_semantic and has_residual:
                status = "raw_only"
            else:
                status = "uncovered"

            result[sid] = {
                "status": status,
                "raw_fallback": status in ("partial", "raw_only", "uncovered"),
                "object_count": len(ref_map.get(sid, [])),
            }

        return result
