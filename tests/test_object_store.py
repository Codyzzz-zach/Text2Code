"""Tests for t2c/object_store.py — SQLite object store."""
import pytest

from t2c.ontology import (
    Block, Claim, CoverageReport, Document, Entity, Event,
    IgnoreSegment, Relation, Residual, Segment,
)
from t2c.object_store import ObjectStore


@pytest.fixture
def store():
    s = ObjectStore()
    yield s
    s.close()


def _make_document(doc_id="test_doc"):
    return Document(
        id=doc_id,
        source_path="test.txt",
        raw_text_hash="sha256:abc",
        total_length=100,
        block_count=1,
        created_at="2026-05-27T10:00:00Z",
    )


def _make_segment(seg_id="test_doc_seg_0001", doc_id="test_doc"):
    return Segment(
        id=seg_id,
        doc_id=doc_id,
        block_index=0,
        segment_type="sentence",
        start_offset=0,
        end_offset=10,
        text_slice="Hello",
        hash="sha256:abc",
    )


class TestCRUD:
    def test_save_and_get_document(self, store):
        doc = _make_document()
        store.save(doc)
        result = store.get("Document", "test_doc")
        assert result is not None
        assert result["id"] == "test_doc"

    def test_save_and_get_segment(self, store):
        seg = _make_segment()
        store.save(seg)
        result = store.get("Segment", "test_doc_seg_0001")
        assert result is not None
        assert result["doc_id"] == "test_doc"

    def test_get_nonexistent(self, store):
        assert store.get("Document", "no_such") is None

    def test_save_entity(self, store):
        ent = Entity(id="e1", name="Alice", kind="person")
        store.save(ent)
        result = store.get("Entity", "e1")
        assert result["name"] == "Alice"

    def test_save_claim(self, store):
        claim = Claim(
            id="c1", subject="Alice", predicate="knows",
            object="Bob", modality="asserted", polarity="positive",
        )
        store.save(claim)
        result = store.get("Claim", "c1")
        assert result["modality"] == "asserted"

    def test_save_overwrite(self, store):
        doc1 = _make_document()
        store.save(doc1)
        doc2 = Document(
            id="test_doc", source_path="updated.txt",
            raw_text_hash="sha256:def", total_length=200,
            block_count=2, created_at="2026-05-27T10:00:00Z",
        )
        store.save(doc2)
        result = store.get("Document", "test_doc")
        assert result["source_path"] == "updated.txt"


class TestQuery:
    def test_query_by_doc_id(self, store):
        for i in range(3):
            seg = Segment(
                id=f"doc_seg_{i:04d}", doc_id="doc1",
                block_index=i, segment_type="sentence",
                start_offset=i * 10, end_offset=(i + 1) * 10,
                text_slice="text", hash="sha256:abc",
            )
            store.save(seg)
        seg_other = Segment(
            id="doc2_seg_0000", doc_id="doc2",
            block_index=0, segment_type="sentence",
            start_offset=0, end_offset=10,
            text_slice="text", hash="sha256:abc",
        )
        store.save(seg_other)

        results = store.get_segments_by_doc("doc1")
        assert len(results) == 3

    def test_query_with_filter(self, store):
        ent1 = Entity(id="e1", name="Alice", kind="person")
        ent2 = Entity(id="e2", name="Acme", kind="org")
        store.save(ent1)
        store.save(ent2)
        results = store.query("Entity", kind="person")
        assert len(results) == 1
        assert results[0]["name"] == "Alice"

    def test_block_stored_by_obj_id(self, store):
        """Fix #2: Block should be stored and retrieved using obj.id, not synthetic key."""
        blk = Block(
            id="my_block_id", doc_id="test_doc", index=0,
            block_type="paragraph", start_offset=0, end_offset=10,
            text_slice="Hello", hash="sha256:abc",
        )
        store.save(blk)
        result = store.get("Block", "my_block_id")
        assert result is not None
        assert result["id"] == "my_block_id"

    def test_claim_query_by_polarity(self, store):
        """Fix #2: Claim should be queryable by polarity column."""
        claim_pos = Claim(
            id="c_pos", subject="Alice", predicate="knows",
            object="Bob", modality="asserted", polarity="positive",
        )
        claim_neg = Claim(
            id="c_neg", subject="Alice", predicate="knows",
            object="Bob", modality="asserted", polarity="negative",
        )
        store.save(claim_pos)
        store.save(claim_neg)
        results = store.query("Claim", polarity="positive")
        assert len(results) == 1
        assert results[0]["id"] == "c_pos"


class TestSemanticLookup:
    def test_get_semantic_objects_for_segment(self, store):
        seg = _make_segment(seg_id="s1")
        store.save(seg)

        ent = Entity(
            id="e1", name="Alice", kind="person",
            source_segment_ids=["s1"],
        )
        store.save(ent)

        results = store.get_semantic_objects_for_segment("s1")
        assert len(results) == 1
        assert results[0]["name"] == "Alice"

    def test_get_residuals_for_segment(self, store):
        seg = _make_segment(seg_id="s2")
        store.save(seg)

        res = Residual(
            id="s2_res_0001", segment_id="s2",
            category="stylistic", importance="medium",
            reason="minor style issue",
        )
        store.save(res)

        results = store.get_residuals_for_segment("s2")
        assert len(results) == 1
        assert results[0]["category"] == "stylistic"


class TestSaveParsed:
    def test_save_parsed_objects(self, store):
        from t2c.parser import T2CParser
        source = '''\
from t2c.ontology import Document

Document(
    id="parsed_doc",
    source_path="test.txt",
    raw_text_hash="sha256:abc",
    total_length=100,
    block_count=1,
    created_at="2026-05-27T10:00:00Z",
)
'''
        parser = T2CParser()
        objects = parser.parse_string(source)
        store.save_parsed(objects)
        result = store.get("Document", "parsed_doc")
        assert result is not None
        assert result["id"] == "parsed_doc"
