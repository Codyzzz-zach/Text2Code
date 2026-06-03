"""Tests for t2c/extractor.py — LLMExtractor with mocked API."""
import json
from unittest.mock import MagicMock, patch

import pytest

from t2c.extractor import LLMExtractor
from t2c.ontology import Segment


def _make_segment(seg_id="hongloumeng_seg_0001", text="测试文本。"):
    return Segment(
        id=seg_id,
        doc_id="hongloumeng",
        block_index=0,
        segment_type="sentence",
        start_offset=0,
        end_offset=len(text),
        text_slice=text,
        hash="sha256:abc",
    )


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
        extractor = LLMExtractor(api_key="fake-key")
        objects = extractor._parse_response(MOCK_RESPONSE_JSON)
        assert len(objects) == 4
        assert objects[0]["type"] == "Entity"
        assert objects[0]["data"]["name"] == "甄士隐"
        assert objects[1]["type"] == "Event"
        assert objects[2]["type"] == "Claim"
        assert objects[3]["type"] == "Relation"

    def test_parse_json_in_code_block(self):
        extractor = LLMExtractor(api_key="fake-key")
        wrapped = f"```json\n{MOCK_RESPONSE_JSON}\n```"
        objects = extractor._parse_response(wrapped)
        assert len(objects) == 4

    def test_parse_json_with_surrounding_text(self):
        extractor = LLMExtractor(api_key="fake-key")
        text = f"Here are the results:\n{MOCK_RESPONSE_JSON}\nThat's all."
        objects = extractor._parse_response(text)
        assert len(objects) == 4

    def test_parse_empty_response(self):
        extractor = LLMExtractor(api_key="fake-key")
        objects = extractor._parse_response("")
        assert objects == []

    def test_parse_invalid_json(self):
        extractor = LLMExtractor(api_key="fake-key")
        objects = extractor._parse_response("not json at all")
        assert objects == []

    def test_counter_tracking(self):
        extractor = LLMExtractor(api_key="fake-key")
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
    @patch("t2c.extractor.anthropic.Anthropic")
    def test_extract_chapter_calls_api(self, mock_anthropic_cls):
        # Setup mock — simulate text block (not thinking block)
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_text_block = MagicMock(type="text", text=MOCK_RESPONSE_JSON)
        mock_message = MagicMock()
        mock_message.content = [mock_text_block]
        mock_message.stop_reason = "end_turn"
        mock_client.messages.create.return_value = mock_message

        extractor = LLMExtractor(api_key="fake-key")
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

    @patch("t2c.extractor.anthropic.Anthropic")
    def test_extract_with_existing_entities(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_text_block = MagicMock(type="text", text=MOCK_RESPONSE_JSON)
        mock_message = MagicMock()
        mock_message.content = [mock_text_block]
        mock_message.stop_reason = "end_turn"
        mock_client.messages.create.return_value = mock_message

        extractor = LLMExtractor(api_key="fake-key")
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
        extractor = LLMExtractor(api_key="fake-key")
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
        extractor = LLMExtractor(api_key="fake-key")
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
        extractor = LLMExtractor(api_key="fake-key")
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
        extractor = LLMExtractor(api_key="fake-key")
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
        extractor = LLMExtractor(api_key="fake-key")
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
