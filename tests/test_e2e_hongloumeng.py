"""End-to-end test — full pipeline with 红楼梦 raw text."""
from pathlib import Path

import pytest

from t2c.claim_safety import ClaimSafetyValidator
from t2c.codegen import CodeGenerator
from t2c.corpus import CorpusManager
from t2c.coverage import CoverageGenerator
from t2c.graph_api import GraphAPI
from t2c.graph_builder import GraphBuilder
from t2c.object_store import ObjectStore
from t2c.ontology import (
    Block,
    Claim,
    Document,
    Entity,
    Event,
    EvidenceRef,
    IgnoreSegment,
    Relation,
    Residual,
    Segment,
)
from t2c.parser import T2CParser
from t2c.segmenter import Segmenter
from t2c.validator import Validator

HONGLOUMENG_PATH = Path(__file__).parent.parent / "rawtxt" / "红楼梦.txt"

# Use first 8000 chars — covers title, author, chapter heading, dialogue
SAMPLE_SIZE = 8000


@pytest.fixture
def hlm_text():
    return HONGLOUMENG_PATH.read_text(encoding="utf-8")[:SAMPLE_SIZE]


@pytest.fixture
def hlm_full_text():
    return HONGLOUMENG_PATH.read_text(encoding="utf-8")


@pytest.fixture
def store():
    s = ObjectStore()
    yield s
    s.close()


# -- P0: Text Map (Corpus + Segmenter) --------------------------------


class TestHongloumengCorpus:
    def test_ingest(self, hlm_text):
        cm = CorpusManager()
        doc, text = cm.ingest_text(hlm_text, "hongloumeng")
        assert doc.id == "hongloumeng"
        assert doc.raw_text_hash.startswith("sha256:")
        assert doc.total_length == len(hlm_text)

    def test_block_generation(self, hlm_text):
        cm = CorpusManager()
        doc, text = cm.ingest_text(hlm_text, "hongloumeng")
        blocks = cm.create_blocks(doc, text)
        assert len(blocks) > 0
        # Should have heading blocks (第X回), paragraph blocks, quote blocks
        block_types = {b.block_type for b in blocks}
        assert "paragraph" in block_types
        # Verify all blocks have id
        for b in blocks:
            assert b.id.startswith("hongloumeng_blk_")
            assert b.doc_id == "hongloumeng"

    def test_block_hash_consistency(self, hlm_text):
        cm = CorpusManager()
        doc, text = cm.ingest_text(hlm_text, "hongloumeng")
        blocks = cm.create_blocks(doc, text)
        for block in blocks:
            slice_text = text[block.start_offset:block.end_offset]
            assert slice_text == block.text_slice
            assert cm.verify_block_hash(block, text)


class TestHongloumengSegmenter:
    def test_segmentation(self, hlm_text):
        cm = CorpusManager()
        doc, text = cm.ingest_text(hlm_text, "hongloumeng")
        blocks = cm.create_blocks(doc, text)
        seg = Segmenter()
        all_segments = []
        for block in blocks:
            block_text = cm.get_block_text(doc, block, text)
            segments = seg.segment_block(doc.id, block, block_text)
            all_segments.extend(segments)
        assert len(all_segments) >= 5

    def test_chinese_dialogue_detection(self, hlm_text):
        cm = CorpusManager()
        doc, text = cm.ingest_text(hlm_text, "hongloumeng")
        blocks = cm.create_blocks(doc, text)
        seg = Segmenter()
        all_segments = []
        for block in blocks:
            block_text = cm.get_block_text(doc, block, text)
            segments = seg.segment_block(doc.id, block, block_text)
            all_segments.extend(segments)
        # 红楼梦 has abundant 「」dialogue
        dialogue_segs = [s for s in all_segments if s.segment_type == "dialogue"]
        assert len(dialogue_segs) >= 1

    def test_heading_detection(self, hlm_text):
        cm = CorpusManager()
        doc, text = cm.ingest_text(hlm_text, "hongloumeng")
        blocks = cm.create_blocks(doc, text)
        seg = Segmenter()
        all_segments = []
        for block in blocks:
            block_text = cm.get_block_text(doc, block, text)
            segments = seg.segment_block(doc.id, block, block_text)
            all_segments.extend(segments)
        heading_segs = [s for s in all_segments if s.segment_type == "heading"]
        # "第一回" is a heading
        assert len(heading_segs) >= 1

    def test_segment_hash_consistency(self, hlm_text):
        cm = CorpusManager()
        doc, text = cm.ingest_text(hlm_text, "hongloumeng")
        blocks = cm.create_blocks(doc, text)
        seg = Segmenter()
        all_segments = []
        for block in blocks:
            block_text = cm.get_block_text(doc, block, text)
            segments = seg.segment_block(doc.id, block, block_text)
            all_segments.extend(segments)
        for s in all_segments:
            assert s.hash.startswith("sha256:")


# -- P0: Code Generation + Validation ---------------------------------


class TestHongloumengCodegen:
    def test_document_code_generation(self, hlm_text):
        cm = CorpusManager()
        doc, text = cm.ingest_text(hlm_text, "hongloumeng")
        blocks = cm.create_blocks(doc, text)
        gen = CodeGenerator()
        code = gen.generate_document_code(doc, blocks)
        compile(code, "<doc>", "exec")
        assert "Document(" in code
        assert "Block(" in code

    def test_segment_code_generation(self, hlm_text):
        cm = CorpusManager()
        doc, text = cm.ingest_text(hlm_text, "hongloumeng")
        blocks = cm.create_blocks(doc, text)
        seg = Segmenter()
        all_segments = []
        for block in blocks:
            block_text = cm.get_block_text(doc, block, text)
            segments = seg.segment_block(doc.id, block, block_text)
            all_segments.extend(segments)
        gen = CodeGenerator()
        code = gen.generate_segments_code(all_segments)
        compile(code, "<seg>", "exec")
        assert "Segment(" in code

    def test_roundtrip_parse_document_code(self, hlm_text):
        cm = CorpusManager()
        doc, text = cm.ingest_text(hlm_text, "hongloumeng")
        blocks = cm.create_blocks(doc, text)
        gen = CodeGenerator()
        code = gen.generate_document_code(doc, blocks)
        parser = T2CParser()
        objects = parser.parse_string(code)
        assert len(objects) >= 1 + len(blocks)  # Document + Blocks

    def test_roundtrip_parse_segment_code(self, hlm_text):
        cm = CorpusManager()
        doc, text = cm.ingest_text(hlm_text, "hongloumeng")
        blocks = cm.create_blocks(doc, text)
        seg = Segmenter()
        all_segments = []
        for block in blocks:
            block_text = cm.get_block_text(doc, block, text)
            segments = seg.segment_block(doc.id, block, block_text)
            all_segments.extend(segments)
        gen = CodeGenerator()
        code = gen.generate_segments_code(all_segments)
        parser = T2CParser()
        objects = parser.parse_string(code)
        assert len(objects) == len(all_segments)

    def test_full_validation(self, hlm_text):
        cm = CorpusManager()
        doc, text = cm.ingest_text(hlm_text, "hongloumeng")
        blocks = cm.create_blocks(doc, text)
        seg = Segmenter()
        all_segments = []
        for block in blocks:
            block_text = cm.get_block_text(doc, block, text)
            segments = seg.segment_block(doc.id, block, block_text)
            all_segments.extend(segments)
        gen = CodeGenerator()
        doc_code = gen.generate_document_code(doc, blocks)
        seg_code = gen.generate_segments_code(all_segments)
        validator = Validator(raw_text_store={"hongloumeng": text})
        result = validator.validate_string(doc_code)
        assert result.valid, f"Document validation errors: {result.errors}"
        result = validator.validate_string(seg_code)
        assert result.valid, f"Segment validation errors: {result.errors}"


# -- P2: Semantic Objects + Claim Safety ------------------------------


class TestHongloumengSemantics:
    def test_entities_and_events(self, hlm_text, store):
        cm = CorpusManager()
        doc, text = cm.ingest_text(hlm_text, "hongloumeng")
        blocks = cm.create_blocks(doc, text)
        seg = Segmenter()
        all_segments = []
        for block in blocks:
            block_text = cm.get_block_text(doc, block, text)
            segments = seg.segment_block(doc.id, block, block_text)
            all_segments.extend(segments)
        store.save(doc)
        for b in blocks:
            store.save(b)
        for s in all_segments:
            store.save(s)

        # Simulate knowledge extraction for first chapter characters
        seg0_id = all_segments[0].id if all_segments else "hongloumeng_seg_0000"
        zhen_shiyin = Entity(
            id="hongloumeng_ent_0001", name="甄士隐", kind="person",
            source_segment_ids=[seg0_id],
        )
        jia_yucun = Entity(
            id="hongloumeng_ent_0002", name="贾雨村", kind="person",
            source_segment_ids=[seg0_id],
        )
        yinglian = Entity(
            id="hongloumeng_ent_0003", name="英莲", kind="person",
            source_segment_ids=[seg0_id],
        )
        store.save(zhen_shiyin)
        store.save(jia_yucun)
        store.save(yinglian)

        event = Event(
            id="hongloumeng_evt_0001", name="甄士隐梦识通灵", kind="occurrence",
            participants=["hongloumeng_ent_0001"],
            source_segment_ids=[seg0_id],
        )
        store.save(event)

        # Verify retrieval
        entities = store.query("Entity", kind="person")
        assert len(entities) >= 3

    def test_claim_safety_on_reported_speech(self, store):
        # 红楼梦 has lots of reported speech — test claim safety
        claim_reported = Claim(
            id="hongloumeng_clm_0001",
            subject="甄士隐", predicate="dreamed", object="通灵宝玉",
            modality="reported", polarity="negative",
            source_segment_ids=["hongloumeng_seg_0001"],
        )
        claim_asserted = Claim(
            id="hongloumeng_clm_0002",
            subject="甄士隐", predicate="lived_in", object="姑苏",
            modality="asserted", polarity="positive",
            source_segment_ids=["hongloumeng_seg_0001"],
        )
        store.save(claim_reported)
        store.save(claim_asserted)

        # Claim safety: reported+positive is violation, reported+negative is ok
        validator = ClaimSafetyValidator()
        rel = Relation(
            id="hongloumeng_rel_0001",
            subject="甄士隐", predicate="dreamed", object="通灵宝玉",
            claim_id="hongloumeng_clm_0001",
        )
        violations = validator.validate_claims([claim_reported], [rel])
        # reported + negative should NOT trigger no_asserted_from_reported
        assert not any(v.rule == "no_asserted_from_reported" for v in violations)

        # reported + positive IS a violation (with relation projecting as fact)
        claim_reported_pos = Claim(
            id="hongloumeng_clm_0003",
            subject="甄士隐", predicate="claimed", object="something",
            modality="reported", polarity="positive",
        )
        rel2 = Relation(
            id="hongloumeng_rel_0002",
            subject="甄士隐", predicate="claimed", object="something",
            claim_id="hongloumeng_clm_0003",
        )
        violations2 = validator.validate_claims([claim_reported_pos], [rel2])
        assert any(v.rule == "no_asserted_from_reported" for v in violations2)


# -- P3: Coverage + Near-Lossless --------------------------------------


class TestHongloumengCoverage:
    def test_coverage_report(self, hlm_text, store):
        cm = CorpusManager()
        doc, text = cm.ingest_text(hlm_text, "hongloumeng")
        blocks = cm.create_blocks(doc, text)
        seg = Segmenter()
        all_segments = []
        for block in blocks:
            block_text = cm.get_block_text(doc, block, text)
            segments = seg.segment_block(doc.id, block, block_text)
            all_segments.extend(segments)
        store.save(doc)
        for b in blocks:
            store.save(b)
        for s in all_segments:
            store.save(s)

        # Add entity for first segment → covered
        if all_segments:
            ent = Entity(
                id="hongloumeng_ent_0001", name="甄士隐", kind="person",
                source_segment_ids=[all_segments[0].id],
            )
            store.save(ent)

        gen = CoverageGenerator(store)
        report = gen.generate_coverage("hongloumeng")
        assert report.id == "hongloumeng_coverage"
        assert report.total_segments == len(all_segments)
        assert "covered" in report.status_counts
        assert "uncovered" in report.status_counts

    def test_residual_tracking(self, hlm_text, store):
        cm = CorpusManager()
        doc, text = cm.ingest_text(hlm_text, "hongloumeng")
        blocks = cm.create_blocks(doc, text)
        seg = Segmenter()
        all_segments = []
        for block in blocks:
            block_text = cm.get_block_text(doc, block, text)
            segments = seg.segment_block(doc.id, block, block_text)
            all_segments.extend(segments)
        store.save(doc)
        for b in blocks:
            store.save(b)
        for s in all_segments:
            store.save(s)

        # Entity covers first segment
        if all_segments:
            ent = Entity(
                id="hongloumeng_ent_0001", name="甄士隐", kind="person",
                source_segment_ids=[all_segments[0].id],
            )
            store.save(ent)
            # Residual: literary style lost in knowledge code
            res = Residual(
                id="hongloumeng_res_0001",
                segment_id=all_segments[0].id,
                category="stylistic",
                importance="high",
                reason="诗词韵律和修辞手法无法以结构化对象表达",
            )
            store.save(res)

        gen = CoverageGenerator(store)
        report = gen.generate_coverage("hongloumeng")
        # First segment should be partial (has semantic + residual)
        if all_segments:
            assert report.status_counts.get("partial", 0) >= 1
            assert all_segments[0].id in report.requires_raw_fallback


# -- P4: Graph + Query -------------------------------------------------


class TestHongloumengGraph:
    def test_graph_build_and_query(self, hlm_text, store):
        cm = CorpusManager()
        doc, text = cm.ingest_text(hlm_text, "hongloumeng")
        blocks = cm.create_blocks(doc, text)
        seg = Segmenter()
        all_segments = []
        for block in blocks:
            block_text = cm.get_block_text(doc, block, text)
            segments = seg.segment_block(doc.id, block, block_text)
            all_segments.extend(segments)
        store.save(doc)
        for b in blocks:
            store.save(b)
        for s in all_segments:
            store.save(s)

        # Create semantic objects
        seg_id = all_segments[0].id if all_segments else "hongloumeng_seg_0000"
        zhen = Entity(
            id="hongloumeng_ent_0001", name="甄士隐", kind="person",
            source_segment_ids=[seg_id],
        )
        yinglian = Entity(
            id="hongloumeng_ent_0002", name="英莲", kind="person",
            source_segment_ids=[seg_id],
        )
        store.save(zhen)
        store.save(yinglian)

        claim = Claim(
            id="hongloumeng_clm_0001",
            subject="甄士隐", predicate="is_father_of", object="英莲",
            modality="asserted", polarity="positive",
            source_segment_ids=[seg_id],
        )
        store.save(claim)

        rel = Relation(
            id="hongloumeng_rel_0001",
            subject="hongloumeng_ent_0001", predicate="is_father_of",
            object="hongloumeng_ent_0002", claim_id="hongloumeng_clm_0001",
        )
        store.save(rel)

        # Build graph
        builder = GraphBuilder(store)
        graph = builder.build_graph("hongloumeng")

        # Verify graph structure
        assert graph.has_node("hongloumeng")
        assert graph.has_node("hongloumeng_ent_0001")
        assert graph.has_node("hongloumeng_ent_0002")
        assert graph.has_edge("hongloumeng_ent_0001", "hongloumeng_ent_0002")
        edge = graph.edges["hongloumeng_ent_0001", "hongloumeng_ent_0002"]
        assert edge["type"] == "relation"
        assert edge["predicate"] == "is_father_of"

        # Query via GraphAPI
        api = GraphAPI(graph, store)
        persons = api.find_entities(kind="person")
        assert len(persons) >= 2
        father_claims = api.find_claims(predicate="is_father_of")
        assert len(father_claims) == 1

        # Segment coverage via graph
        if all_segments:
            seg_status = graph.nodes[all_segments[0].id].get("status")
            assert seg_status == "covered"


# -- Full Pipeline: Large Sample ----------------------------------------


class TestHongloumengLargeSample:
    def test_first_chapter_pipeline(self, hlm_full_text, store):
        """Full pipeline on first chapter (~10K chars) of 红楼梦."""
        # First chapter ends at "且看下回分解" or similar
        first_chapter = hlm_full_text[:15000]

        # P0: Ingest + Segment
        cm = CorpusManager()
        doc, text = cm.ingest_text(first_chapter, "hongloumeng_ch1")
        blocks = cm.create_blocks(doc, text)
        seg = Segmenter()
        all_segments = []
        for block in blocks:
            block_text = cm.get_block_text(doc, block, text)
            segments = seg.segment_block(doc.id, block, block_text)
            all_segments.extend(segments)

        assert len(blocks) >= 5, f"Expected >=5 blocks, got {len(blocks)}"
        assert len(all_segments) >= 10, f"Expected >=10 segments, got {len(all_segments)}"

        # P0: Codegen + Parse roundtrip
        gen = CodeGenerator()
        doc_code = gen.generate_document_code(doc, blocks)
        seg_code = gen.generate_segments_code(all_segments)
        compile(doc_code, "<doc>", "exec")
        compile(seg_code, "<seg>", "exec")

        parser = T2CParser()
        doc_objects = parser.parse_string(doc_code)
        seg_objects = parser.parse_string(seg_code)
        assert len(doc_objects) == 1 + len(blocks)
        assert len(seg_objects) == len(all_segments)

        # P1: Validation
        validator = Validator(raw_text_store={"hongloumeng_ch1": text})
        result = validator.validate_string(doc_code)
        assert result.valid, f"Document validation errors: {result.errors}"
        result = validator.validate_string(seg_code)
        assert result.valid, f"Segment validation errors: {result.errors}"

        # Store all objects
        store.save(doc)
        for b in blocks:
            store.save(b)
        for s in all_segments:
            store.save(s)

        # P2: Add semantic objects
        ev = EvidenceRef(
            segment_id=all_segments[0].id, start=0,
            end=len(all_segments[0].text_slice),
            quote_hash=all_segments[0].hash,
        )
        zhen = Entity(
            id="hongloumeng_ch1_ent_0001", name="甄士隐", kind="person",
            evidence_refs=[ev],
            source_segment_ids=[all_segments[0].id],
        )
        jia = Entity(
            id="hongloumeng_ch1_ent_0002", name="贾雨村", kind="person",
            source_segment_ids=[all_segments[0].id],
        )
        store.save(zhen)
        store.save(jia)

        dream_event = Event(
            id="hongloumeng_ch1_evt_0001", name="甄士隐梦幻识通灵",
            kind="occurrence",
            participants=["hongloumeng_ch1_ent_0001"],
            source_segment_ids=[all_segments[0].id],
        )
        store.save(dream_event)

        fire_claim = Claim(
            id="hongloumeng_ch1_clm_0001",
            subject="甄士隐", predicate="lost_home_in", object="fire",
            modality="asserted", polarity="positive",
            source_segment_ids=[all_segments[0].id],
        )
        store.save(fire_claim)

        father_rel = Relation(
            id="hongloumeng_ch1_rel_0001",
            subject="甄士隐", predicate="is_father_of", object="英莲",
            claim_id="hongloumeng_ch1_clm_0001",
        )
        store.save(father_rel)

        # P2: Claim safety
        csv = ClaimSafetyValidator()
        violations = csv.validate_claims([fire_claim], [father_rel])
        assert len(violations) == 0, f"Unexpected violations: {violations}"

        # P3: Coverage
        cov_gen = CoverageGenerator(store)
        report = cov_gen.generate_coverage("hongloumeng_ch1")
        assert report.total_segments > 0
        assert sum(report.status_counts.values()) == report.total_segments

        # P3: Add residual — literary style loss
        if all_segments:
            res = Residual(
                id="hongloumeng_ch1_res_0001",
                segment_id=all_segments[0].id,
                category="stylistic", importance="high",
                reason="古典小说的语言韵律无法以结构化知识对象表达",
            )
            store.save(res)

        report2 = cov_gen.generate_coverage("hongloumeng_ch1")
        # After adding residual, first segment becomes partial
        assert report2.status_counts.get("partial", 0) >= 1

        # P4: Graph
        builder = GraphBuilder(store)
        graph = builder.build_graph("hongloumeng_ch1")
        api = GraphAPI(graph, store)

        # Verify entities in graph
        persons = api.find_entities(kind="person")
        assert len(persons) >= 2

        # Verify coverage via graph
        if all_segments:
            seg_status = api.get_segment_coverage(all_segments[0].id)
            assert seg_status == "partial"

        # Trace neighbors from 甄士隐
        neighbors = api.trace_neighbors("hongloumeng_ch1_ent_0001", depth=1)
        assert neighbors["node"]["name"] == "甄士隐"


# -- Full Novel Stress Test ---------------------------------------------


class TestHongloumengFullNovel:
    def test_full_novel_pipeline(self, hlm_full_text, store):
        """Full pipeline on the entire 红楼梦 (878K chars, 120 chapters)."""
        text = hlm_full_text

        # P0: Ingest
        cm = CorpusManager()
        doc, raw = cm.ingest_text(text, "hongloumeng_full")
        assert doc.total_length == len(text)

        # P0: Block generation
        blocks = cm.create_blocks(doc, text)
        assert len(blocks) >= 100  # 120 chapters + many paragraphs

        # Verify heading blocks for chapter markers
        heading_blocks = [b for b in blocks if b.block_type == "heading"]
        assert len(heading_blocks) >= 100  # ~120 chapters

        # P0: Segmentation
        seg = Segmenter()
        all_segments = []
        for block in blocks:
            block_text = cm.get_block_text(doc, block, text)
            segments = seg.segment_block(doc.id, block, block_text)
            all_segments.extend(segments)

        assert len(all_segments) >= 1000  # Large novel → many segments

        # Verify unique segment IDs
        seg_ids = [s.id for s in all_segments]
        assert len(seg_ids) == len(set(seg_ids)), "Segment IDs must be unique"

        # Verify segment types
        from collections import Counter
        types = Counter(s.segment_type for s in all_segments)
        assert types.get("sentence", 0) > 0
        assert types.get("dialogue", 0) > 0  # 红楼梦 has abundant dialogue
        assert types.get("heading", 0) > 0    # Chapter headings

        # P0: Codegen — document code
        gen = CodeGenerator()
        doc_code = gen.generate_document_code(doc, blocks)
        compile(doc_code, "<doc>", "exec")

        # P0: Codegen — segment code
        seg_code = gen.generate_segments_code(all_segments)
        compile(seg_code, "<seg>", "exec")

        # P1: Parse roundtrip
        parser = T2CParser()
        doc_objects = parser.parse_string(doc_code)
        seg_objects = parser.parse_string(seg_code)
        assert len(doc_objects) == 1 + len(blocks)
        assert len(seg_objects) == len(all_segments)

        # P1: Validation
        validator = Validator(raw_text_store={"hongloumeng_full": text})
        result = validator.validate_string(doc_code)
        assert result.valid, f"Document validation errors: {result.errors}"
        result = validator.validate_string(seg_code)
        assert result.valid, f"Segment validation errors: {result.errors}"

        # Store all objects for downstream tests
        store.save(doc)
        for b in blocks:
            store.save(b)
        for s in all_segments:
            store.save(s)

        # P2: Add representative semantic objects
        # Find a segment from a dialogue for evidence
        dialogue_seg = next((s for s in all_segments if s.segment_type == "dialogue"), None)
        heading_seg = next((s for s in all_segments if s.segment_type == "heading"), None)

        ev = EvidenceRef(
            segment_id=dialogue_seg.id, start=0,
            end=len(dialogue_seg.text_slice),
            quote_hash=dialogue_seg.hash,
        ) if dialogue_seg else None

        # Key entities from 红楼梦
        entities_data = [
            ("hongloumeng_full_ent_0001", "贾宝玉", "person"),
            ("hongloumeng_full_ent_0002", "林黛玉", "person"),
            ("hongloumeng_full_ent_0003", "薛宝钗", "person"),
            ("hongloumeng_full_ent_0004", "王熙凤", "person"),
            ("hongloumeng_full_ent_0005", "贾母", "person"),
            ("hongloumeng_full_ent_0006", "荣国府", "location"),
            ("hongloumeng_full_ent_0007", "宁国府", "location"),
        ]
        seg_id = dialogue_seg.id if dialogue_seg else all_segments[0].id
        for ent_id, name, kind in entities_data:
            ent = Entity(
                id=ent_id, name=name, kind=kind,
                evidence_refs=[ev] if ev and kind == "person" else [],
                source_segment_ids=[seg_id],
            )
            store.save(ent)

        # Key events
        events_data = [
            ("hongloumeng_full_evt_0001", "黛玉进贾府", "occurrence"),
            ("hongloumeng_full_evt_0002", "宝黛初会", "occurrence"),
        ]
        for evt_id, name, kind in events_data:
            evt = Event(
                id=evt_id, name=name, kind=kind,
                participants=["hongloumeng_full_ent_0001", "hongloumeng_full_ent_0002"],
                source_segment_ids=[seg_id],
            )
            store.save(evt)

        # Key claims
        claim1 = Claim(
            id="hongloumeng_full_clm_0001",
            subject="贾宝玉", predicate="loves", object="林黛玉",
            modality="asserted", polarity="positive",
            source_segment_ids=[seg_id],
        )
        claim2 = Claim(
            id="hongloumeng_full_clm_0002",
            subject="贾宝玉", predicate="marries", object="薛宝钗",
            modality="reported", polarity="negative",
            source_segment_ids=[seg_id],
        )
        store.save(claim1)
        store.save(claim2)

        # Relations
        rel1 = Relation(
            id="hongloumeng_full_rel_0001",
            subject="hongloumeng_full_ent_0001", predicate="loves",
            object="hongloumeng_full_ent_0002", claim_id="hongloumeng_full_clm_0001",
        )
        store.save(rel1)

        # P2: Claim safety
        csv = ClaimSafetyValidator()
        violations = csv.validate_claims([claim1, claim2], [rel1])
        # claim2 is reported+negative → should NOT trigger no_asserted_from_reported
        assert not any(v.rule == "no_asserted_from_reported" and v.claim_id == "hongloumeng_full_clm_0002" for v in violations)

        # P3: Coverage
        cov_gen = CoverageGenerator(store)
        report = cov_gen.generate_coverage("hongloumeng_full")
        assert report.total_segments > 0
        assert sum(report.status_counts.values()) == report.total_segments
        assert report.status_counts.get("covered", 0) > 0

        # P3: Add residual for literary style loss
        if dialogue_seg:
            res = Residual(
                id="hongloumeng_full_res_0001",
                segment_id=dialogue_seg.id,
                category="stylistic", importance="high",
                reason="古典小说的对话语气、诗词韵律和修辞手法无法以结构化对象表达",
            )
            store.save(res)

        report2 = cov_gen.generate_coverage("hongloumeng_full")
        assert report2.status_counts.get("partial", 0) >= 1

        # P4: Graph
        builder = GraphBuilder(store)
        graph = builder.build_graph("hongloumeng_full")
        api = GraphAPI(graph, store)

        # Verify graph structure
        assert graph.has_node("hongloumeng_full")
        assert graph.has_node("hongloumeng_full_ent_0001")
        assert graph.has_edge("hongloumeng_full_ent_0001", "hongloumeng_full_ent_0002")

        # Query
        persons = api.find_entities(kind="person")
        assert len(persons) >= 5
        locations = api.find_entities(kind="location")
        assert len(locations) >= 2
        love_claims = api.find_claims(predicate="loves")
        assert len(love_claims) == 1

        # Trace from 贾宝玉
        neighbors = api.trace_neighbors("hongloumeng_full_ent_0001", depth=1)
        assert neighbors["node"]["name"] == "贾宝玉"
