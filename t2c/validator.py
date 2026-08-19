"""Validator — full pipeline: AST → Schema → Reference → Evidence → Claim Safety → Coverage."""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from pydantic import BaseModel

from t2c.coverage import CoverageGenerator
from t2c.claim_safety import ClaimSafetyValidator
from t2c.parser import T2CParseError, T2CParser
from t2c.schema import SchemaValidator, SchemaViolation

logger = logging.getLogger(__name__)


class ValidationResult(BaseModel):
    valid: bool
    errors: list[str] = []
    warnings: list[str] = []


class Validator:
    """Full validation pipeline: AST grammar → Schema → Reference → Evidence → Claim Safety."""

    def __init__(
        self,
        raw_text_store: dict[str, str] | None = None,
        external_index: dict[str, set[str]] | None = None,
    ) -> None:
        self._parser = T2CParser()
        self._schema_validator = SchemaValidator()
        self._claim_safety_validator = ClaimSafetyValidator()
        self._raw_text_store: dict[str, str] = raw_text_store or {}
        # external_index maps type names to sets of known IDs from external files
        self._external_index: dict[str, set[str]] = external_index or {}

    def set_raw_text(self, doc_id: str, text: str) -> None:
        self._raw_text_store[doc_id] = text

    # -- Main validation methods -----------------------------------------

    def validate_file(self, path: Path) -> ValidationResult:
        source = path.read_text(encoding="utf-8")
        return self.validate_string(source)

    def validate_string(self, source: str) -> ValidationResult:
        errors: list[str] = []
        warnings: list[str] = []

        # Step 1: Parse (includes AST grammar validation)
        try:
            objects = self._parser.parse_string(source)
        except T2CParseError as e:
            return ValidationResult(valid=False, errors=[str(e)])

        # Step 2: Schema validation
        schema_violations = self._schema_validator.validate(objects)
        for v in schema_violations:
            errors.append(f"Schema violation in {v.object_type} ({v.object_id}): {v.field} — {v.message}")

        # Step 2b: ID uniqueness validation
        id_errors, id_warnings = self._validate_id_uniqueness(objects)
        errors.extend(id_errors)
        warnings.extend(id_warnings)

        # Step 3: Reference validation (full ID reference checks)
        ref_errors, ref_warnings = self._validate_references(objects)
        errors.extend(ref_errors)
        warnings.extend(ref_warnings)

        # Step 4: Evidence validation (span/hash for EvidenceRef)
        ev_errors, ev_warnings = self._validate_evidence(objects)
        errors.extend(ev_errors)
        warnings.extend(ev_warnings)

        # Step 5: Claim Safety validation
        cs_errors, cs_warnings = self._validate_claim_safety(objects)
        errors.extend(cs_errors)
        warnings.extend(cs_warnings)

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    def _validate_coverage(self, objects: list[dict]) -> list[str]:
        """D8 gate: Check that all segments are accounted for (not uncovered).
        
        Uses CoverageGenerator.coverage_from_parsed_objects to compute coverage
        from parsed objects without needing an ObjectStore. Returns warnings
        (not errors) since uncovered segments are a quality issue, not a
        correctness issue.
        """
        warnings: list[str] = []
        try:
            report = CoverageGenerator.coverage_from_parsed_objects(objects)
            if report is None:
                return warnings
            status_counts = report.get("status_counts", {})
            uncovered = status_counts.get("uncovered", 0)
            total = report.get("total_segments", 0)
            covered = status_counts.get("covered", 0)
            if total > 0:
                rate = covered / total
                logger.info(
                    "Coverage gate: %d/%d segments covered (%.1f%%), %d uncovered",
                    covered, total, rate * 100, uncovered,
                )
            if uncovered > 0:
                warnings.append(
                    f"Coverage: {uncovered} segments uncovered out of {total} total "
                    f"(covered={covered}, rate={rate:.1%})"
                )
        except Exception as exc:
            logger.warning("Coverage gate failed: %s: %s", type(exc).__name__, exc)
        return warnings


    def validate_objects(self, objects: list[dict], *, validate_coverage: bool = False) -> ValidationResult:
        errors: list[str] = []
        warnings: list[str] = []

        # Schema validation
        schema_violations = self._schema_validator.validate(objects)
        for v in schema_violations:
            errors.append(f"Schema violation in {v.object_type} ({v.object_id}): {v.field} — {v.message}")

        # ID uniqueness validation
        id_errors, id_warnings = self._validate_id_uniqueness(objects)
        errors.extend(id_errors)
        warnings.extend(id_warnings)

        # Reference validation (ID-based)
        ref_errors, ref_warnings = self._validate_references(objects)
        errors.extend(ref_errors)
        warnings.extend(ref_warnings)

        # Evidence validation
        ev_errors, ev_warnings = self._validate_evidence(objects)
        errors.extend(ev_errors)
        warnings.extend(ev_warnings)

        # Claim Safety validation
        cs_errors, cs_warnings = self._validate_claim_safety(objects)
        errors.extend(cs_errors)
        warnings.extend(cs_warnings)


        # D8: Coverage gate (opt-in)
        if validate_coverage:
            cov_warnings = self._validate_coverage(objects)
            warnings.extend(cov_warnings)

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    # -- Index builders --------------------------------------------------

    def _build_type_id_sets(self, objects: list[dict]) -> dict[str, set[str]]:
        """Build {type_name: set(object_ids)} from parsed object dicts."""
        id_sets: dict[str, set[str]] = {}
        for obj in objects:
            type_name = obj.get("type", "")
            data = obj.get("data", {})
            obj_id = data.get("id")
            if obj_id:
                id_sets.setdefault(type_name, set()).add(str(obj_id))
        return id_sets

    def _build_all_id_set(self, objects: list[dict]) -> set[str]:
        """Build set of all object IDs across all types."""
        all_ids: set[str] = set()
        for obj in objects:
            data = obj.get("data", {})
            obj_id = data.get("id")
            if obj_id:
                all_ids.add(str(obj_id))
        return all_ids

    def _validate_id_uniqueness(self, objects: list[dict]) -> tuple[list[str], list[str]]:
        """P1 gate: Check that no two objects of the same type share the same ID."""
        errors: list[str] = []
        seen: dict[str, dict[str, str]] = {}  # type_name -> {id: obj_id_for_error}
        for obj in objects:
            type_name = obj.get("type", "")
            data = obj.get("data", {})
            obj_id = data.get("id")
            if not obj_id:
                continue
            obj_id = str(obj_id)
            type_seen = seen.setdefault(type_name, {})
            if obj_id in type_seen:
                errors.append(
                    f"Duplicate {type_name} ID: {obj_id} "
                    f"(also in {type_seen[obj_id]})"
                )
            else:
                type_seen[obj_id] = type_name  # Just store type for error msg
        return errors, []

    # -- Reference validation -------------------------------------------

    def _validate_references(self, objects: list[dict]) -> tuple[list[str], list[str]]:
        """Check that all cross-references resolve to existing objects.

        For each object type, validates:
        - Entity: source_segment_ids → Segment, evidence_refs[].segment_id → Segment
        - Event: participants → Entity, source_segment_ids → Segment, evidence_refs[].segment_id → Segment
        - Claim: subject → Entity, object → Entity (if entity ID style), source → Entity/Claim,
                  derived_from → Claim, source_segment_ids → Segment, evidence_refs[].segment_id → Segment
        - Relation: subject → Entity, object → Entity, claim_id → Claim, evidence_refs[].segment_id → Segment
        - Residual: segment_id → Segment, evidence_refs[].segment_id → Segment
        - IgnoreSegment: segment_id → Segment, evidence_refs[].segment_id → Segment
        - Block: doc_id → Document
        - Segment: doc_id → Document
        """
        errors: list[str] = []
        warnings: list[str] = []

        id_sets = self._build_type_id_sets(objects)
        all_ids = self._build_all_id_set(objects)

        # Merge external index into id_sets for cross-file reference resolution
        merged_id_sets: dict[str, set[str]] = {}
        for type_name, ids in id_sets.items():
            merged_id_sets[type_name] = ids | self._external_index.get(type_name, set())
        for type_name, ids in self._external_index.items():
            if type_name not in merged_id_sets:
                merged_id_sets[type_name] = ids

        for obj in objects:
            type_name = obj.get("type", "")
            data = obj.get("data", {})
            obj_id = data.get("id", "?")

            if type_name == "Block":
                self._check_ref(
                    obj_id, "Block", "doc_id", data.get("doc_id"),
                    "Document", id_sets, merged_id_sets, errors, warnings,
                )

            elif type_name == "Segment":
                self._check_ref(
                    obj_id, "Segment", "doc_id", data.get("doc_id"),
                    "Document", id_sets, merged_id_sets, errors, warnings,
                )

            elif type_name == "Entity":
                self._check_ref_list(
                    obj_id, "Entity", "source_segment_ids",
                    data.get("source_segment_ids", []),
                    "Segment", id_sets, merged_id_sets, errors, warnings,
                )
                # evidence_refs[].segment_id
                for eref in data.get("evidence_refs", []):
                    eref_data = self._unwrap_eref(eref)
                    self._check_ref(
                        obj_id, "Entity", "evidence_refs[].segment_id",
                        eref_data.get("segment_id"),
                        "Segment", id_sets, merged_id_sets, errors, warnings,
                    )

            elif type_name == "Event":
                self._check_ref_list(
                    obj_id, "Event", "participants",
                    data.get("participants", []),
                    "Entity", id_sets, merged_id_sets, errors, warnings,
                )
                self._check_ref_list(
                    obj_id, "Event", "source_segment_ids",
                    data.get("source_segment_ids", []),
                    "Segment", id_sets, merged_id_sets, errors, warnings,
                )
                for eref in data.get("evidence_refs", []):
                    eref_data = self._unwrap_eref(eref)
                    self._check_ref(
                        obj_id, "Event", "evidence_refs[].segment_id",
                        eref_data.get("segment_id"),
                        "Segment", id_sets, merged_id_sets, errors, warnings,
                    )

            elif type_name == "Claim":
                self._check_ref(
                    obj_id, "Claim", "subject", data.get("subject"),
                    "Entity", id_sets, merged_id_sets, errors, warnings,
                )
                # object: only validate if it looks like an entity ID
                obj_val = data.get("object")
                if obj_val and not self._is_symbol_marker(obj_val) and self._is_entity_id_style(str(obj_val)):
                    self._check_ref(
                        obj_id, "Claim", "object", str(obj_val),
                        "Entity", id_sets, merged_id_sets, errors, warnings,
                    )
                # D3: Detect self-referencing Claims (subject==object, both entity IDs)
                subj_val = data.get("subject")
                if (subj_val and obj_val
                    and not self._is_symbol_marker(subj_val)
                    and not self._is_symbol_marker(str(obj_val))
                    and subj_val == str(obj_val)
                    and self._is_entity_id_style(subj_val)):
                    errors.append(
                        f"Reference error in Claim ({obj_id}): "
                        f"self-referencing subject==object: '{subj_val}'"
                    )
                # source: Entity.id or Claim.id
                source_val = data.get("source")
                if source_val and not self._is_symbol_marker(source_val):
                    found_in_entity = source_val in merged_id_sets.get("Entity", set())
                    found_in_claim = source_val in merged_id_sets.get("Claim", set())
                    if not found_in_entity and not found_in_claim:
                        if "Entity" in id_sets or "Claim" in id_sets:
                            errors.append(
                                f"Reference error in Claim ({obj_id}): "
                                f"source '{source_val}' not found in Entity or Claim ids"
                            )
                        else:
                            warnings.append(
                                f"Reference warning in Claim ({obj_id}): "
                                f"source '{source_val}' not found (no Entity/Claim in current file)"
                            )
                self._check_ref_list(
                    obj_id, "Claim", "derived_from",
                    data.get("derived_from", []),
                    "Claim", id_sets, merged_id_sets, errors, warnings,
                )
                self._check_ref_list(
                    obj_id, "Claim", "source_segment_ids",
                    data.get("source_segment_ids", []),
                    "Segment", id_sets, merged_id_sets, errors, warnings,
                )
                for eref in data.get("evidence_refs", []):
                    eref_data = self._unwrap_eref(eref)
                    self._check_ref(
                        obj_id, "Claim", "evidence_refs[].segment_id",
                        eref_data.get("segment_id"),
                        "Segment", id_sets, merged_id_sets, errors, warnings,
                    )

            elif type_name == "Relation":
                self._check_ref(
                    obj_id, "Relation", "subject", data.get("subject"),
                    "Entity", id_sets, merged_id_sets, errors, warnings,
                )
                self._check_ref(
                    obj_id, "Relation", "object", data.get("object"),
                    "Entity", id_sets, merged_id_sets, errors, warnings,
                )
                self._check_ref(
                    obj_id, "Relation", "claim_id", data.get("claim_id"),
                    "Claim", id_sets, merged_id_sets, errors, warnings,
                )
                for eref in data.get("evidence_refs", []):
                    eref_data = self._unwrap_eref(eref)
                    self._check_ref(
                        obj_id, "Relation", "evidence_refs[].segment_id",
                        eref_data.get("segment_id"),
                        "Segment", id_sets, merged_id_sets, errors, warnings,
                    )

            elif type_name == "Residual":
                self._check_ref(
                    obj_id, "Residual", "segment_id", data.get("segment_id"),
                    "Segment", id_sets, merged_id_sets, errors, warnings,
                )
                for eref in data.get("evidence_refs", []):
                    eref_data = self._unwrap_eref(eref)
                    self._check_ref(
                        obj_id, "Residual", "evidence_refs[].segment_id",
                        eref_data.get("segment_id"),
                        "Segment", id_sets, merged_id_sets, errors, warnings,
                    )

            elif type_name == "IgnoreSegment":
                self._check_ref(
                    obj_id, "IgnoreSegment", "segment_id", data.get("segment_id"),
                    "Segment", id_sets, merged_id_sets, errors, warnings,
                )
                for eref in data.get("evidence_refs", []):
                    eref_data = self._unwrap_eref(eref)
                    self._check_ref(
                        obj_id, "IgnoreSegment", "evidence_refs[].segment_id",
                        eref_data.get("segment_id"),
                        "Segment", id_sets, merged_id_sets, errors, warnings,
                    )

        return errors, warnings

    @staticmethod
    def _is_entity_id_style(value: str) -> bool:
        """Check if a value looks like an Entity ID (contains '_ent_' prefix)."""
        return "_ent_" in value

    @staticmethod
    def _is_symbol_marker(value: object) -> bool:
        """Check if a value is a __symbol__ marker dict from the parser."""
        return isinstance(value, dict) and "__symbol__" in value

    @staticmethod
    def _unwrap_eref(eref: dict) -> dict:
        """Unwrap an evidence_ref entry from parser output.

        Parser may output either:
        - {"segment_id": "...", ...} (old format)
        - {"type": "EvidenceRef", "data": {"segment": {"__symbol__": "..."}, ...}} (new format)
        Returns the flat data dict.
        """
        if "type" in eref and "data" in eref:
            return eref["data"]
        return eref

    def _check_ref(
        self,
        obj_id: str,
        obj_type: str,
        field_name: str,
        ref_value: str | None,
        target_type: str,
        id_sets: dict[str, set[str]],
        merged_id_sets: dict[str, set[str]],
        errors: list[str],
        warnings: list[str],
    ) -> None:
        """Check a single reference value resolves to an existing object."""
        if ref_value is None:
            return

        # v3.3: skip __symbol__ markers — validated by _validate_symbol_references
        if self._is_symbol_marker(ref_value):
            return

        # Check merged index (local + external)
        if ref_value in merged_id_sets.get(target_type, set()):
            return

        # Not found in merged index
        if target_type in id_sets and id_sets[target_type]:
            # Target type objects exist locally — dangling ref is an error
            errors.append(
                f"Reference error in {obj_type} ({obj_id}): "
                f"{field_name} '{ref_value}' not found in {target_type} ids"
            )
        else:
            # No local objects of target type — may be cross-file reference
            warnings.append(
                f"Reference warning in {obj_type} ({obj_id}): "
                f"{field_name} '{ref_value}' not found in current {target_type} ids (may be external)"
            )

    def _check_ref_list(
        self,
        obj_id: str,
        obj_type: str,
        field_name: str,
        ref_values: list[str],
        target_type: str,
        id_sets: dict[str, set[str]],
        merged_id_sets: dict[str, set[str]],
        errors: list[str],
        warnings: list[str],
    ) -> None:
        """Check each value in a reference list."""
        for i, ref_val in enumerate(ref_values):
            self._check_ref(
                obj_id, obj_type, f"{field_name}[{i}]",
                ref_val, target_type, id_sets, merged_id_sets, errors, warnings,
            )

    # -- v3.3 Symbol reference validation — REMOVED in v6.0 (M1) -------------
    #
    # Generated packages now carry bare-Name references backed by real
    # imports, so dangling/mistyped symbol references fail at import time
    # (C10) and under Pyright (C8). The hand-rolled simulation of the import
    # system (`_validate_symbol_references`, `_build_symbol_type_map`,
    # `_get_symbol_ref_expected_type`, `_SYMBOL_REF_EXPECTED_TYPES`) is
    # deleted; pipeline-time FK reference checks above are retained as the
    # LLM-output quality gate.

    # -- Evidence validation ---------------------------------------------

    def _validate_evidence(self, objects: list[dict]) -> tuple[list[str], list[str]]:
        """Validate evidence references against raw text when available.

        Validates:
        - Block/Segment: text_slice hash, raw text offset replay
        - EvidenceRef: segment_id existence, start >= 0, end > start, end <= len(text_slice),
          sha256(segment.text_slice[start:end]) == quote_hash
        """
        errors: list[str] = []
        warnings: list[str] = []

        # Build segment text map for EvidenceRef validation
        seg_text_map: dict[str, str] = {}
        for obj in objects:
            if obj.get("type") == "Segment":
                data = obj.get("data", {})
                seg_id = data.get("id")
                text_slice = data.get("text_slice")
                if seg_id and text_slice:
                    seg_text_map[seg_id] = text_slice

        # Build id sets for EvidenceRef segment_id reference check
        id_sets = self._build_type_id_sets(objects)

        # Block/Segment hash and raw text replay validation
        for obj in objects:
            type_name = obj.get("type", "")
            data = obj.get("data", {})
            obj_id = data.get("id", "?")

            if type_name in ("Block", "Segment"):
                doc_id = data.get("doc_id")
                start = data.get("start_offset")
                end = data.get("end_offset")
                text_slice = data.get("text_slice")
                stored_hash = data.get("hash")

                if text_slice and stored_hash:
                    actual_hash = f"sha256:{hashlib.sha256(text_slice.encode('utf-8')).hexdigest()}"
                    if stored_hash != actual_hash:
                        errors.append(
                            f"Evidence error in {type_name} ({obj_id}): "
                            f"hash does not match text_slice content"
                        )

                if doc_id and doc_id in self._raw_text_store:
                    raw_text = self._raw_text_store[doc_id]
                    if start is not None and end is not None and text_slice:
                        actual_slice = raw_text[start:end]
                        if text_slice != actual_slice:
                            errors.append(
                                f"Evidence error in {type_name} ({obj_id}): "
                                f"text_slice does not match raw_text[{start}:{end}]"
                            )
                elif doc_id:
                    warnings.append(
                        f"Evidence warning in {type_name} ({obj_id}): "
                        f"raw text for doc_id '{doc_id}' not available for validation"
                    )

            # EvidenceRef validation for semantic objects
            if type_name in ("Entity", "Event", "Claim", "Relation", "Residual", "IgnoreSegment"):
                erefs = data.get("evidence_refs", [])
                for i, eref in enumerate(erefs):
                    seg_id = eref.get("segment_id")
                    start = eref.get("start")
                    end = eref.get("end")
                    quote_hash = eref.get("quote_hash")

                    # segment_id must exist
                    if seg_id and "Segment" in id_sets and seg_id not in id_sets["Segment"]:
                        errors.append(
                            f"Evidence error in {type_name} ({obj_id}): "
                            f"evidence_refs[{i}].segment_id '{seg_id}' not found in Segment ids"
                        )
                        continue  # Can't validate span/hash if segment doesn't exist

                    # Span and hash validation (only if segment text is available)
                    if seg_id and seg_id in seg_text_map:
                        seg_text = seg_text_map[seg_id]

                        # start >= 0
                        if start is not None and start < 0:
                            errors.append(
                                f"Evidence error in {type_name} ({obj_id}): "
                                f"evidence_refs[{i}].start={start} must be >= 0"
                            )

                        # end > start
                        if start is not None and end is not None and end <= start:
                            errors.append(
                                f"Evidence error in {type_name} ({obj_id}): "
                                f"evidence_refs[{i}].end={end} must be > start={start}"
                            )

                        # end <= len(text_slice)
                        if end is not None and end > len(seg_text):
                            errors.append(
                                f"Evidence error in {type_name} ({obj_id}): "
                                f"evidence_refs[{i}].end={end} exceeds segment text length {len(seg_text)}"
                            )

                        # Hash validation: sha256(segment.text_slice[start:end]) == quote_hash
                        if (
                            start is not None
                            and end is not None
                            and start >= 0
                            and end <= len(seg_text)
                            and end > start
                            and quote_hash
                        ):
                            actual_hash = f"sha256:{hashlib.sha256(seg_text[start:end].encode('utf-8')).hexdigest()}"
                            if actual_hash != quote_hash:
                                errors.append(
                                    f"Evidence error in {type_name} ({obj_id}): "
                                    f"evidence_refs[{i}] quote_hash mismatch for segment {seg_id}[{start}:{end}]"
                                )

            # v6.0 M3 evidence-presence gate: a Claim/Event without evidence
            # must not stand as fact — it degrades to Residual via the
            # repair loop. (inferred claims are backed by derived_from
            # instead of direct evidence.)
            if type_name in ("Claim", "Event"):
                if data.get("modality") == "inferred":
                    continue
                if not data.get("evidence_refs"):
                    errors.append(
                        f"Evidence error in {type_name} ({obj_id}): "
                        f"no evidence_refs — object must degrade to Residual "
                        f"rather than stand as fact"
                    )

        return errors, warnings

    # -- Claim Safety validation -----------------------------------------

    def _validate_claim_safety(self, objects: list[dict]) -> tuple[list[str], list[str]]:
        """Validate claim safety rules."""
        errors: list[str] = []
        warnings: list[str] = []

        claims_data = [obj for obj in objects if obj.get("type") == "Claim"]
        relations_data = [obj for obj in objects if obj.get("type") == "Relation"]

        claim_models, claim_violations = self._schema_validator.validate_and_construct(claims_data)
        for v in claim_violations:
            warnings.append(
                f"Schema warning in Claim ({v.object_id}): {v.field} — {v.message}"
            )

        relation_models, rel_violations = self._schema_validator.validate_and_construct(relations_data)
        for v in rel_violations:
            warnings.append(
                f"Schema warning in Relation ({v.object_id}): {v.field} — {v.message}"
            )

        if claim_models and relation_models:
            violations = self._claim_safety_validator.validate_claims(claim_models, relation_models)
            for v in violations:
                errors.append(
                    f"Claim safety error ({v.claim_id}): {v.rule} — {v.message}"
                )

        return errors, warnings