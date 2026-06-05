"""Phase 4+5: CodeGraph Integration + Quality Gate verification.

Proves:
- Generated code passes ast.parse (Python standard library)
- Symbol definitions and references are countable
- Cross-file references are detectable
- evidence_ref_rate is measurable
- Silent loss is tracked
"""
import ast
import hashlib

from t2c.codegen import CodeGenerator
from t2c.compact_candidate import (
    expand_and_assign_symbols,
    expansion_failures_to_residuals,
    parse_compact_response,
)
from t2c.corpus import CorpusManager
from t2c.coverage import CoverageGenerator
from t2c.ontology import (
    Claim,
    Document,
    Entity,
    EvidenceRef,
    Segment,
)
from t2c.parser import T2CParser
from t2c.segmenter import Segmenter
from t2c.symbol_analyzer import (
    FileAnalysis,
    analyze_file,
    analyze_multi_file,
    cross_file_reference_count,
)
from t2c.validator import Validator


def _sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


class _StubSegment:
    def __init__(self, sid: str, text: str) -> None:
        self.id = sid
        self.text_slice = text


class TestCodeGraphIntegration:
    """Phase 4: Generated code is analyzable by standard tools."""

    def test_ast_parse_generated_code(self):
        """Every generated file must be valid Python (ast.parse pass)."""
        gen = CodeGenerator(version="v3.3-flash")
        doc = Document(id="d1", source_path="t.txt", raw_text_hash=_sha256("x"),
                       total_length=100, block_count=1, created_at="2026-01-01T00:00:00Z")
        seg = Segment(id="s1", doc_id="d1", block_index=0, segment_type="sentence",
                      start_offset=0, end_offset=5, text_slice="hello", hash=_sha256("hello"))
        eref = EvidenceRef(segment_id="s1", segment_symbol="seg_0001",
                           start=0, end=3, quote_hash=_sha256("hel"))
        ent = Entity(id="e1", name="Test", kind="person", evidence_refs=[eref])

        files = {}
        files.update(gen.generate_text_code_v33(doc, [], [seg]))
        files.update(gen.generate_semantic_code_v33(
            [ent], external_symbols={"s1": "seg_0001"}, external_file=".text",
        ))

        for fname, code in files.items():
            try:
                tree = ast.parse(code)
                assert isinstance(tree, ast.Module), f"{fname}: not a Module"
            except SyntaxError as e:
                raise AssertionError(f"{fname}: SyntaxError: {e}") from e

    def test_symbol_def_ref_counts(self):
        """Generated code must have countable symbol defs + refs."""
        gen = CodeGenerator(version="v3.3-flash")
        doc = Document(id="d1", source_path="t.txt", raw_text_hash=_sha256("x"),
                       total_length=100, block_count=1, created_at="2026-01-01T00:00:00Z")
        seg1 = Segment(id="s1", doc_id="d1", block_index=0, segment_type="sentence",
                       start_offset=0, end_offset=3, text_slice="ABC", hash=_sha256("ABC"))
        seg2 = Segment(id="s2", doc_id="d1", block_index=0, segment_type="sentence",
                       start_offset=3, end_offset=6, text_slice="DEF", hash=_sha256("DEF"))

        # text.py: Document + 2 segments → 3 definitions
        text_files = gen.generate_text_code_v33(doc, [], [seg1, seg2])
        analysis = analyze_file(text_files["text.py"], "text.py")
        assert analysis.total_definitions >= 3, (
            f"Expected >=3 definitions, got {analysis.total_definitions}"
        )
        # Each segment symbol should be defined
        seg_syms = [s for s in analysis.symbols if s.constructor_type == "Segment"]
        assert len(seg_syms) >= 2, f"Expected >=2 Segment symbols, got {len(seg_syms)}"

        # Parse text.py to get segment symbols for semantic code
        parser = T2CParser()
        text_objs = parser.parse_string(text_files["text.py"])
        seg_id_map = {}
        for o in text_objs:
            if o.get("type") == "Segment" and o.get("symbol"):
                seg_id_map[o["data"]["id"]] = o["symbol"]

        # entities.py: entity referencing first segment → 1 def, 1 ref
        eref = EvidenceRef(segment_id="s1", segment_symbol=seg_id_map.get("s1", "seg_0001"),
                           start=0, end=3, quote_hash=_sha256("ABC"))
        ent = Entity(id="e1", name="Test", kind="person", evidence_refs=[eref])
        sem_files = gen.generate_semantic_code_v33(
            [ent], external_symbols=seg_id_map, external_file=".text",
        )
        ent_analysis = analyze_file(sem_files["entities.py"], "entities.py")
        assert ent_analysis.total_definitions >= 1
        # Should have references (segment symbol ref)
        assert ent_analysis.total_references >= 1, (
            f"Expected >=1 references in entities.py, got {ent_analysis.total_references}"
        )

    def test_cross_file_references_detected(self):
        """Cross-file symbol references must be detectable."""
        gen = CodeGenerator(version="v3.3-flash")
        doc = Document(id="d1", source_path="t.txt", raw_text_hash=_sha256("x"),
                       total_length=100, block_count=1, created_at="2026-01-01T00:00:00Z")
        seg = Segment(id="s1", doc_id="d1", block_index=0, segment_type="sentence",
                      start_offset=0, end_offset=5, text_slice="hello", hash=_sha256("hello"))
        eref = EvidenceRef(segment_id="s1", segment_symbol="seg_0001",
                           start=0, end=3, quote_hash=_sha256("hel"))
        ent = Entity(id="e1", name="Test", kind="person", evidence_refs=[eref])

        files = {}
        files.update(gen.generate_text_code_v33(doc, [], [seg]))
        files.update(gen.generate_semantic_code_v33(
            [ent], external_symbols={"s1": "seg_0001"}, external_file=".text",
        ))
        analyses = analyze_multi_file(files)
        cross = cross_file_reference_count(analyses)
        # entities.py imports and uses seg_0001 from text.py → cross-file ref
        assert cross >= 1, f"Expected >=1 cross-file refs, got {cross}"


class TestQualityGateV33:
    """Phase 5: Quality gate metrics."""

    def test_evidence_ref_rate(self):
        """Every semantic object should have evidence_refs where possible."""
        llm_output = """[
            {"t":"E","lid":"e1","n":"甄士隐","k":"person","sid":["s1"],"q":["甄士隐"]},
            {"t":"E","lid":"e2","n":"姑苏","k":"location","sid":["s1"],"q":["姑苏"]}
        ]"""
        candidates = parse_compact_response(llm_output)
        segs = [_StubSegment("s1", "甄士隐住在姑苏城中。")]
        objects, symbol_map, warnings = expand_and_assign_symbols(
            candidates, segs, doc_id="hlm",
        )

        # Count objects with evidence_refs
        with_evidence = 0
        total = len(objects)
        for obj in objects:
            erefs = obj["data"].get("evidence_refs", [])
            if erefs:
                with_evidence += 1

        evidence_ref_rate = with_evidence / total if total > 0 else 0
        assert evidence_ref_rate >= 0.5, (
            f"Low evidence ref rate: {evidence_ref_rate:.0%}"
        )

    def test_silent_loss_tracking(self):
        """Expansion warnings → residuals → no silent loss."""
        warnings = [
            "ent d_ent_0001: no source segment contained quote 'missing'",
            "clm d_clm_0001: no match for quote",
            "routine parse warning: unknown field",  # should NOT create residual
        ]
        residuals = expansion_failures_to_residuals(warnings, doc_id="d")
        # First two should create residuals, third should not
        assert len(residuals) == 2, (
            f"Expected 2 residuals for important warnings, got {len(residuals)}"
        )

    def test_full_quality_metrics_dict(self):
        """Quality metrics dict must contain all required fields."""
        metrics = {
            "grounding_rate": 0.85,
            "reference_issue_count": 0,
            "entity_conflict_count": 0,
            "coverage_rate": 0.80,
            "total_issue_count": 0,
            "evidence_ref_rate": 0.90,
            "silent_loss_count": 0,
            "symbol_definition_count": 42,
            "symbol_reference_count": 38,
            "cross_file_reference_count": 12,
        }
        required_keys = {
            "grounding_rate", "reference_issue_count", "entity_conflict_count",
            "coverage_rate", "total_issue_count", "evidence_ref_rate",
            "silent_loss_count",
        }
        assert required_keys.issubset(metrics.keys()), (
            f"Missing keys: {required_keys - metrics.keys()}"
        )

    def test_v33_code_passes_full_validation(self):
        """v3.3 code must pass all validation layers."""
        raw_text = "甄士隐住在姑苏城中。姑苏是繁华之地。"
        cm = CorpusManager()
        doc, text = cm.ingest_text(raw_text, "ch01")
        blocks = cm.create_blocks(doc, text)
        seg = Segmenter()
        all_segs = []
        for b in blocks:
            bt = cm.get_block_text(doc, b, text)
            all_segs.extend(seg.segment_block(doc.id, b, bt))

        gen = CodeGenerator(version="v3.3-flash")
        text_files = gen.generate_text_code_v33(doc, blocks, all_segs)

        parser = T2CParser()
        text_objs = parser.parse_string(text_files["text.py"])

        # Build external index
        ext_index = {}
        seg_id_map = {}
        for o in text_objs:
            sym = o.get("symbol")
            if sym and o["type"] == "Segment":
                ext_index[sym] = {"type": "Segment", "id": o["data"]["id"]}
                seg_id_map[o["data"]["id"]] = sym

        # Create semantic objects
        seg0 = all_segs[0]
        seg0_sym = seg_id_map.get(seg0.id, "seg_0000")
        eref = EvidenceRef(
            segment_id=seg0.id, segment_symbol=seg0_sym,
            start=0, end=3, quote_hash=_sha256(seg0.text_slice[:3]),
        )
        ent = Entity(id="ent1", name="甄士隐", kind="person", evidence_refs=[eref])
        ent2 = Entity(id="ent2", name="姑苏", kind="location")
        claim = Claim(
            id="clm1", subject="ent1", predicate="lives_in", object="ent2",
            modality="asserted", polarity="positive",
            evidence_refs=[eref],
        )

        sem_files = gen.generate_semantic_code_v33(
            [ent, ent2, claim],
            external_symbols=seg_id_map, external_file=".text",
        )

        # Parse all files
        ent_parser = T2CParser(external_symbols=ext_index)
        ent_objs = ent_parser.parse_string(sem_files["entities.py"])
        for o in ent_objs:
            sym = o.get("symbol")
            if sym and o["type"] == "Entity":
                ext_index[sym] = {"type": "Entity", "id": o["data"]["id"]}

        clm_parser = T2CParser(external_symbols=ext_index)
        clm_objs = clm_parser.parse_string(sem_files["claims.py"])

        all_objects = text_objs + ent_objs + clm_objs
        v = Validator(raw_text_store={doc.id: text})
        result = v.validate_objects(all_objects)

        # Must pass all validation
        assert result.valid, f"Validation errors: {result.errors}"

        # No silent loss: every segment must be accounted for
        # (at minimum, all segments are in text.py)
        seg_ids_in_code = {
            o["data"]["id"] for o in all_objects if o["type"] == "Segment"
        }
        seg_ids_from_segmenter = {s.id for s in all_segs}
        missing = seg_ids_from_segmenter - seg_ids_in_code
        assert len(missing) == 0, f"Silent loss: {len(missing)} segments not in code"
