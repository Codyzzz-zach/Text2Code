"""Pipeline — orchestrate the full Text → Code flow with validation and repair."""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any

from t2c.codegen import CodeGenerator
from t2c.corpus import CorpusManager
from t2c.extractor import LLMExtractor
from t2c.object_store import ObjectStore
from t2c.ontology import Block, Document, Segment
from t2c.schema import SchemaValidator
from t2c.segmenter import Segmenter
from t2c.validator import Validator

logger = logging.getLogger(__name__)

MAX_REPAIR_ATTEMPTS = 2


@dataclass
class PipelineResult:
    objects: list[dict] = field(default_factory=list)
    code: str = ""
    valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    repair_attempts: int = 0
    raw_fallback_segment_ids: list[str] = field(default_factory=list)
    saved_count: int = 0
    rejected_count: int = 0
    # v3.4.1: extraction telemetry
    batches_truncated: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    api_elapsed_sec: float = 0.0


class Pipeline:
    """Full pipeline: Raw Text -> Segments -> Candidates -> Validation -> Repair -> Code -> Store."""

    def __init__(
        self,
        store: ObjectStore | None = None,
        extractor: LLMExtractor | None = None,
        *,
        max_repair_attempts: int = MAX_REPAIR_ATTEMPTS,
    ) -> None:
        self._store = store or ObjectStore()
        self._extractor = extractor
        self._max_repair = max_repair_attempts

    @property
    def store(self) -> ObjectStore:
        return self._store

    def process_text(
        self,
        raw_text: str,
        doc_id: str,
        source_path: str = "",
        chapter_num: int = 1,
        chapter_title: str = "",
    ) -> PipelineResult:
        """Process raw text through the full pipeline.

        Steps:
        1. Ingest text into corpus (Document + raw_text_hash)
        2. Create blocks from text
        3. Segment each block
        4. Extract candidates via LLM (if extractor available)
        5. Validate candidates
        6. Repair if invalid (up to max_repair_attempts)
        7. Validate schema + construct models
        8. Generate code from valid models
        9. Save valid objects to store (with validation gate)
        10. Generate raw fallback Residual for unrepairable segments
        """
        result = PipelineResult()

        # Step 1: Ingest text into corpus
        corpus = CorpusManager()
        doc, stored_text = corpus.ingest_text(raw_text, doc_id, source_path)
        logger.info("Ingested document %s (%d chars)", doc_id, len(raw_text))

        # Step 2: Create blocks
        blocks = corpus.create_blocks(doc, raw_text)
        logger.info("Created %d blocks for %s", len(blocks), doc_id)

        # Step 3: Segment each block
        segmenter = Segmenter()
        all_segments: list[Segment] = []
        for block in blocks:
            block_text = corpus.get_block_text(doc, block, raw_text)
            segs = segmenter.segment_block(doc_id, block, block_text)
            all_segments.extend(segs)
        logger.info("Segmented %s into %d segments", doc_id, len(all_segments))

        # Save document and segments to store
        self._store.save(doc)
        for seg in all_segments:
            self._store.save(seg)

        # Step 4: Extract (if extractor available)
        if self._extractor is None:
            logger.warning("No extractor configured - skipping candidate extraction")
            result.warnings.append("No extractor configured")
            return result

        objects = self._extractor.extract_chapter(
            doc_id=doc_id,
            chapter_num=chapter_num,
            chapter_title=chapter_title,
            segments=all_segments,
        )
        result.objects = objects
        # v3.4.1: capture extraction telemetry
        result.batches_truncated = 1 if getattr(self._extractor, "_last_batch_truncated", False) else 0
        result.total_input_tokens = getattr(self._extractor, "_total_input_tokens", 0)
        result.total_output_tokens = getattr(self._extractor, "_total_output_tokens", 0)
        result.api_elapsed_sec = getattr(self._extractor, "_api_elapsed_sec", 0.0)
        logger.info("Extracted %d candidate objects", len(objects))

        # Step 5: Validate (with raw_text for evidence checks)
        self._store.set_raw_text(doc_id, raw_text)
        validator = Validator(
            raw_text_store={doc_id: raw_text},
            external_index=self._store._build_id_index(),
        )
        val_result = validator.validate_objects(objects)
        result.errors = val_result.errors
        result.warnings = val_result.warnings

        # Step 6: Repair loop
        repair_attempts = 0
        while not val_result.valid and repair_attempts < self._max_repair:
            repair_attempts += 1
            logger.info("Repair attempt %d/%d", repair_attempts, self._max_repair)

            objects = self._repair(objects, val_result.errors, all_segments)
            val_result = validator.validate_objects(objects)
            result.errors = val_result.errors
            result.warnings = val_result.warnings

        result.repair_attempts = repair_attempts
        result.valid = val_result.valid

        # Step 7: Validate schema + construct models
        models: list = []
        if objects:
            sv = SchemaValidator()
            models, _ = sv.validate_and_construct(objects)

        # Step 8: Generate code from validated models
        if models:
            codegen = CodeGenerator()
            result.code = codegen.generate_knowledge_code(models)

        # Step 9: Save valid objects to store (with validation gate)
        if models:
            saved_count, val_errors = self._store.save_validated_batch(models)
            result.saved_count = saved_count
            result.rejected_count = len(models) - saved_count

        # Step 10: Raw fallback for uncovered segments.
        # v4.0: always run — uncovers silent loss even when validation passed.
        # The internal logic distinguishes "validation error" (high importance)
        # from "uncovered" (medium importance) and labels accordingly.
        raw_fallback_ids = self._generate_raw_fallbacks(
            objects, all_segments, doc_id, val_result.errors
        )
        result.raw_fallback_segment_ids = raw_fallback_ids

        return result

    def _repair(
        self,
        objects: list[dict],
        errors: list[str],
        segments: list[Segment],
    ) -> list[dict]:
        """Attempt to repair invalid objects by removing problematic references.

        Current strategy: remove objects with errors rather than re-calling LLM.
        This avoids the cost of additional API calls for simple reference errors.
        Objects with only warnings are kept.
        Also cleans up dangling references (IDs referenced in fields but not
        present in any object).
        """
        # Build set of object IDs that have errors
        error_ids: set[str] = set()
        for err in errors:
            for obj in objects:
                obj_id = obj.get("data", {}).get("id", "")
                if obj_id and obj_id in err:
                    error_ids.add(obj_id)

        # Remove objects with errors
        repaired = [obj for obj in objects if obj.get("data", {}).get("id", "") not in error_ids]

        # Build set of all known valid IDs after removal
        known_ids: set[str] = set()
        for obj in repaired:
            obj_id = obj.get("data", {}).get("id", "")
            if obj_id:
                known_ids.add(obj_id)
        for seg in segments:
            known_ids.add(seg.id)

        # Combined set of IDs to purge: removed objects + dangling references
        purge_ids = error_ids.copy()
        for err in errors:
            # Extract ID-like tokens from error messages for dangling references
            # e.g. "dangling reference to 'e2'" → e2
            for obj in repaired:
                for field_name in ("participants", "subject", "object", "claim_id",
                                   "source", "derived_from", "source_segment_ids",
                                   "segment_id", "evidence_refs"):
                    val = obj.get("data", {}).get(field_name)
                    if val is None:
                        continue
                    ids_to_check = val if isinstance(val, list) else [val]
                    for ref_id in ids_to_check:
                        if isinstance(ref_id, str) and ref_id not in known_ids:
                            purge_ids.add(ref_id)

        for obj in repaired:
            data = obj.get("data", {})
            # Clean up source_segment_ids
            if "source_segment_ids" in data:
                data["source_segment_ids"] = [
                    sid for sid in data["source_segment_ids"] if sid not in purge_ids
                ]
            # Clean up participants
            if "participants" in data:
                data["participants"] = [
                    p for p in data["participants"] if p not in purge_ids
                ]
            # Clean up derived_from
            if "derived_from" in data:
                data["derived_from"] = [
                    d for d in data["derived_from"] if d not in purge_ids
                ]
            # Clean up subject/object scalar references
            if data.get("subject") in purge_ids:
                data["subject"] = None
            if data.get("object") in purge_ids:
                data["object"] = None
            # Remove Relation with dangling claim_id
            if data.get("claim_id") in purge_ids:
                data["claim_id"] = None
            # Clean up segment_id scalar reference
            if data.get("segment_id") in purge_ids:
                data["segment_id"] = None

        return repaired

    def _generate_raw_fallbacks(
        self,
        objects: list[dict],
        segments: list[Segment],
        doc_id: str,
        errors: list[str],
    ) -> list[str]:
        """Generate Residual objects for segments that couldn't be properly structured.

        Returns list of segment IDs that got raw fallback treatment.

        v4.0 fix: also produce Residuals for *uncovered* segments
        (no semantic object, no residual, no ignore). These represent
        silent loss and must be made visible.
        """
        # Find segments that are referenced by objects with errors
        error_obj_ids: set[str] = set()
        for err in errors:
            for obj in objects:
                obj_id = obj.get("data", {}).get("id", "")
                if obj_id and obj_id in err:
                    error_obj_ids.add(obj_id)

        # Find segment IDs that need raw fallback
        fallback_seg_ids: set[str] = set()
        for obj in objects:
            if obj.get("data", {}).get("id", "") in error_obj_ids:
                for seg_id in obj.get("data", {}).get("source_segment_ids", []):
                    fallback_seg_ids.add(seg_id)

        # v4.0: also find segments that no object ever references. These
        # would be silent loss; we emit a medium-importance Residual so
        # coverage can label them "raw_only" and they appear in the ledger.
        referenced_segs: set[str] = set()
        for obj in objects:
            for sid in obj.get("data", {}).get("source_segment_ids", []) or []:
                referenced_segs.add(sid)
            for eref in obj.get("data", {}).get("evidence_refs", []) or []:
                sid = eref.get("segment_id") if isinstance(eref, dict) else getattr(eref, "segment_id", None)
                if sid:
                    referenced_segs.add(sid)
        seg_ids = {s.id for s in segments}
        uncovered_seg_ids = seg_ids - referenced_segs
        fallback_seg_ids |= uncovered_seg_ids

        # Generate Residual objects for these segments
        seg_map = {s.id: s for s in segments}
        sv = SchemaValidator()
        for seg_id in fallback_seg_ids:
            seg = seg_map.get(seg_id)
            if seg is None:
                continue
            if seg_id in uncovered_seg_ids:
                # Silent loss: no object ever referenced this segment.
                importance = "medium"
                category = "structural"
                reason = "Segment has no semantic object, no Residual, no Ignore — silent loss marker"
            else:
                # Validation error forced fallback.
                importance = "high"
                category = "structural"
                reason = "Segment contains information that could not be safely structured due to validation errors"
            residual = {
                "type": "Residual",
                "data": {
                    "id": f"{doc_id}_res_raw_{seg_id}",
                    "segment_id": seg_id,
                    "category": category,
                    "importance": importance,
                    "reason": reason,
                },
            }
            models, _ = sv.validate_and_construct([residual])
            for m in models:
                self._store.save(m)

        return list(fallback_seg_ids)
