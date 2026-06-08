#!/usr/bin/env python3
"""Extract semantic objects for 红楼梦 chapter 10 using v4.1 multi-file output.

This script runs the full T2C pipeline on chapter 10 to establish a baseline
for the v4.1 iteration optimization plan. The output will be used to compute
Compile Quality Metrics (CQM) and identify optimization opportunities.

Output directory:
  examples/knowledge/hongloumeng/ch10/
    text.py / entities.py / events.py / claims.py / residuals.py / derived.py / coverage.py / __init__.py

Configuration via .env (T2C_LLM_*) or explicit LLMConfig.
"""
from __future__ import annotations

import json
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
    """Return (start, end, title) for the requested chapter.

    Supports Chinese numerals 一 through 十.
    """
    cn = "一二三四五六七八九十"
    if chapter_num < 1 or chapter_num > 10:
        raise ValueError(f"Chapter number {chapter_num} out of range (1-10)")

    # Handle 十 specially
    if chapter_num == 10:
        cur = "十"
        nxt = None  # No chapter 11 pattern needed for this script
        pattern = re.compile(rf"^第{cur}回\s+(.+)$", re.MULTILINE)
    else:
        cur = cn[chapter_num - 1]
        nxt = cn[chapter_num] if chapter_num < 10 else "十"
        pattern = re.compile(rf"^第{cur}回\s+(.+)$", re.MULTILINE)

    m = pattern.search(raw_text)
    if not m:
        raise ValueError(f"Chapter {chapter_num} (第{cur}回) not found")

    start = m.start()
    title = m.group(1).strip()

    # Find next chapter marker
    if chapter_num < 10:
        next_cn = cn[chapter_num]  # e.g., 十一 for chapter 11
        next_pattern = re.compile(rf"^第{next_cn}回\s+", re.MULTILINE)
        nm = next_pattern.search(raw_text, start + 1)
        end = nm.start() if nm else len(raw_text)
    else:
        # For chapter 10, look for 第十一回
        next_pattern = re.compile(rf"^第十一回\s+", re.MULTILINE)
        nm = next_pattern.search(raw_text, start + 1)
        end = nm.start() if nm else len(raw_text)

    return start, end, title


def _print_telemetry(result, model: str) -> None:
    """Print LLM telemetry with cost estimate."""
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


def collect_cqm_metrics(
    store: ObjectStore,
    result,
    doc_id: str,
    chapter_characters: list[str] | None = None,
) -> dict:
    """Collect Compile Quality Metrics (CQM) for the extraction.

    Args:
        store: ObjectStore with extracted objects
        result: PipelineResult from pipeline.process_text()
        doc_id: Document ID
        chapter_characters: Optional list of known character names in the chapter
                          (for recall calculation). If None, recall is not computed.

    Returns:
        dict with CQM metrics
    """
    entities = list(store.query("Entity"))
    events = list(store.query("Event"))
    claims = list(store.query("Claim"))
    relations = list(store.query("Relation"))
    residuals = list(store.query("Residual"))
    segments = list(store.query("Segment", doc_id=doc_id))

    # Entity metrics
    person_entities = [e for e in entities if getattr(e, "kind", "") == "person"]
    person_names = [getattr(e, "name", "") for e in person_entities]

    # Reference correctness (requires manual annotation - set to N/A for baseline)
    # This will be filled in manually after examining the output

    # Coverage metrics
    total_segments = len(segments)
    covered_segments = 0
    partial_segments = 0
    for seg in segments:
        # Check if segment is referenced by any semantic object
        seg_id = getattr(seg, "id", "")
        is_referenced = False
        ref_count = 0
        for obj in entities + events + claims:
            source_segs = getattr(obj, "source_segment_ids", []) or []
            if seg_id in source_segs:
                is_referenced = True
                ref_count += 1
            evidence_refs = getattr(obj, "evidence_refs", []) or []
            for eref in evidence_refs:
                if getattr(eref, "segment_id", "") == seg_id:
                    is_referenced = True
                    ref_count += 1
        if is_referenced:
            if ref_count >= 2:
                covered_segments += 1
            else:
                partial_segments += 1

    # Evidence coverage
    objects_with_evidence = 0
    total_semantic_objects = len(entities) + len(events) + len(claims)
    for obj in entities + events + claims:
        ev_refs = getattr(obj, "evidence_refs", []) or []
        if ev_refs:
            objects_with_evidence += 1

    # Residual distribution
    residual_categories: dict[str, int] = {}
    residual_importance: dict[str, int] = {}
    for r in residuals:
        cat = getattr(r, "category", "unknown")
        imp = getattr(r, "importance", "unknown")
        residual_categories[cat] = residual_categories.get(cat, 0) + 1
        residual_importance[imp] = residual_importance.get(imp, 0) + 1

    # Predicate vocabulary
    predicates_used: dict[str, int] = {}
    for c in claims:
        pred = getattr(c, "predicate", "")
        if pred:
            predicates_used[pred] = predicates_used.get(pred, 0) + 1

    # Compute metrics
    metrics = {
        "extraction_counts": {
            "entities_total": len(entities),
            "person_entities": len(person_entities),
            "events_total": len(events),
            "claims_total": len(claims),
            "relations_total": len(relations),
            "residuals_total": len(residuals),
            "segments_total": total_segments,
        },
        "entity_metrics": {
            "person_names_extracted": person_names,
            "person_count": len(person_entities),
        },
        "coverage_metrics": {
            "segments_total": total_segments,
            "segments_covered": covered_segments,
            "segments_partial": partial_segments,
            "segments_uncovered": total_segments - covered_segments - partial_segments,
            "coverage_rate": (covered_segments / total_segments * 100) if total_segments > 0 else 0,
        },
        "evidence_metrics": {
            "objects_with_evidence": objects_with_evidence,
            "total_semantic_objects": total_semantic_objects,
            "evidence_rate": (objects_with_evidence / total_semantic_objects * 100) if total_semantic_objects > 0 else 0,
        },
        "residual_metrics": {
            "total": len(residuals),
            "categories": residual_categories,
            "importance": residual_importance,
            "entropy": _compute_entropy(list(residual_categories.values())) + _compute_entropy(list(residual_importance.values())),
        },
        "predicate_metrics": {
            "predicates_used": predicates_used,
            "unique_predicates": len(predicates_used),
        },
        "pipeline_metrics": {
            "candidates_extracted": len(result.objects),
            "saved_count": result.saved_count,
            "rejected_count": result.rejected_count,
            "raw_fallback_segments": len(result.raw_fallback_segment_ids),
            "repair_attempts": result.repair_attempts,
            "errors_count": len(result.errors),
            "warnings_count": len(result.warnings),
        },
        "llm_telemetry": {
            "total_input_tokens": result.total_input_tokens,
            "total_output_tokens": result.total_output_tokens,
            "api_elapsed_sec": result.api_elapsed_sec,
        },
    }

    # Add recall if ground truth provided
    if chapter_characters:
        extracted_set = set(person_names)
        ground_truth_set = set(chapter_characters)
        true_positives = extracted_set & ground_truth_set
        false_negatives = ground_truth_set - extracted_set
        false_positives = extracted_set - ground_truth_set

        recall = len(true_positives) / len(ground_truth_set) * 100 if ground_truth_set else 0
        precision = len(true_positives) / len(extracted_set) * 100 if extracted_set else 0

        metrics["entity_metrics"].update({
            "ground_truth_characters": chapter_characters,
            "true_positives": list(true_positives),
            "false_negatives": list(false_negatives),
            "false_positives": list(false_positives),
            "recall_rate": recall,
            "precision_rate": precision,
        })

    return metrics


def _compute_entropy(counts: list[int]) -> float:
    """Compute Shannon entropy of a distribution."""
    import math
    total = sum(counts)
    if total == 0:
        return 0.0
    entropy = 0.0
    for c in counts:
        if c > 0:
            p = c / total
            entropy -= p * math.log2(p)
    return entropy


def main() -> int:
    # Paths - use data/rawtxt/ which is the actual location
    raw_path = project_root / "data" / "rawtxt" / "红楼梦.txt"
    output_dir = project_root / "examples" / "knowledge" / "hongloumeng" / "ch10"
    log_path = output_dir / "extraction_ch10_v4.log"
    metrics_path = output_dir / "cqm_baseline.json"

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
    logger = logging.getLogger("extract_ch10")
    logger.info("=== v4.1 ch10 baseline extraction started ===")

    # Build LLM config from .env
    cfg = LLMConfig.from_env()
    print(f"=== v4.1 ch10 baseline extraction ===")
    print(f"provider: {cfg.provider}")
    print(f"model:    {cfg.model}")
    print(f"base_url: {cfg.base_url}")
    print(f"api_key:  *** ({len(cfg.api_key)} chars)")
    print()

    raw_text = raw_path.read_text(encoding="utf-8")
    print(f"Loaded {raw_path} ({len(raw_text):,} characters)")

    # Slice to chapter 10
    doc_id = "hongloumeng"
    chapter_num = 10
    start, end, title = find_chapter_range(raw_text, chapter_num)
    chapter_text = raw_text[start:end]
    print(f"Chapter {chapter_num}: {title}")
    print(f"  Slice: offset {start}..{end} ({len(chapter_text):,} chars)")
    print()

    # Build the v4.1 Pipeline with the LLM extractor
    from t2c.extractor import LLMExtractor
    extractor = LLMExtractor(config=cfg)
    store = ObjectStore()
    pipeline = Pipeline(store=store, extractor=extractor, max_repair_attempts=2)

    t0 = time.time()
    result = pipeline.process_text(
        raw_text=chapter_text,
        doc_id=doc_id,
        source_path="data/rawtxt/红楼梦.txt",
        chapter_num=chapter_num,
        chapter_title=title,
    )
    elapsed = time.time() - t0

    # Count by type
    type_counts: dict[str, int] = {}
    for obj in result.objects:
        t = obj.get("type", "Unknown")
        type_counts[t] = type_counts.get(t, 0) + 1

    # Retrieve Pydantic models from store
    segments = list(store.query("Segment", doc_id=doc_id))
    entities = list(store.query("Entity"))
    events = list(store.query("Event"))
    claims = list(store.query("Claim"))
    relations = list(store.query("Relation"))
    residuals = list(store.query("Residual"))
    ignores = list(store.query("IgnoreSegment"))
    blocks = list(store.query("Block", doc_id=doc_id))
    docs = list(store.query("Document", id=doc_id))

    # Build CoverageReport
    cov_gen = CoverageGenerator(store)
    coverage_report = cov_gen.generate_coverage(doc_id)

    print()
    print("=" * 60)
    print(f"v4.1 Pipeline result for 第{chapter_num}回: {title}")
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

    # v4.1: write multi-file Knowledge Code
    print()
    print(f"Writing Knowledge Code to {output_dir} ...")
    written = compile_to_knowledge_code(
        doc=doc, blocks=blocks, segments=segments,
        entities=entities, events=events, claims=claims,
        residuals=residuals, ignores=ignores, relations=relations,
        coverage_report=coverage_report,
        output_dir=output_dir,
        version="v4.1",
    )
    total_bytes = 0
    for fname, fpath in sorted(written.items()):
        size = fpath.stat().st_size
        total_bytes += size
        print(f"  {fname:20s} {size:>10,} bytes")
    print(f"  Total: {len(written)} files, {total_bytes:,} bytes")

    # Parse-back verification
    print()
    print("Parse-back + symbol_analyzer verification...")
    from t2c.symbol_analyzer import analyze_multi_file, cross_file_reference_count
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

    # Collect CQM metrics
    print()
    print("Collecting CQM metrics...")

    # Chapter 10 known characters (ground truth for recall calculation)
    # 金寡妇(金荣之母), 胡氏(金荣之妻), 贾璜, 尤氏, 秦可卿, 张太医, 金荣, 宝玉(mentioned), 贾珍(mentioned)
    ch10_characters = [
        "金荣", "金寡妇", "胡氏", "贾璜", "尤氏", "秦可卿", "张太医",
        "宝玉", "贾珍", "秦钟", "智能", "凤姐",  # some may be mentioned only
    ]

    metrics = collect_cqm_metrics(store, result, doc_id, ch10_characters)

    # Print summary
    print()
    print("CQM Metrics Summary:")
    print(f"  Entities: {metrics['extraction_counts']['entities_total']} total, {metrics['extraction_counts']['person_entities']} person")
    if "recall_rate" in metrics["entity_metrics"]:
        print(f"  Entity Recall: {metrics['entity_metrics']['recall_rate']:.1f}%")
        print(f"  Entity Precision: {metrics['entity_metrics']['precision_rate']:.1f}%")
        print(f"  True Positives: {metrics['entity_metrics']['true_positives']}")
        print(f"  False Negatives: {metrics['entity_metrics']['false_negatives']}")
    print(f"  Coverage: {metrics['coverage_metrics']['coverage_rate']:.1f}% ({metrics['coverage_metrics']['segments_covered']}/{metrics['coverage_metrics']['segments_total']})")
    print(f"  Evidence Rate: {metrics['evidence_metrics']['evidence_rate']:.1f}%")
    print(f"  Residual Entropy: {metrics['residual_metrics']['entropy']:.2f}")
    print(f"  Unique Predicates: {metrics['predicate_metrics']['unique_predicates']}")

    # Save metrics to JSON
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)
    print(f"\nMetrics saved to {metrics_path}")

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
        "=== v4.1 ch10 done: %d candidates, %d saved, %d raw_fallback, %.1fs ===",
        len(result.objects), result.saved_count,
        len(result.raw_fallback_segment_ids), elapsed,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
