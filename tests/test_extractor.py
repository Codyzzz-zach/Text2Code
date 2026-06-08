"""Tests for t2c/extractor.py — LLMExtractor with mocked API."""
import json
from unittest.mock import MagicMock, patch

import pytest

from t2c.extractor import LLMExtractor
from t2c.ontology import Segment


def _sha256(text: str) -> str:
    import hashlib
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _make_segment(seg_id="hongloumeng_seg_0001", text="测试文本。"):
    return Segment(
        id=seg_id,
        doc_id="hongloumeng",
        block_index=0,
        segment_type="sentence",
        start_offset=0,
        end_offset=len(text),
        text_slice=text,
        hash=_sha256(text),
    )


def _make_extractor() -> LLMExtractor:
    """Create an LLMExtractor with a mock client — no anthropic dependency needed."""
    return LLMExtractor(_client=MagicMock())


MOCK_RESPONSE_JSON = json.dumps([
    {
        "type": "Entity",
        "data": {
            "id": "hongloumeng_ent_0001",
            "name": "甄士隐",
            "kind": "person",
            "aliases": ["士隐"],
            "source_segment_ids": ["hongloumeng_seg_0001"],
        },
    },
    {
        "type": "Event",
        "data": {
            "id": "hongloumeng_evt_0001",
            "name": "甄士隐做梦",
            "kind": "occurrence",
            "participants": ["hongloumeng_ent_0001"],
            "source_segment_ids": ["hongloumeng_seg_0001"],
        },
    },
    {
        "type": "Claim",
        "data": {
            "id": "hongloumeng_clm_0001",
            "subject": "hongloumeng_ent_0001",
            "predicate": "lives_in",
            "object": "hongloumeng_ent_0002",
            "modality": "asserted",
            "polarity": "positive",
            "source_segment_ids": ["hongloumeng_seg_0001"],
        },
    },
    {
        "type": "Relation",
        "data": {
            "id": "hongloumeng_rel_0001",
            "subject": "hongloumeng_ent_0001",
            "predicate": "lives_in",
            "object": "hongloumeng_ent_0002",
            "claim_id": "hongloumeng_clm_0001",
        },
    },
])


class TestLLMExtractorParsing:
    def test_parse_clean_json(self):
        extractor = _make_extractor()
        objects = extractor._parse_response(MOCK_RESPONSE_JSON)
        assert len(objects) == 4
        assert objects[0]["type"] == "Entity"
        assert objects[0]["data"]["name"] == "甄士隐"
        assert objects[1]["type"] == "Event"
        assert objects[2]["type"] == "Claim"
        assert objects[3]["type"] == "Relation"

    def test_parse_json_in_code_block(self):
        extractor = _make_extractor()
        wrapped = f"```json\n{MOCK_RESPONSE_JSON}\n```"
        objects = extractor._parse_response(wrapped)
        assert len(objects) == 4

    def test_parse_json_with_surrounding_text(self):
        extractor = _make_extractor()
        text = f"Here are the results:\n{MOCK_RESPONSE_JSON}\nThat's all."
        objects = extractor._parse_response(text)
        assert len(objects) == 4

    def test_parse_empty_response(self):
        extractor = _make_extractor()
        objects = extractor._parse_response("")
        assert objects == []

    def test_parse_invalid_json(self):
        extractor = _make_extractor()
        objects = extractor._parse_response("not json at all")
        assert objects == []

    def test_counter_tracking(self):
        extractor = _make_extractor()
        objects = extractor._parse_response(MOCK_RESPONSE_JSON)
        assert extractor._counters.get("ent") == 1
        assert extractor._counters.get("evt") == 1
        assert extractor._counters.get("clm") == 1
        assert extractor._counters.get("rel") == 1


class TestBuildEntityMap:
    def test_build_from_entities(self):
        objects = [
            {"type": "Entity", "data": {
                "id": "e1", "name": "贾宝玉", "kind": "person",
                "aliases": ["宝玉", "宝二爷"],
            }},
            {"type": "Claim", "data": {
                "id": "c1", "subject": "e1", "predicate": "test",
                "modality": "asserted", "polarity": "positive",
            }},
        ]
        mapping = LLMExtractor.build_entity_map(objects)
        assert mapping["贾宝玉"] == "e1"
        assert mapping["宝玉"] == "e1"
        assert mapping["宝二爷"] == "e1"
        assert "Claim" not in mapping


class TestExtractChapterMocked:
    def test_extract_chapter_calls_api(self):
        # v3.4.2: MOCK_RESPONSE_JSON is verbose form, so opt into verbose-v1
        # to exercise the legacy code path. New tests in TestCompactProtocol
        # cover the default compact path.
        mock_client = MagicMock()
        mock_text_block = MagicMock(type="text", text=MOCK_RESPONSE_JSON)
        mock_message = MagicMock()
        mock_message.content = [mock_text_block]
        mock_message.stop_reason = "end_turn"
        mock_client.messages.create.return_value = mock_message

        extractor = LLMExtractor(_client=mock_client, extractor_protocol="verbose-v1", cache_mode="off")
        segments = [
            _make_segment("hongloumeng_seg_0001", "甄士隐住在姑苏。"),
            _make_segment("hongloumeng_seg_0002", "他做了一个梦。"),
        ]
        objects = extractor.extract_chapter(
            doc_id="hongloumeng",
            chapter_num=1,
            chapter_title="甄士隐梦幻识通灵",
            segments=segments,
        )

        assert len(objects) == 4
        mock_client.messages.create.assert_called_once()
        # Verify prompt contains segment IDs
        call_args = mock_client.messages.create.call_args
        prompt = call_args.kwargs["messages"][0]["content"]
        assert "hongloumeng_seg_0001" in prompt
        assert "甄士隐" in prompt

    def test_extract_with_existing_entities(self):
        mock_client = MagicMock()
        mock_text_block = MagicMock(type="text", text=MOCK_RESPONSE_JSON)
        mock_message = MagicMock()
        mock_message.content = [mock_text_block]
        mock_message.stop_reason = "end_turn"
        mock_client.messages.create.return_value = mock_message

        extractor = LLMExtractor(_client=mock_client, extractor_protocol="verbose-v1", cache_mode="off")
        segments = [_make_segment()]
        existing = {"甄士隐": "hongloumeng_ent_0001"}
        objects = extractor.extract_chapter(
            doc_id="hongloumeng",
            chapter_num=2,
            chapter_title="第二回",
            segments=segments,
            existing_entities=existing,
        )

        # Verify prompt includes existing entities section
        call_args = mock_client.messages.create.call_args
        prompt = call_args.kwargs["messages"][0]["content"]
        assert "已知人物" in prompt
        assert "甄士隐" in prompt


class TestNormalizeIds:
    def test_normalize_char_to_ent(self):
        extractor = _make_extractor()
        objects = [
            {"type": "Entity", "data": {
                "id": "hongloumeng_char_0001", "name": "甄士隐", "kind": "person",
                "aliases": ["士隐"], "source_segment_ids": ["seg1"],
            }},
            {"type": "Event", "data": {
                "id": "hongloumeng_evt_0001", "name": "事件",
                "participants": ["hongloumeng_char_0001"],
                "source_segment_ids": ["seg1"],
            }},
            {"type": "Claim", "data": {
                "id": "hongloumeng_clm_0001", "subject": "hongloumeng_char_0001",
                "predicate": "test", "object": "hongloumeng_char_0002",
                "modality": "asserted", "polarity": "positive",
                "source_segment_ids": ["seg1"],
            }},
            {"type": "Entity", "data": {
                "id": "hongloumeng_char_0002", "name": "封肃", "kind": "person",
                "aliases": [], "source_segment_ids": ["seg2"],
            }},
            {"type": "Relation", "data": {
                "id": "hongloumeng_rel_0001", "subject": "hongloumeng_char_0001",
                "predicate": "test", "object": "hongloumeng_char_0002",
                "claim_id": "hongloumeng_clm_0001",
            }},
        ]
        result = extractor._normalize_ids(objects, "hongloumeng")
        # Entity IDs should be normalized
        assert result[0]["data"]["id"] == "hongloumeng_ent_0001"
        assert result[3]["data"]["id"] == "hongloumeng_ent_0002"
        # References should be normalized
        assert result[1]["data"]["participants"] == ["hongloumeng_ent_0001"]
        assert result[2]["data"]["subject"] == "hongloumeng_ent_0001"
        assert result[2]["data"]["object"] == "hongloumeng_ent_0002"
        assert result[4]["data"]["subject"] == "hongloumeng_ent_0001"
        assert result[4]["data"]["object"] == "hongloumeng_ent_0002"

    def test_no_normalize_when_ids_correct(self):
        extractor = _make_extractor()
        objects = [
            {"type": "Entity", "data": {
                "id": "hongloumeng_ent_0001", "name": "甄士隐",
                "kind": "person", "aliases": [],
                "source_segment_ids": ["seg1"],
            }},
        ]
        result = extractor._normalize_ids(objects, "hongloumeng")
        assert result[0]["data"]["id"] == "hongloumeng_ent_0001"


class TestValidateGrounding:
    def test_trim_ungrounded_alias(self):
        extractor = _make_extractor()
        segments = [
            _make_segment("seg1", "甄士隐住在姑苏城中。"),
            _make_segment("seg2", "封肃是本地人。"),
        ]
        objects = [
            {"type": "Entity", "data": {
                "id": "ent1", "name": "甄士隐", "kind": "person",
                "aliases": ["士隐", "疯道人"],  # "疯道人" not in source
                "source_segment_ids": ["seg1"],
            }},
        ]
        result = extractor._validate_grounding(objects, segments)
        assert "士隐" in result[0]["data"]["aliases"]
        assert "疯道人" not in result[0]["data"]["aliases"]

    def test_keep_grounded_alias(self):
        extractor = _make_extractor()
        segments = [_make_segment("seg1", "甄士隐做梦。士隐惊醒。")]
        objects = [
            {"type": "Entity", "data": {
                "id": "ent1", "name": "甄士隐", "kind": "person",
                "aliases": ["士隐"],
                "source_segment_ids": ["seg1"],
            }},
        ]
        result = extractor._validate_grounding(objects, segments)
        assert "士隐" in result[0]["data"]["aliases"]

    def test_recover_alias_from_broader_segments(self):
        extractor = _make_extractor()
        segments = [
            _make_segment("seg1", "此人姓甄。"),
            _make_segment("seg2", "士隐惊醒后出门。"),
        ]
        objects = [
            {"type": "Entity", "data": {
                "id": "ent1", "name": "甄士隐", "kind": "person",
                "aliases": ["士隐"],
                "source_segment_ids": ["seg1"],  # alias only in seg2, not seg1
            }},
        ]
        result = extractor._validate_grounding(objects, segments)
        assert "士隐" in result[0]["data"]["aliases"]
        # Should also add seg2 to source_segment_ids since alias was found there
        assert "seg2" in result[0]["data"]["source_segment_ids"]


class TestLazyImport:
    def test_extractor_without_anthropics_raises_import_error(self):
        """When anthropic is not installed and no _client is given, raise clear ImportError."""
        import t2c.extractor as ext_mod
        original = ext_mod.anthropic
        try:
            ext_mod.anthropic = None
            with pytest.raises(ImportError, match="optional anthropic dependency"):
                LLMExtractor(api_key="fake-key")
        finally:
            ext_mod.anthropic = original

    def test_extractor_with_mock_client_works(self):
        """When _client is provided, no anthropic import is needed."""
        mock_client = MagicMock()
        extractor = LLMExtractor(_client=mock_client)
        assert extractor._client is mock_client


class TestMaxTokensConfig:
    """v3.4.1: configurable max_tokens and thinking_budget.
    v3.4.2: defaults lowered (max_tokens 32768→8192, thinking 2048→1024,
    batch_chars 900→1200) to discourage long outputs and pair with the
    compact protocol.
    """

    def test_default_max_tokens_is_8192(self):
        ext = LLMExtractor(_client=MagicMock())
        assert ext._max_tokens == 8192

    def test_default_thinking_budget_is_1024(self):
        ext = LLMExtractor(_client=MagicMock())
        assert ext._thinking_budget == 1024

    def test_explicit_max_tokens_overrides_default(self):
        ext = LLMExtractor(_client=MagicMock(), max_tokens=8192)
        assert ext._max_tokens == 8192

    def test_explicit_thinking_budget_overrides_default(self):
        ext = LLMExtractor(_client=MagicMock(), thinking_budget=1024)
        assert ext._thinking_budget == 1024

    def test_env_var_overrides_default_max_tokens(self, monkeypatch):
        monkeypatch.setenv("T2C_MAX_TOKENS", "65536")
        ext = LLMExtractor(_client=MagicMock())
        assert ext._max_tokens == 65536

    def test_env_var_overrides_default_thinking_budget(self, monkeypatch):
        monkeypatch.setenv("T2C_THINKING_BUDGET", "512")
        ext = LLMExtractor(_client=MagicMock())
        assert ext._thinking_budget == 512

    def test_explicit_arg_beats_env_var(self, monkeypatch):
        monkeypatch.setenv("T2C_MAX_TOKENS", "9999")
        ext = LLMExtractor(_client=MagicMock(), max_tokens=4096)
        assert ext._max_tokens == 4096

    def test_max_batch_chars_default_is_4000(self):
        # v4.2: 900 → 1200 → 4000 — increased batch size to reduce
        # API call overhead per batch and improve DeepSeek prefix cache hit.
        from t2c.extractor import _MAX_BATCH_CHARS
        assert _MAX_BATCH_CHARS == 4000

    def test_telemetry_fields_initialized(self):
        ext = LLMExtractor(_client=MagicMock())
        assert ext._last_batch_truncated is False
        assert ext._total_input_tokens == 0
        assert ext._total_output_tokens == 0
        assert ext._api_elapsed_sec == 0.0

    def test_default_protocol_is_compact(self):
        # v3.4.2: default protocol switched from verbose-v1 to compact-v1.
        ext = LLMExtractor(_client=MagicMock())
        assert ext._protocol == "compact-v1"
        assert ext._prompt_version == "compact-main-v2"

    def test_verbose_protocol_explicit(self):
        ext = LLMExtractor(_client=MagicMock(), extractor_protocol="verbose-v1")
        assert ext._protocol == "verbose-v1"
        assert ext._prompt_version == "verbose-main-v1"


class TestPartialRecovery:
    """v3.4.1: _recover_partial_objects salvages complete {...} blocks from truncated JSON."""

    def test_recovers_complete_object_before_truncation(self):
        text = (
            '[{"type": "Entity", "data": {"id": "d_ent_0001", "name": "Alice", '
            '"kind": "person"}}, {"type": "Event", "data": {"id": "d_evt_0001"'
        )
        rec = LLMExtractor._recover_partial_objects(None, text)  # type: ignore[arg-type]
        # Bound method: pass instance.
        rec = LLMExtractor(_client=MagicMock())._recover_partial_objects(text)
        assert len(rec) == 1
        assert rec[0]["type"] == "Entity"
        assert rec[0]["data"]["id"] == "d_ent_0001"

    def test_returns_empty_when_no_complete_objects(self):
        text = '[{"type": "Entity", "data": {"id": "d_ent_0001", "name":'
        rec = LLMExtractor(_client=MagicMock())._recover_partial_objects(text)
        assert rec == []

    def test_strips_markdown_fences_before_scan(self):
        text = '```json\n[{"type": "Entity", "data": {"id": "x", "name": "y"}},\n'
        rec = LLMExtractor(_client=MagicMock())._recover_partial_objects(text)
        assert len(rec) == 1
        assert rec[0]["data"]["id"] == "x"

    def test_normalizes_flat_format(self):
        text = '[{"type": "Entity", "id": "x", "name": "y"}'
        rec = LLMExtractor(_client=MagicMock())._recover_partial_objects(text)
        assert len(rec) == 1
        assert rec[0] == {"type": "Entity", "data": {"id": "x", "name": "y"}}

    def test_handles_nested_braces_in_strings(self):
        text = '[{"type": "Entity", "data": {"id": "x", "name": "{nested}"}}'
        rec = LLMExtractor(_client=MagicMock())._recover_partial_objects(text)
        assert len(rec) == 1
        assert rec[0]["data"]["name"] == "{nested}"


# ---------------------------------------------------------------------------
# v3.4.2: compact protocol + cache integration
# ---------------------------------------------------------------------------


_COMPACT_RESPONSE = """[
  {"t":"E","lid":"e1","n":"甄士隐","k":"person","a":["士隐"],"sid":["hongloumeng_seg_0001"],"q":["甄士隐"]},
  {"t":"E","lid":"e2","n":"姑苏","k":"location","sid":["hongloumeng_seg_0001"],"q":["姑苏"]},
  {"t":"C","s":"e1","p":"lives_in","o":"e2","m":"asserted","pol":"positive","sid":["hongloumeng_seg_0001"],"q":["住"]},
  {"t":"I","sid":"hongloumeng_seg_0002","r":"chapter title"}
]"""


class TestCompactProtocolEndToEnd:
    def test_compact_response_expands_and_derives_relation(self):
        mock_client = MagicMock()
        mock_text_block = MagicMock(type="text", text=_COMPACT_RESPONSE)
        mock_message = MagicMock()
        mock_message.content = [mock_text_block]
        mock_message.stop_reason = "end_turn"
        mock_client.messages.create.return_value = mock_message

        extractor = LLMExtractor(_client=mock_client, cache_mode="off")
        segments = [
            _make_segment("hongloumeng_seg_0001", "甄士隐住在姑苏。"),
            _make_segment("hongloumeng_seg_0002", "第1回"),
        ]
        objects = extractor.extract_chapter(
            doc_id="hongloumeng",
            chapter_num=1,
            chapter_title="第1回",
            segments=segments,
        )
        # 2 Entity + 1 Claim + 1 derived Relation = 4 (I removed from VALID_COMPACT_TYPES)
        assert len(objects) == 4, f"Got {len(objects)} objects: {[o['type'] for o in objects]}"
        types = {o["type"] for o in objects}
        assert types == {"Entity", "Claim", "Relation"}, f"Unexpected types: {types}"
        # The compact prompt is what was sent (not verbose). The compact
        # prompt forbids Relation and EvidenceRef explicitly, so we look
        # for those markers rather than English strings.
        prompt = mock_client.messages.create.call_args.kwargs["messages"][0]["content"]
        assert "严禁输出" in prompt
        assert "R (Relation)" in prompt
        assert "EvidenceRef 字段" in prompt

    def test_compact_does_not_pass_relation_through(self):
        # Even if the LLM emits R in the response, the compact path ignores
        # it (Relation is derived, not emitted).
        bad_response = """[
          {"t":"R","id":"foo","subject":"e1","predicate":"x","object":"e2","claim_id":"c1"},
          {"t":"E","lid":"e1","n":"A","k":"person","sid":["s1"]},
          {"t":"E","lid":"e2","n":"B","k":"person","sid":["s1"]},
          {"t":"C","s":"e1","p":"x","o":"e2","m":"asserted","pol":"positive","sid":["s1"]}
        ]"""
        mock_client = MagicMock()
        mock_text_block = MagicMock(type="text", text=bad_response)
        mock_message = MagicMock()
        mock_message.content = [mock_text_block]
        mock_message.stop_reason = "end_turn"
        mock_client.messages.create.return_value = mock_message

        extractor = LLMExtractor(_client=mock_client)
        segments = [_make_segment("s1", "A and B")]
        objects = extractor.extract_chapter(
            doc_id="d", chapter_num=1, chapter_title="t", segments=segments,
        )
        # No raw R from the LLM; the program-derived R is the only Relation.
        rels = [o for o in objects if o["type"] == "Relation"]
        assert len(rels) == 1
        assert rels[0]["data"]["claim_id"].startswith("d_clm_")


class TestLLMCacheIntegration:
    def test_cache_hit_does_not_call_llm_client(self, tmp_path):
        mock_client = MagicMock()
        mock_text_block = MagicMock(type="text", text=_COMPACT_RESPONSE)
        mock_message = MagicMock()
        mock_message.content = [mock_text_block]
        mock_message.stop_reason = "end_turn"
        mock_client.messages.create.return_value = mock_message

        # First run with read_write to populate the cache
        ext1 = LLMExtractor(
            _client=mock_client,
            cache_mode="read_write",
            cache_dir=tmp_path,
        )
        segments = [
            _make_segment("hongloumeng_seg_0001", "甄士隐住在姑苏。"),
            _make_segment("hongloumeng_seg_0002", "第1回"),
        ]
        ext1.extract_chapter(
            doc_id="hongloumeng", chapter_num=1,
            chapter_title="第1回", segments=segments,
        )
        assert mock_client.messages.create.call_count == 1
        assert ext1._cache_hits == 0
        assert ext1._cache_misses == 1

        # Second run with a fresh client — cache hit should bypass the LLM.
        mock_client2 = MagicMock()  # would raise if called
        ext2 = LLMExtractor(
            _client=mock_client2,
            cache_mode="read_only",
            cache_dir=tmp_path,
        )
        objects = ext2.extract_chapter(
            doc_id="hongloumeng", chapter_num=1,
            chapter_title="第1回", segments=segments,
        )
        assert mock_client2.messages.create.call_count == 0
        assert ext2._cache_hits == 1
        assert ext2._cache_misses == 0
        assert len(objects) == 4  # I removed from VALID_COMPACT_TYPES

    def test_read_only_misses_raise(self, tmp_path):
        mock_client = MagicMock()
        mock_text_block = MagicMock(type="text", text=_COMPACT_RESPONSE)
        mock_message = MagicMock()
        mock_message.content = [mock_text_block]
        mock_message.stop_reason = "end_turn"
        mock_client.messages.create.return_value = mock_message

        ext = LLMExtractor(
            _client=mock_client,
            cache_mode="read_only",
            cache_dir=tmp_path,
        )
        with pytest.raises(FileNotFoundError, match="Cache miss"):
            ext.extract_chapter(
                doc_id="d", chapter_num=1, chapter_title="t",
                segments=[_make_segment("s1", "x")],
            )
        # LLM must NOT have been called
        mock_client.messages.create.assert_not_called()

    def test_off_mode_never_reads_or_writes_cache(self, tmp_path):
        mock_client = MagicMock()
        mock_text_block = MagicMock(type="text", text=_COMPACT_RESPONSE)
        mock_message = MagicMock()
        mock_message.content = [mock_text_block]
        mock_message.stop_reason = "end_turn"
        mock_client.messages.create.return_value = mock_message

        ext = LLMExtractor(_client=mock_client, cache_mode="off", cache_dir=tmp_path)
        segments = [
            _make_segment("hongloumeng_seg_0001", "甄士隐住在姑苏。"),
        ]
        ext.extract_chapter(
            doc_id="hongloumeng", chapter_num=1,
            chapter_title="第1回", segments=segments,
        )
        # No cache lookups in OFF mode
        assert ext._cache is None

    def test_refresh_mode_overwrites_existing_cache(self, tmp_path):
        mock_client = MagicMock()
        mock_text_block = MagicMock(type="text", text=_COMPACT_RESPONSE)
        mock_message = MagicMock()
        mock_message.content = [mock_text_block]
        mock_message.stop_reason = "end_turn"
        mock_client.messages.create.return_value = mock_message

        # First run: read_write
        ext1 = LLMExtractor(
            _client=mock_client, cache_mode="read_write", cache_dir=tmp_path,
        )
        ext1.extract_chapter(
            doc_id="d", chapter_num=1, chapter_title="t",
            segments=[_make_segment("s1", "x")],
        )
        # Second run: refresh should call LLM again, not serve from cache
        ext2 = LLMExtractor(
            _client=mock_client, cache_mode="refresh", cache_dir=tmp_path,
        )
        ext2.extract_chapter(
            doc_id="d", chapter_num=1, chapter_title="t",
            segments=[_make_segment("s1", "x")],
        )
        # Two LLM calls total (1 from first, 1 from refresh)
        assert mock_client.messages.create.call_count == 2
        # In refresh, no hit was recorded (it bypasses the lookup)
        assert ext2._cache_hits == 0


class TestExtractorTelemetryV342:
    """v3.4.2: cache telemetry fields are exposed."""

    def test_cache_counters_init_zero(self):
        ext = LLMExtractor(_client=MagicMock())
        assert ext._cache_hits == 0
        assert ext._cache_misses == 0
        assert ext._cache_lookups == 0

    def test_seed_entity_map(self):
        ext = LLMExtractor(_client=MagicMock())
        ext._seed_entity_map({"甄士隐": "d_ent_9999"})
        assert ext._seed_entities == {"甄士隐": "d_ent_9999"}
