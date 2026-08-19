"""v6.0 codegraph contract tests — run verify_codegraph against a compiled package.

These tests compile a small synthetic book through the real codegen path and
assert the acceptance gates from spec/t2c_design_v6.0.md §4 hold on the
artifact: ARR=100%, live imports, self-declared symbols, import-as-validation
(C10), and hash replay (C12).
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from verify_codegraph import verify_package, _break_symbol  # noqa: E402

from t2c.compile_target import compile_to_knowledge_code  # noqa: E402
from t2c.corpus import CorpusManager  # noqa: E402
from t2c.ontology import Claim, Entity, EvidenceRef  # noqa: E402
from t2c.segmenter import Segmenter  # noqa: E402


def _sha(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _compile_fixture(tmp_path: Path) -> Path:
    raw_text = "甄士隐住在姑苏城中。姑苏是繁华之地。"
    cm = CorpusManager()
    doc, text = cm.ingest_text(raw_text, "book1")
    blocks = cm.create_blocks(doc, text)
    segmenter = Segmenter()
    segments = []
    for b in blocks:
        segments.extend(segmenter.segment_block(doc.id, b, cm.get_block_text(doc, b, text)))
    doc.block_count = len(blocks)

    seg0 = segments[0]
    eref = EvidenceRef(
        segment_id=seg0.id, start=0, end=3,
        quote_hash=_sha(seg0.text_slice[:3]),
    )
    ent1 = Entity(id="book1_ent_0001", name="甄士隐", kind="person",
                  evidence_refs=[eref], source_segment_ids=[seg0.id])
    ent2 = Entity(id="book1_ent_0002", name="姑苏", kind="location",
                  evidence_refs=[EvidenceRef(
                      segment_id=seg0.id, start=6, end=8,
                      quote_hash=_sha(seg0.text_slice[6:8]),
                  )])
    claim = Claim(
        id="book1_clm_0001", subject=ent1.id, predicate="lives_in", object=ent2.id,
        modality="asserted", polarity="positive",
        evidence_refs=[eref], source_segment_ids=[seg0.id],
    )

    pkg = tmp_path / "book1"
    compile_to_knowledge_code(
        doc=doc, blocks=blocks, segments=segments,
        entities=[ent1, ent2], claims=[claim],
        output_dir=pkg,
    )
    return pkg


def test_fixture_package_passes_contract(tmp_path):
    pkg = _compile_fixture(tmp_path)
    report = verify_package(pkg)
    failures = {
        name: check["detail"]
        for name, check in report["checks"].items()
        if not check["ok"]
    }
    assert report["ok"], f"contract failures: {failures}"


def test_arr_is_100_percent(tmp_path):
    pkg = _compile_fixture(tmp_path)
    report = verify_package(pkg)
    arr = report["checks"]["ARR"]["detail"]
    assert arr["total"] > 0, "fixture must contain at least one symbol reference"
    assert arr["ast_reference_rate"] == 1.0


def test_c10_break_symbol_negative(tmp_path):
    """Removing one entity definition must break package import (ImportError)."""
    pkg = _compile_fixture(tmp_path)
    # The entity is referenced by claims.py — removing it must be fatal.
    from t2c.symbols import compute_symbol_table
    from t2c.ontology import Entity as Ent
    ent1 = Ent(id="book1_ent_0001", name="甄士隐", kind="person")
    sym = compute_symbol_table(entities=[ent1]).symbol_for("book1_ent_0001")
    ok, msg = _break_symbol(pkg, sym)
    assert ok, msg


def test_dangling_fk_fails_at_codegen(tmp_path):
    """A Claim referencing a non-existent entity never reaches disk."""
    from t2c.symbols import CodegenSymbolError

    raw_text = "甄士隐住在姑苏城中。"
    cm = CorpusManager()
    doc, text = cm.ingest_text(raw_text, "book2")
    blocks = cm.create_blocks(doc, text)
    segments = []
    for b in blocks:
        segments.extend(Segmenter().segment_block(doc.id, b, cm.get_block_text(doc, b, text)))

    bad_claim = Claim(
        id="book2_clm_0001", subject="book2_ent_9999", predicate="lives_in",
        object=None, modality="asserted", polarity="positive",
    )
    with pytest.raises(CodegenSymbolError):
        compile_to_knowledge_code(
            doc=doc, blocks=blocks, segments=segments,
            claims=[bad_claim], output_dir=tmp_path / "book2",
        )
