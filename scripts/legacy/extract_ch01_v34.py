#!/usr/bin/env python3
"""Legacy v3.4 extraction script for 红楼梦 chapter 1.

This script demonstrates the v3.4 near-lossless candidate flow:
  Segment → Extract → Validate → Repair loop → Schema construct
  → Save validated → Raw fallback (for unrepairable segments).

It no longer writes product Knowledge Code. Use `t2c compile ... --llm`
for the current product path.
"""
from __future__ import annotations

import logging
import os
import re
import sys
import time
from pathlib import Path

# v3.4.2: respect explicit env override; default to the new compact-protocol
# budget (8192) when nothing is set. For a fair A/B against v3.4.1's verbose
# 32K runs, callers can export T2C_MAX_TOKENS=32768.
os.environ.setdefault("T2C_MAX_TOKENS", "8192")
# Cache mode: off (write nothing), read_write (default for first run),
# read_only (for second run / cost-zero repeat).
os.environ.setdefault("T2C_CACHE_MODE", "read_write")
os.environ.setdefault("T2C_CACHE_DIR", ".t2c_cache")

# Add project root to path
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

from t2c.extractor import LLMExtractor
from t2c.object_store import ObjectStore
from t2c.pipeline import Pipeline


def find_chapter_range(raw_text: str, chapter_num: int) -> tuple[int, int, str]:
    """Return (start, end, title) for the requested chapter.

    Chapters in 红楼梦.txt are headed by '第N回  TITLE' (Chinese numerals).
    """
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


# Anthropic Claude Sonnet 4.6 public pricing (USD per million tokens).
_PRICE_INPUT_PER_M = 3.0
_PRICE_OUTPUT_PER_M = 15.0


def _estimate_cost(input_tokens: int, output_tokens: int) -> float:
    """Estimate USD cost using Sonnet 4.6 public rates."""
    in_cost = input_tokens / 1_000_000 * _PRICE_INPUT_PER_M
    out_cost = output_tokens / 1_000_000 * _PRICE_OUTPUT_PER_M
    return in_cost + out_cost


def _print_telemetry(result) -> None:
    """Print v3.4.1 truncation/token/cost summary table."""
    in_t = result.total_input_tokens
    out_t = result.total_output_tokens
    api_s = result.api_elapsed_sec
    cost = _estimate_cost(in_t, out_t)
    print()
    print("Batch 截断汇总：")
    print(f"  batches_truncated: {result.batches_truncated}")
    print(f"  total_input_tokens:  {in_t:,}")
    print(f"  total_output_tokens: {out_t:,}")
    print(f"  api_elapsed:         {api_s:.1f}s")
    print(
        f"  cost_estimate:       ${cost:.4f}  "
        f"(Sonnet 4.6: ${_PRICE_INPUT_PER_M}/M in, ${_PRICE_OUTPUT_PER_M}/M out)"
    )


def main() -> int:
    raw_path = project_root / "data" / "rawtxt" / "红楼梦.txt"
    output_dir = project_root / "examples" / "knowledge"

    if not raw_path.exists():
        print(f"Error: Raw text not found at {raw_path}")
        return 1

    # Configure logging — console + file
    log_path = output_dir / "extraction_ch01_v34.log"
    output_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_path, mode="w", encoding="utf-8"),
        ],
    )
    logger = logging.getLogger("extract_v34")
    logger.info("=== v3.4 ch01 extraction started ===")

    raw_text = raw_path.read_text(encoding="utf-8")
    print(f"Loaded {raw_path} ({len(raw_text):,} characters)")

    # Chapter 1 boundaries
    doc_id = "hongloumeng"
    chapter_num = 1
    start, end, title = find_chapter_range(raw_text, chapter_num)
    chapter_text = raw_text[start:end]
    print(f"Chapter {chapter_num}: {title}")
    print(f"  Slice: offset {start}..{end} ({len(chapter_text):,} chars)")

    # Build the v3.4 Pipeline with a real LLMExtractor
    model = os.environ.get("ANTHROPIC_MODEL", "MiniMax-M3")
    base_url = os.environ.get("ANTHROPIC_BASE_URL", "https://api.minimaxi.com/anthropic")
    api_key = os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY")

    if not api_key:
        print("Error: ANTHROPIC_AUTH_TOKEN or ANTHROPIC_API_KEY not set")
        return 1

    print(f"Using model: {model}, base_url: {base_url}")

    extractor = LLMExtractor(model=model, api_key=api_key, base_url=base_url)
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

    print()
    print("=" * 60)
    print(f"v3.4 Pipeline result for 第{chapter_num}回: {title}")
    print("=" * 60)
    print(f"  Candidates extracted:  {len(result.objects)}")
    for t, c in sorted(type_counts.items()):
        print(f"    {t}: {c}")
    print(f"  Valid: {result.valid}")
    print(f"  Repair attempts: {result.repair_attempts}")
    print(f"  Saved to store:  {result.saved_count}")
    print(f"  Rejected by gate: {result.rejected_count}")
    print(f"  Raw fallback segments: {len(result.raw_fallback_segment_ids)}")
    print(f"  Errors: {len(result.errors)}")
    print(f"  Warnings: {len(result.warnings)}")
    print(f"  Elapsed: {elapsed:.1f}s")

    # v3.4.1: token / cost summary table
    _print_telemetry(result)
    if result.errors:
        for err in result.errors[:5]:
            print(f"    ERR: {err}")
    if result.raw_fallback_segment_ids:
        for seg_id in result.raw_fallback_segment_ids[:5]:
            print(f"    FALLBACK: {seg_id}")
    print()

    print("This legacy v3.4 script no longer writes Knowledge Code directly.")
    print("Use the product CLI instead:")
    print("  t2c compile data/rawtxt/红楼梦.txt --output examples/knowledge/hongloumeng/ch01 --llm")

    logger.info("=== v3.4 ch01 extraction done: %d candidates, %d saved, %d errors ===",
                len(result.objects), result.saved_count, len(result.errors))
    return 0


if __name__ == "__main__":
    sys.exit(main())
