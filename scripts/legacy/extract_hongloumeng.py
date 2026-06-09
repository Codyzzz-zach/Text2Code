#!/usr/bin/env python3
"""Extract semantic objects for 红楼梦 chapters 1-3 using LLM."""
from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

from t2c.pipeline import T2CPipeline


def main():
    raw_path = project_root / "data" / "rawtxt" / "红楼梦.txt"
    output_dir = project_root / "examples" / "knowledge"

    if not raw_path.exists():
        print(f"Error: Raw text not found at {raw_path}")
        sys.exit(1)

    # Configure logging — console + file
    log_path = output_dir / "extraction_errors.log"
    output_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_path, mode="w", encoding="utf-8"),
        ],
    )
    logger = logging.getLogger("extract")
    logger.info("=== Extraction run started ===")

    print(f"Reading {raw_path}...")
    raw_text = raw_path.read_text(encoding="utf-8")
    print(f"  Total length: {len(raw_text):,} characters")

    doc_id = "hongloumeng"
    chapters_to_extract = list(range(1, 4))  # Chapters 1-3

    # MiniMax M3 via Anthropic-compatible API
    model = os.environ.get("ANTHROPIC_MODEL", "MiniMax-M3")
    base_url = os.environ.get("ANTHROPIC_BASE_URL", "https://api.minimaxi.com/anthropic")
    api_key = os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY")

    if not api_key:
        print("Error: ANTHROPIC_AUTH_TOKEN or ANTHROPIC_API_KEY not set")
        sys.exit(1)

    print(f"Using model: {model}")
    print(f"API base URL: {base_url}")
    print(f"Extracting chapters: {chapters_to_extract}")
    print(f"Output directory: {output_dir}")
    print(f"Log file: {log_path}")
    print()

    pipeline = T2CPipeline(output_dir=output_dir, model=model, api_key=api_key, base_url=base_url)

    # Step 1: Generate text map (Document + Block + Segment)
    print("Step 1: Generating text map...")
    doc, blocks = pipeline.run_document(raw_text, doc_id)
    all_segments = pipeline.run_segments(doc, blocks, raw_text)
    print(f"  Document: {doc.id}")
    print(f"  Blocks: {len(blocks)}")
    print(f"  Segments: {len(all_segments)}")

    # Write text map code
    doc_path, seg_path = pipeline.write_text_map(doc, blocks, all_segments)
    print(f"  Written: {doc_path.name}, {seg_path.name}")
    print()

    # Step 2: Extract semantic objects chapter by chapter
    print("Step 2: Extracting semantic objects with LLM...")
    print("-" * 60)

    total_objects = 0
    total_entities = 0
    total_events = 0
    total_claims = 0
    total_relations = 0
    total_errors = 0
    total_warnings = 0

    results = pipeline.run_chapters(raw_text, doc_id, chapter_nums=chapters_to_extract, precomputed_segments=all_segments)

    for i, result in enumerate(results):
        ch_num = result["chapter_num"]
        title = result["title"]
        objects = result["semantic_objects"]
        validation = result["validation"]

        # Count by type
        entities = [o for o in objects if o.get("type") == "Entity"]
        events = [o for o in objects if o.get("type") == "Event"]
        claims = [o for o in objects if o.get("type") == "Claim"]
        relations = [o for o in objects if o.get("type") == "Relation"]

        print(f"  第{ch_num}回: {title}")
        print(f"    Entities: {len(entities)}, Events: {len(events)}, "
              f"Claims: {len(claims)}, Relations: {len(relations)}")
        if validation.errors:
            print(f"    Validation errors: {len(validation.errors)}")
            for err in validation.errors[:3]:
                print(f"      - {err}")
            if len(validation.errors) > 3:
                print(f"      ... and {len(validation.errors) - 3} more")
            total_errors += len(validation.errors)
        if validation.warnings:
            total_warnings += len(validation.warnings)

        # Write knowledge code
        if objects:
            path = pipeline.write_chapter_knowledge(ch_num, objects)
            print(f"    Written: {path.name}")

        total_objects += len(objects)
        total_entities += len(entities)
        total_events += len(events)
        total_claims += len(claims)
        total_relations += len(relations)

        # Small delay between chapters to avoid rate limits
        if i < len(results) - 1:
            time.sleep(2)

    # Step 3: Summary
    print()
    print("=" * 60)
    print("EXTRACTION COMPLETE")
    print("=" * 60)
    print(f"  Chapters processed: {len(results)}")
    print(f"  Total objects: {total_objects}")
    print(f"    Entities:   {total_entities}")
    print(f"    Events:     {total_events}")
    print(f"    Claims:     {total_claims}")
    print(f"    Relations:  {total_relations}")
    print(f"  Validation errors: {total_errors}")
    print(f"  Validation warnings: {total_warnings}")
    print(f"  Log file: {log_path}")
    print()

    # Step 4: Validate all generated knowledge files
    print("Step 3: Validating generated .t2c.py files...")
    from t2c.validator import Validator
    validator = Validator(raw_text_store={doc_id: raw_text})

    knowledge_files = sorted(output_dir.glob("hongloumeng_ch*.knowledge.t2c.py"))
    for kf in knowledge_files:
        result = validator.validate_file(kf)
        status = "VALID" if result.valid else "INVALID"
        print(f"  {kf.name}: {status}")
        if result.errors:
            for err in result.errors[:2]:
                print(f"    ERROR: {err}")
        if result.warnings:
            print(f"    Warnings: {len(result.warnings)}")

    print()
    print("Output files:")
    for f in sorted(output_dir.glob("hongloumeng*.t2c.py")):
        size = f.stat().st_size
        print(f"  {f.name} ({size:,} bytes)")

    logger.info("=== Extraction run complete: %d objects, %d errors ===", total_objects, total_errors)


if __name__ == "__main__":
    main()
