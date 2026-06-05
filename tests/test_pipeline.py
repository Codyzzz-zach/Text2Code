"""Tests for t2c/pipeline.py — full pipeline orchestration."""
import hashlib

import pytest

from t2c.object_store import ObjectStore
from t2c.ontology import (
    Block, Claim, Document, Entity, Event,
    IgnoreSegment, Relation, Residual, Segment,
)
from t2c.pipeline import Pipeline, PipelineResult
from t2c.segmenter import Segmenter
from t2c.validator import Validator


def _sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


class TestPipelineNoExtractor:
    """Pipeline without extractor should handle ingestion only."""

    def test_no_extractor_returns_warning(self):
        store = ObjectStore()
        pipeline = Pipeline(store=store, extractor=None)
        result = pipeline.process_text(
            raw_text="Hello world. This is a test.",
            doc_id="test_doc",
            source_path="test.txt",
        )
        assert isinstance(result, PipelineResult)
        assert "No extractor configured" in result.warnings
        assert result.objects == []
        assert result.valid is True

    def test_no_extractor_stores_document_and_segments(self):
        store = ObjectStore()
        pipeline = Pipeline(store=store, extractor=None)
        pipeline.process_text(
            raw_text="First sentence. Second sentence. Third sentence.",
            doc_id="test_doc",
        )
        docs = list(store.query("Document"))
        assert len(docs) == 1
        assert docs[0].id == "test_doc"
        segs = list(store.query("Segment"))
        assert len(segs) > 0


class TestPipelineRepair:
    """Test the _repair method directly."""

    def test_removes_objects_with_errors(self):
        store = ObjectStore()
        pipeline = Pipeline(store=store, extractor=None)
        objects = [
            {"type": "Entity", "data": {"id": "e1", "name": "Alice", "kind": "person",
                                         "source_segment_ids": ["s1"]}},
            {"type": "Entity", "data": {"id": "e2", "name": "Bob", "kind": "person",
                                         "source_segment_ids": ["s1"]}},
            {"type": "Event", "data": {"id": "ev1", "name": "meeting", "kind": "occurrence",
                                        "participants": ["e1", "e2"],
                                        "source_segment_ids": ["s1"]}},
        ]
        errors = ["Object e2 has a reference error"]
        repaired = pipeline._repair(objects, errors, [])
        ids = [o["data"]["id"] for o in repaired]
        assert "e1" in ids
        assert "e2" not in ids
        assert "ev1" in ids

    def test_cleans_dangling_references(self):
        store = ObjectStore()
        pipeline = Pipeline(store=store, extractor=None)
        objects = [
            {"type": "Entity", "data": {"id": "e1", "name": "Alice", "kind": "person",
                                         "source_segment_ids": ["s1"]}},
            {"type": "Event", "data": {"id": "ev1", "name": "meeting", "kind": "occurrence",
                                        "participants": ["e1", "e2"],
                                        "source_segment_ids": ["s1"],
                                        "derived_from": ["e2"],
                                        "claim_id": "e2"}},
        ]
        errors = ["Object e2 has error"]
        repaired = pipeline._repair(objects, errors, [])
        # Find the event by ID (order may vary)
        event = next(o for o in repaired if o["data"]["id"] == "ev1")
        assert "e2" not in event["data"]["participants"]
        assert "e2" not in event["data"]["derived_from"]
        assert event["data"]["claim_id"] is None

    def test_objects_with_only_warnings_are_kept(self):
        store = ObjectStore()
        pipeline = Pipeline(store=store, extractor=None)
        objects = [
            {"type": "Entity", "data": {"id": "e1", "name": "Alice", "kind": "person",
                                         "source_segment_ids": ["s1"]}},
        ]
        errors = []  # No errors
        repaired = pipeline._repair(objects, errors, [])
        assert len(repaired) == 1


class TestPipelineRawFallback:
    """Test _generate_raw_fallbacks method."""

    def test_generates_residual_for_error_segments(self):
        store = ObjectStore()
        pipeline = Pipeline(store=store, extractor=None)

        seg = Segment(
            id="test_seg_0001", doc_id="test", block_index=0,
            segment_type="sentence", start_offset=0, end_offset=10,
            text_slice="Hello", hash=_sha256("Hello"),
        )
        objects = [
            {"type": "Entity", "data": {"id": "e_bad", "name": "Bad", "kind": "person",
                                         "source_segment_ids": ["test_seg_0001"]}},
        ]
        errors = ["Object e_bad has validation error"]

        fallback_ids = pipeline._generate_raw_fallbacks(
            objects, [seg], "test", errors
        )
        assert "test_seg_0001" in fallback_ids
        residuals = list(store.query("Residual"))
        assert len(residuals) == 1
        assert residuals[0].segment_id == "test_seg_0001"

    def test_no_fallback_for_valid_objects(self):
        store = ObjectStore()
        pipeline = Pipeline(store=store, extractor=None)

        seg = Segment(
            id="test_seg_0001", doc_id="test", block_index=0,
            segment_type="sentence", start_offset=0, end_offset=10,
            text_slice="Hello", hash=_sha256("Hello"),
        )
        objects = [
            {"type": "Entity", "data": {"id": "e_good", "name": "Good", "kind": "person",
                                         "source_segment_ids": ["test_seg_0001"]}},
        ]
        errors = []

        fallback_ids = pipeline._generate_raw_fallbacks(
            objects, [seg], "test", errors
        )
        assert len(fallback_ids) == 0


class TestPipelineTelemetry:
    """v3.4.1: PipelineResult carries extraction telemetry."""

    def test_result_has_new_telemetry_fields(self):
        from t2c.pipeline import PipelineResult
        r = PipelineResult()
        assert hasattr(r, "batches_truncated")
        assert hasattr(r, "total_input_tokens")
        assert hasattr(r, "total_output_tokens")
        assert hasattr(r, "api_elapsed_sec")
        assert r.batches_truncated == 0
        assert r.total_input_tokens == 0
        assert r.total_output_tokens == 0
        assert r.api_elapsed_sec == 0.0

    def test_no_extractor_leaves_telemetry_zero(self):
        store = ObjectStore()
        pipeline = Pipeline(store=store, extractor=None)
        result = pipeline.process_text(
            raw_text="hello. world.",
            doc_id="telemetry_test",
        )
        # No extractor → no LLM calls → telemetry stays at 0.
        assert result.total_input_tokens == 0
        assert result.total_output_tokens == 0
        assert result.api_elapsed_sec == 0.0
        assert result.batches_truncated == 0

    def test_pipeline_reads_extractor_telemetry(self):
        """When the extractor reports telemetry, Pipeline copies it into result."""
        from unittest.mock import MagicMock
        from t2c.extractor import LLMExtractor

        class StubExtractor(LLMExtractor):
            def __init__(self):
                super().__init__(_client=MagicMock())
                self._last_batch_truncated = True
                self._total_input_tokens = 1234
                self._total_output_tokens = 5678
                self._api_elapsed_sec = 9.5

            def extract_chapter(self, **_):
                return []

        pipeline = Pipeline(extractor=StubExtractor())
        result = pipeline.process_text(raw_text="hi. there.", doc_id="t")
        assert result.batches_truncated == 1
        assert result.total_input_tokens == 1234
        assert result.total_output_tokens == 5678
        assert result.api_elapsed_sec == 9.5
