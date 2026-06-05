"""End-to-end demo: case_001.txt → examples/knowledge/case_001/.

This script is the v4.0 end-to-end entry. It:
  1. Ingests raw text via CorpusManager
  2. Generates Block[] + Segment[]
  3. (No LLM in this demo — uses hardcoded entities/claims)
  4. Calls compile_to_knowledge_code to write 7 .t2c.py files
  5. Reports file sizes

Run:
  $ .venv/bin/python3 examples/run_case_001.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from t2c.compile_target import compile_to_knowledge_code
from t2c.corpus import CorpusManager
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
from t2c.segmenter import Segmenter
import hashlib


def sha(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def main() -> int:
    project_root = Path(__file__).resolve().parent.parent
    raw_path = project_root / "examples" / "corpus" / "case_001.txt"
    output_dir = project_root / "examples" / "knowledge" / "case_001"

    print(f"=== v4.0 end-to-end demo ===")
    print(f"raw text: {raw_path}")
    print(f"output:   {output_dir}")
    print()

    raw_text = raw_path.read_text(encoding="utf-8")
    print(f"raw text length: {len(raw_text):,} chars")

    # Step 1-3: ingest + block + segment
    cm = CorpusManager()
    doc, _ = cm.ingest_text(raw_text, doc_id="case_001", source_path=str(raw_path))
    blocks = cm.create_blocks(doc, raw_text)
    print(f"blocks: {len(blocks)}")

    segmenter = Segmenter()
    all_segments: list[Segment] = []
    for block in blocks:
        block_text = cm.get_block_text(doc, block, raw_text)
        segs = segmenter.segment_block(doc.id, block, block_text)
        all_segments.extend(segs)
    print(f"segments: {len(all_segments)}")

    # Update doc.block_count
    doc.block_count = len(blocks)

    # Step 4: hardcoded demo entities/claims (skip LLM for this fixture)
    seg_first = all_segments[0] if all_segments else None
    if seg_first is None:
        print("ERROR: no segments produced")
        return 1

    # The first segment contains "爱丽丝站在火车站的月台上，寒风刺骨。"
    # We craft entities/claims that reference it.
    entities = [
        Entity(
            id="case_001_ent_0001",
            name="爱丽丝",
            kind="person",
            evidence_refs=[EvidenceRef(
                segment_id=seg_first.id, start=0, end=3,
                quote_hash=sha("爱丽丝"),
            )],
            source_segment_ids=[seg_first.id],
        ),
        Entity(
            id="case_001_ent_0002",
            name="火车站",
            kind="location",
            evidence_refs=[EvidenceRef(
                segment_id=seg_first.id, start=4, end=7,
                quote_hash=sha("火车站"),
            )],
            source_segment_ids=[seg_first.id],
        ),
    ]
    claims = [
        Claim(
            id="case_001_clm_0001",
            subject="case_001_ent_0001",
            predicate="at",
            object="case_001_ent_0002",
            modality="asserted",
            polarity="positive",
            evidence_refs=[EvidenceRef(
                segment_id=seg_first.id, start=0, end=8,
                quote_hash=sha(seg_first.text_slice[0:8] if seg_first.text_slice else ""),
            )] if seg_first.text_slice and len(seg_first.text_slice) >= 8 else [],
            source_segment_ids=[seg_first.id],
        ),
    ]
    relations = [
        Relation(
            id="case_001_rel_0001",
            subject="case_001_ent_0001",
            predicate="at",
            object="case_001_ent_0002",
            claim_id="case_001_clm_0001",
            evidence_refs=[],
        ),
    ]
    coverage_report = CoverageReport(
        id="case_001_coverage",
        doc_id="case_001",
        total_segments=len(all_segments),
        status_counts={"covered": 1, "partial": 0, "raw_only": 0, "ignored": 0, "uncovered": max(0, len(all_segments) - 1)},
        requires_raw_fallback=[],
        generated_at="2026-06-05T00:00:00Z",
    )

    # Step 5: write to disk
    print()
    print("Writing Knowledge Code...")
    written = compile_to_knowledge_code(
        doc=doc,
        blocks=blocks,
        segments=all_segments,
        entities=entities,
        claims=claims,
        relations=relations,
        coverage_report=coverage_report,
        output_dir=output_dir,
    )
    for fname, fpath in sorted(written.items()):
        size = fpath.stat().st_size
        print(f"  {fname:20s} {size:>10,} bytes")
    print()
    print(f"Done. Total: {len(written)} files at {output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
