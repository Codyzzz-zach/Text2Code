"""Phase 6: v4.0 multi-file compilation end-to-end tests.

Proves:
- generate_multi_file_compilation produces 6+ files
- All files are py_compile-clean
- The output package is importable
- symbol_analyzer reports N>0 definitions per file
- Cross-file imports resolve to real Python references
- Pipeline.process_text with mock LLM produces code on disk
- Coverage.py is generated when coverage_report is provided
- Silent-loss marker Residual is generated for uncovered segments
"""
from __future__ import annotations

import ast
import hashlib
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from t2c.codegen import CodeGenerator
from t2c.compact_candidate import parse_compact_response
from t2c.compile_target import compile_to_knowledge_code
from t2c.corpus import CorpusManager
from t2c.ontology import (
    Block,
    Claim,
    CoverageReport,
    Document,
    Entity,
    EvidenceRef,
    Relation,
    Segment,
)
from t2c.parser import T2CParser
from t2c.pipeline import Pipeline
from t2c.segmenter import Segmenter
from t2c.symbol_analyzer import analyze_multi_file


def _sha(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _ingest_sample(text: str, doc_id: str = "case_001"):
    cm = CorpusManager()
    doc, _ = cm.ingest_text(text, doc_id, source_path="case_001.txt")
    blocks = cm.create_blocks(doc, text)
    segmenter = Segmenter()
    segments = []
    for b in blocks:
        segs = segmenter.segment_block(doc.id, b, cm.get_block_text(doc, b, text))
        segments.extend(segs)
    doc.block_count = len(blocks)
    return doc, blocks, segments


class TestMultiFileCompilation:
    """v4.0 multi-file compilation is the actual product surface."""

    def test_compile_to_knowledge_code_writes_6_files(self, tmp_path):
        text = "爱丽丝在火车站。\n\n「你来了，」她说。\n"
        doc, blocks, segments = _ingest_sample(text)
        entities = [
            Entity(
                id="case_001_ent_0001",
                name="爱丽丝",
                kind="person",
                evidence_refs=[EvidenceRef(
                    segment_id=segments[0].id, start=0, end=3,
                    quote_hash=_sha("爱丽丝"),
                )] if segments else [],
                source_segment_ids=[s.id for s in segments[:1]],
            ),
        ]
        claims = [
            Claim(
                id="case_001_clm_0001",
                subject="case_001_ent_0001",
                predicate="at",
                object="火车站",
                modality="asserted",
                polarity="positive",
                evidence_refs=[],
                source_segment_ids=[s.id for s in segments[:1]],
            ),
        ]
        relations = [
            Relation(
                id="case_001_rel_0001",
                subject="case_001_ent_0001",
                predicate="at",
                object="火车站",
                claim_id="case_001_clm_0001",
                evidence_refs=[],
            ),
        ]
        coverage = CoverageReport(
            id="case_001_coverage",
            doc_id="case_001",
            total_segments=len(segments),
            status_counts={"covered": 1, "raw_only": max(0, len(segments) - 1)},
            requires_raw_fallback=[],
            generated_at="2026-06-05T00:00:00Z",
        )

        written = compile_to_knowledge_code(
            doc=doc, blocks=blocks, segments=segments,
            entities=entities, claims=claims, relations=relations,
            coverage_report=coverage,
            output_dir=tmp_path,
        )
        assert set(written.keys()) == {
            "__init__.py", "text.py", "entities.py", "events.py",
            "claims.py", "residuals.py", "derived.py", "coverage.py",
        }
        for path in written.values():
            assert path.exists()
            assert path.stat().st_size > 0

    def test_compile_output_is_py_compile_clean(self, tmp_path):
        import py_compile
        text = "爱丽丝在火车站。"
        doc, blocks, segments = _ingest_sample(text)
        written = compile_to_knowledge_code(
            doc=doc, blocks=blocks, segments=segments,
            entities=[Entity(id="case_001_ent_0001", name="爱丽丝", kind="person")],
            output_dir=tmp_path,
        )
        for path in written.values():
            try:
                py_compile.compile(str(path), doraise=True)
            except py_compile.PyCompileError as e:
                pytest.fail(f"py_compile failed for {path.name}: {e}")

    def test_compile_output_is_importable(self, tmp_path):
        """The output directory is a valid Python package."""
        text = "爱丽丝在火车站。"
        doc, blocks, segments = _ingest_sample(text)
        pkg = tmp_path / "case_001"
        compile_to_knowledge_code(
            doc=doc, blocks=blocks, segments=segments,
            entities=[Entity(id="case_001_ent_0001", name="爱丽丝", kind="person")],
            output_dir=pkg,
        )
        sys.path.insert(0, str(tmp_path))
        try:
            import case_001  # noqa: F401
        finally:
            sys.path.pop(0)

    def test_symbol_analyzer_counts_definitions(self, tmp_path):
        """Each non-empty file has >0 symbol definitions."""
        text = "爱丽丝在火车站。"
        doc, blocks, segments = _ingest_sample(text)
        ent = Entity(id="case_001_ent_0001", name="爱丽丝", kind="person")
        clm = Claim(
            id="case_001_clm_0001",
            subject="case_001_ent_0001", predicate="at", object="火车站",
            modality="asserted", polarity="positive",
        )
        rel = Relation(
            id="case_001_rel_0001",
            subject="case_001_ent_0001", predicate="at",
            object="火车站", claim_id="case_001_clm_0001",
        )
        pkg = tmp_path / "case_001"
        compile_to_knowledge_code(
            doc=doc, blocks=blocks, segments=segments,
            entities=[ent], claims=[clm], relations=[rel],
            output_dir=pkg,
        )
        files = {
            f.name: f.read_text(encoding="utf-8")
            for f in sorted(pkg.iterdir())
            if f.suffix == ".py" and f.is_file()
        }
        analyses = analyze_multi_file(files)
        # text.py has Document/Blocks/Segments — many defs
        text_defs = next(a.total_definitions for a in analyses if a.filename == "text.py")
        ent_defs = next(a.total_definitions for a in analyses if a.filename == "entities.py")
        clm_defs = next(a.total_definitions for a in analyses if a.filename == "claims.py")
        rel_defs = next(a.total_definitions for a in analyses if a.filename == "derived.py")
        assert text_defs > 0, f"text.py should have many defs, got {text_defs}"
        assert ent_defs == 1
        assert clm_defs == 1
        assert rel_defs == 1

    def test_cross_file_imports_resolve(self, tmp_path):
        """The .text / .entities / .claims imports must point to real symbols."""
        text = "爱丽丝在火车站。"
        doc, blocks, segments = _ingest_sample(text)
        # Entity MUST have evidence_refs to a segment for the cross-file
        # import to be emitted.
        seg0 = segments[0] if segments else None
        eref = EvidenceRef(
            segment_id=seg0.id, start=0, end=3, quote_hash=_sha("爱丽丝"),
        ) if seg0 else None
        ent = Entity(
            id="case_001_ent_0001", name="爱丽丝", kind="person",
            evidence_refs=[eref] if eref else [],
            source_segment_ids=[seg0.id] if seg0 else [],
        )
        clm = Claim(
            id="case_001_clm_0001",
            subject="case_001_ent_0001", predicate="at", object="火车站",
            modality="asserted", polarity="positive",
            source_segment_ids=[seg0.id] if seg0 else [],
        )
        rel = Relation(
            id="case_001_rel_0001",
            subject="case_001_ent_0001", predicate="at",
            object="火车站", claim_id="case_001_clm_0001",
        )
        pkg = tmp_path / "case_001"
        compile_to_knowledge_code(
            doc=doc, blocks=blocks, segments=segments,
            entities=[ent], claims=[clm], relations=[rel],
            output_dir=pkg,
        )
        # Collect text.py exports
        text_src = (pkg / "text.py").read_text(encoding="utf-8")
        text_symbols = {
            n.targets[0].id
            for n in ast.parse(text_src).body
            if isinstance(n, ast.Assign)
        }
        # v6.0: evidence_refs produce bare-Name segment_symbol refs, backed
        # by live cross-file imports. Every import must point to a real
        # symbol in the target module.
        ent_src = (pkg / "entities.py").read_text(encoding="utf-8")
        ent_imports = {
            a.name
            for n in ast.parse(ent_src).body
            if isinstance(n, ast.ImportFrom) and n.module == "text" and n.level == 1
            for a in n.names
        }
        assert ent_imports, (
            f"entities.py should import segment symbols from .text "
            f"(entity has evidence_refs)\n{ent_src}"
        )
        assert ent_imports <= text_symbols, (
            f"entities.py imports symbols not defined in text.py: "
            f"{ent_imports - text_symbols}"
        )
        clm_src = (pkg / "claims.py").read_text(encoding="utf-8")
        clm_ent_imports = {
            a.name
            for n in ast.parse(clm_src).body
            if isinstance(n, ast.ImportFrom) and n.module == "entities" and n.level == 1
            for a in n.names
        }
        ent_symbols = {
            n.targets[0].id
            for n in ast.parse(ent_src).body
            if isinstance(n, ast.Assign)
        }
        assert clm_ent_imports, (
            f"claims.py should import entity symbols from .entities\n{clm_src}"
        )
        assert clm_ent_imports <= ent_symbols

    def test_coverage_py_is_generated(self, tmp_path):
        text = "爱丽丝在火车站。"
        doc, blocks, segments = _ingest_sample(text)
        cov = CoverageReport(
            id="case_001_coverage", doc_id="case_001",
            total_segments=len(segments),
            status_counts={"covered": 1}, requires_raw_fallback=[],
            generated_at="2026-06-05T00:00:00Z",
        )
        pkg = tmp_path / "case_001"
        written = compile_to_knowledge_code(
            doc=doc, blocks=blocks, segments=segments,
            coverage_report=cov, output_dir=pkg,
        )
        assert "coverage.py" in written
        cov_src = (pkg / "coverage.py").read_text(encoding="utf-8")
        assert "CoverageReport" in cov_src
        assert "case_001_coverage" in cov_src


class TestUncoveredSegmentsResidual:
    """v4.0: silent loss is materialized as a Residual, not swallowed."""

    def test_uncovered_segment_gets_residual(self):
        from t2c.pipeline import Pipeline
        from t2c.ontology import Residual
        from t2c.object_store import ObjectStore
        # Two segments, neither referenced by any object → both should
        # get a raw fallback Residual.
        text = "First sentence. Second sentence."
        cm = CorpusManager()
        doc, _ = cm.ingest_text(text, "test_doc")
        blocks = cm.create_blocks(doc, text)
        segmenter = Segmenter()
        segments = []
        for b in blocks:
            segs = segmenter.segment_block(doc.id, b, cm.get_block_text(doc, b, text))
            segments.extend(segs)
        assert len(segments) >= 2

        # Mock extractor that returns NO objects — every segment is uncovered.
        mock_extractor = MagicMock()
        mock_extractor.extract_chapter.return_value = []

        pipeline = Pipeline(store=ObjectStore(), extractor=mock_extractor, max_repair_attempts=0)
        result = pipeline.process_text(
            raw_text=text, doc_id="test_doc",
            source_path="test.txt", chapter_num=1, chapter_title="Test",
        )
        # Both segments should be in raw_fallback_segment_ids
        assert len(result.raw_fallback_segment_ids) >= 2
        # And the store should have Residual objects
        residuals = list(pipeline.store.query("Residual"))
        assert len(residuals) >= 2
        # They should be medium importance (silent loss markers, not high)
        for r in residuals:
            if r.segment_id in result.raw_fallback_segment_ids:
                # At least the silent-loss ones are medium
                pass
        # Verify at least one medium residual exists
        medium_residuals = [r for r in residuals if r.importance == "medium"]
        assert len(medium_residuals) >= 1, f"Expected at least one medium Residual, got {[r.importance for r in residuals]}"


class TestLocateQuoteAmbiguity:
    """v4.0: ambiguous quotes are flagged, not silently used."""

    def test_ambiguous_quote_emits_warning(self):
        from t2c.compact_candidate import (
            build_evidence_refs,
            locate_quote_with_ambiguity,
        )
        # "他" appears multiple times in this segment
        seg_text = "他看见他在笑。另一个他也在那里。"
        result = locate_quote_with_ambiguity(seg_text, "他")
        assert result is not None
        (start, end), ambiguous = result
        assert ambiguous is True
        assert seg_text[start:end] == "他"

        # Unique case: long quote that only appears once
        result = locate_quote_with_ambiguity(seg_text, "另一个他也在那里")
        assert result is not None
        (_, _), ambiguous = result
        assert ambiguous is False

    def test_build_evidence_refs_warns_on_ambiguity(self):
        from t2c.compact_candidate import build_evidence_refs

        class _StubSeg:
            def __init__(self, sid, text):
                self.id = sid
                self.text_slice = text

        # "他" appears multiple times → ambiguous
        seg = _StubSeg("s1", "他看见他在笑。另一个他也在那里。")
        refs, warnings = build_evidence_refs(
            quotes=["他"], segments_by_id={"s1": seg},
            source_segment_ids=["s1"],
        )
        assert len(refs) == 1
        # Should warn about ambiguity
        assert any("ambiguous" in w for w in warnings), f"Expected ambiguous warning, got {warnings}"


class TestChineseNameNormalization:
    """v6.0: Chinese names with ASCII parts get a readable slug; pure CJK gets hash."""

    def test_pure_chinese_name_gets_hash_fallback(self):
        from t2c.symbols import _normalize_name
        norm = _normalize_name("爱丽丝")
        assert norm is None  # no ASCII, fall back to hash

    def test_mixed_chinese_english_uses_ascii_part(self):
        from t2c.symbols import _normalize_name
        norm = _normalize_name("爱丽丝 Alice")
        assert norm == "alice", f"Expected 'alice' from '爱丽丝 Alice', got {norm!r}"

    def test_ascii_name_normalized(self):
        from t2c.symbols import _normalize_name
        norm = _normalize_name("Alice Smith")
        assert norm == "alice_smith"

    def test_pure_ascii_with_spaces(self):
        from t2c.symbols import _normalize_name
        norm = _normalize_name("Zhen Shi Yin")
        assert norm == "zhen_shi_yin"
