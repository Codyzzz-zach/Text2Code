"""LLM Extractor — extract semantic objects from text segments using Claude API.

Two extraction protocols are supported:

* ``verbose-v1`` (legacy): the LLM emits full ``{"type": ..., "data": {...}}``
  objects, including Relation and EvidenceRef directly. This is the original
  v3.4 behavior — kept for backward compatibility with already-generated
  knowledge files and existing tests.

* ``compact-v1`` (default since v3.4.2): the LLM emits short-key compact
  candidates that the program expands into verbose objects. Relation is
  derived from Claim (modality=asserted, polarity=positive, entity-entity);
  EvidenceRef is generated from the LLM-supplied ``q`` (quote) list by
  locating the quote inside Segment.text_slice and computing the hash.
  Residual is reserved for a separate second stage (see
  ``t2c.compact_candidate`` and ``t2c.residual_stage``).

When the ``compact-v1`` protocol is active, every LLM batch is wrapped by
an LLMCache lookup so repeat runs are free.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any

from t2c.compact_candidate import (
    COMPACT_TYPE_ENTITY,
    derive_relations,
    expand_candidates,
    parse_compact_response,
)
from t2c.llm_cache import CacheEntry, CacheMode, LLMCache, compute_cache_key
from t2c.ontology import Segment

logger = logging.getLogger(__name__)

# Lazy import: anthropic is optional at import time, required only when
# actually instantiating an API client. This prevents test collection
# failures when anthropic is not installed.
try:
    import anthropic
except ImportError:
    anthropic = None  # type: ignore[assignment]

EXTRACTION_PROMPT = """\
你是一个文学文本结构化专家。请从以下《红楼梦》第{chapter_num}回「{chapter_title}」的文本中提取语义对象。

## 输入文本

每行格式：[segment_id] 文本内容

{segments_formatted}

{existing_entities_section}

## 提取要求

请提取以下类型的对象，以 JSON 数组返回。每个元素格式为 {{"type": "类型名", "data": {{...}}}}。

### Entity（实体）
- kind: person（人物）, location（地点）, org（组织/家族）, artifact（物品）, concept（概念）
- name: 实体名称（用原文中最常见的称呼）
- aliases: 该实体的其他称呼列表（如 贾宝玉→["宝玉","宝二爷"]）
- source_segment_ids: 该实体首次出现或被描述的 segment ID 列表

### Event（事件）
- kind: occurrence（发生的事）, action（主动行为）, state_change（状态变化）
- name: 事件简述
- participants: 参与者 entity ID 列表
- time: 时间描述（如有，否则不填）
- location: 地点描述（如有，否则不填）
- source_segment_ids: 事件发生的 segment ID 列表

### Claim（声明/命题）
- subject: entity ID
- predicate: 关系谓词（如 "is_child_of", "lives_in", "owns", "said", "is_member_of"）
- object: entity ID（如有，否则不填）
- modality: asserted（确凿事实）, reported（转述）, claimed_by_source（原文声称）, uncertain（不确定）, hypothetical（假设）
- polarity: positive 或 negative
- source_segment_ids: 声明来源 segment ID 列表

### Relation（关系）
- subject: entity ID
- predicate: 关系谓词
- object: entity ID
- claim_id: 来源 Claim 的 ID

### Residual（残余信息）
- segment_id: 信息所在的 segment ID
- category: structural（结构）, stylistic（风格）, pragmatic（语用）, modal（情态）, interpersonal（人际）, cultural（文化）, implication（隐含）, other（其他）
- importance: medium 或 high（只有中高重要性才提取，不提取低价值残余）
- reason: 为什么这段信息重要但无法被安全结构化

### IgnoreSegment（忽略段）
- segment_id: 要忽略的 segment ID
- reason: 为什么可以忽略（如：页码、目录、格式噪声）

## ID 命名规则

**严格遵守以下 ID 前缀，不要使用其他前缀（如 _char_、_person_ 等都是错误的）：**

- Entity: `{doc_id}_ent_{{序号:04d}}`（从 {next_ent_idx:04d} 开始，**前缀必须是 _ent_ 不是 _char_**）
- Event: `{doc_id}_evt_{{序号:04d}}`（从 {next_evt_idx:04d} 开始）
- Claim: `{doc_id}_clm_{{序号:04d}}`（从 {next_clm_idx:04d} 开始）
- Relation: `{doc_id}_rel_{{序号:04d}}`（从 {next_rel_idx:04d} 开始）
- Residual: `{doc_id}_res_{{序号:04d}}`（从 {next_res_idx:04d} 开始）
- IgnoreSegment: `{doc_id}_ign_{{序号:04d}}`（从 {next_ign_idx:04d} 开始）

示例：hongloumeng_ent_0001, hongloumeng_evt_0001, hongloumeng_clm_0001, hongloumeng_rel_0001, hongloumeng_res_0001, hongloumeng_ign_0001

## 损耗声明（核心原则）

**如果某段信息重要，但无法被安全表达为 Entity/Event/Claim/Relation，请输出 Residual，不要强行结构化成事实。**

这意味着：
- 反讽、暗示、心理活动、模糊因果等重要但不可安全结构化的信息 → Residual（importance=high）
- 不确定、转述、否定信息不得生成 Relation fact edge（modality≠asserted 或 polarity≠positive 的 Claim 不应产生 Relation）
- 页码、目录、格式噪声等 → IgnoreSegment
- 所有对象必须引用已有 segment（source_segment_ids 或 segment_id）
- 所有语义对象尽量生成 EvidenceRef（如能精确定位原文位置）
- 不要追求所有信息都结构化——Residual 只记录高价值异常，不记录所有未抽取内容
- 不确定的信息宁可降级为 Residual，不要强行提升为 Claim(asserted)

## 重要约束

1. source_segment_ids 必须是上面输入中存在的 segment ID
2. Claim 的 subject/object 必须引用已定义的 Entity ID（包括已知人物列表中的）
3. Relation 的 claim_id 必须引用同章已定义的 Claim ID
4. 同一人物在不同 segment 中出现时，使用相同 Entity ID
5. 已知人物列表中的人物，直接使用其 Entity ID，不要创建新的
6. 只提取明确出现在文本中的信息，不要推断
7. 对白中的内容用 modality="reported" 或 "claimed_by_source"
8. 叙述中确定的事实用 modality="asserted"
9. Residual 的 importance 只能是 medium 或 high，不要为低价值信息生成 Residual
10. IgnoreSegment 的 reason 必须明确（如"页码"、"目录"、"格式噪声"）

请直接返回 JSON 数组，不要添加任何解释文本。不要用 markdown 代码块包裹。
"""

# Compact prompt used by extractor_protocol="compact-v1". Mirrors the verbose
# prompt's intent but uses short keys to keep output tokens low, and asks the
# LLM NOT to emit Relation (program-derived) or EvidenceRef (computed from
# `q` quotes). Residual is intentionally absent here — it is a separate
# second-stage concern.
COMPACT_PROMPT = """\
你是一个文学文本结构化专家。从以下《红楼梦》第{chapter_num}回「{chapter_title}」的文本中提取**紧凑**候选对象。

## 输入文本

每行格式：`[segment_id] 文本内容`

{segments_formatted}

{existing_entities_section}

## 输出要求

**只输出 JSON 数组**。每个元素是单个候选对象，字段尽量短。只用以下四种 type：

### E = Entity（实体）
```json
{{"t":"E","lid":"e1","n":"甄士隐","k":"person","a":["士隐"],"sid":["hongloumeng_seg_0009"],"q":["甄士隐"]}}
```
- `lid` = 本批内有效 local id（其他候选可引用）
- `n` = 实体名，`k` = kind（person/location/org/artifact/concept）
- `a` = 其他称呼列表，可省
- `sid` = 出现的 segment id 列表
- `q` = 用于 EvidenceRef 定位的原文引用片段列表，可省

### EV = Event（事件）
```json
{{"t":"EV","n":"甄士隐做梦","k":"occurrence","p":["e1"],"sid":["hongloumeng_seg_0015"],"q":["梦"]}}
```
- `p` = 参与者 entity id 列表（lid 或已知 entity id）

### C = Claim（声明）
```json
{{"t":"C","s":"e1","p":"lives_in","o":"姑苏","m":"asserted","pol":"positive","sid":["seg1"],"q":["姑苏"]}}
```
- `s` = subject (entity id or lid)
- `p` = predicate
- `o` = object (entity id, lid, or literal string)
- `m` = modality (asserted/reported/claimed_by_source/uncertain/hypothetical/conditional/inferred)
- `pol` = polarity (positive/negative)

### I = IgnoreSegment（忽略）
```json
{{"t":"I","sid":"seg1","r":"chapter title"}}
```
- `r` = 忽略原因

## 严禁输出

- **R (Relation)** — 由程序从 Claim 自动派生（仅 modality=asserted + polarity=positive + entity-entity + 有证据）
- **EvidenceRef 字段（start/end/quote_hash）** — 由程序从 `q` 引用片段定位
- Residual — 留到第二阶段
- Markdown 包裹
- 任何解释文本

## 核心原则

1. 同一人物用相同 lid；跨实体引用时优先用本批的 lid
2. 不确定信息用 modality=uncertain，不要硬上 asserted
3. 转述/对白用 reported 或 claimed_by_source
4. `q` 给出一小段原文引用即可，程序会精确定位并算 hash
5. `sid` 必须是输入中真实存在的 segment id
6. 不编造，不推断，找不到的宁可不写

请直接返回紧凑 JSON 数组。
"""

# Max segment text per single LLM call.
# v3.4.2: 1200 chars / batch — paired with the compact protocol and a
# shorter prompt, this keeps input tokens modest while still letting
# multiple segments land in a single batch.
_MAX_BATCH_CHARS = 1200

# Default output cap.
# v3.4.2: lowered from 32768 to 8192. The compact protocol is much terser
# than verbose, so a 32K ceiling mostly encourages verbose output. 8192
# is enough for ~40 compact candidates with room to spare.
_DEFAULT_MAX_TOKENS = 8192
# Env var override — convenient for one-off runs without code changes.
_MAX_TOKENS_ENV = "T2C_MAX_TOKENS"
_THINKING_BUDGET_ENV = "T2C_THINKING_BUDGET"
# v3.4.2: lowered from 2048 to 1024. Compact candidates don't need deep
# deliberation; we want the budget spent on output tokens.
_DEFAULT_THINKING_BUDGET = 1024

# Default protocol + prompt version. Bump either to force a cache wipe.
_DEFAULT_EXTRACTOR_PROTOCOL = "compact-v1"
_DEFAULT_PROMPT_VERSION = "compact-main-v1"
_VERBOSE_EXTRACTOR_PROTOCOL = "verbose-v1"
_VERBOSE_PROMPT_VERSION = "verbose-main-v1"


class LLMExtractor:
    """Extract semantic objects from text segments using Claude API."""

    def __init__(
        self,
        model: str = "MiniMax-M3",
        api_key: str | None = None,
        base_url: str | None = None,
        *,
        max_tokens: int | None = None,
        thinking_budget: int | None = None,
        extractor_protocol: str | None = None,
        prompt_version: str | None = None,
        cache_mode: CacheMode | str | None = None,
        cache_dir: str | None = None,
        _client: Any = None,
    ) -> None:
        if _client is not None:
            self._client = _client
        else:
            if anthropic is None:
                raise ImportError(
                    "LLMExtractor requires the optional anthropic dependency. "
                    "Install project dependencies or configure an extractor backend."
                )
            self._client = anthropic.Anthropic(
                api_key=api_key or os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY"),
                base_url=base_url or os.environ.get("ANTHROPIC_BASE_URL"),
            )
        self._model = model
        # max_tokens: explicit arg > T2C_MAX_TOKENS env > _DEFAULT_MAX_TOKENS
        if max_tokens is not None:
            self._max_tokens = max_tokens
        else:
            env_val = os.environ.get(_MAX_TOKENS_ENV)
            self._max_tokens = int(env_val) if env_val else _DEFAULT_MAX_TOKENS
        # thinking_budget: explicit arg > T2C_THINKING_BUDGET env > _DEFAULT_THINKING_BUDGET
        if thinking_budget is not None:
            self._thinking_budget = thinking_budget
        else:
            env_val = os.environ.get(_THINKING_BUDGET_ENV)
            self._thinking_budget = int(env_val) if env_val else _DEFAULT_THINKING_BUDGET
        # Protocol + prompt version. v3.4.2 default is the compact protocol;
        # callers can opt back into verbose by passing
        # extractor_protocol="verbose-v1".
        if extractor_protocol is None:
            self._protocol = _DEFAULT_EXTRACTOR_PROTOCOL
        else:
            self._protocol = str(extractor_protocol)
        if prompt_version is None:
            self._prompt_version = (
                _VERBOSE_PROMPT_VERSION if self._protocol == _VERBOSE_EXTRACTOR_PROTOCOL
                else _DEFAULT_PROMPT_VERSION
            )
        else:
            self._prompt_version = str(prompt_version)
        # Cache: mode is required; dir defaults to .t2c_cache/llm/v1.
        if cache_mode is None:
            mode_str = os.environ.get("T2C_CACHE_MODE", CacheMode.OFF.value)
            self._cache_mode = CacheMode(mode_str)
        elif isinstance(cache_mode, CacheMode):
            self._cache_mode = cache_mode
        else:
            self._cache_mode = CacheMode(str(cache_mode))
        env_cache_dir = os.environ.get("T2C_CACHE_DIR")
        self._cache_dir = cache_dir or env_cache_dir or None
        self._cache: LLMCache | None
        if self._cache_mode == CacheMode.OFF:
            self._cache = None
        else:
            self._cache = LLMCache(cache_dir=self._cache_dir)
        # Telemetry for cache hits/misses — Pipeline / scripts can read these.
        self._cache_hits: int = 0
        self._cache_misses: int = 0
        self._cache_lookups: int = 0
        # Track per-type counters across calls for consistent ID assignment
        self._counters: dict[str, int] = {}
        # Telemetry for the most recent extract_chapter / extract_batch call.
        # Pipeline reads these to populate PipelineResult.
        self._last_batch_truncated: bool = False
        self._total_input_tokens: int = 0
        self._total_output_tokens: int = 0
        self._api_elapsed_sec: float = 0.0
        # Carry over pre-existing entity map state from a previous run
        # (callers can update via _seed_entity_map).
        self._seed_entities: dict[str, str] = {}

    def _next_index(self, type_key: str) -> int:
        idx = self._counters.get(type_key, 0) + 1
        self._counters[type_key] = idx
        return idx

    def extract_chapter(
        self,
        doc_id: str,
        chapter_num: int,
        chapter_title: str,
        segments: list[Segment],
        existing_entities: dict[str, str] | None = None,
    ) -> list[dict]:
        """Extract semantic objects for one chapter, batching if segments are too long.

        Args:
            doc_id: Document ID (e.g. "hongloumeng")
            chapter_num: Chapter number (1-based)
            chapter_title: Chapter heading text
            segments: List of Segment objects for this chapter
            existing_entities: Optional dict of {entity_name: entity_id} for cross-chapter resolution

        Returns:
            List of {"type": str, "data": dict} objects (Entity, Event, Claim, Relation)
        """
        # Reset telemetry accumulators for this run.
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._api_elapsed_sec = 0.0
        self._last_batch_truncated = False
        self._cache_hits = 0
        self._cache_misses = 0
        self._cache_lookups = 0

        # Split into batches if total text is too long
        batches = self._batch_segments(segments)
        is_compact = self._protocol != _VERBOSE_EXTRACTOR_PROTOCOL

        # Single-batch fast path
        if len(batches) == 1:
            if is_compact:
                return self._extract_batch_compact(
                    doc_id, chapter_num, chapter_title,
                    segments, existing_entities, batch_index=0,
                )
            return self._extract_batch(doc_id, chapter_num, chapter_title, segments, existing_entities)

        # Multi-batch: extract each batch, then merge
        all_objects: list[dict] = []
        batch_entities = dict(existing_entities or {})
        # Seed the cross-batch entity map with anything the caller pre-loaded
        # (e.g. from a previous chapter's run).
        if self._seed_entities:
            batch_entities.update(self._seed_entities)
        pre_entity_count = len(batch_entities)
        truncated_batches = 0

        for i, batch in enumerate(batches):
            logger.info("Ch%d batch %d/%d: %d segments", chapter_num, i + 1, len(batches), len(batch))
            try:
                if is_compact:
                    objects = self._extract_batch_compact(
                        doc_id, chapter_num, chapter_title,
                        batch, batch_entities, batch_index=i,
                    )
                else:
                    objects = self._extract_batch(
                        doc_id, chapter_num, chapter_title, batch, batch_entities,
                    )
            except Exception as exc:
                # v3.4.1: an LLM-side error (safety filter, rate limit, network) on
                # one batch must not abort the whole chapter. Log loudly and skip.
                logger.error(
                    "Ch%d batch %d/%d failed: %s: %s — continuing with next batch",
                    chapter_num, i + 1, len(batches), type(exc).__name__, exc,
                )
                self._last_batch_truncated = False
                if i < len(batches) - 1:
                    time.sleep(2)
                continue
            all_objects.extend(objects)
            if self._last_batch_truncated:
                truncated_batches += 1
            # Update entity map for next batch
            new_entities = self.build_entity_map(objects)
            batch_entities.update(new_entities)
            logger.info(
                "Ch%d batch %d: %d objects, entity_map grew %d→%d",
                chapter_num, i + 1, len(objects), pre_entity_count, len(batch_entities),
            )
            pre_entity_count = len(batch_entities)
            if i < len(batches) - 1:
                time.sleep(1)

        # Persist aggregated truncation count to the public flag for the
        # *most recent* batch — Pipeline.py reads this after the call.
        self._last_batch_truncated = truncated_batches > 0
        return all_objects

    def _extract_batch(
        self,
        doc_id: str,
        chapter_num: int,
        chapter_title: str,
        segments: list[Segment],
        existing_entities: dict[str, str] | None = None,
    ) -> list[dict]:
        """Extract semantic objects for one batch of segments."""
        prompt = self._build_prompt(doc_id, chapter_num, chapter_title, segments, existing_entities)
        # Anthropic SDK requires streaming for max_tokens > 21,333 (10-min timeout
        # rule). We always try non-streaming first, fall back to streaming on the
        # SDK's ValueError, and re-aggregate the streamed events into a synthetic
        # response with the same shape (content blocks + usage + stop_reason).
        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        # For Anthropic-compatible APIs that support extended thinking,
        # limit thinking budget so it doesn't consume all output tokens.
        t0 = time.time()
        response = None
        try:
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": self._thinking_budget}
            response = self._client.messages.create(**kwargs)
        except TypeError:
            # Fallback: API doesn't support thinking parameter
            kwargs.pop("thinking", None)
            try:
                response = self._client.messages.create(**kwargs)
            except ValueError as exc:
                # SDK says max_tokens requires streaming (>10 min wall clock).
                response = self._stream_response(kwargs)
        except ValueError as exc:
            # Same SDK rule but on the first try.
            response = self._stream_response(kwargs)
        elapsed = time.time() - t0

        # Log API response metadata + accumulate telemetry
        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "input_tokens", 0) if usage else 0
        output_tokens = getattr(usage, "output_tokens", 0) if usage else 0
        self._total_input_tokens += input_tokens
        self._total_output_tokens += output_tokens
        self._api_elapsed_sec += elapsed
        logger.info(
            "Ch%d batch API: stop_reason=%s, tokens=%s→%s, %.1fs",
            chapter_num, response.stop_reason, input_tokens, output_tokens, elapsed,
        )
        truncated = response.stop_reason == "max_tokens"
        self._last_batch_truncated = truncated
        if truncated:
            logger.warning("Ch%d batch hit max_tokens — output likely truncated", chapter_num)

        response_text = self._get_text_from_response(response)
        if response_text is None:
            logger.warning("Ch%d batch: no text content (stop_reason=%s)", chapter_num, response.stop_reason)
            return []
        objects = self._parse_response(response_text)
        # v3.4.1: partial recovery — when truncated, try to extract complete {...}
        # blocks even if the JSON array as a whole is invalid.
        if not objects and truncated:
            recovered = self._recover_partial_objects(response_text)
            if recovered:
                logger.info(
                    "Ch%d partial recovery: salvaged %d objects from truncated response",
                    chapter_num, len(recovered),
                )
                objects = recovered
        # Normalize wrong ID prefixes (e.g. _char_ → _ent_)
        objects = self._normalize_ids(objects, doc_id)
        # Auto-assign missing IDs
        objects = self._assign_missing_ids(objects, doc_id)
        # Trim ungrounded aliases
        objects = self._validate_grounding(objects, segments)
        return objects

    def _seed_entity_map(self, mapping: dict[str, str]) -> None:
        """Pre-load entity name→id mapping (e.g. from a previous run).

        Useful when multiple chapters share characters and we want the
        second chapter to reuse the first chapter's entity ids without
        having to re-extract them.
        """
        self._seed_entities.update(mapping)

    def _extract_batch_compact(
        self,
        doc_id: str,
        chapter_num: int,
        chapter_title: str,
        segments: list[Segment],
        existing_entities: dict[str, str] | None,
        *,
        batch_index: int,
    ) -> list[dict]:
        """Extract compact candidates and expand to verbose objects.

        This is the v3.4.2 path. Differences from ``_extract_batch``:

        * Uses the compact prompt.
        * Looks up the batch in LLMCache before calling the model.
        * Parses the response as compact JSON and expands to verbose form
          (with EvidenceRef computed from `q` quotes, Relation derived
          from eligible Claims).
        """
        seg_ids = [s.id for s in segments]
        seg_hashes = [s.hash for s in segments]
        options = {
            "max_tokens": self._max_tokens,
            "thinking_budget": self._thinking_budget,
            "temperature": 0,
        }
        cache_key = compute_cache_key(
            doc_id=doc_id,
            chapter_num=chapter_num,
            chapter_title=chapter_title,
            batch_index=batch_index,
            segment_ids=seg_ids,
            segment_hashes=seg_hashes,
            known_entities=existing_entities,
            model=self._model,
            prompt_version=self._prompt_version,
            extractor_protocol=self._protocol,
            options=options,
        )

        # Cache lookup
        if self._cache is not None and self._cache_mode != CacheMode.OFF:
            self._cache_lookups += 1
            entry = self._cache.lookup(cache_key)
            if entry is not None and self._cache_mode != CacheMode.REFRESH:
                self._cache_hits += 1
                logger.info(
                    "Ch%d batch %d: cache hit key=%s",
                    chapter_num, batch_index + 1, cache_key[:24] + "...",
                )
                objects, parse_warnings = self._expand_cached_entry(
                    entry, segments, doc_id,
                )
                self._last_batch_truncated = bool(
                    entry.quality.get("truncated", False)
                )
                return objects

        if self._cache_mode == CacheMode.READ_ONLY:
            # v3.4.2 contract: read_only + miss = explicit failure.
            raise FileNotFoundError(
                f"Cache miss for batch {doc_id} ch{chapter_num} batch {batch_index + 1} "
                f"(key={cache_key[:24]}...). "
                f"Run with cache_mode=read_write or refresh to populate cache."
            )

        self._cache_misses += 1

        # Build the compact prompt and call the model.
        prompt = self._build_compact_prompt(
            doc_id, chapter_num, chapter_title, segments, existing_entities,
        )
        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        t0 = time.time()
        response = None
        try:
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": self._thinking_budget}
            response = self._client.messages.create(**kwargs)
        except TypeError:
            kwargs.pop("thinking", None)
            try:
                response = self._client.messages.create(**kwargs)
            except ValueError:
                response = self._stream_response(kwargs)
        except ValueError:
            response = self._stream_response(kwargs)
        elapsed = time.time() - t0

        usage = getattr(response, "usage", None)
        # Cast to int — MagicMock attribute access returns MagicMock, which
        # is truthy and would otherwise flow into the cache entry as a
        # non-serializable object.
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0) if usage else 0
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0) if usage else 0
        self._total_input_tokens += input_tokens
        self._total_output_tokens += output_tokens
        self._api_elapsed_sec += elapsed

        truncated = response.stop_reason == "max_tokens"
        self._last_batch_truncated = truncated
        response_text = self._get_text_from_response(response) or ""
        if not response_text:
            logger.warning(
                "Ch%d batch %d: no text content (stop_reason=%s)",
                chapter_num, batch_index + 1, response.stop_reason,
            )
            return []

        # Parse + expand
        objects = self._postprocess_compact_response(
            response_text, segments, doc_id,
        )

        # Cache store (only on read_write or refresh; never on read_only).
        if self._cache is not None and self._cache_mode in (
            CacheMode.READ_WRITE, CacheMode.REFRESH,
        ):
            entry = CacheEntry(
                cache_schema="t2c-llm-cache-v1",
                cache_key=cache_key,
                created_at=LLMCache.now_iso(),
                request={
                    "model": self._model,
                    "prompt_version": self._prompt_version,
                    "extractor_protocol": self._protocol,
                    "segments": [
                        {"id": s.id, "hash": s.hash, "text": s.text_slice}
                        for s in segments
                    ],
                    "known_entities": dict(existing_entities or {}),
                },
                response={
                    "raw_text": response_text,
                    "parsed_candidates": objects,
                    "stop_reason": response.stop_reason,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "elapsed_sec": elapsed,
                },
                quality={
                    "parse_ok": bool(objects) or not response_text.strip(),
                    "truncated": truncated,
                    "recovered_partial": False,
                },
            )
            try:
                self._cache.store(entry)
            except (OSError, TypeError, ValueError) as exc:
                # TypeError/ValueError covers non-serializable entries (e.g.
                # from a buggy mock client); OSError covers disk failures.
                logger.warning("LLMCache: failed to write %s: %s", cache_key, exc)

        return objects

    def _postprocess_compact_response(
        self,
        response_text: str,
        segments: list[Segment],
        doc_id: str,
    ) -> list[dict]:
        """Parse compact JSON, expand to verbose form, derive Relations.

        Always runs even on truncated responses — the parser falls back
        to brace-balanced recovery when the JSON array itself is invalid.
        """
        candidates = parse_compact_response(response_text)
        objects, expand_warnings = expand_candidates(
            candidates, segments, doc_id,
        )
        for w in expand_warnings:
            logger.debug("Ch expand: %s", w)

        # Normalize wrong ID prefixes (defensive — LLM might still emit them).
        objects = self._normalize_ids(objects, doc_id)
        # Auto-assign IDs in case any candidate slipped through without one.
        objects = self._assign_missing_ids(objects, doc_id)
        # Trim ungrounded aliases — keeps the same invariant the verbose
        # path enforces.
        objects = self._validate_grounding(objects, segments)

        # Derive Relations from eligible Claims (asserted + positive +
        # entity-entity + has evidence).
        entity_ids = {
            o["data"]["id"] for o in objects if o.get("type") == "Entity"
        }
        relations, rel_warnings = derive_relations(
            objects, entity_ids, doc_id=doc_id,
        )
        for w in rel_warnings:
            logger.debug("Ch relation: %s", w)
        objects.extend(relations)
        return objects

    def _expand_cached_entry(
        self,
        entry: CacheEntry,
        segments: list[Segment],
        doc_id: str,
    ) -> tuple[list[dict], list[str]]:
        """Reconstruct the verbose object list from a cached entry.

        The cached entry stores the already-expanded verbose form, so we
        just return it after a defensive parse-OK check. If the cache
        entry predates the compact protocol (e.g. a manually-imported
        verbose cache), we re-run the expand on the raw text.
        """
        parsed = entry.response.get("parsed_candidates")
        if isinstance(parsed, list) and parsed:
            # Honor any tokens/elapsed the cache recorded (so repeated
            # runs still show cost in the run summary).
            self._total_input_tokens += int(
                entry.response.get("input_tokens", 0) or 0
            )
            self._total_output_tokens += int(
                entry.response.get("output_tokens", 0) or 0
            )
            self._api_elapsed_sec += float(
                entry.response.get("elapsed_sec", 0.0) or 0.0
            )
            return list(parsed), []
        # Fall back: re-run the expander on the raw text.
        return self._postprocess_compact_response(
            entry.response.get("raw_text", ""),
            segments, doc_id,
        ), []

    def _build_compact_prompt(
        self,
        doc_id: str,
        chapter_num: int,
        chapter_title: str,
        segments: list[Segment],
        existing_entities: dict[str, str] | None,
    ) -> str:
        segments_formatted = "\n".join(
            f"[{s.id}] {s.text_slice}" for s in segments
        )
        if existing_entities:
            lines = [f"- {eid}: {name}" for name, eid in existing_entities.items()]
            existing_section = "## 已知人物（前几回已提取，直接复用其 ID）\n\n" + "\n".join(lines)
        else:
            existing_section = ""
        return COMPACT_PROMPT.format(
            chapter_num=chapter_num,
            chapter_title=chapter_title,
            segments_formatted=segments_formatted,
            existing_entities_section=existing_section,
        )

    def _stream_response(self, kwargs: dict[str, Any]) -> Any:
        """Issue a streaming request and re-assemble the events into a response-shaped object.

        Required because anthropic SDK refuses non-streamed calls when max_tokens
        would imply > 10 minutes of wall-clock work. We aggregate streamed
        content_block_delta events into the final content blocks, and pull
        `stop_reason` and `usage` from the `message_stop` event.
        """
        logger.info("Falling back to streaming for max_tokens=%d", kwargs.get("max_tokens"))
        stream = self._client.messages.create(stream=True, **kwargs)
        text_parts: list[str] = []
        # Track per-index text deltas to support multiple text blocks.
        block_text: dict[int, str] = {}
        stop_reason: str | None = None
        usage_obj: Any = None

        for event in stream:
            etype = getattr(event, "type", None)
            if etype == "content_block_start":
                idx = getattr(event, "index", 0)
                block_text.setdefault(idx, "")
            elif etype == "content_block_delta":
                delta = getattr(event, "delta", None)
                if delta is not None and getattr(delta, "type", None) == "text_delta":
                    idx = getattr(event, "index", 0)
                    block_text[idx] = block_text.get(idx, "") + getattr(delta, "text", "")
            elif etype == "content_block_stop":
                idx = getattr(event, "index", 0)
                txt = block_text.get(idx, "")
                if txt:
                    text_parts.append(txt)
            elif etype == "message_delta":
                delta = getattr(event, "delta", None)
                if delta is not None:
                    stop_reason = getattr(delta, "stop_reason", stop_reason)
                usage_obj = getattr(event, "usage", usage_obj)
            elif etype == "message_stop":
                # Final event; usage may live here for some API versions.
                usage_obj = getattr(event, "usage", usage_obj) or usage_obj

        # Build a synthetic response with the same interface downstream code expects.
        full_text = "".join(text_parts)

        class _TextBlock:
            def __init__(self, text: str) -> None:
                self.type = "text"
                self.text = text

        class _Usage:
            pass

        class _Response:
            pass

        resp = _Response()
        resp.content = [_TextBlock(full_text)] if full_text else []
        resp.stop_reason = stop_reason or "end_turn"
        u = _Usage()
        u.input_tokens = getattr(usage_obj, "input_tokens", 0) if usage_obj else 0
        u.output_tokens = getattr(usage_obj, "output_tokens", 0) if usage_obj else 0
        resp.usage = u
        return resp

    def _recover_partial_objects(self, response_text: str) -> list[dict]:
        """Best-effort salvage of complete JSON objects from a truncated response.

        Strategy: scan for top-level `{...}` blocks via brace matching. Each block
        that parses as JSON AND has both `type` and a payload key (`id` or `data`)
        is kept. This recovers candidates emitted before the truncation point even
        when the surrounding `[...]` array is incomplete.
        """
        text = response_text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*\n?", "", text)
            text = re.sub(r"\n?```\s*$", "", text).strip()
        # Walk the string and extract balanced {...} blocks.
        blocks: list[str] = []
        depth = 0
        start_idx = -1
        in_str = False
        escape = False
        for i, ch in enumerate(text):
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == "{":
                if depth == 0:
                    start_idx = i
                depth += 1
            elif ch == "}":
                if depth > 0:
                    depth -= 1
                    if depth == 0 and start_idx >= 0:
                        blocks.append(text[start_idx:i + 1])
                        start_idx = -1
        recovered: list[dict] = []
        for blk in blocks:
            try:
                obj = json.loads(blk)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            if "type" in obj and "data" in obj:
                recovered.append(obj)
            elif "type" in obj and "id" in obj:
                type_name = obj.pop("type")
                recovered.append({"type": type_name, "data": obj})
        return recovered

    def _get_text_from_response(self, response: Any) -> str | None:
        """Extract text from API response, handling thinking blocks etc."""
        for block in response.content:
            if block.type == "text" and block.text is not None:
                return block.text
        return None

    def _batch_segments(self, segments: list[Segment]) -> list[list[Segment]]:
        """Split segments into batches that fit within context limits."""
        total_chars = sum(len(s.text_slice) for s in segments)
        if total_chars <= _MAX_BATCH_CHARS:
            return [segments]

        batches: list[list[Segment]] = []
        current_batch: list[Segment] = []
        current_chars = 0

        for seg in segments:
            seg_len = len(seg.text_slice)
            if current_chars + seg_len > _MAX_BATCH_CHARS and current_batch:
                batches.append(current_batch)
                current_batch = []
                current_chars = 0
            current_batch.append(seg)
            current_chars += seg_len

        if current_batch:
            batches.append(current_batch)

        return batches

    def _build_prompt(
        self,
        doc_id: str,
        chapter_num: int,
        chapter_title: str,
        segments: list[Segment],
        existing_entities: dict[str, str] | None,
    ) -> str:
        segments_formatted = "\n".join(
            f"[{s.id}] {s.text_slice}" for s in segments
        )
        if existing_entities:
            lines = [f"- {eid}: {name}" for name, eid in existing_entities.items()]
            existing_section = "## 已知人物（前几回已提取，直接复用其 ID）\n\n" + "\n".join(lines)
        else:
            existing_section = ""

        # Compute next indices for ID assignment
        next_ent = self._counters.get("ent", 0) + 1
        next_evt = self._counters.get("evt", 0) + 1
        next_clm = self._counters.get("clm", 0) + 1
        next_rel = self._counters.get("rel", 0) + 1
        next_res = self._counters.get("res", 0) + 1
        next_ign = self._counters.get("ign", 0) + 1

        return EXTRACTION_PROMPT.format(
            chapter_num=chapter_num,
            chapter_title=chapter_title,
            segments_formatted=segments_formatted,
            existing_entities_section=existing_section,
            doc_id=doc_id,
            next_ent_idx=next_ent,
            next_evt_idx=next_evt,
            next_clm_idx=next_clm,
            next_rel_idx=next_rel,
            next_res_idx=next_res,
            next_ign_idx=next_ign,
        )

    def _parse_response(self, response_text: str) -> list[dict]:
        """Parse LLM response into structured objects."""
        text = response_text.strip()

        # Strip markdown code block if present
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*\n?", "", text)
            text = re.sub(r"\n?```\s*$", "", text)
            text = text.strip()

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            # Try to extract JSON array from surrounding text
            match = re.search(r"\[[\s\S]*\]", text)
            if match:
                try:
                    parsed = json.loads(match.group())
                except json.JSONDecodeError:
                    return []
            else:
                return []

        if not isinstance(parsed, list):
            return []

        # Normalize each item to {"type": ..., "data": ...}
        objects: list[dict] = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            if "type" in item and "data" in item:
                objects.append(item)
            elif "type" in item and "id" in item:
                # Flat format — wrap in {"type", "data"}
                type_name = item.pop("type")
                objects.append({"type": type_name, "data": item})

        # Update counters based on extracted IDs
        for obj in objects:
            obj_id = obj.get("data", {}).get("id", "")
            for prefix, key in [("ent", "ent"), ("evt", "evt"), ("clm", "clm"), ("rel", "rel"), ("res", "res"), ("ign", "ign")]:
                if f"_{prefix}_" in obj_id:
                    try:
                        num = int(obj_id.split(f"_{prefix}_")[-1])
                        self._counters[key] = max(self._counters.get(key, 0), num)
                    except (ValueError, IndexError):
                        pass

        return objects

    def _normalize_ids(self, objects: list[dict], doc_id: str) -> list[dict]:
        """Normalize entity ID prefixes: LLM sometimes uses _char_ instead of _ent_.

        Also normalizes all references to those IDs in Event/Claim/Relation fields.
        """
        # Build mapping of wrong→correct IDs from Entity objects
        id_fixes: dict[str, str] = {}
        for obj in objects:
            if obj.get("type") != "Entity":
                continue
            data = obj.get("data", {})
            eid = data.get("id", "")
            if "_char_" in eid:
                correct_id = eid.replace("_char_", "_ent_")
                id_fixes[eid] = correct_id
                data["id"] = correct_id

        if not id_fixes:
            return objects

        # Fix references in all object types
        ref_fields = {
            "Event": ["participants"],
            "Claim": ["subject", "object"],
            "Relation": ["subject", "object", "claim_id"],
        }
        for obj in objects:
            type_name = obj.get("type", "")
            fields = ref_fields.get(type_name, [])
            data = obj.get("data", {})
            for field in fields:
                val = data.get(field)
                if val is None:
                    continue
                if isinstance(val, str):
                    if val in id_fixes:
                        data[field] = id_fixes[val]
                elif isinstance(val, list):
                    data[field] = [id_fixes.get(v, v) for v in val]

        logger.info("Normalized %d entity ID prefixes (_char_ → _ent_)", len(id_fixes))
        return objects

    def _validate_grounding(
        self, objects: list[dict], segments: list[Segment]
    ) -> list[dict]:
        """Remove entity aliases and names that don't appear in their source segments.

        This catches LLM hallucinations where it invents aliases not present in the text.
        """
        seg_map = {s.id: s.text_slice for s in segments}
        trimmed = 0

        for obj in objects:
            if obj.get("type") != "Entity":
                continue
            data = obj.get("data", {})
            seg_ids = list(data.get("source_segment_ids", []))
            combined = " ".join(seg_map.get(sid, "") for sid in seg_ids)

            # Check aliases — trim those not grounded in source text
            aliases = data.get("aliases", [])
            grounded_aliases = []
            for alias in aliases:
                if alias in combined:
                    grounded_aliases.append(alias)
                else:
                    # Search broader segment range
                    found = False
                    for s in segments:
                        if alias in s.text_slice:
                            if s.id not in seg_ids:
                                seg_ids.append(s.id)
                            grounded_aliases.append(alias)
                            found = True
                            break
                    if not found:
                        trimmed += 1
                        logger.debug("Trimmed ungrounded alias '%s' from entity '%s'", alias, data.get("name", ""))
            data["aliases"] = grounded_aliases
            data["source_segment_ids"] = seg_ids

        if trimmed:
            logger.info("Trimmed %d ungrounded aliases from entities", trimmed)
        return objects

    def _assign_missing_ids(self, objects: list[dict], doc_id: str) -> list[dict]:
        """Auto-assign IDs to objects that lack them."""
        prefix_map = {
            "Entity": "ent", "Event": "evt", "Claim": "clm",
            "Relation": "rel", "Residual": "res", "IgnoreSegment": "ign",
        }
        for obj in objects:
            data = obj.get("data", {})
            if "id" not in data or not data["id"]:
                type_name = obj.get("type", "obj")
                prefix = prefix_map.get(type_name, "obj")
                idx = self._next_index(prefix)
                data["id"] = f"{doc_id}_{prefix}_{idx:04d}"
        return objects

    @staticmethod
    def build_entity_map(objects: list[dict]) -> dict[str, str]:
        """Build {entity_name: entity_id} mapping from extracted objects.

        Includes both name and all aliases as keys.
        """
        mapping: dict[str, str] = {}
        for obj in objects:
            if obj.get("type") != "Entity":
                continue
            data = obj.get("data", {})
            eid = data.get("id", "")
            name = data.get("name", "")
            if name and eid:
                mapping[name] = eid
            for alias in data.get("aliases", []):
                if alias and eid:
                    mapping[alias] = eid
        return mapping

    def reset_counters(self) -> None:
        """Reset ID counters (for fresh extraction runs)."""
        self._counters = {}