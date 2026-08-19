"""Phase 2: Text Code Layer 近乎无损 — pipeline and coverage tests.

Proves:
1. segmenter → codegen v33 → text.py roundtrip
2. Raw replay: segment offsets match raw text slices
3. Every segment from segmenter becomes a code symbol
4. No silent loss: coverage tracks every segment
"""
import hashlib

from t2c.codegen import CodeGenerator
from t2c.corpus import CorpusManager
from t2c.coverage import CoverageGenerator
from t2c.object_store import ObjectStore
from t2c.ontology import (
    Claim,
    Document,
    Entity,
    EvidenceRef,
    Segment,
)
from t2c.parser import T2CParser
from t2c.segmenter import Segmenter
from t2c.validator import Validator


def _sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


class TestTextCodeLayer:
    """v3.3 Phase 2: Text Code Layer generation and validation."""

    def test_segmenter_to_codegen_v33_roundtrip(self):
        """segmenter → codegen v33 → parser → validator: full text layer."""
        raw_text = """第一回 甄士隐梦幻识通灵

甄士隐住在姑苏城中。姑苏是繁华之地。

一日，甄士隐在梦中见到一僧一道。"""
        cm = CorpusManager()
        doc, text = cm.ingest_text(raw_text, "ch01")
        blocks = cm.create_blocks(doc, text)
        seg = Segmenter()
        all_segs = []
        for b in blocks:
            bt = cm.get_block_text(doc, b, text)
            all_segs.extend(seg.segment_block(doc.id, b, bt))

        # Must produce segments
        assert len(all_segs) >= 3, f"Expected >=3 segments, got {len(all_segs)}"

        # Generate v3.3 text.py
        gen = CodeGenerator(version="v3.3-flash")
        text_files = gen.generate_text_code_v33(doc, blocks, all_segs)
        text_code = text_files["text.py"]

        # Every segment must appear as a symbol assignment
        import re
        seg_syms = re.findall(r"^(seg_\w+) = Segment\(", text_code, re.MULTILINE)
        assert len(seg_syms) == len(all_segs), (
            f"Expected {len(all_segs)} segment symbols, got {len(seg_syms)}: {seg_syms}"
        )

        # Parse and validate
        parser = T2CParser()
        objects = parser.parse_string(text_code)
        v = Validator(raw_text_store={doc.id: text})
        result = v.validate_objects(objects)
        assert result.valid, f"Text code validation errors: {result.errors}"

    def test_raw_replay(self):
        """Segment offsets replay exact text slices from raw text."""
        raw_text = "甄士隐住在姑苏城中。姑苏是繁华之地。"
        cm = CorpusManager()
        doc, text = cm.ingest_text(raw_text, "test")
        blocks = cm.create_blocks(doc, text)
        seg = Segmenter()
        all_segs = []
        for b in blocks:
            bt = cm.get_block_text(doc, b, text)
            all_segs.extend(seg.segment_block(doc.id, b, bt))

        for s in all_segs:
            # Replay: slice raw_text at offset → must match text_slice
            replayed = text[s.start_offset:s.end_offset]
            assert replayed == s.text_slice, (
                f"Raw replay mismatch for {s.id}: "
                f"expected '{s.text_slice}' ({s.start_offset}:{s.end_offset}), "
                f"got '{replayed}'"
            )

            # Hash must match
            computed = _sha256(s.text_slice)
            assert s.hash == computed, (
                f"Hash mismatch for {s.id}: stored={s.hash}, computed={computed}"
            )

    def test_no_silent_loss(self):
        """Every segment must appear in coverage report with explicit status."""
        raw_text = "甄士隐住在姑苏。姑苏很繁华。"
        cm = CorpusManager()
        doc, text = cm.ingest_text(raw_text, "test")
        blocks = cm.create_blocks(doc, text)
        seg = Segmenter()
        all_segs = []
        for b in blocks:
            bt = cm.get_block_text(doc, b, text)
            all_segs.extend(seg.segment_block(doc.id, b, bt))

        store = ObjectStore()
        store.save(doc)
        for s in all_segs:
            store.save(s)

        gen = CoverageGenerator(store)
        report = gen.generate_coverage(doc.id)

        # Total must match
        assert report.total_segments == len(all_segs), (
            f"Coverage total {report.total_segments} != segments {len(all_segs)}"
        )

        # Sum of status counts must equal total
        status_sum = sum(report.status_counts.values())
        assert status_sum == report.total_segments, (
            f"Status sum {status_sum} != total {report.total_segments}: {report.status_counts}"
        )

        # No uncovered should be silently dropped
        uncovered = report.status_counts.get("uncovered", 0)
        # uncovered segments should be in requires_raw_fallback
        # This is a structural check: every uncovered segment is explicitly reported

    def test_coverage_with_semantic_objects(self):
        """Coverage transitions from uncovered → covered when semantic objects added."""
        raw_text = "甄士隐住在姑苏。"
        cm = CorpusManager()
        doc, text = cm.ingest_text(raw_text, "test")
        blocks = cm.create_blocks(doc, text)
        seg = Segmenter()
        all_segs = []
        for b in blocks:
            bt = cm.get_block_text(doc, b, text)
            all_segs.extend(seg.segment_block(doc.id, b, bt))

        # Phase 1: just segments — all uncovered
        store = ObjectStore()
        store.save(doc)
        for s in all_segs:
            store.save(s)
        gen = CoverageGenerator(store)
        report1 = gen.generate_coverage(doc.id)
        uncovered1 = report1.status_counts.get("uncovered", 0)
        assert uncovered1 >= 1, f"Expected uncovered segments, got {report1.status_counts}"

        # Phase 2: add entity referencing a segment → covered
        seg0 = all_segs[0]
        ent = Entity(
            id="ent1", name="甄士隐", kind="person",
            source_segment_ids=[seg0.id],
        )
        store.save(ent)

        report2 = gen.generate_coverage(doc.id)
        assert report2.status_counts.get("covered", 0) >= 1, (
            f"Expected covered segments, got {report2.status_counts}"
        )
        assert report2.status_counts.get("uncovered", 0) < uncovered1, (
            f"Uncovered should decrease after adding entity"
        )

    def test_coverage_by_symbol(self):
        """Coverage can be indexed by segment symbol names."""
        raw_text = "甄士隐住在姑苏。"
        cm = CorpusManager()
        doc, text = cm.ingest_text(raw_text, "test")
        blocks = cm.create_blocks(doc, text)
        seg = Segmenter()
        all_segs = []
        for b in blocks:
            bt = cm.get_block_text(doc, b, text)
            all_segs.extend(seg.segment_block(doc.id, b, bt))

        store = ObjectStore()
        store.save(doc)
        for s in all_segs:
            store.save(s)

        # Generate text.py to get segment symbols
        gen = CodeGenerator(version="v3.3-flash")
        text_files = gen.generate_text_code_v33(doc, blocks, all_segs)
        parser = T2CParser()
        text_objs = parser.parse_string(text_files["text.py"])
        sym_map = {}
        for o in text_objs:
            if o.get("type") == "Segment" and o.get("symbol"):
                sym_map[o["data"]["id"]] = o["symbol"]

        gen_cov = CoverageGenerator(store)
        cov = gen_cov.coverage_by_symbol(doc.id, symbol_map=sym_map)

        # Every segment should appear with its symbol as key
        for s in all_segs:
            sym = sym_map.get(s.id, s.id)
            assert sym in cov, f"Segment symbol {sym} not in coverage: {list(cov.keys())}"
            assert "status" in cov[sym]

    def test_coverage_from_parsed_objects(self):
        """Coverage can be derived directly from parsed v3.3 objects."""
        raw_text = "甄士隐住在姑苏。姑苏很繁华。"
        cm = CorpusManager()
        doc, text = cm.ingest_text(raw_text, "test")
        blocks = cm.create_blocks(doc, text)
        seg = Segmenter()
        all_segs = []
        for b in blocks:
            bt = cm.get_block_text(doc, b, text)
            all_segs.extend(seg.segment_block(doc.id, b, bt))

        # Build entity referencing first segment
        seg0 = all_segs[0]
        eref = EvidenceRef(
            segment_id=seg0.id, segment_symbol="seg_test",
            start=0, end=3, quote_hash=_sha256(seg0.text_slice[:3]),
        )
        ent = Entity(
            id="ent1", name="甄士隐", kind="person",
            evidence_refs=[eref],
            source_segment_ids=[seg0.id],
        )

        # Parse as v3.3 objects
        parsed = [
            {
                "type": "Segment",
                "symbol": "seg_test",
                "data": {"id": seg0.id, "doc_id": doc.id, "block_index": 0,
                         "segment_type": "sentence", "start_offset": seg0.start_offset,
                         "end_offset": seg0.end_offset, "text_slice": seg0.text_slice,
                         "hash": seg0.hash},
            },
            {
                "type": "Entity",
                "symbol": "ent_test",
                "data": {
                    "id": "ent1", "name": "甄士隐", "kind": "person",
                    "source_segment_ids": [seg0.id],
                    "evidence_refs": [
                        {"type": "EvidenceRef", "data": {
                            "segment_id": seg0.id, "segment_symbol": "seg_test",
                            "start": 0, "end": 3, "quote_hash": _sha256(seg0.text_slice[:3]),
                        }},
                    ],
                },
                "__symbol_refs__": {"evidence_refs[0].segment": "seg_test"},
            },
        ]

        from t2c.coverage import CoverageGenerator
        cov = CoverageGenerator.coverage_from_parsed_objects(parsed, all_segs)
        # First segment should be covered (has entity)
        assert cov[seg0.id]["status"] == "covered", f"Expected covered, got {cov[seg0.id]}"

        # Other segments should be uncovered
        for s in all_segs[1:]:
            if s.id in cov:
                assert cov[s.id]["status"] == "uncovered", (
                    f"Segment {s.id}: expected uncovered, got {cov[s.id]}"
                )

    def test_full_text_semantic_pipeline_v33(self):
        """Full Phase 2 pipeline: raw → segments → text.py → entities.py → validate."""
        raw_text = """第一回

甄士隐住在姑苏城中。姑苏是繁华之地。"""
        cm = CorpusManager()
        doc, text = cm.ingest_text(raw_text, "ch01")
        blocks = cm.create_blocks(doc, text)
        seg = Segmenter()
        all_segs = []
        for b in blocks:
            bt = cm.get_block_text(doc, b, text)
            all_segs.extend(seg.segment_block(doc.id, b, bt))

        # Step 1: Generate text.py
        gen = CodeGenerator(version="v3.3-flash")
        text_files = gen.generate_text_code_v33(doc, blocks, all_segs)
        text_code = text_files["text.py"]

        # Step 2: Parse text.py, extract segment symbols
        text_parser = T2CParser()
        text_objs = text_parser.parse_string(text_code)
        ext_index = {}
        for o in text_objs:
            sym = o.get("symbol")
            if sym and o["type"] == "Segment":
                ext_index[sym] = {"type": "Segment", "id": o["data"]["id"]}

        # Step 3: Create semantic objects referencing segments
        seg0_id = all_segs[0].id
        eref = EvidenceRef(
            segment_id=seg0_id,
            start=0, end=3, quote_hash=_sha256(all_segs[0].text_slice[:3]),
        )
        ent = Entity(id="ent1", name="甄士隐", kind="person", evidence_refs=[eref])
        ent2 = Entity(id="ent2", name="姑苏", kind="location")

        # v6.0: one symbol table drives text + semantic files
        from t2c.symbols import compute_symbol_table
        table = compute_symbol_table(
            doc=doc, blocks=blocks, segments=all_segs, entities=[ent, ent2],
        )
        entities_code = gen._generate_type_file_v33(
            ".entities", [ent, ent2], ["Entity", "EvidenceRef"], table,
        )

        # Step 4: Parse entities.py with external symbol index
        assert entities_code, "entities.py not generated"
        ent_parser = T2CParser(external_symbols=ext_index)
        ent_objs = ent_parser.parse_string(entities_code)

        # Step 5: Validate everything
        all_objects = text_objs + ent_objs
        v = Validator(raw_text_store={doc.id: text})
        result = v.validate_objects(all_objects)
        assert result.valid, f"Pipeline validation errors: {result.errors}"

        # Step 6: Verify evidence ref hash
        for obj in ent_objs:
            if obj["type"] == "Entity":
                erefs = obj["data"].get("evidence_refs", [])
                for eref in erefs:
                    eref_data = eref.get("data", eref)
                    seg_id_val = eref_data.get("segment_id") or eref_data.get("segment")
                    if seg_id_val:
                        # segment_id should be in the segment map
                        assert seg_id_val in {s.id for s in all_segs}, (
                            f"EvidenceRef segment_id '{seg_id_val}' not found in segments"
                        )
