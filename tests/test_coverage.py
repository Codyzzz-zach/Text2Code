"""Tests for t2c/coverage.py — coverage auto-derivation."""
import pytest

from t2c.coverage import CoverageGenerator
from t2c.object_store import ObjectStore
from t2c.ontology import (
    Document, Entity, IgnoreSegment, Residual, Segment,
)


@pytest.fixture
def store():
    s = ObjectStore()
    yield s
    s.close()


def _setup_doc(store, doc_id="doc1"):
    doc = Document(
        id=doc_id, source_path="test.txt",
        raw_text_hash="sha256:abc", total_length=100,
        block_count=1, created_at="2026-05-27T10:00:00Z",
    )
    store.save(doc)
    for i in range(5):
        seg = Segment(
            id=f"{doc_id}_seg_{i:04d}", doc_id=doc_id,
            block_index=0, segment_type="sentence",
            start_offset=i * 20, end_offset=(i + 1) * 20,
            text_slice="text " * 4, hash="sha256:abc",
        )
        store.save(seg)


class TestCoverageStatus:
    def test_covered_segment(self, store):
        _setup_doc(store)
        ent = Entity(
            id="e1", name="Alice", kind="person",
            source_segment_ids=["doc1_seg_0000"],
        )
        store.save(ent)

        gen = CoverageGenerator(store)
        report = gen.generate_coverage("doc1")
        assert report.status_counts["covered"] == 1
        assert report.status_counts["uncovered"] == 4

    def test_partial_segment(self, store):
        _setup_doc(store)
        ent = Entity(
            id="e1", name="Alice", kind="person",
            source_segment_ids=["doc1_seg_0000"],
        )
        store.save(ent)
        res = Residual(
            id="doc1_res_0001", segment_id="doc1_seg_0000",
            category="stylistic", importance="medium",
            reason="minor style",
        )
        store.save(res)

        gen = CoverageGenerator(store)
        report = gen.generate_coverage("doc1")
        assert report.status_counts["partial"] == 1

    def test_raw_only_segment(self, store):
        _setup_doc(store)
        res = Residual(
            id="doc1_res_0001", segment_id="doc1_seg_0001",
            category="modal", importance="medium",
            reason="modal nuance",
        )
        store.save(res)

        gen = CoverageGenerator(store)
        report = gen.generate_coverage("doc1")
        assert report.status_counts["raw_only"] == 1

    def test_ignored_segment(self, store):
        _setup_doc(store)
        ign = IgnoreSegment(
            id="doc1_ign_0001", segment_id="doc1_seg_0002",
            reason="boilerplate",
        )
        store.save(ign)

        gen = CoverageGenerator(store)
        report = gen.generate_coverage("doc1")
        assert report.status_counts["ignored"] == 1

    def test_uncovered_segment(self, store):
        _setup_doc(store)
        gen = CoverageGenerator(store)
        report = gen.generate_coverage("doc1")
        assert report.status_counts["uncovered"] == 5


class TestRawFallback:
    def test_partial_triggers_fallback(self, store):
        _setup_doc(store)
        ent = Entity(
            id="e1", name="Alice", kind="person",
            source_segment_ids=["doc1_seg_0000"],
        )
        store.save(ent)
        res = Residual(
            id="doc1_res_0001", segment_id="doc1_seg_0000",
            category="stylistic", importance="medium",
            reason="minor style",
        )
        store.save(res)

        gen = CoverageGenerator(store)
        report = gen.generate_coverage("doc1")
        assert "doc1_seg_0000" in report.requires_raw_fallback

    def test_high_residual_triggers_fallback(self, store):
        _setup_doc(store)
        ent = Entity(
            id="e1", name="Alice", kind="person",
            source_segment_ids=["doc1_seg_0000"],
        )
        store.save(ent)
        res = Residual(
            id="doc1_res_0001", segment_id="doc1_seg_0000",
            category="pragmatic", importance="high",
            reason="critical nuance",
        )
        store.save(res)

        gen = CoverageGenerator(store)
        report = gen.generate_coverage("doc1")
        assert "doc1_seg_0000" in report.requires_raw_fallback

    def test_covered_no_residual_no_fallback(self, store):
        _setup_doc(store)
        ent = Entity(
            id="e1", name="Alice", kind="person",
            source_segment_ids=["doc1_seg_0000"],
        )
        store.save(ent)

        gen = CoverageGenerator(store)
        report = gen.generate_coverage("doc1")
        assert "doc1_seg_0000" not in report.requires_raw_fallback