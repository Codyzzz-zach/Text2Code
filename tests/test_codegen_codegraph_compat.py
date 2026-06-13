"""Tests for CodeGraph adaptation — v4.1 .t2c.py output.

Proves:
- emit_symbol_refs defaults to False (string literals, Pydantic-safe)
- Cross-file imports are complete for all file types (events, derived, claims)
- CoverageReport uses assignment format (not orphaned call)
- Inline comments provide FTS5-searchable Chinese names
- SYMBOL_REF_TO_FIELD populates _symbol fields from __symbol_refs__ metadata
- Symbol refs mode (emit_symbol_refs=True) is available but breaks Pydantic
"""
from __future__ import annotations

import ast
import hashlib

from t2c.codegen import CodeGenerator
from t2c.ontology import (
    Block,
    Claim,
    CoverageReport,
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
from t2c.schema import SchemaValidator


def _sha(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _make_doc_seg():
    """Create a minimal Document + Segment for test fixtures."""
    doc = Document(
        id="doc1", source_path="test.txt",
        raw_text_hash=_sha("甄士隐住在姑苏"), total_length=7,
        block_count=1, created_at="2026-01-01T00:00:00Z",
    )
    seg = Segment(
        id="seg1", doc_id="doc1", block_index=0,
        segment_type="sentence", start_offset=0, end_offset=7,
        text_slice="甄士隐住在姑苏", hash=_sha("甄士隐住在姑苏"),
    )
    blk = Block(
        id="blk1", doc_id="doc1", index=0, block_type="paragraph",
        start_offset=0, end_offset=7, text_slice="甄士隐住在姑苏",
        hash=_sha("甄士隐住在姑苏"),
    )
    return doc, blk, seg


# ---------------------------------------------------------------------------
# Step 2: emit_symbol_refs default
# ---------------------------------------------------------------------------


class TestEmitSymbolRefsDefault:
    """emit_symbol_refs defaults to False (Pydantic-safe string literals)."""

    def test_default_emit_symbol_refs_is_false(self):
        gen = CodeGenerator()
        assert gen._emit_symbol_refs is False

    def test_explicit_false_produces_string_literals(self):
        """When emit_symbol_refs=False, reference fields use string literals."""
        gen = CodeGenerator(emit_symbol_refs=False)
        _, _, seg = _make_doc_seg()
        ent1 = Entity(id="ent1", name="甄士隐", kind="person")
        ent2 = Entity(id="ent2", name="姑苏", kind="location")
        claim = Claim(
            id="clm1", subject="ent1", predicate="lives_in", object="ent2",
            modality="asserted", polarity="positive",
        )
        ext_syms = {"seg1": "seg_0001"}
        files = gen.generate_semantic_code_v33(
            [ent1, ent2, claim],
            external_symbols=ext_syms, external_file=".text",
        )
        code = files["claims.py"]
        # String literal mode: subject='ent1', not subject=ent_zh_...
        assert "subject='ent1'" in code
        assert "object='ent2'" in code

    def test_string_literals_in_multi_file_output(self):
        """Multi-file compilation emits string literals by default (Pydantic-safe)."""
        doc, blk, seg = _make_doc_seg()
        ent1 = Entity(id="ent1", name="甄士隐", kind="person")
        ent2 = Entity(id="ent2", name="姑苏", kind="location")
        claim = Claim(
            id="clm1", subject="ent1", predicate="lives_in", object="ent2",
            modality="asserted", polarity="positive",
            evidence_refs=[EvidenceRef(
                segment_id="seg1", start=0, end=3, quote_hash=_sha("甄士隐"),
            )],
        )
        rel = Relation(
            id="rel1", subject="ent1", predicate="lives_in",
            object="ent2", claim_id="clm1",
        )

        gen = CodeGenerator()
        files = gen.generate_multi_file_compilation(
            doc=doc, blocks=[blk], segments=[seg],
            entities=[ent1, ent2], claims=[claim], relations=[rel],
        )

        # claims.py should use string literals for subject/object
        claims_code = files["claims.py"]
        assert "subject='ent1'" in claims_code, f"Expected string literal in claims.py, got: {claims_code}"
        assert "object='ent2'" in claims_code

        # derived.py should use string literals for subject/object/claim
        derived_code = files["derived.py"]
        assert "subject='ent1'" in derived_code
        assert "object='ent2'" in derived_code
        assert "claim_id='clm1'" in derived_code

    def test_symbol_refs_available_when_explicitly_enabled(self):
        """emit_symbol_refs=True produces symbol refs (but breaks Pydantic)."""
        doc, blk, seg = _make_doc_seg()
        ent1 = Entity(id="ent1", name="甄士隐", kind="person")
        ent2 = Entity(id="ent2", name="姑苏", kind="location")
        claim = Claim(
            id="clm1", subject="ent1", predicate="lives_in", object="ent2",
            modality="asserted", polarity="positive",
        )

        gen = CodeGenerator(emit_symbol_refs=True)
        files = gen.generate_multi_file_compilation(
            doc=doc, blocks=[blk], segments=[seg],
            entities=[ent1, ent2], claims=[claim],
        )

        # Symbol ref mode: subject=ent_zh_..., not subject='ent1'
        claims_code = files["claims.py"]
        assert "subject=ent_" in claims_code, f"Expected symbol ref in claims.py, got: {claims_code}"


# ---------------------------------------------------------------------------
# Step 1: Cross-file imports for events.py and derived.py
# ---------------------------------------------------------------------------


class TestCrossFileImports:
    """All semantic files must import the symbols they reference."""

    def test_events_py_imports_entity_symbols(self):
        """events.py imports entity symbols only when emit_symbol_refs=True."""
        doc, blk, seg = _make_doc_seg()
        ent = Entity(id="ent1", name="甄士隐", kind="person")
        evt = Event(
            id="evt1", name="甄士隐梦游太虚", kind="dream",
            participants=["ent1"],
            evidence_refs=[EvidenceRef(
                segment_id="seg1", start=0, end=3, quote_hash=_sha("甄士隐"),
            )],
        )

        # Default mode (emit_symbol_refs=False): no dead imports
        gen = CodeGenerator()
        files = gen.generate_multi_file_compilation(
            doc=doc, blocks=[blk], segments=[seg],
            entities=[ent], events=[evt],
        )
        events_code = files["events.py"]
        # P4-2: no imports when emit_symbol_refs=False (dead imports removed)
        assert "from .entities import" not in events_code, (
            f"events.py should NOT import from .entities when emit_symbol_refs=False\n{events_code}"
        )
        # participants use string literals (Pydantic-safe)
        assert "participants=['ent1']" in events_code

        # Symbol ref mode: imports present
        gen_sym = CodeGenerator(emit_symbol_refs=True)
        files_sym = gen_sym.generate_multi_file_compilation(
            doc=doc, blocks=[blk], segments=[seg],
            entities=[ent], events=[evt],
        )
        events_sym_code = files_sym["events.py"]
        assert "from .entities import" in events_sym_code, (
            f"events.py should import from .entities when emit_symbol_refs=True\n{events_sym_code}"
        )

    def test_derived_py_imports_entity_and_claim_symbols(self):
        """derived.py imports only when emit_symbol_refs=True."""
        doc, blk, seg = _make_doc_seg()
        ent1 = Entity(id="ent1", name="甄士隐", kind="person")
        ent2 = Entity(id="ent2", name="姑苏", kind="location")
        claim = Claim(
            id="clm1", subject="ent1", predicate="lives_in", object="ent2",
            modality="asserted", polarity="positive",
        )
        rel = Relation(
            id="rel1", subject="ent1", predicate="lives_in",
            object="ent2", claim_id="clm1",
        )

        # Default mode (emit_symbol_refs=False): no dead imports
        gen = CodeGenerator()
        files = gen.generate_multi_file_compilation(
            doc=doc, blocks=[blk], segments=[seg],
            entities=[ent1, ent2], claims=[claim], relations=[rel],
        )

        derived_code = files["derived.py"]
        # P4-2: no imports when emit_symbol_refs=False
        assert "from .entities import" not in derived_code, (
            f"derived.py should NOT import from .entities when emit_symbol_refs=False\n{derived_code}"
        )
        assert "from .claims import" not in derived_code, (
            f"derived.py should NOT import from .claims when emit_symbol_refs=False\n{derived_code}"
        )

        # Symbol ref mode: imports present
        gen_sym = CodeGenerator(emit_symbol_refs=True)
        files_sym = gen_sym.generate_multi_file_compilation(
            doc=doc, blocks=[blk], segments=[seg],
            entities=[ent1, ent2], claims=[claim], relations=[rel],
        )
        derived_sym = files_sym["derived.py"]
        assert "from .entities import" in derived_sym
        assert "from .claims import" in derived_sym

    def test_events_py_no_entity_imports_when_no_entities(self):
        """events.py should not import from .entities when no entities exist."""
        doc, blk, seg = _make_doc_seg()
        evt = Event(
            id="evt1", name="甄士隐梦游太虚", kind="dream",
            participants=["ent1"],  # references non-existent entity
        )

        gen = CodeGenerator()
        files = gen.generate_multi_file_compilation(
            doc=doc, blocks=[blk], segments=[seg],
            events=[evt],
        )

        events_code = files["events.py"]
        # No .entities import when no entity symbols available
        assert "from .entities import" not in events_code


# ---------------------------------------------------------------------------
# Step 3: CoverageReport assignment format
# ---------------------------------------------------------------------------


class TestCoverageReportAssignment:
    """CoverageReport must be an assignment for CodeGraph indexing."""

    def test_coverage_report_is_assignment(self):
        gen = CodeGenerator()
        cov = CoverageReport(
            id="doc1_coverage", doc_id="doc1",
            total_segments=5, status_counts={"covered": 3},
            requires_raw_fallback=[], generated_at="2026-06-05T00:00:00Z",
        )
        code = gen.generate_coverage_code(cov)
        assert "coverage_report = CoverageReport(" in code
        # Parse it to verify it's valid Python with an assignment
        tree = ast.parse(code)
        assigns = [n for n in tree.body if isinstance(n, ast.Assign)]
        assert len(assigns) >= 1
        target = assigns[0].targets[0]
        assert isinstance(target, ast.Name)
        assert target.id == "coverage_report"


# ---------------------------------------------------------------------------
# Step 4: Inline comments for FTS5 searchability
# ---------------------------------------------------------------------------


class TestFTS5Comments:
    """Inline comments make Chinese names searchable via CodeGraph FTS5."""

    def test_entity_assignment_has_name_comment(self):
        doc, blk, seg = _make_doc_seg()
        ent = Entity(id="ent1", name="甄士隐", kind="person")

        gen = CodeGenerator()
        files = gen.generate_multi_file_compilation(
            doc=doc, blocks=[blk], segments=[seg],
            entities=[ent],
        )
        entities_code = files["entities.py"]
        assert "# 甄士隐 (person)" in entities_code

    def test_event_assignment_has_name_comment(self):
        doc, blk, seg = _make_doc_seg()
        evt = Event(id="evt1", name="甄士隐梦游太虚", kind="dream")

        gen = CodeGenerator()
        files = gen.generate_multi_file_compilation(
            doc=doc, blocks=[blk], segments=[seg],
            events=[evt],
        )
        events_code = files["events.py"]
        assert "# 甄士隐梦游太虚" in events_code

    def test_segment_assignment_has_text_comment(self):
        doc, blk, seg = _make_doc_seg()

        gen = CodeGenerator()
        files = gen.generate_multi_file_compilation(
            doc=doc, blocks=[blk], segments=[seg],
        )
        text_code = files["text.py"]
        # Segment comment should contain a preview of the text
        assert "# 甄士隐住在姑苏" in text_code

    def test_long_segment_text_is_truncated(self):
        """Segment comments truncate long text with ..."""
        long_text = "这是一个非常长的段落" * 10  # > 40 chars
        doc = Document(
            id="doc1", source_path="test.txt",
            raw_text_hash=_sha(long_text), total_length=len(long_text),
            block_count=1, created_at="2026-01-01T00:00:00Z",
        )
        blk = Block(
            id="blk1", doc_id="doc1", index=0, block_type="paragraph",
            start_offset=0, end_offset=len(long_text), text_slice=long_text,
            hash=_sha(long_text),
        )
        seg = Segment(
            id="seg1", doc_id="doc1", block_index=0,
            segment_type="sentence", start_offset=0, end_offset=len(long_text),
            text_slice=long_text, hash=_sha(long_text),
        )

        gen = CodeGenerator()
        files = gen.generate_multi_file_compilation(
            doc=doc, blocks=[blk], segments=[seg],
        )
        text_code = files["text.py"]
        assert "..." in text_code  # truncated

    def test_comment_does_not_break_parser(self):
        """Generated code with comments is still parseable by T2CParser."""
        doc, blk, seg = _make_doc_seg()
        ent = Entity(id="ent1", name="甄士隐", kind="person",
                     evidence_refs=[EvidenceRef(
                         segment_id="seg1", start=0, end=3, quote_hash=_sha("甄士隐"),
                     )])

        gen = CodeGenerator()
        files = gen.generate_multi_file_compilation(
            doc=doc, blocks=[blk], segments=[seg],
            entities=[ent],
        )

        # Parse text.py
        text_objects = T2CParser().parse_string(files["text.py"])
        assert len(text_objects) >= 2

        # Parse entities.py with external symbols
        seg_syms = {
            o.get("symbol", ""): {"type": o.get("type", ""), "id": o.get("data", {}).get("id", "")}
            for o in text_objects if o.get("symbol")
        }
        ent_objects = T2CParser(external_symbols=seg_syms).parse_string(files["entities.py"])
        assert len(ent_objects) >= 1


# ---------------------------------------------------------------------------
# Step 5: SYMBOL_REF_TO_FIELD wiring in SchemaValidator
# ---------------------------------------------------------------------------


class TestSymbolRefToField:
    """__symbol_refs__ metadata populates _symbol fields on Pydantic models."""

    def test_symbol_refs_populate_claim_symbol_fields(self):
        claim_dict = {
            "type": "Claim",
            "data": {
                "id": "clm1",
                "subject": "ent1",
                "predicate": "lives_in",
                "object": "ent2",
                "modality": "asserted",
                "polarity": "positive",
            },
            "__symbol_refs__": {"subject": "ent_zhen", "object": "ent_gusu"},
        }
        sv = SchemaValidator()
        models, violations = sv.validate_and_construct([claim_dict])
        assert not violations, f"Unexpected violations: {violations}"
        assert len(models) == 1
        claim = models[0]
        assert claim.subject_symbol == "ent_zhen"
        assert claim.object_symbol == "ent_gusu"

    def test_symbol_refs_populate_evidence_ref_segment_symbol(self):
        eref_dict = {
            "type": "EvidenceRef",
            "data": {
                "segment_id": "seg1",
                "start": 0,
                "end": 3,
                "quote_hash": "sha256:abc",
            },
            "__symbol_refs__": {"segment": "seg_0001"},
        }
        sv = SchemaValidator()
        models, violations = sv.validate_and_construct([eref_dict])
        assert not violations, f"Unexpected violations: {violations}"
        assert len(models) == 1
        eref = models[0]
        assert eref.segment_symbol == "seg_0001"

    def test_symbol_refs_populate_event_participant_symbols(self):
        event_dict = {
            "type": "Event",
            "data": {
                "id": "evt1",
                "name": "甄士隐梦游太虚",
                "kind": "dream",
                "participants": ["ent1", "ent2"],
            },
            "__symbol_refs__": {
                "participants[0]": "ent_zhen",
                "participants[1]": "ent_gusu",
            },
        }
        sv = SchemaValidator()
        models, violations = sv.validate_and_construct([event_dict])
        assert not violations, f"Unexpected violations: {violations}"
        assert len(models) == 1
        evt = models[0]
        assert evt.participant_symbols == ["ent_zhen", "ent_gusu"]

    def test_symbol_refs_populate_relation_symbol_fields(self):
        rel_dict = {
            "type": "Relation",
            "data": {
                "id": "rel1",
                "subject": "ent1",
                "predicate": "lives_in",
                "object": "ent2",
                "claim_id": "clm1",
            },
            "__symbol_refs__": {
                "subject": "ent_zhen",
                "object": "ent_gusu",
                "claim": "claim_lives",
            },
        }
        sv = SchemaValidator()
        models, violations = sv.validate_and_construct([rel_dict])
        assert not violations, f"Unexpected violations: {violations}"
        assert len(models) == 1
        rel = models[0]
        assert rel.subject_symbol == "ent_zhen"
        assert rel.object_symbol == "ent_gusu"
        assert rel.claim_symbol == "claim_lives"

    def test_no_symbol_refs_no_symbol_fields(self):
        """Objects without __symbol_refs__ have default None/[] symbol fields."""
        claim_dict = {
            "type": "Claim",
            "data": {
                "id": "clm1",
                "subject": "ent1",
                "predicate": "lives_in",
                "object": "ent2",
                "modality": "asserted",
                "polarity": "positive",
            },
        }
        sv = SchemaValidator()
        models, violations = sv.validate_and_construct([claim_dict])
        assert not violations
        assert len(models) == 1
        claim = models[0]
        assert claim.subject_symbol is None
        assert claim.object_symbol is None

    def test_event_participant_symbols_empty_without_refs(self):
        """Event without __symbol_refs__ has empty participant_symbols."""
        event_dict = {
            "type": "Event",
            "data": {
                "id": "evt1",
                "name": "event",
                "kind": "action",
                "participants": ["ent1"],
            },
        }
        sv = SchemaValidator()
        models, violations = sv.validate_and_construct([event_dict])
        assert not violations
        assert models[0].participant_symbols == []
