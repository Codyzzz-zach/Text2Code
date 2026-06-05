"""Tests for t2c/validator.py — v3.3 symbol reference validation."""
import hashlib

from t2c.validator import Validator, ValidationResult


def _sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _seg(sym: str, seg_id: str = "seg1", text: str = "hello world") -> dict:
    return {
        "type": "Segment",
        "symbol": sym,
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


def _entity(sym: str, ent_id: str = "ent1", name: str = "Test") -> dict:
    return {
        "type": "Entity",
        "symbol": sym,
        "data": {
            "id": ent_id,
            "name": name,
            "kind": "person",
        },
    }


def _claim(sym: str, clm_id: str = "clm1") -> dict:
    return {
        "type": "Claim",
        "symbol": sym,
        "data": {
            "id": clm_id,
            "subject": "ent1",
            "predicate": "lives_in",
            "object": "ent2",
            "modality": "asserted",
            "polarity": "positive",
        },
    }


class TestSymbolReferenceValidation:
    """v3.3: symbol ref type checking.

    The parser resolves symbol refs to string IDs in data.
    __symbol_refs__ metadata tracks which fields use symbol refs for codegen.
    The validator checks that each symbol ref's type matches the expected type.
    """

    def test_valid_evidence_ref_segment_symbol(self):
        """EvidenceRef.segment → Segment: valid case."""
        seg = _seg("seg_0001", "seg1")
        ent = {
            "type": "Entity",
            "symbol": "ent_test",
            "data": {
                "id": "ent1",
                "name": "Test",
                "kind": "person",
                "evidence_refs": [
                    {
                        "type": "EvidenceRef",
                        "data": {
                            "segment_id": "seg1",  # resolved ID from parser
                            "segment_symbol": "seg_0001",  # from parser mapping
                            "start": 0,
                            "end": 3,
                            "quote_hash": _sha256("hel"),
                        },
                    }
                ],
            },
            "__symbol_refs__": {"evidence_refs[0].segment": "seg_0001"},
        }
        v = Validator()
        result = v.validate_objects([seg, ent])
        assert result.valid, f"Errors: {result.errors}"

    def test_evidence_ref_segment_wrong_type(self):
        """EvidenceRef.segment → entity symbol should fail."""
        ent_wrong = _entity("ent_wrong", "ent1", "Alice")
        ent = {
            "type": "Entity",
            "symbol": "ent_bob",
            "data": {
                "id": "ent2",
                "name": "Bob",
                "kind": "person",
                "evidence_refs": [
                    {
                        "type": "EvidenceRef",
                        "data": {
                            "segment_id": "ent1",  # resolved ID — but it's an Entity!
                            "segment_symbol": "ent_wrong",
                            "start": 0,
                            "end": 3,
                            "quote_hash": _sha256("hel"),
                        },
                    }
                ],
            },
            "__symbol_refs__": {"evidence_refs[0].segment": "ent_wrong"},
        }
        v = Validator()
        result = v.validate_objects([ent_wrong, ent])
        # The symbol ref type check MUST catch this
        assert not result.valid, f"Expected validation failure, got errors: {result.errors}"
        assert any("expected Segment" in e for e in result.errors), f"Wrong error: {result.errors}"

    def test_claim_subject_symbol_valid(self):
        """Claim.subject → Entity: valid case."""
        ent = _entity("ent_zhen", "ent1", "甄士隐")
        claim = {
            "type": "Claim",
            "symbol": "claim_zhen",
            "data": {
                "id": "clm1",
                "subject": "ent1",  # resolved ID
                "predicate": "lives_in",
                "object": "姑苏",
                "modality": "asserted",
                "polarity": "positive",
            },
            "__symbol_refs__": {"subject": "ent_zhen"},
        }
        v = Validator()
        result = v.validate_objects([ent, claim])
        assert result.valid, f"Errors: {result.errors}"

    def test_claim_subject_symbol_wrong_type(self):
        """Claim.subject → segment symbol should fail."""
        seg = _seg("seg_0001", "seg1")
        claim = {
            "type": "Claim",
            "symbol": "claim_1",
            "data": {
                "id": "clm1",
                "subject": "seg1",  # resolved ID — but it's a Segment!
                "predicate": "lives_in",
                "object": "姑苏",
                "modality": "asserted",
                "polarity": "positive",
            },
            "__symbol_refs__": {"subject": "seg_0001"},
        }
        v = Validator()
        result = v.validate_objects([seg, claim])
        # The symbol ref type check MUST catch this
        assert not result.valid, f"Expected validation failure, got errors: {result.errors}"
        assert any("expected Entity" in e for e in result.errors), f"Wrong error: {result.errors}"

    def test_event_participant_symbol_valid(self):
        """Event.participants → Entity: valid case."""
        ent = _entity("ent_alice", "ent1", "Alice")
        evt = {
            "type": "Event",
            "symbol": "evt_meeting",
            "data": {
                "id": "evt1",
                "name": "Meeting",
                "kind": "occurrence",
                "participants": ["ent1"],  # resolved ID
            },
            "__symbol_refs__": {"participants[0]": "ent_alice"},
        }
        v = Validator()
        result = v.validate_objects([ent, evt])
        assert result.valid, f"Errors: {result.errors}"

    def test_event_participant_wrong_type(self):
        """Event.participants → segment symbol should fail."""
        seg = _seg("seg_0001", "seg1")
        evt = {
            "type": "Event",
            "symbol": "evt_1",
            "data": {
                "id": "evt1",
                "name": "Meeting",
                "kind": "occurrence",
                "participants": ["seg1"],  # resolved ID — but it's a Segment!
            },
            "__symbol_refs__": {"participants[0]": "seg_0001"},
        }
        v = Validator()
        result = v.validate_objects([seg, evt])
        assert not result.valid, f"Expected validation failure, got errors: {result.errors}"
        assert any("expected Entity" in e for e in result.errors), f"Wrong error: {result.errors}"

    def test_undefined_symbol_ref(self):
        """Symbol ref to undefined symbol should fail."""
        ent = {
            "type": "Entity",
            "symbol": "ent_test",
            "data": {
                "id": "ent1",
                "name": "Test",
                "kind": "person",
            },
            "__symbol_refs__": {"evidence_refs[0].segment": "missing_seg"},
        }
        v = Validator()
        result = v.validate_objects([ent])
        assert not result.valid
        assert any("not defined" in e for e in result.errors)

    def test_relation_subject_symbol(self):
        """Relation.subject → Entity symbol ref."""
        ent_a = _entity("ent_a", "ent1", "Alice")
        ent_b = _entity("ent_b", "ent2", "Bob")
        rel = {
            "type": "Relation",
            "symbol": "rel_1",
            "data": {
                "id": "rel1",
                "subject": "ent1",  # resolved ID
                "predicate": "lives_in",
                "object": "ent2",
                "claim_id": "clm1",
            },
            "__symbol_refs__": {"subject": "ent_a"},
        }
        v = Validator()
        result = v.validate_objects([ent_a, ent_b, rel])
        assert result.valid, f"Errors: {result.errors}"


class TestSymbolValidationBackwardCompat:
    """Symbol ref validation doesn't break old-format validation."""

    def test_old_format_no_symbol_refs(self):
        """Objects without symbol or __symbol_refs__ should validate fine."""
        objects = [
            {
                "type": "Segment",
                "data": {
                    "id": "seg1",
                    "doc_id": "doc1",
                    "block_index": 0,
                    "segment_type": "sentence",
                    "start_offset": 0,
                    "end_offset": 5,
                    "text_slice": "hello",
                    "hash": _sha256("hello"),
                },
            },
            {
                "type": "Entity",
                "data": {
                    "id": "ent1",
                    "name": "Test",
                    "kind": "person",
                },
            },
        ]
        v = Validator()
        result = v.validate_objects(objects)
        assert result.valid
