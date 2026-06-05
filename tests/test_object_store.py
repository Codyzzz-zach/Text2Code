"""Tests for t2c/object_store.py — SQLite object store with validation gate."""
import hashlib

import pytest

from t2c.ontology import (
    Block, Claim, Document, Entity, Event,
    IgnoreSegment, Relation, Residual, Segment,
)
from t2c.object_store import ObjectStore


def _sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.fixture
def store():
    s = ObjectStore()
    yield s
    s.close()


def _make_document(doc_id="test_doc"):
    return Document(
        id=doc_id,
        source_path="test.txt",
        raw_text_hash=_sha256("raw text"),
        total_length=100,
        block_count=1,
        created_at="2026-05-27T10:00:00Z",
    )


def _make_segment(seg_id="test_doc_seg_0001", doc_id="test_doc", text="Hello"):
    return Segment(
        id=seg_id,
        doc_id=doc_id,
        block_index=0,
        segment_type="sentence",
        start_offset=0,
        end_offset=len(text),
        text_slice=text,
        hash=_sha256(text),
    )


class TestCRUD:
    def test_save_and_load_document(self, store):
        doc = _make_document()
        store.save(doc)
        result = store.load("Document", "test_doc")
        assert result is not None
        assert result.id == "test_doc"

    def test_save_and_load_segment(self, store):
        seg = _make_segment()
        store.save(seg)
        result = store.load("Segment", "test_doc_seg_0001")
        assert result is not None
        assert result.doc_id == "test_doc"

    def test_load_nonexistent(self, store):
        assert store.load("Document", "no_such") is None

    def test_save_entity(self, store):
        ent = Entity(id="e1", name="Alice", kind="person")
        store.save(ent)
        result = store.load("Entity", "e1")
        assert result.name == "Alice"

    def test_save_claim(self, store):
        claim = Claim(
            id="c1", subject="Alice", predicate="knows",
            object="Bob", modality="asserted", polarity="positive",
        )
        store.save(claim)
        result = store.load("Claim", "c1")
        assert result.modality == "asserted"

    def test_save_overwrite(self, store):
        doc1 = _make_document()
        store.save(doc1)
        doc2 = Document(
            id="test_doc", source_path="updated.txt",
            raw_text_hash=_sha256("updated raw text"), total_length=200,
            block_count=2, created_at="2026-05-27T10:00:00Z",
        )
        store.save(doc2)
        result = store.load("Document", "test_doc")
        assert result.source_path == "updated.txt"


class TestQuery:
    def test_query_by_type(self, store):
        for i in range(3):
            ent = Entity(id=f"e{i}", name=f"Person{i}", kind="person")
            store.save(ent)
        org = Entity(id="org1", name="Acme", kind="org")
        store.save(org)

        people = list(store.query("Entity", kind="person"))
        assert len(people) == 3

    def test_count(self, store):
        store.save(Entity(id="e1", name="A", kind="person"))
        store.save(Entity(id="e2", name="B", kind="person"))
        assert store.count("Entity") == 2
        assert store.count() == 2

    def test_delete(self, store):
        store.save(Entity(id="e1", name="Alice", kind="person"))
        assert store.load("Entity", "e1") is not None
        assert store.delete("Entity", "e1") is True
        assert store.load("Entity", "e1") is None


class TestSemanticLookup:
    def test_query_entities_by_source_segment(self, store):
        seg = _make_segment(seg_id="s1")
        store.save(seg)
        ent = Entity(id="e1", name="Alice", kind="person", source_segment_ids=["s1"])
        store.save(ent)

        # Query all entities and filter
        results = [e for e in store.query("Entity") if "s1" in e.source_segment_ids]
        assert len(results) == 1
        assert results[0].name == "Alice"

    def test_save_and_load_residual(self, store):
        seg = _make_segment(seg_id="s2")
        store.save(seg)
        res = Residual(
            id="s2_res_0001", segment_id="s2",
            category="stylistic", importance="medium",
            reason="minor style issue",
        )
        store.save(res)
        result = store.load("Residual", "s2_res_0001")
        assert result is not None
        assert result.category == "stylistic"


class TestValidatedBatch:
    """Tests for save_validated_batch — the validation gate for ObjectStore."""

    def test_valid_batch_is_saved(self, store):
        """A well-formed batch should be saved without rejection."""
        doc = Document(id="doc1", source_path="t.txt", raw_text_hash=_sha256("raw text"),
                       total_length=100, block_count=1, created_at="2026-06-01T00:00:00Z")
        seg = Segment(id="seg1", doc_id="doc1", block_index=0, segment_type="sentence",
                      start_offset=0, end_offset=5, text_slice="hello",
                      hash=_sha256("hello"))
        ent = Entity(id="ent1", name="Alice", kind="person", aliases=[], source_segment_ids=["seg1"])

        saved_count, errors = store.save_validated_batch([doc, seg, ent])
        assert saved_count >= 1
        assert len(errors) == 0
        assert store.load("Document", "doc1") is not None

    def test_batch_with_dangling_refs_rejects_invalid(self, store):
        """Objects with dangling references should be rejected when target type is in batch."""
        doc = Document(id="doc1", source_path="t.txt", raw_text_hash=_sha256("raw text"),
                       total_length=100, block_count=1, created_at="2026-06-01T00:00:00Z")
        seg = Segment(id="seg1", doc_id="doc1", block_index=0, segment_type="sentence",
                      start_offset=0, end_offset=5, text_slice="hello",
                      hash=_sha256("hello"))
        # Entity references missing_seg — dangling ref since Segment seg1 exists in batch
        ent = Entity(id="ent1", name="Alice", kind="person", aliases=[], source_segment_ids=["missing_seg"])

        saved_count, errors = store.save_validated_batch([doc, seg, ent])
        # Entity should be rejected, Document and Segment saved
        assert len(errors) >= 1
        assert store.load("Document", "doc1") is not None
        assert store.load("Segment", "seg1") is not None
        assert store.load("Entity", "ent1") is None

    def test_batch_with_cross_store_refs_uses_external_index(self, store):
        """References to objects already in the store should resolve via external_index."""
        # Pre-populate store with a Segment
        store.save(_make_segment(seg_id="seg1"))
        ent = Entity(id="ent1", name="Alice", kind="person", aliases=[], source_segment_ids=["seg1"])

        saved_count, errors = store.save_validated_batch([ent])
        assert saved_count >= 1
        assert len(errors) == 0

    def test_save_validated_single_object(self, store):
        """save_validated validates then saves a single object."""
        doc = _make_document()
        success, errors = store.save_validated(doc)
        assert success is True
        assert len(errors) == 0
        assert store.load("Document", "test_doc") is not None
