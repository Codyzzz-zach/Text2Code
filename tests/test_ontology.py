"""Tests for t2c/ontology.py — core object models."""
from t2c.ontology import (
    Block,
    Claim,
    CoverageReport,
    Document,
    Entity,
    Event,
    EvidenceRef,
    IgnoreSegment,
    ONTOLOGY_CLASSES,
    Relation,
    Residual,
    Segment,
)


class TestEvidenceRef:
    def test_create(self):
        ref = EvidenceRef(segment_id="case_001_seg_0001", start=0, end=5, quote_hash="sha256:abc")
        assert ref.segment_id == "case_001_seg_0001"
        assert ref.start == 0
        assert ref.end == 5

    def test_serialization(self):
        ref = EvidenceRef(segment_id="s1", start=0, end=10, quote_hash="sha256:abc")
        d = ref.model_dump()
        restored = EvidenceRef.model_validate(d)
        assert restored == ref


class TestDocument:
    def test_create(self):
        doc = Document(
            id="case_001",
            source_path="case_001.txt",
            raw_text_hash="sha256:abc",
            total_length=100,
            block_count=3,
            created_at="2026-05-27T10:00:00Z",
        )
        assert doc.id == "case_001"
        assert doc.block_count == 3

    def test_missing_field_raises(self):
        import pytest
        with pytest.raises(Exception):
            Document(id="x")  # missing required fields


class TestBlock:
    def test_create(self):
        b = Block(
            id="case_001_blk_0000",
            doc_id="case_001", index=0, block_type="paragraph",
            start_offset=0, end_offset=50, text_slice="Hello", hash="sha256:abc",
        )
        assert b.block_type == "paragraph"

    def test_invalid_block_type(self):
        import pytest
        with pytest.raises(Exception):
            Block(
                id="case_001_blk_0000",
                doc_id="case_001", index=0, block_type="invalid_type",
                start_offset=0, end_offset=50, text_slice="Hello", hash="sha256:abc",
            )


class TestSegment:
    def test_create(self):
        seg = Segment(
            id="case_001_seg_0001",
            doc_id="case_001",
            block_index=0,
            segment_type="sentence",
            start_offset=0,
            end_offset=10,
            text_slice="Hello world",
            hash="sha256:def",
        )
        assert seg.segment_type == "sentence"

    def test_invalid_segment_type(self):
        import pytest
        with pytest.raises(Exception):
            Segment(
                id="s1", doc_id="d1", block_index=0, segment_type="invalid",
                start_offset=0, end_offset=5, text_slice="Hi", hash="sha256:x",
            )


class TestSemanticObjects:
    def test_entity_with_evidence(self):
        ev = EvidenceRef(segment_id="s1", start=0, end=5, quote_hash="sha256:abc")
        e = Entity(id="e1", name="Alice", kind="person", evidence_refs=[ev])
        assert len(e.evidence_refs) == 1

    def test_claim_modality(self):
        c = Claim(id="c1", subject="Alice", predicate="waited", modality="asserted", polarity="positive")
        assert c.modality == "asserted"

    def test_relation(self):
        r = Relation(id="r1", subject="e1", predicate="met", object="e2", claim_id="c1")
        assert r.claim_id == "c1"

    def test_inferred_claim_requires_derived_from(self):
        # derived_from is optional (empty list), but semantically inferred claims should have it
        c = Claim(id="c2", subject="Bob", predicate="knows", modality="inferred", polarity="positive", derived_from=["c1"])
        assert len(c.derived_from) == 1


class TestNearLosslessObjects:
    def test_residual(self):
        ev = EvidenceRef(segment_id="s1", start=0, end=5, quote_hash="sha256:x")
        r = Residual(id="r1", segment_id="s1", category="pragmatic", importance="high", reason="implied threat", evidence_refs=[ev])
        assert r.importance == "high"

    def test_ignore_segment(self):
        ig = IgnoreSegment(id="ig1", segment_id="s1", reason="boilerplate")
        assert ig.reason == "boilerplate"

    def test_coverage_report(self):
        cr = CoverageReport(
            id="d1_coverage",
            doc_id="d1", total_segments=10,
            status_counts={"covered": 5, "partial": 2, "raw_only": 1, "ignored": 1, "uncovered": 1},
            requires_raw_fallback=["s3"],
            generated_at="2026-05-27T10:00:00Z",
        )
        assert cr.total_segments == 10


class TestOntologyRegistry:
    def test_all_types_registered(self):
        expected = {"EvidenceRef", "Document", "Block", "Segment", "Entity", "Event",
                    "Claim", "Relation", "Residual", "IgnoreSegment", "CoverageReport"}
        assert set(ONTOLOGY_CLASSES.keys()) == expected

    def test_registry_maps_to_classes(self):
        assert ONTOLOGY_CLASSES["Document"] is Document
        assert ONTOLOGY_CLASSES["Entity"] is Entity