"""LLM Extractor — extract semantic objects from text segments using Claude API."""
from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any

import anthropic

from t2c.ontology import Segment

logger = logging.getLogger(__name__)

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

## ID 命名规则

**严格遵守以下 ID 前缀，不要使用其他前缀（如 _char_、_person_ 等都是错误的）：**

- Entity: `{doc_id}_ent_{{序号:04d}}`（从 {next_ent_idx:04d} 开始，**前缀必须是 _ent_ 不是 _char_**）
- Event: `{doc_id}_evt_{{序号:04d}}`（从 {next_evt_idx:04d} 开始）
- Claim: `{doc_id}_clm_{{序号:04d}}`（从 {next_clm_idx:04d} 开始）
- Relation: `{doc_id}_rel_{{序号:04d}}`（从 {next_rel_idx:04d} 开始）

示例：hongloumeng_ent_0001, hongloumeng_evt_0001, hongloumeng_clm_0001, hongloumeng_rel_0001

## 重要约束

1. source_segment_ids 必须是上面输入中存在的 segment ID
2. Claim 的 subject/object 必须引用已定义的 Entity ID（包括已知人物列表中的）
3. Relation 的 claim_id 必须引用同章已定义的 Claim ID
4. 同一人物在不同 segment 中出现时，使用相同 Entity ID
5. 已知人物列表中的人物，直接使用其 Entity ID，不要创建新的
6. 只提取明确出现在文本中的信息，不要推断
7. 对白中的内容用 modality="reported" 或 "claimed_by_source"
8. 叙述中确定的事实用 modality="asserted"

请直接返回 JSON 数组，不要添加任何解释文本。不要用 markdown 代码块包裹。
"""

# Max segment text per single LLM call — MiniMax-M3 thinking uses tokens aggressively,
# so keep input small enough that output fits within max_tokens.
_MAX_BATCH_CHARS = 1500


class LLMExtractor:
    """Extract semantic objects from text segments using Claude API."""

    def __init__(
        self,
        model: str = "MiniMax-M3",
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self._client = anthropic.Anthropic(
            api_key=api_key or os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY"),
            base_url=base_url or os.environ.get("ANTHROPIC_BASE_URL"),
        )
        self._model = model
        # Track per-type counters across calls for consistent ID assignment
        self._counters: dict[str, int] = {}

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
        # Split into batches if total text is too long
        batches = self._batch_segments(segments)

        if len(batches) == 1:
            return self._extract_batch(doc_id, chapter_num, chapter_title, segments, existing_entities)

        # Multi-batch: extract each batch, then merge
        all_objects: list[dict] = []
        batch_entities = dict(existing_entities or {})
        pre_entity_count = len(batch_entities)

        for i, batch in enumerate(batches):
            logger.info("Ch%d batch %d/%d: %d segments", chapter_num, i + 1, len(batches), len(batch))
            objects = self._extract_batch(doc_id, chapter_num, chapter_title, batch, batch_entities)
            all_objects.extend(objects)
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
        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": 16384,
            "messages": [{"role": "user", "content": prompt}],
        }
        # For Anthropic-compatible APIs that support extended thinking,
        # limit thinking budget so it doesn't consume all output tokens.
        t0 = time.time()
        try:
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": 2048}
            response = self._client.messages.create(**kwargs)
        except (anthropic.BadRequestError, TypeError):
            # Fallback: API doesn't support thinking parameter
            del kwargs["thinking"]
            response = self._client.messages.create(**kwargs)
        elapsed = time.time() - t0

        # Log API response metadata
        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "input_tokens", "?") if usage else "?"
        output_tokens = getattr(usage, "output_tokens", "?") if usage else "?"
        logger.info(
            "Ch%d batch API: stop_reason=%s, tokens=%s→%s, %.1fs",
            chapter_num, response.stop_reason, input_tokens, output_tokens, elapsed,
        )
        if response.stop_reason == "max_tokens":
            logger.warning("Ch%d batch hit max_tokens — output likely truncated", chapter_num)

        response_text = self._get_text_from_response(response)
        if response_text is None:
            logger.warning("Ch%d batch: no text content (stop_reason=%s)", chapter_num, response.stop_reason)
            return []
        objects = self._parse_response(response_text)
        # Normalize wrong ID prefixes (e.g. _char_ → _ent_)
        objects = self._normalize_ids(objects, doc_id)
        # Auto-assign missing IDs
        objects = self._assign_missing_ids(objects, doc_id)
        # Trim ungrounded aliases
        objects = self._validate_grounding(objects, segments)
        return objects

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
            for prefix, key in [("ent", "ent"), ("evt", "evt"), ("clm", "clm"), ("rel", "rel")]:
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
        prefix_map = {"Entity": "ent", "Event": "evt", "Claim": "clm", "Relation": "rel"}
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