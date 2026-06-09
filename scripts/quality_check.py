#!/usr/bin/env python3
"""Quality check: compare extracted knowledge code against raw text for grounding & integrity.

v3.3: added --json output and --fail-under threshold support.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from t2c.corpus import CorpusManager
from t2c.ontology import Claim, Entity, Event, Relation, Segment
from t2c.parser import T2CParser
from t2c.segmenter import Segmenter


def load_raw_text() -> str:
    raw_path = project_root / "data" / "rawtxt" / "红楼梦.txt"
    return raw_path.read_text(encoding="utf-8")


def find_chapter_boundaries(raw_text: str) -> list[tuple[int, str, int, int]]:
    chapters = list(re.finditer(r"第[一二三四五六七八九十百千零\d]+回", raw_text))
    boundaries = []
    for i, m in enumerate(chapters):
        title = raw_text[m.start():m.start() + 40].split("\n")[0].strip()
        start = m.start()
        end = chapters[i + 1].start() if i + 1 < len(chapters) else len(raw_text)
        boundaries.append((i + 1, title, start, end))
    return boundaries


def build_all_data(raw_text: str) -> tuple[dict[str, str], list[Segment]]:
    """Build segment map and segment objects once."""
    cm = CorpusManager()
    doc, _ = cm.ingest_text(raw_text, "hongloumeng")
    blocks = cm.create_blocks(doc, raw_text)
    seg = Segmenter()
    all_segs: list[Segment] = []
    for b in blocks:
        bt = raw_text[b.start_offset:b.end_offset]
        all_segs.extend(seg.segment_block(doc.id, b, bt))
    seg_map = {s.id: s.text_slice for s in all_segs}
    return seg_map, all_segs


def parse_knowledge_file(path: Path) -> dict[str, list]:
    """Parse a .t2c.py knowledge file into typed lists."""
    from t2c.schema import SchemaValidator
    code = path.read_text(encoding="utf-8")
    parser = T2CParser()
    raw_objects = parser.parse_string(code)

    # Group by type
    entities_raw = [o for o in raw_objects if o.get("type") == "Entity"]
    events_raw = [o for o in raw_objects if o.get("type") == "Event"]
    claims_raw = [o for o in raw_objects if o.get("type") == "Claim"]
    relations_raw = [o for o in raw_objects if o.get("type") == "Relation"]

    # Validate and construct Pydantic models
    sv = SchemaValidator()
    entities, _ = sv.validate_and_construct(entities_raw)
    events, _ = sv.validate_and_construct(events_raw)
    claims, _ = sv.validate_and_construct(claims_raw)
    relations, _ = sv.validate_and_construct(relations_raw)

    return {"entities": entities, "events": events, "claims": claims, "relations": relations}


def parse_knowledge_package(path: Path) -> dict[str, list]:
    """Parse a v4 multi-file Knowledge Code package.

    The current product output is a directory containing text.py,
    entities.py, events.py, claims.py, derived.py, residuals.py, coverage.py.
    Quality checks must evaluate that product surface before falling back
    to legacy single-file `.knowledge.t2c.py` artifacts.
    """
    from t2c.schema import SchemaValidator

    raw_objects: list[dict] = []
    for filename in ("text.py", "entities.py", "events.py", "claims.py", "derived.py"):
        fpath = path / filename
        if not fpath.exists():
            continue
        parser = T2CParser()
        raw_objects.extend(parser.parse_string(fpath.read_text(encoding="utf-8")))

    sv = SchemaValidator()
    segments, _ = sv.validate_and_construct([o for o in raw_objects if o.get("type") == "Segment"])
    entities, _ = sv.validate_and_construct([o for o in raw_objects if o.get("type") == "Entity"])
    events, _ = sv.validate_and_construct([o for o in raw_objects if o.get("type") == "Event"])
    claims, _ = sv.validate_and_construct([o for o in raw_objects if o.get("type") == "Claim"])
    relations, _ = sv.validate_and_construct([o for o in raw_objects if o.get("type") == "Relation"])

    return {
        "segments": segments,
        "entities": entities,
        "events": events,
        "claims": claims,
        "relations": relations,
    }


def find_v4_packages(output_dir: Path) -> dict[int, Path]:
    """Return {chapter_num: package_path} for current v4 Hongloumeng output."""
    root = output_dir / "hongloumeng"
    if not root.exists():
        return {}
    packages: dict[int, Path] = {}
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        m = re.fullmatch(r"ch(\d+)", child.name)
        if not m:
            continue
        if (child / "text.py").exists():
            packages[int(m.group(1))] = child
    return packages


def check_grounding(
    objects: dict[str, list],
    seg_map: dict[str, str],
) -> list[dict]:
    """A. Text grounding: verify names/aliases appear in source segments."""
    issues = []

    for ent in objects["entities"]:
        seg_ids = [sid for sid in ent.source_segment_ids if sid in seg_map]
        if not seg_ids:
            issues.append({
                "dim": "grounding",
                "obj_id": ent.id,
                "detail": f"Entity '{ent.name}': no valid source_segment_ids",
            })
            continue
        combined = " ".join(seg_map[sid] for sid in seg_ids)

        if ent.name not in combined:
            issues.append({
                "dim": "grounding",
                "obj_id": ent.id,
                "detail": f"Entity name '{ent.name}' not found in source segments",
            })
        for alias in (ent.aliases or []):
            if alias not in combined:
                issues.append({
                    "dim": "grounding",
                    "obj_id": ent.id,
                    "detail": f"Entity alias '{alias}' (of '{ent.name}') not found in source segments",
                })

    return issues


def check_referential_integrity(
    objects: dict[str, list],
    seg_ids_set: set[str],
    all_entity_ids: set[str] | None = None,
) -> list[dict]:
    """B. Referential integrity: verify all ID references exist.

    all_entity_ids: if provided, includes entities from ALL chapters (cross-chapter refs are valid).
    """
    issues = []
    entity_ids = {e.id for e in objects["entities"]}
    # If cross-chapter entity IDs are available, merge them
    valid_entity_ids = entity_ids | (all_entity_ids or set())
    claim_ids = {c.id for c in objects["claims"]}

    for ent in objects["entities"]:
        for sid in ent.source_segment_ids:
            if sid not in seg_ids_set:
                issues.append({
                    "dim": "ref",
                    "obj_id": ent.id,
                    "detail": f"Entity '{ent.name}' references non-existent segment '{sid}'",
                })

    for evt in objects["events"]:
        for sid in evt.source_segment_ids:
            if sid not in seg_ids_set:
                issues.append({
                    "dim": "ref",
                    "obj_id": evt.id,
                    "detail": f"Event '{evt.name}' references non-existent segment '{sid}'",
                })
        for pid in (evt.participants or []):
            if pid not in valid_entity_ids:
                issues.append({
                    "dim": "ref",
                    "obj_id": evt.id,
                    "detail": f"Event '{evt.name}' references non-existent entity '{pid}'",
                })

    for clm in objects["claims"]:
        for sid in clm.source_segment_ids:
            if sid not in seg_ids_set:
                issues.append({
                    "dim": "ref",
                    "obj_id": clm.id,
                    "detail": f"Claim references non-existent segment '{sid}'",
                })
        if clm.subject and clm.subject not in valid_entity_ids:
            issues.append({
                "dim": "ref",
                "obj_id": clm.id,
                "detail": f"Claim subject '{clm.subject}' not in known entities",
            })
        if clm.object and clm.object not in valid_entity_ids:
            issues.append({
                "dim": "ref",
                "obj_id": clm.id,
                "detail": f"Claim object '{clm.object}' not in known entities",
            })

    for rel in objects["relations"]:
        if rel.subject and rel.subject not in valid_entity_ids:
            issues.append({
                "dim": "ref",
                "obj_id": rel.id,
                "detail": f"Relation subject '{rel.subject}' not in known entities",
            })
        if rel.object and rel.object not in valid_entity_ids:
            issues.append({
                "dim": "ref",
                "obj_id": rel.id,
                "detail": f"Relation object '{rel.object}' not in known entities",
            })
        if rel.claim_id and rel.claim_id not in claim_ids:
            issues.append({
                "dim": "ref",
                "obj_id": rel.id,
                "detail": f"Relation claim_id '{rel.claim_id}' not in chapter claims",
            })

    return issues


def check_coverage(
    objects: dict[str, list],
    ch_seg_ids: set[str],
) -> tuple[float, list[str]]:
    """C. Coverage: percentage of segments referenced by at least one object."""
    referenced = set()
    for ent in objects["entities"]:
        referenced.update(ent.source_segment_ids)
    for evt in objects["events"]:
        referenced.update(evt.source_segment_ids)
    for clm in objects["claims"]:
        referenced.update(clm.source_segment_ids)

    referenced_in_ch = referenced & ch_seg_ids
    coverage = len(referenced_in_ch) / len(ch_seg_ids) if ch_seg_ids else 0.0
    unreferenced = sorted(ch_seg_ids - referenced_in_ch)

    return coverage, unreferenced


def check_entity_consistency(
    chapter_objects: dict[int, dict[str, list]],
) -> list[dict]:
    """D. Entity consistency across chapters: detect duplicate entities."""
    issues = []
    name_chapters: dict[str, dict[int, str]] = defaultdict(dict)

    for ch_num, objects in chapter_objects.items():
        for ent in objects["entities"]:
            name_chapters[ent.name][ch_num] = ent.id
            for alias in (ent.aliases or []):
                name_chapters[alias][ch_num] = ent.id

    for name, ch_map in name_chapters.items():
        unique_ids = set(ch_map.values())
        if len(unique_ids) > 1:
            chapters_str = ", ".join(f"Ch{ch}={eid}" for ch, eid in sorted(ch_map.items()))
            issues.append({
                "dim": "entity",
                "obj_id": list(ch_map.values())[0],
                "detail": f"Entity '{name}' has different IDs across chapters: {chapters_str}",
            })

    return issues


def run_quality_check(json_output: bool = False, fail_under: float | None = None) -> tuple[dict, int]:
    """Run quality check and return (metrics, exit_code).

    metrics includes:
    - grounding_rate
    - reference_issue_count
    - entity_conflict_count
    - coverage_rate
    - total_issue_count
    """
    def _p(*args, **kwargs):
        """Conditional print — only when not in JSON mode."""
        if not json_output:
            print(*args, **kwargs)

    _p("Loading raw text...")
    raw_text = load_raw_text()
    _p(f"  Total: {len(raw_text):,} characters")

    _p("Building segment map...")
    seg_map, all_segs = build_all_data(raw_text)
    _p(f"  Total segments: {len(seg_map):,}")

    _p("Finding chapter boundaries...")
    boundaries = find_chapter_boundaries(raw_text)
    _p(f"  Total chapters: {len(boundaries)}")

    output_dir = project_root / "examples" / "knowledge"

    chapter_objects: dict[int, dict[str, list]] = {}
    chapter_seg_maps: dict[int, dict[str, str]] = {}
    all_issues: list[dict] = []
    all_entity_ids: set[str] = set()

    v4_packages = find_v4_packages(output_dir)
    if v4_packages:
        chapter_nums = sorted(v4_packages)
        _p(f"Using v4 Knowledge Code packages: {', '.join('ch%02d' % n for n in chapter_nums)}")
    else:
        chapter_nums = [1, 2, 3]
        _p("Using legacy single-file knowledge artifacts")

    # First pass: parse all chapter knowledge to build all_entity_ids.
    for ch_num in chapter_nums:
        if v4_packages:
            objects = parse_knowledge_package(v4_packages[ch_num])
            chapter_seg_maps[ch_num] = {s.id: s.text_slice for s in objects.get("segments", [])}
        else:
            kf = output_dir / f"hongloumeng_ch{ch_num:02d}.knowledge.t2c.py"
            if not kf.exists():
                continue
            objects = parse_knowledge_file(kf)
        chapter_objects[ch_num] = objects
        all_entity_ids.update(e.id for e in objects["entities"])

    # Second pass: run quality checks per chapter
    for ch_num in chapter_nums:
        if ch_num not in chapter_objects:
            _p(f"\n  WARNING: Ch{ch_num} knowledge file not found, skipping")
            continue

        if ch_num in chapter_seg_maps:
            ch_title = v4_packages[ch_num].name
            current_seg_map = chapter_seg_maps[ch_num]
            ch_seg_ids = set(current_seg_map)
        else:
            ch_info = None
            for num, title, start, end in boundaries:
                if num == ch_num:
                    ch_info = (num, title, start, end)
                    break
            if not ch_info:
                _p(f"\n  WARNING: Ch{ch_num} boundary not found")
                continue

            _, ch_title, ch_start, ch_end = ch_info
            current_seg_map = seg_map
            ch_seg_ids = {s.id for s in all_segs
                          if s.start_offset >= ch_start and s.start_offset < ch_end}

        _p(f"\n{'=' * 60}")
        _p(f"质量报告：第{ch_num}回「{ch_title}」")
        _p(f"{'=' * 60}")
        _p(f"  Segments: {len(ch_seg_ids)}")

        objects = chapter_objects[ch_num]
        _p(f"  Entities: {len(objects['entities'])}, Events: {len(objects['events'])}, "
           f"Claims: {len(objects['claims'])}, Relations: {len(objects['relations'])}")

        # A. Grounding
        grounding_issues = check_grounding(objects, current_seg_map)
        total_names_aliases = sum(1 + len(e.aliases or []) for e in objects["entities"])
        grounding_rate = 1.0 - (len(grounding_issues) / max(1, total_names_aliases))
        _p(f"\n  A. 文本溯源命中率: {grounding_rate:.0%}")
        if grounding_issues:
            _p(f"     问题: {len(grounding_issues)}")
            for iss in grounding_issues[:5]:
                _p(f"     - {iss['detail']}")
            if len(grounding_issues) > 5:
                _p(f"     ... and {len(grounding_issues) - 5} more")
        all_issues.extend(grounding_issues)

        # B. Referential integrity
        ref_issues = check_referential_integrity(objects, set(current_seg_map.keys()), all_entity_ids)
        # Count total references checked
        ref_total = 0
        for e in objects["entities"]:
            ref_total += len(e.source_segment_ids)
        for evt in objects["events"]:
            ref_total += len(evt.source_segment_ids) + len(evt.participants or [])
        for c in objects["claims"]:
            ref_total += len(c.source_segment_ids) + (1 if c.subject else 0) + (1 if c.object else 0)
        for r in objects["relations"]:
            ref_total += (1 if r.subject else 0) + (1 if r.object else 0) + (1 if r.claim_id else 0)
        ref_pass = ref_total - len(ref_issues)
        _p(f"\n  B. 引用完整性: {ref_pass}/{ref_total}")
        if ref_issues:
            _p(f"     问题: {len(ref_issues)}")
            for iss in ref_issues[:5]:
                _p(f"     - {iss['detail']}")
            if len(ref_issues) > 5:
                _p(f"     ... and {len(ref_issues) - 5} more")
        all_issues.extend(ref_issues)

        # C. Coverage
        coverage, unreferenced = check_coverage(objects, ch_seg_ids)
        _p(f"\n  C. 覆盖率: {coverage:.0%} ({len(ch_seg_ids) - len(unreferenced)}/{len(ch_seg_ids)} segments)")
        if unreferenced and len(unreferenced) <= 10:
            _p(f"     未引用 segments: {unreferenced}")
        elif unreferenced:
            _p(f"     未引用 segments: {len(unreferenced)} total (showing first 5)")
            for sid in unreferenced[:5]:
                txt = current_seg_map.get(sid, "?")[:40]
                _p(f"     - {sid}: {txt}...")

        # D. Event density
        evt_count = len(objects["events"])
        seg_count = len(ch_seg_ids)
        evt_ratio = evt_count / seg_count if seg_count else 0
        _p(f"\n  D. 事件密度: {evt_count} events / {seg_count} segments = {evt_ratio:.2f}")

    # Cross-chapter entity consistency
    if len(chapter_objects) > 1:
        _p(f"\n{'=' * 60}")
        _p("跨章实体一致性检查")
        _p(f"{'=' * 60}")
        entity_issues = check_entity_consistency(chapter_objects)
        if entity_issues:
            _p(f"  问题: {len(entity_issues)}")
            for iss in entity_issues[:10]:
                _p(f"  - {iss['detail']}")
            if len(entity_issues) > 10:
                _p(f"  ... and {len(entity_issues) - 10} more")
        else:
            _p("  无跨章实体冲突")
        all_issues.extend(entity_issues)

    # Summary
    by_dim = defaultdict(int)
    for iss in all_issues:
        by_dim[iss["dim"]] += 1
    total = len(all_issues)

    _p(f"\n{'=' * 60}")
    _p("汇总")
    _p(f"{'=' * 60}")
    for dim, count in sorted(by_dim.items()):
        _p(f"  {dim}: {count} issues")
    _p(f"  总计: {total} issues")

    # Write detailed report (always)
    report_path = output_dir / "quality_report.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        if v4_packages:
            f.write("T2C 当前 v4 Knowledge Code 质量报告\n")
        else:
            f.write("T2C legacy 单文件知识产物质量报告\n")
        f.write("=" * 60 + "\n\n")
        for iss in all_issues:
            f.write(f"[{iss['dim']}] {iss['obj_id']}: {iss['detail']}\n")

    _p(f"\n详细报告已写入: {report_path}")

    # Compute metrics
    total_names_aliases = 0
    for ch_num in chapter_objects:
        for e in chapter_objects[ch_num].get("entities", []):
            total_names_aliases += 1 + len(e.aliases or [])

    grounding_issues_count = sum(1 for iss in all_issues if iss["dim"] == "grounding")
    grounding_rate = 1.0 - (grounding_issues_count / max(1, total_names_aliases)) if total_names_aliases > 0 else 1.0

    ref_issues_count = sum(1 for iss in all_issues if iss["dim"] == "ref")
    entity_conflicts = sum(1 for iss in all_issues if iss["dim"] == "entity")

    # Aggregate coverage across chapters
    total_ch_segs = 0
    total_referenced = 0
    for ch_num in chapter_objects:
        if ch_num in chapter_seg_maps:
            ch_seg_ids = set(chapter_seg_maps[ch_num])
        else:
            ch_info = None
            for num, title, start, end in boundaries:
                if num == ch_num:
                    ch_info = (num, title, start, end)
                    break
            if not ch_info:
                continue
            _, _, ch_start, ch_end = ch_info
            ch_seg_ids = {s.id for s in all_segs
                          if s.start_offset >= ch_start and s.start_offset < ch_end}
        objects = chapter_objects[ch_num]
        referenced = set()
        for ent in objects["entities"]:
            referenced.update(ent.source_segment_ids)
        for evt in objects["events"]:
            referenced.update(evt.source_segment_ids)
        for clm in objects["claims"]:
            referenced.update(clm.source_segment_ids)
        total_ch_segs += len(ch_seg_ids)
        total_referenced += len(referenced & ch_seg_ids)

    coverage_rate = total_referenced / total_ch_segs if total_ch_segs > 0 else 0.0

    metrics = {
        "grounding_rate": round(grounding_rate, 4),
        "reference_issue_count": ref_issues_count,
        "entity_conflict_count": entity_conflicts,
        "coverage_rate": round(coverage_rate, 4),
        "total_issue_count": total,
        "issues_by_dim": dict(by_dim),
        "report_path": str(report_path),
    }

    if json_output:
        print(json.dumps(metrics, ensure_ascii=False, indent=2))

    exit_code = 0
    if fail_under is not None:
        if grounding_rate < fail_under:
            exit_code = 1

    return metrics, exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description="T2C Quality Check")
    parser.add_argument("--json", action="store_true", help="Output JSON metrics.")
    parser.add_argument(
        "--fail-under", type=float, default=None,
        help="Exit with code 1 if grounding_rate is below this threshold (0.0-1.0).",
    )
    args = parser.parse_args()
    _, exit_code = run_quality_check(json_output=args.json, fail_under=args.fail_under)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
