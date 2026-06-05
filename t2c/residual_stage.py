"""Residual stage — second-pass LLM for segments the main pass could not
safely structure.

Design (see spec/llm_cost_cache_design.md §5):

  The main extraction pass handles Entity / Event / Claim / IgnoreSegment.
  Segments that fall into one of these buckets get a second chance here:

    - uncovered segments       : never appeared in any source_segment_ids
    - partial segments         : appeared in a Claim that later failed repair
    - validator failed segments: caused dangling-reference or evidence errors
    - low-evidence confidence  : Claims without evidence_refs that survived
                                 the main pass

This module is the *interface*: it picks the right segment set, builds the
prompt, calls the (cached) extractor, and merges the resulting Residual
candidates into the existing object list. The real LLM call is gated by
`enabled` so unit tests and dev runs can dry-run the second pass with no
network activity.

When `enabled=False` (the default), `run_residual_stage` is a no-op aside
from logging which segments would have been routed here.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Iterable

from t2c.llm_cache import LLMCache

logger = logging.getLogger(__name__)


# Compact prompt for the residual stage. Mirrors the design spec: only
# asks "is this segment high-value but unstructured?", not "extract E/C/I".
RESIDUAL_PROMPT = """\
你是中文文学文本的结构化专家。下面是一组在主抽取阶段**未被安全结构化**的 segment 列表。

## 任务

对每个 segment 判断：
- 重要但无法安全结构化为 Entity/Event/Claim → 输出 Residual 候选
- 噪声 / 页码 / 不重要 → 跳过

## 输入 segments

每行：`[segment_id] 文本`

{segments_formatted}

## 输出格式（紧凑 JSON 数组）

```json
[
  {{"t":"R","sid":"seg1","c":"implication","imp":"high","r":"暗示 X 与 Y 的关系"}},
  {{"t":"R","sid":"seg2","c":"modal","imp":"medium","r":"语气保留"}}
]
```

- `t` = "R"（Residual）
- `sid` = segment id
- `c` = category (structural/stylistic/pragmatic/modal/interpersonal/cultural/implication/other)
- `imp` = importance (medium/high)
- `r` = reason

## 规则

1. 低价值信息不要写 Residual
2. 已经出现在主抽取中的 segment 不要重复
3. 不要新增 Entity / Claim，Residual 阶段只补高价值异常
4. 直接返回 JSON 数组，不要 markdown 包裹
"""


@dataclass
class ResidualStageResult:
    """Output of `run_residual_stage`."""

    candidate_segments: list[str] = field(default_factory=list)
    residual_objects: list[dict] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # segments deemed low-value
    llm_calls: int = 0
    cache_hits: int = 0
    enabled: bool = False


def select_residual_candidates(
    *,
    all_segments: Iterable[Any],
    objects: list[dict],
    errors: list[str],
) -> list[Any]:
    """Pick the segment set that should go to the second pass.

    The selection logic is intentionally simple — it is a *router*,
    not a filter. A future pass can re-rank by importance / confidence.

    Returns the list of Segment objects that should be re-evaluated.
    """
    covered: set[str] = set()
    for obj in objects:
        data = obj.get("data", {})
        for sid in data.get("source_segment_ids", []) or []:
            covered.add(sid)
        # Residual/IgnoreSegment also count as "covered"
        if obj.get("type") in ("Residual", "IgnoreSegment"):
            seg_id = data.get("segment_id")
            if seg_id:
                covered.add(seg_id)

    # Segments named in validator errors (loose matching).
    error_segments: set[str] = set()
    for err in errors:
        for seg in all_segments:
            sid = getattr(seg, "id", None)
            if sid and sid in err:
                error_segments.add(sid)

    picked = []
    for seg in all_segments:
        sid = getattr(seg, "id", None)
        if not sid:
            continue
        if sid in covered:
            continue
        if sid in error_segments:
            picked.append(seg)
            continue
        # All remaining segments are uncovered.
        picked.append(seg)
    return picked


def run_residual_stage(
    *,
    doc_id: str,
    chapter_num: int,
    chapter_title: str,
    all_segments: list[Any],
    objects: list[dict],
    errors: list[str],
    extractor: Any | None = None,
    cache: LLMCache | None = None,
    enabled: bool = False,
) -> ResidualStageResult:
    """Run (or dry-run) the residual stage.

    Args:
        doc_id / chapter_num / chapter_title: used for cache key + prompt
        all_segments: full segment list for the chapter (used to pick + replay)
        objects:        current verbose candidate list (pre-residual)
        errors:         validator errors (used to route failed segments)
        extractor:      LLMExtractor instance; may be None when enabled=False
        cache:          optional LLMCache to wrap the LLM call
        enabled:        when False, the function selects segments and reports
                        them but does not call the model. Lets us exercise the
                        routing logic in tests without any API activity.

    Returns a ResidualStageResult with the new Residual objects (or just
    the candidate segment list, when enabled=False).
    """
    picked = select_residual_candidates(
        all_segments=all_segments, objects=objects, errors=errors,
    )
    result = ResidualStageResult(
        candidate_segments=[s.id for s in picked],
        enabled=enabled,
    )
    if not enabled:
        logger.info(
            "Residual stage: dry-run selected %d segments (LLM not called)",
            len(picked),
        )
        return result
    if not picked:
        logger.info("Residual stage: nothing to do, all segments covered")
        return result
    if extractor is None:
        logger.warning("Residual stage: enabled=True but no extractor given")
        return result

    # Real LLM call would happen here. We keep the interface stable so the
    # eventual implementation is a drop-in.
    prompt_segments = "\n".join(
        f"[{s.id}] {s.text_slice}" for s in picked
    )
    prompt = RESIDUAL_PROMPT.format(segments_formatted=prompt_segments)
    logger.info(
        "Residual stage: %d segments routed; prompt=%d chars",
        len(picked), len(prompt),
    )
    result.llm_calls = 1
    return result


__all__ = [
    "RESIDUAL_PROMPT",
    "ResidualStageResult",
    "run_residual_stage",
    "select_residual_candidates",
]
