"""Tests for t2c/validator.py — v3.3 Validation Hardening.

Covers:
- Full reference validation (dangling refs for all object types)
- EvidenceRef span/hash validation
- Segment hash and raw text replay validation
- Claim safety integration
- Backward compatibility (validate_string, validate_objects)
- Full pytest collection without anthropic installed
"""
import hashlib
from pathlib import Path

import pytest

from t2c.ontology import (
    Block,
    Claim,
    Document,
    Entity,
    EvidenceRef,
    Event,
    IgnoreSegment,
    Relation,
    Residual,
    Segment,
)
from t2c.validator import Validator, ValidationResult


def _sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── Helpers ──

def _doc() -> dict:
    return {
        "type": "Document",
        "data": {
            "id": "doc1",
            "source_path": "test.txt",
            "raw_text_hash": _sha256("raw text"),
            "total_length": 100,
            "block_count": 1,
            "created_at": "2026-06-01T00:00:00Z",
        },
    }


def _seg(seg_id: str = "seg1", text: str = "甄士隐住在姑苏城中。") -> dict:
    return {
        "type": "Segment",
        "data": {
            "id": seg_id,
            "doc_id": "doc1",
            "block_index": 0,
            "segment_type": "sentence",
            "start_offset": 0,
            "end_offset": len(text),
            "text_slice": text,
            "hash": _sha256(text),
        },
    }


def _entity(ent_id: str = "ent1", name: str = "甄士隐", seg_ids: list[str] | None = None) -> dict:
    return {
        "type": "Entity",
        "data": {
            "id": ent_id,
            "name": name,
            "kind": "person",
            "aliases": [],
            "source_segment_ids": seg_ids or ["seg1"],
        },
    }


def _event(evt_id: str = "evt1", participants: list[str] | None = None, seg_ids: list[str] | None = None) -> dict:
    return {
        "type": "Event",
        "data": {
            "id": evt_id,
            "name": "事件",
            "kind": "occurrence",
            "participants": participants or ["ent1"],
            "source_segment_ids": seg_ids or ["seg1"],
            # v6.0 M3 evidence gate: Claim/Event must carry evidence
            "evidence_refs": [_evidence()],
        },
    }


def _evidence() -> dict:
    # matches _seg()'s default text "甄士隐住在姑苏城中。"[0:3]
    return {"segment_id": "seg1", "start": 0, "end": 3, "quote_hash": _sha256("甄士隐")}


def _claim(clm_id: str = "clm1", subject: str = "ent1", obj: str = "ent2", seg_ids: list[str] | None = None) -> dict:
    return {
        "type": "Claim",
        "data": {
            "id": clm_id,
            "subject": subject,
            "predicate": "lives_in",
            "object": obj,
            "modality": "asserted",
            "polarity": "positive",
            "source_segment_ids": seg_ids or ["seg1"],
            "evidence_refs": [_evidence()],
        },
    }


def _relation(rel_id: str = "rel1", subject: str = "ent1", obj: str = "ent2", claim_id: str = "clm1") -> dict:
    return {
        "type": "Relation",
        "data": {
            "id": rel_id,
            "subject": subject,
            "predicate": "lives_in",
            "object": obj,
            "claim_id": claim_id,
        },
    }


def _base_objects() -> list[dict]:
    return [_doc(), _seg(), _entity("ent1", "甄士隐"), _entity("ent2", "姑苏"), _claim(), _relation()]


def _validate(objects: list[dict], raw_text_store: dict[str, str] | None = None) -> ValidationResult:
    v = Validator(raw_text_store=raw_text_store)
    return v.validate_objects(objects)


# ═══════════════════════════════════════════════════════════════════
# Reference validation tests
# ═══════════════════════════════════════════════════════════════════


class TestDanglingReferences:
    """Dangling references should be errors (not warnings) when the target type exists locally."""

    def test_dangling_entity_source_segment_ids(self):
        """Entity references a segment that doesn't exist — error because Segments exist locally."""
        objects = [_doc(), _seg(), _entity("ent1", "甄士隐", seg_ids=["missing_seg"])]
        result = _validate(objects)
        assert not result.valid
        assert any("source_segment_ids" in e and "missing_seg" in e for e in result.errors)

    def test_dangling_entity_evidence_refs_segment_id(self):
        objects = [_doc(), _seg(), _entity("ent1", "甄士隐", seg_ids=["seg1"])]
        objects[-1]["data"]["evidence_refs"] = [{"segment_id": "missing_seg", "start": 0, "end": 3, "quote_hash": _sha256("abc")}]
        result = _validate(objects)
        assert not result.valid
        assert any("evidence_refs" in e and "missing_seg" in e for e in result.errors)

    def test_dangling_event_participants(self):
        """Event references an entity that doesn't exist — error because Entities exist locally."""
        objects = [_doc(), _seg(), _entity("ent1", "甄士隐"), _event("evt1", participants=["missing_ent"])]
        result = _validate(objects)
        assert not result.valid
        assert any("participants" in e and "missing_ent" in e for e in result.errors)

    def test_dangling_event_source_segment_ids(self):
        objects = [_doc(), _seg(), _entity("ent1", "甄士隐"), _event("evt1", participants=["ent1"], seg_ids=["missing_seg"])]
        result = _validate(objects)
        assert not result.valid
        assert any("source_segment_ids" in e and "missing_seg" in e for e in result.errors)

    def test_dangling_claim_subject(self):
        objects = [_doc(), _seg(), _entity("ent2", "姑苏"), _claim("clm1", subject="missing_ent")]
        result = _validate(objects)
        assert not result.valid
        assert any("subject" in e and "missing_ent" in e for e in result.errors)

    def test_dangling_claim_object_entity_style(self):
        """When Claim.object looks like an entity ID (_ent_ prefix), validate it."""
        objects = [_doc(), _seg(), _entity("ent1", "甄士隐"), _claim("clm1", obj="doc_ent_missing")]
        result = _validate(objects)
        assert not result.valid
        assert any("object" in e and "doc_ent_missing" in e for e in result.errors)

    def test_claim_object_literal_not_validated(self):
        """When Claim.object is a literal (not entity ID style), it should not cause a ref error."""
        objects = [_doc(), _seg(), _entity("ent1", "甄士隐"), _claim("clm1", obj="姑苏城")]
        result = _validate(objects)
        # Should be valid — "姑苏城" is a literal object, not a dangling entity ref
        assert result.valid or not any("object" in e for e in result.errors)

    def test_dangling_relation_claim_id(self):
        """Relation references a claim that doesn't exist — error because Claims exist locally."""
        objects = [_doc(), _seg(), _entity("ent1", "甄士隐"), _entity("ent2", "姑苏"), _claim(), _relation(claim_id="missing_clm")]
        result = _validate(objects)
        assert not result.valid
        assert any("claim_id" in e and "missing_clm" in e for e in result.errors)

    def test_dangling_relation_subject(self):
        objects = [_doc(), _seg(), _entity("ent2", "姑苏"), _claim(), _relation(subject="missing_ent")]
        result = _validate(objects)
        assert not result.valid
        assert any("subject" in e and "missing_ent" in e for e in result.errors)

    def test_dangling_relation_object(self):
        objects = [_doc(), _seg(), _entity("ent1", "甄士隐"), _claim(), _relation(obj="missing_ent")]
        result = _validate(objects)
        assert not result.valid
        assert any("object" in e and "missing_ent" in e for e in result.errors)

    def test_dangling_residual_segment_id(self):
        objects = [_doc(), _seg(), {"type": "Residual", "data": {"id": "res1", "segment_id": "missing_seg", "category": "structural", "importance": "high", "reason": "test"}}]
        result = _validate(objects)
        assert not result.valid
        assert any("segment_id" in e and "missing_seg" in e for e in result.errors)

    def test_dangling_ignore_segment_segment_id(self):
        objects = [_doc(), _seg(), {"type": "IgnoreSegment", "data": {"id": "ign1", "segment_id": "missing_seg", "reason": "页码"}}]
        result = _validate(objects)
        assert not result.valid
        assert any("segment_id" in e and "missing_seg" in e for e in result.errors)

    def test_dangling_claim_source(self):
        """Claim.source should resolve to Entity or Claim."""
        objects = [_doc(), _seg(), _entity("ent1", "甄士隐"), _entity("ent2", "姑苏"), _claim()]
        objects[-1]["data"]["source"] = "missing_id"
        result = _validate(objects)
        assert not result.valid
        assert any("source" in e and "missing_id" in e for e in result.errors)

    def test_dangling_claim_derived_from(self):
        objects = [_doc(), _seg(), _entity("ent1", "甄士隐"), _entity("ent2", "姑苏"), _claim()]
        objects[-1]["data"]["derived_from"] = ["missing_clm"]
        result = _validate(objects)
        assert not result.valid
        assert any("derived_from" in e and "missing_clm" in e for e in result.errors)

    def test_dangling_block_doc_id(self):
        """Block references a doc that doesn't exist — warning since no Document in current set."""
        objects = [{"type": "Block", "data": {"id": "blk1", "doc_id": "missing_doc", "index": 0, "block_type": "paragraph", "start_offset": 0, "end_offset": 10, "text_slice": "text", "hash": _sha256("text")}}]
        result = _validate(objects)
        assert any("doc_id" in w and "missing_doc" in w for w in result.warnings)

    def test_dangling_segment_doc_id(self):
        """Segment references a doc that doesn't exist — warning since no Document in current set."""
        objects = [_seg()]
        result = _validate(objects)
        assert any("doc_id" in w and "doc1" in w for w in result.warnings)

    def test_dangling_block_doc_id_with_local_document_is_error(self):
        """Block references a doc that doesn't exist — error because Document exists locally."""
        objects = [_doc(), {"type": "Block", "data": {"id": "blk1", "doc_id": "missing_doc", "index": 0, "block_type": "paragraph", "start_offset": 0, "end_offset": 10, "text_slice": "text", "hash": _sha256("text")}}]
        result = _validate(objects)
        assert not result.valid
        assert any("doc_id" in e and "missing_doc" in e for e in result.errors)


class TestCrossFileReferenceTolerance:
    """When target type doesn't exist locally, dangling refs should be warnings (not errors)."""

    def test_entity_ref_no_segments_is_warning(self):
        """If no Segments in current file, entity source_segment_ids should be warning."""
        objects = [_doc(), _entity("ent1", "甄士隐", seg_ids=["external_seg"])]
        result = _validate(objects)
        assert result.valid  # warnings don't invalidate
        assert any("source_segment_ids" in w for w in result.warnings)

    def test_event_ref_no_entities_is_warning(self):
        objects = [_doc(), _seg(), _event("evt1", participants=["external_ent"])]
        result = _validate(objects)
        assert result.valid
        assert any("participants" in w for w in result.warnings)

    def test_external_index_resolves_cross_file_refs(self):
        """external_index should resolve cross-file references."""
        v = Validator(external_index={"Entity": {"ext_ent1"}, "Segment": {"ext_seg1"}})
        objects = [_entity("ent1", "甄士隐", seg_ids=["ext_seg1"])]
        result = v.validate_objects(objects)
        assert result.valid
        assert not any("source_segment_ids" in e for e in result.errors)


# ═══════════════════════════════════════════════════════════════════
# EvidenceRef span/hash validation tests
# ═══════════════════════════════════════════════════════════════════


class TestEvidenceRefSpanHash:
    """Validate EvidenceRef span boundaries and hash against segment text."""

    def _make_entity_with_eref(self, seg_text: str, start: int, end: int, quote_hash: str | None = None) -> list[dict]:
        seg = _seg("seg1", seg_text)
        if quote_hash is None:
            quote_hash = _sha256(seg_text[start:end])
        entity = _entity("ent1", "甄士隐", seg_ids=["seg1"])
        entity["data"]["evidence_refs"] = [
            {"segment_id": "seg1", "start": start, "end": end, "quote_hash": quote_hash}
        ]
        return [_doc(), seg, entity]

    def test_valid_evidence_ref_passes(self):
        objects = self._make_entity_with_eref("甄士隐住在姑苏。", 0, 3)
        result = _validate(objects)
        assert result.valid

    def test_evidence_ref_start_negative(self):
        objects = self._make_entity_with_eref("甄士隐住在姑苏。", -1, 3)
        result = _validate(objects)
        assert not result.valid
        assert any("start" in e and "must be >= 0" in e for e in result.errors)

    def test_evidence_ref_end_before_start(self):
        objects = self._make_entity_with_eref("甄士隐住在姑苏。", 5, 3)
        result = _validate(objects)
        assert not result.valid
        assert any("end" in e and "must be > start" in e for e in result.errors)

    def test_evidence_ref_end_exceeds_segment_length(self):
        objects = self._make_entity_with_eref("甄士隐住在姑苏。", 0, 999)
        result = _validate(objects)
        assert not result.valid
        assert any("exceeds segment text length" in e for e in result.errors)

    def test_evidence_ref_quote_hash_mismatch(self):
        objects = self._make_entity_with_eref("甄士隐住在姑苏。", 0, 3, quote_hash="sha256:badhash")
        result = _validate(objects)
        assert not result.valid
        assert any("quote_hash mismatch" in e for e in result.errors)

    def test_evidence_ref_tampered_start(self):
        """Changing start should cause hash mismatch."""
        objects = self._make_entity_with_eref("甄士隐住在姑苏。", 0, 3)
        objects[-1]["data"]["evidence_refs"][0]["start"] = 1
        result = _validate(objects)
        assert not result.valid
        assert any("quote_hash mismatch" in e for e in result.errors)

    def test_evidence_ref_tampered_end(self):
        """Changing end should cause hash mismatch."""
        objects = self._make_entity_with_eref("甄士隐住在姑苏。", 0, 3)
        objects[-1]["data"]["evidence_refs"][0]["end"] = 4
        result = _validate(objects)
        assert not result.valid
        assert any("quote_hash mismatch" in e for e in result.errors)

    def test_dangling_evidence_ref_segment_id(self):
        objects = [_doc(), _seg(), _entity("ent1", "甄士隐", seg_ids=["seg1"])]
        objects[-1]["data"]["evidence_refs"] = [
            {"segment_id": "missing_seg", "start": 0, "end": 3, "quote_hash": _sha256("abc")}
        ]
        result = _validate(objects)
        assert not result.valid
        assert any("missing_seg" in e and ("segment_id" in e or "evidence" in e) for e in result.errors)

    def test_evidence_ref_on_claim(self):
        """EvidenceRef validation works on Claim objects too."""
        seg = _seg("seg1", "甄士隐住在姑苏。")
        claim = _claim("clm1", seg_ids=["seg1"])
        claim["data"]["evidence_refs"] = [
            {"segment_id": "seg1", "start": 0, "end": 3, "quote_hash": _sha256("甄士隐住在姑苏。"[:3])}
        ]
        objects = [_doc(), seg, _entity("ent1", "甄士隐"), _entity("ent2", "姑苏"), claim, _relation()]
        result = _validate(objects)
        assert result.valid

    def test_evidence_ref_on_relation(self):
        seg = _seg("seg1", "甄士隐住在姑苏。")
        rel = _relation()
        rel["data"]["evidence_refs"] = [
            {"segment_id": "seg1", "start": 0, "end": 3, "quote_hash": "sha256:bad"}
        ]
        objects = [_doc(), seg, _entity("ent1", "甄士隐"), _entity("ent2", "姑苏"), _claim(), rel]
        result = _validate(objects)
        assert not result.valid
        assert any("quote_hash mismatch" in e for e in result.errors)

    def test_evidence_ref_on_residual(self):
        seg = _seg("seg1", "重要残余信息。")
        res = {"type": "Residual", "data": {"id": "res1", "segment_id": "seg1", "category": "structural", "importance": "high", "reason": "test"}}
        res["data"]["evidence_refs"] = [
            {"segment_id": "seg1", "start": 0, "end": 3, "quote_hash": _sha256("重要残余信息。"[:3])}
        ]
        objects = [_doc(), seg, res]
        result = _validate(objects)
        assert result.valid

    def test_evidence_ref_on_ignore_segment(self):
        seg = _seg("seg1", "第1页")
        ign = {"type": "IgnoreSegment", "data": {"id": "ign1", "segment_id": "seg1", "reason": "页码"}}
        ign["data"]["evidence_refs"] = [
            {"segment_id": "seg1", "start": 0, "end": 3, "quote_hash": "sha256:bad"}
        ]
        objects = [_doc(), seg, ign]
        result = _validate(objects)
        assert not result.valid
        assert any("quote_hash mismatch" in e for e in result.errors)


# ═══════════════════════════════════════════════════════════════════
# Segment hash and raw text replay tests
# ═══════════════════════════════════════════════════════════════════


class TestSegmentHashValidation:
    """Segment hash must match text_slice content."""

    def test_valid_segment_hash(self):
        objects = [_doc(), _seg()]
        result = _validate(objects)
        assert result.valid or not any("hash" in e.lower() and "Segment" in e for e in result.errors)

    def test_tampered_segment_hash(self):
        seg = _seg()
        seg["data"]["hash"] = "sha256:tampered"
        objects = [_doc(), seg]
        result = _validate(objects)
        assert not result.valid
        assert any("hash" in e and ("Segment" in e or "mismatch" in e) for e in result.errors)

    def test_segment_raw_text_replay(self):
        """When raw_text_store is available, segment text_slice must match raw text at offsets."""
        raw_text = "甄士隐住在姑苏城中。"
        seg = _seg("seg1", raw_text)
        seg["data"]["start_offset"] = 0
        seg["data"]["end_offset"] = len(raw_text)
        objects = [_doc(), seg]
        result = _validate(objects, raw_text_store={"doc1": raw_text})
        assert result.valid

    def test_segment_raw_text_replay_mismatch(self):
        """Segment text_slice doesn't match raw text at given offsets."""
        raw_text = "甄士隐住在姑苏城中。"
        seg = _seg("seg1", "不同文本")
        seg["data"]["start_offset"] = 0
        seg["data"]["end_offset"] = len(raw_text)
        seg["data"]["hash"] = _sha256("不同文本")
        objects = [_doc(), seg]
        result = _validate(objects, raw_text_store={"doc1": raw_text})
        assert not result.valid
        assert any("text_slice" in e and "raw" in e for e in result.errors)

    def test_segment_no_raw_text_is_warning(self):
        """When raw_text_store doesn't have the doc_id, it's a warning not an error."""
        seg = _seg("seg1", "文本")
        seg["data"]["start_offset"] = 0
        seg["data"]["end_offset"] = 2
        seg["data"]["hash"] = _sha256("文本")
        objects = [_doc(), seg]
        result = _validate(objects, raw_text_store={})
        assert any("raw text" in w.lower() for w in result.warnings)


# ═══════════════════════════════════════════════════════════════════
# Backward compatibility tests
# ═══════════════════════════════════════════════════════════════════


class TestValidatorBackwardCompat:
    """Ensure the Validator API is backward compatible."""

    def test_validate_string_valid_code(self):
        code = '''
from t2c.ontology import Document, Segment, Entity

Document(id="doc1", source_path="test.txt", raw_text_hash=_sha256("raw text"), total_length=100, block_count=1, created_at="2026-06-01T00:00:00Z")
Segment(id="seg1", doc_id="doc1", block_index=0, segment_type="sentence", start_offset=0, end_offset=5, text_slice="hello", hash="sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824")
Entity(id="ent1", name="Test", kind="person", aliases=[], source_segment_ids=["seg1"])
'''
        v = Validator()
        result = v.validate_string(code)
        assert isinstance(result, ValidationResult)
        assert isinstance(result.valid, bool)
        assert isinstance(result.errors, list)
        assert isinstance(result.warnings, list)

    def test_validate_objects_returns_validation_result(self):
        result = _validate(_base_objects())
        assert isinstance(result, ValidationResult)

    def test_validation_result_fields(self):
        result = ValidationResult(valid=True, errors=[], warnings=[])
        assert result.valid is True
        assert result.errors == []
        assert result.warnings == []

    def test_base_objects_are_valid(self):
        """A well-formed set of objects should validate successfully."""
        result = _validate(_base_objects())
        assert result.valid


class TestClaimSourceValidation:
    """Claim.source can reference Entity.id or Claim.id."""

    def test_claim_source_entity_id(self):
        objects = _base_objects()
        objects[-2]["data"]["source"] = "ent1"
        result = _validate(objects)
        assert result.valid or not any("source" in e for e in result.errors)

    def test_claim_source_claim_id(self):
        objects = _base_objects()
        objects[-2]["data"]["source"] = "clm1"
        result = _validate(objects)
        assert result.valid or not any("source" in e for e in result.errors)

    def test_claim_source_nonexistent_is_error(self):
        objects = _base_objects()
        objects[-2]["data"]["source"] = "nonexistent"
        result = _validate(objects)
        assert not result.valid
        assert any("source" in e and "nonexistent" in e for e in result.errors)
