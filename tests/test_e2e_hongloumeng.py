"""End-to-end tests using the Hongloumeng (红楼梦) sample data."""
import hashlib
from pathlib import Path

import pytest

from t2c.corpus import CorpusManager
from t2c.coverage import CoverageGenerator
from t2c.graph_api import GraphAPI
from t2c.graph_builder import GraphBuilder
from t2c.object_store import ObjectStore
from t2c.ontology import (
    Block, Claim, Document, Entity, Event,
    IgnoreSegment, Relation, Residual, Segment,
)
from t2c.parser import T2CParser
from t2c.segmenter import Segmenter
from t2c.validator import Validator

SAMPLE_DIR = Path(__file__).parent.parent / "examples" / "knowledge"
RAW_TXT = Path(__file__).parent.parent / "examples" / "rawtxt"


def _sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


class TestHongloumengParsing:
    """Test parsing of existing .t2c.py knowledge files."""

    @pytest.fixture
    def ch01_path(self):
        p = SAMPLE_DIR / "hongloumeng_ch01.t2c.py"
        if not p.exists():
            pytest.skip("hongloumeng_ch01.t2c.py not found")
        return p

    def test_parse_ch01_produces_objects(self, ch01_path):
        parser = T2CParser()
        objects = parser.parse_file(ch01_path)
        assert len(objects) > 0

    def test_parse_ch01_has_entities_and_events(self, ch01_path):
        parser = T2CParser()
        objects = parser.parse_file(ch01_path)
        types = {obj["type"] for obj in objects}
        assert "Entity" in types
        assert "Event" in types


class TestHongloumengSegmentation:
    """Test segmentation of the raw Hongloumeng text."""

    @pytest.fixture
    def raw_text(self):
        p = RAW_TXT / "红楼梦.txt"
        if not p.exists():
            pytest.skip("红楼梦.txt not found")
        return p.read_text(encoding="utf-8")

    def test_segment_produces_segments(self, raw_text):
        segmenter = Segmenter()
        segments = segmenter.segment(raw_text)
        assert len(segments) > 0

    def test_segments_have_hash(self, raw_text):
        segmenter = Segmenter()
        segments = segmenter.segment(raw_text)
        for seg in segments:
            assert seg.hash is not None
            assert seg.hash.startswith("sha256:")


class TestHongloumengSemantics:
    """Test semantic object storage and querying."""

    @pytest.fixture
    def store(self):
        s = ObjectStore()
        # Populate with sample data
        s.save(Document(
            id="hongloumeng", source_path="红楼梦.txt",
            raw_text_hash=_sha256("红楼梦 raw text"), total_length=10000,
            block_count=10, created_at="2026-05-27T10:00:00Z",
        ))
        s.save(Segment(
            id="hongloumeng_seg_0001", doc_id="hongloumeng",
            block_index=0, segment_type="sentence",
            start_offset=0, end_offset=10, text_slice="甄士隐住在姑苏。",
            hash=_sha256("甄士隐住在姑苏。"),
        ))
        s.save(Entity(
            id="hongloumeng_ent_0001", name="甄士隐", kind="person",
            aliases=["士隐"], source_segment_ids=["hongloumeng_seg_0001"],
        ))
        s.save(Entity(
            id="hongloumeng_ent_0002", name="封肃", kind="person",
            aliases=[], source_segment_ids=["hongloumeng_seg_0001"],
        ))
        s.save(Event(
            id="hongloumeng_evt_0001", name="甄士隐做梦", kind="occurrence",
            participants=["hongloumeng_ent_0001"],
            source_segment_ids=["hongloumeng_seg_0001"],
        ))
        s.save(Claim(
            id="hongloumeng_clm_0001", subject="hongloumeng_ent_0001",
            predicate="lives_in", object="hongloumeng_ent_0002",
            modality="asserted", polarity="positive",
            source_segment_ids=["hongloumeng_seg_0001"],
        ))
        s.save(Relation(
            id="hongloumeng_rel_0001", subject="hongloumeng_ent_0001",
            predicate="lives_in", object="hongloumeng_ent_0002",
            claim_id="hongloumeng_clm_0001",
        ))
        yield s
        s.close()

    def test_entities_and_events(self, store):
        entities = list(store.query("Entity"))
        events = list(store.query("Event"))
        assert len(entities) == 2
        assert len(events) == 1
        assert entities[0].name == "甄士隐"

    def test_claims_and_relations(self, store):
        claims = list(store.query("Claim"))
        relations = list(store.query("Relation"))
        assert len(claims) == 1
        assert len(relations) == 1
        assert relations[0].claim_id == "hongloumeng_clm_0001"

    def test_graph_build(self, store):
        builder = GraphBuilder(store)
        graph = builder.build_graph()
        assert "nodes" in graph
        assert "edges" in graph
        assert "hongloumeng_ent_0001" in graph["nodes"]

    def test_graph_api_query(self, store):
        api = GraphAPI(store)
        node = api.get_node("hongloumeng_ent_0001")
        assert node is not None
        assert node["label"] == "甄士隐"

    def test_coverage_report(self, store):
        gen = CoverageGenerator(store)
        report = gen.generate_coverage("hongloumeng")
        assert report.total_segments >= 1
        assert report.status_counts.get("covered", 0) >= 0
