#!/usr/bin/env python3
"""Extract semantic objects for 红楼梦 chapter 1 using v4.0 multi-file output.

v4.0: writes a directory of files
  examples/knowledge/hongloumeng/ch01/
    text.py / entities.py / events.py / claims.py / residuals.py / derived.py / coverage.py / __init__.py

Configuration via .env (T2C_LLM_*) or explicit LLMConfig.
"""
from __future__ import annotations

import logging
import os
import re
import sys
import time
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from t2c.codegen import CodeGenerator
from t2c.compile_target import compile_to_knowledge_code
from t2c.coverage import CoverageGenerator
from t2c.llm_config import LLMConfig
from t2c.object_store import ObjectStore
from t2c.ontology import CoverageReport
from t2c.parser import T2CParser
from t2c.pipeline import Pipeline


def find_chapter_range(raw_text: str, chapter_num: int) -> tuple[int, int, str]:
    """Return (start, end, title) for the requested chapter."""
    cn = "一二三四五六七八九十百千"
    if chapter_num - 1 >= len(cn):
        raise ValueError(f"Chapter number {chapter_num} too large for CN numerals")
    cur = cn[chapter_num - 1]
    nxt = cn[chapter_num] if chapter_num < len(cn) else None
    pattern = re.compile(rf"^第{cur}回\s+(.+)$", re.MULTILINE)
    if nxt is not None:
        next_pattern = re.compile(rf"^第{nxt}回\s+", re.MULTILINE)
    else:
        next_pattern = None
    m = pattern.search(raw_text)
    if not m:
        raise ValueError(f"Chapter {chapter_num} (第{cur}回) not found")
    start = m.start()
    nm = next_pattern.search(raw_text, start + 1) if next_pattern else None
    end = nm.start() if nm else len(raw_text)
    title = m.group(1).strip()
    return start, end, title


def _print_telemetry(result, model: str) -> None:
    in_t = result.total_input_tokens
    out_t = result.total_output_tokens
    api_s = result.api_elapsed_sec
    # MiniMax public pricing
    PRICE_IN = 3.0
    PRICE_OUT = 15.0
    cost = (in_t / 1_000_000 * PRICE_IN) + (out_t / 1_000_000 * PRICE_OUT)
    print()
    print("LLM telemetry:")
    print(f"  model:                {model}")
    print(f"  total_input_tokens:   {in_t:,}")
    print(f"  total_output_tokens:  {out_t:,}")
    print(f"  api_elapsed:          {api_s:.1f}s")
    print(
        f"  cost_estimate:        ${cost:.4f}  "
        f"(MiniMax-M3: ${PRICE_IN}/M in, ${PRICE_OUT}/M out)"
    )


def main() -> int:
    raw_path = project_root / "rawtxt" / "红楼梦.txt"
    output_dir = project_root / "examples" / "knowledge" / "hongloumeng" / "ch01"
    log_path = output_dir / "extraction_ch01_v4.log"

    if not raw_path.exists():
        print(f"Error: Raw text not found at {raw_path}")
        return 1

    output_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_path, mode="w", encoding="utf-8"),
        ],
    )
    logger = logging.getLogger("extract_v4")
    logger.info("=== v4.0 ch01 extraction started ===")

    # Build LLM config from .env (or fall back to env vars)
    cfg = LLMConfig.from_env()
    print(f"=== v4.0 end-to-end extraction ===")
    print(f"provider: {cfg.provider}")
    print(f"model:    {cfg.model}")
    print(f"base_url: {cfg.base_url}")
    print(f"api_key:  *** ({len(cfg.api_key)} chars)")
    print()

    raw_text = raw_path.read_text(encoding="utf-8")
    print(f"Loaded {raw_path} ({len(raw_text):,} characters)")

    # Slice to chapter 1
    doc_id = "hongloumeng"
    chapter_num = 1
    start, end, title = find_chapter_range(raw_text, chapter_num)
    chapter_text = raw_text[start:end]
    print(f"Chapter {chapter_num}: {title}")
    print(f"  Slice: offset {start}..{end} ({len(chapter_text):,} chars)")
    print()

    # Build the v4.0 Pipeline with the LLM extractor
    from t2c.extractor import LLMExtractor
    extractor = LLMExtractor(config=cfg)
    store = ObjectStore()
    pipeline = Pipeline(store=store, extractor=extractor, max_repair_attempts=2)

    t0 = time.time()
    result = pipeline.process_text(
        raw_text=chapter_text,
        doc_id=doc_id,
        source_path="rawtxt/红楼梦.txt",
        chapter_num=chapter_num,
        chapter_title=title,
    )
    elapsed = time.time() - t0

    # Count by type
    type_counts: dict[str, int] = {}
    for obj in result.objects:
        t = obj.get("type", "Unknown")
        type_counts[t] = type_counts.get(t, 0) + 1

    # Retrieve Pydantic models from store to build coverage + code
    segments = list(store.query("Segment", doc_id=doc_id))
    entities = list(store.query("Entity"))
    events = list(store.query("Event"))
    claims = list(store.query("Claim"))
    relations = list(store.query("Relation"))
    residuals = list(store.query("Residual"))
    ignores = list(store.query("IgnoreSegment"))
    blocks = list(store.query("Block", doc_id=doc_id))
    docs = list(store.query("Document", id=doc_id))

    # Build CoverageReport via the existing generator
    cov_gen = CoverageGenerator(store)
    coverage_report = cov_gen.generate_coverage(doc_id)

    print()
    print("=" * 60)
    print(f"v4.0 Pipeline result for 第{chapter_num}回: {title}")
    print("=" * 60)
    print(f"  Candidates extracted:  {len(result.objects)}")
    for t, c in sorted(type_counts.items()):
        print(f"    {t}: {c}")
    print(f"  Saved to store:        {result.saved_count}")
    print(f"  Rejected by gate:      {result.rejected_count}")
    print(f"  Raw fallback segments: {len(result.raw_fallback_segment_ids)}")
    print(f"  Coverage:")
    for k, v in coverage_report.status_counts.items():
        print(f"    {k}: {v}")
    print(f"  Repair attempts: {result.repair_attempts}")
    print(f"  Errors:   {len(result.errors)}")
    print(f"  Warnings: {len(result.warnings)}")
    print(f"  Elapsed:  {elapsed:.1f}s")

    _print_telemetry(result, cfg.model)

    if not docs:
        print("ERROR: Document not in store")
        return 1
    doc = docs[0]

    # v4.0: write multi-file Knowledge Code
    print()
    print(f"Writing Knowledge Code to {output_dir} ...")
    written = compile_to_knowledge_code(
        doc=doc, blocks=blocks, segments=segments,
        entities=entities, events=events, claims=claims,
        residuals=residuals, ignores=ignores, relations=relations,
        coverage_report=coverage_report,
        output_dir=output_dir,
        version="v4.0-flash",
    )
    total_bytes = 0
    for fname, fpath in sorted(written.items()):
        size = fpath.stat().st_size
        total_bytes += size
        print(f"  {fname:20s} {size:>10,} bytes")
    print(f"  Total: {len(written)} files, {total_bytes:,} bytes")

    # Quick parse-back check
    print()
    print("Parse-back + symbol_analyzer verification...")
    from t2c.symbol_analyzer import analyze_multi_file, cross_file_reference_count
    import ast
    file_dict = {f.name: f.read_text(encoding="utf-8") for f in output_dir.iterdir() if f.suffix == ".py"}
    analyses = analyze_multi_file(file_dict)
    total_defs = sum(a.total_definitions for a in analyses)
    total_refs = sum(a.total_references for a in analyses)
    total_cross = cross_file_reference_count(analyses)
    print(f"  symbol defs:           {total_defs}")
    print(f"  symbol refs:           {total_refs}")
    print(f"  cross-file refs:       {total_cross}")
    print(f"  files analyzed:        {len(analyses)}")
    for a in analyses:
        print(f"    {a.filename:20s} defs={a.total_definitions:3d} cross={a.cross_file_ref_count:2d}")

    if result.errors:
        print()
        print("First 5 errors:")
        for err in result.errors[:5]:
            print(f"  ERR: {err}")
    if result.raw_fallback_segment_ids:
        print()
        print(f"First 5 raw fallback segments ({len(result.raw_fallback_segment_ids)} total):")
        for sid in result.raw_fallback_segment_ids[:5]:
            print(f"  FALLBACK: {sid}")

    logger.info(
        "=== v4.0 ch01 done: %d candidates, %d saved, %d raw_fallback, %.1fs ===",
        len(result.objects), result.saved_count,
        len(result.raw_fallback_segment_ids), elapsed,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
