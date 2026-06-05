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
        mock_client = MagicMock()
        mock_text_block = MagicMock(type="text", text=MOCK_RESPONSE_JSON)
        mock_message = MagicMock()
        mock_message.content = [mock_text_block]
        mock_message.stop_reason = "end_turn"
        mock_client.messages.create.return_value = mock_message

        extractor = LLMExtractor(_client=mock_client)
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

        extractor = LLMExtractor(_client=mock_client)
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
    """v3.4.1: configurable max_tokens and thinking_budget."""

    def test_default_max_tokens_is_32768(self):
        ext = LLMExtractor(_client=MagicMock())
        assert ext._max_tokens == 32768

    def test_default_thinking_budget_is_2048(self):
        ext = LLMExtractor(_client=MagicMock())
        assert ext._thinking_budget == 2048

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

    def test_max_batch_chars_default_is_900(self):
        # Imported lazily so the test also serves as a guard against accidental
        # reverts to 1500.
        from t2c.extractor import _MAX_BATCH_CHARS
        assert _MAX_BATCH_CHARS == 900

    def test_telemetry_fields_initialized(self):
        ext = LLMExtractor(_client=MagicMock())
        assert ext._last_batch_truncated is False
        assert ext._total_input_tokens == 0
        assert ext._total_output_tokens == 0
        assert ext._api_elapsed_sec == 0.0


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
