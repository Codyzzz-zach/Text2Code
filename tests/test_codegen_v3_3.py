"""Tests for t2c/codegen.py — v3.3 assignment + symbol ref code generation."""
import ast

from t2c.codegen import CodeGenerator
from t2c.ontology import (
    Block,
    Claim,
    Document,
    Entity,
    EvidenceRef,
    Event,
    IgnoreSegment,
    Relation,
    Residual,
    Segment,
)
from t2c.parser import T2CParser


def _sha256(text: str) -> str:
    import hashlib
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


class TestV33CodeGeneration:
    """v3.3 assignment-based code generation."""

    def test_generate_text_code_v33_valid_python(self):
        gen = CodeGenerator(version="v3.3-flash")
        doc = Document(
            id="doc1", source_path="test.txt",
            raw_text_hash=_sha256("hello"), total_length=100,
            block_count=1, created_at="2026-01-01T00:00:00Z",
        )
        blk = Block(
            id="blk1", doc_id="doc1", index=0, block_type="paragraph",
            start_offset=0, end_offset=5, text_slice="hello",
            hash=_sha256("hello"),
        )
        seg = Segment(
            id="seg1", doc_id="doc1", block_index=0,
            segment_type="sentence", start_offset=0, end_offset=5,
            text_slice="hello", hash=_sha256("hello"),
        )
        files = gen.generate_text_code_v33(doc, [blk], [seg])
        assert "text.py" in files
        code = files["text.py"]
        # Must be valid Python
        compile(code, "<text.py>", "exec")
        # Must contain assignment
        assert " = Segment(" in code
        assert " = Document(" in code

    def test_segment_symbol_naming(self):
        gen = CodeGenerator(version="v3.3-flash")
        seg1 = Segment(
            id="seg1", doc_id="doc1", block_index=0,
            segment_type="sentence", start_offset=0, end_offset=5,
            text_slice="hello", hash=_sha256("hello"),
        )
        seg2 = Segment(
            id="seg2", doc_id="doc1", block_index=0,  # same block_index!
            segment_type="sentence", start_offset=5, end_offset=10,
            text_slice="world", hash=_sha256("world"),
        )
        doc = Document(
            id="doc1", source_path="test.txt",
            raw_text_hash=_sha256("hello"), total_length=100,
            block_count=1, created_at="2026-01-01T00:00:00Z",
        )
        files = gen.generate_text_code_v33(doc, [], [seg1, seg2])
        code = files["text.py"]
        # Sequential naming: segments after Document get seg_0001, seg_0002
        # (not block_index-based or suffix-based)
        assert " = Segment(" in code  # assignment format
        assert "seg_0000_1" not in code  # No suffix-based naming
        # Both segments should have consecutive symbols
        import re
        seg_syms = re.findall(r"(seg_\d+) = Segment\(", code)
        assert len(seg_syms) == 2, f"Expected 2 segment symbols, got {seg_syms}"
        # Symbols should be sequential
        nums = [int(s.split('_')[1]) for s in seg_syms]
        assert nums == sorted(nums), f"Segment symbols not sequential: {seg_syms}"

    def test_entity_with_evidence_symbol_ref(self):
        # v3.3 mode: emit symbol refs in EvidenceRef. Opt-in via flag.
        gen = CodeGenerator(version="v3.3-flash", emit_symbol_refs=True)
        seg = Segment(
            id="seg1", doc_id="doc1", block_index=0,
            segment_type="sentence", start_offset=0, end_offset=9,
            text_slice="甄士隐住在姑苏", hash=_sha256("甄士隐住在姑苏"),
        )
        eref = EvidenceRef(
            segment_id="seg1", segment_symbol="seg_0000",
            start=0, end=3, quote_hash=_sha256("甄士隐"),
        )
        ent = Entity(
            id="ent1", name="甄士隐", kind="person",
            evidence_refs=[eref],
        )

        # External symbols: seg1 → seg_0000
        ext_syms = {"seg1": "seg_0000"}
        files = gen.generate_semantic_code_v33([ent], external_symbols=ext_syms, external_file=".text")
        assert "entities.py" in files
        code = files["entities.py"]
        # Must be valid Python
        compile(code, "<entities.py>", "exec")
        # v3.3 mode: keyword is v3.3 alias 'segment' and value is symbol ref
        assert "segment=seg_0000" in code
        # Must import from .text
        assert "from .text import seg_0000" in code
        # Must have assignment
        assert "ent_zh_" in code
        assert " = Entity(" in code

    def test_claim_subject_object_symbol_ref(self):
        gen = CodeGenerator(version="v3.3-flash")
        seg = Segment(
            id="seg1", doc_id="doc1", block_index=0,
            segment_type="sentence", start_offset=0, end_offset=9,
            text_slice="甄士隐住在姑苏", hash=_sha256("甄士隐住在姑苏"),
        )
        eref = EvidenceRef(
            segment_id="seg1", segment_symbol="seg_0000",
            start=0, end=3, quote_hash=_sha256("甄士隐"),
        )
        ent1 = Entity(id="ent1", name="甄士隐", kind="person")
        ent2 = Entity(id="ent2", name="姑苏", kind="location")
        claim = Claim(
            id="clm1", subject="ent1", predicate="lives_in", object="ent2",
            modality="asserted", polarity="positive",
            evidence_refs=[eref],
        )
        # External seg symbols
        ext_syms = {"seg1": "seg_0000"}
        # Entity symbols (will be computed)
        files = gen.generate_semantic_code_v33(
            [ent1, ent2, claim],
            external_symbols=ext_syms,
            external_file=".text",
        )
        assert "claims.py" in files
        code = files["claims.py"]
        compile(code, "<claims.py>", "exec")
        # Subject and object should be entity symbol refs (not strings)
        # The entity symbols should appear in Claim arguments
        assert "subject=" in code
        assert "object=" in code

    def test_generated_code_roundtrip(self):
        """Generated v3.3 code must be parseable by the parser."""
        gen = CodeGenerator(version="v3.3-flash")
        doc = Document(
            id="doc1", source_path="test.txt",
            raw_text_hash=_sha256("hello"), total_length=100,
            block_count=1, created_at="2026-01-01T00:00:00Z",
        )
        seg = Segment(
            id="seg1", doc_id="doc1", block_index=0,
            segment_type="sentence", start_offset=0, end_offset=5,
            text_slice="hello", hash=_sha256("hello"),
        )
        files = gen.generate_text_code_v33(doc, [], [seg])
        code = files["text.py"]

        parser = T2CParser()
        objects = parser.parse_string(code)
        assert len(objects) >= 2  # Document + Segment
        # Verify symbols
        symbols = [o.get("symbol") for o in objects if o.get("symbol")]
        assert len(symbols) >= 2

    def test_symbol_names_stable(self):
        """Same input should produce same symbol names."""
        gen = CodeGenerator(version="v3.3-flash")
        seg = Segment(
            id="seg1", doc_id="doc1", block_index=0,
            segment_type="sentence", start_offset=0, end_offset=5,
            text_slice="hello", hash=_sha256("hello"),
        )
        doc = Document(
            id="doc1", source_path="test.txt",
            raw_text_hash=_sha256("hello"), total_length=100,
            block_count=1, created_at="2026-01-01T00:00:00Z",
        )
        files1 = gen.generate_text_code_v33(doc, [], [seg])
        files2 = gen.generate_text_code_v33(doc, [], [seg])
        assert files1["text.py"] == files2["text.py"]

    def test_claim_long_id_uses_hash(self):
        """Claims with long ASCII subject/object IDs should use hash names."""
        gen = CodeGenerator(version="v3.3-flash")
        claim = Claim(
            id="clm1",
            subject="hongloumeng_ent_0001",
            predicate="lives_in",
            object="hongloumeng_ent_0002",
            modality="asserted",
            polarity="positive",
        )
        symbols = gen._compute_symbol_names([claim])
        sym = symbols["clm1"]
        # Should be claim_zh_<hash>, not the full concatenated ID string
        assert sym.startswith("claim_zh_"), f"Expected hash-based name, got {sym}"
        assert len(sym) <= 18, f"Symbol too long: {sym}"

    def test_chinese_entity_hash_symbol(self):
        """Chinese entity names produce stable hash-based symbols."""
        gen = CodeGenerator(version="v3.3-flash")
        ent = Entity(id="ent1", name="甄士隐", kind="person")
        symbols = gen._compute_symbol_names([ent])
        sym = symbols["ent1"]
        # Should be ent_zh_<hash>
        assert sym.startswith("ent_zh_")
        assert len(sym) == len("ent_zh_") + 6  # 6 hex chars

    def test_derived_code_generation(self):
        gen = CodeGenerator(version="v3.3-flash")
        rel = Relation(
            id="rel1", subject="ent1", predicate="lives_in",
            object="ent2", claim_id="clm1",
        )
        ign = IgnoreSegment(id="ign1", segment_id="seg1", reason="page number")

        ext_syms = {"seg1": "seg_0000", "ent1": "ent_zh_abc123", "ent2": "ent_zh_def456", "clm1": "claim_zh_789abc"}
        files = gen.generate_semantic_code_v33(
            [rel, ign],
            external_symbols=ext_syms,
            external_file=".text",
        )
        assert "derived.py" in files
        code = files["derived.py"]
        compile(code, "<derived.py>", "exec")
        # Should contain Relation and IgnoreSegment
        assert "Relation(" in code
        assert "IgnoreSegment(" in code


class TestV33BackwardCompat:
    """Old codegen methods still work."""

    def test_old_generate_knowledge_code(self):
        gen = CodeGenerator()
        ent = Entity(id="ent1", name="Alice", kind="person")
        code = gen.generate_knowledge_code([ent])
        assert "Entity(" in code
        assert "ent1" in code
        compile(code, "<test>", "exec")

    def test_old_generate_segments_code(self):
        gen = CodeGenerator()
        seg = Segment(
            id="seg1", doc_id="doc1", block_index=0,
            segment_type="sentence", start_offset=0, end_offset=5,
            text_slice="hello", hash=_sha256("hello"),
        )
        code = gen.generate_segments_code([seg])
        assert "Segment(" in code
        compile(code, "<test>", "exec")
