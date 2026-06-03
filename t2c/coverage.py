"""Coverage — auto-derive coverage report for a document's segments."""
from __future__ import annotations

from datetime import datetime, timezone

from t2c.object_store import ObjectStore
from t2c.ontology import CoverageReport


class CoverageGenerator:
    def __init__(self, store: ObjectStore) -> None:
        self._store = store

    def generate_coverage(self, doc_id: str) -> CoverageReport:
        segments = self._store.get_segments_by_doc(doc_id)
        total = len(segments)
        status_counts = {"covered": 0, "partial": 0, "raw_only": 0, "ignored": 0, "uncovered": 0}
        requires_raw_fallback: list[str] = []

        for seg_data in segments:
            seg_id = seg_data["id"]
            status = self._segment_status(seg_id)
            status_counts[status] += 1
            if self._requires_raw_fallback(seg_id, status):
                requires_raw_fallback.append(seg_id)

        return CoverageReport(
            id=f"{doc_id}_coverage",
            doc_id=doc_id,
            total_segments=total,
            status_counts=status_counts,
            requires_raw_fallback=requires_raw_fallback,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    def _segment_status(self, segment_id: str) -> str:
        has_semantic = bool(self._store.get_semantic_objects_for_segment(segment_id))
        residuals = self._store.get_residuals_for_segment(segment_id)
        has_residual = bool(residuals)
        is_ignored = bool(self._store.get("IgnoreSegment",
                                          self._ignored_id(segment_id)))

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
        residuals = self._store.get_residuals_for_segment(segment_id)
        for r in residuals:
            if r.get("importance") == "high":
                return True

        # Check for non-asserted claims or non-positive polarity
        semantic = self._store.get_semantic_objects_for_segment(segment_id)
        for obj in semantic:
            if obj.get("modality") and obj["modality"] != "asserted":
                return True
            if obj.get("polarity") and obj["polarity"] != "positive":
                return True

        return False

    def _ignored_id(self, segment_id: str) -> str:
        # Convention: ignore segment ID = segment_id + "_ign"
        # Try to find by querying segment_id directly
        rows = self._store.query("IgnoreSegment", segment_id=segment_id)
        if rows:
            return rows[0].get("id", "")
        return ""
