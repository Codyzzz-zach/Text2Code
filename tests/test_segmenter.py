"""Tests for t2c/segmenter.py — Segmenter with Chinese + English support."""
from t2c.corpus import CorpusManager
from t2c.ontology import Block
from t2c.segmenter import Segmenter


def _sha256(text: str) -> str:
    import hashlib
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _make_block(text: str, block_type: str = "paragraph", index: int = 0) -> tuple[Block, str]:
    """Create a Block and its text for testing."""
    block = Block(
        id=f"test_blk_{index:04d}",
        doc_id="test",
        index=index,
        block_type=block_type,
        start_offset=0,
        end_offset=len(text),
        text_slice=text,
        hash=_sha256(text),
    )
    return block, text


class TestParagraphSegmentation:
    def test_chinese_sentences(self):
        seg = Segmenter()
        block, text = _make_block("第一句话。第二句话！第三句话？")
        segments = seg.segment_block("test", block, text)
        assert len(segments) >= 2
        assert segments[0].segment_type == "sentence"

    def test_english_sentences(self):
        seg = Segmenter()
        block, text = _make_block("First sentence. Second sentence! Third sentence?")
        segments = seg.segment_block("test", block, text)
        assert len(segments) >= 2

    def test_mixed_chinese_english(self):
        seg = Segmenter()
        block, text = _make_block("这是中文。This is English. 混合文本！")
        segments = seg.segment_block("test", block, text)
        assert len(segments) >= 2

    def test_single_sentence(self):
        seg = Segmenter()
        block, text = _make_block("只有一句话。")
        segments = seg.segment_block("test", block, text)
        assert len(segments) == 1

    def test_empty_text(self):
        seg = Segmenter()
        block, text = _make_block("")
        segments = seg.segment_block("test", block, text)
        assert len(segments) == 0


class TestDialogueSegmentation:
    def test_chinese_dialogue(self):
        seg = Segmenter()
        block, text = _make_block("他说：「你好啊。」她回答：「我很好。」")
        segments = seg.segment_block("test", block, text)
        dialogue_segs = [s for s in segments if s.segment_type == "dialogue"]
        assert len(dialogue_segs) >= 2

    def test_english_dialogue(self):
        seg = Segmenter()
        block, text = _make_block('He said "hello there" and she replied "how are you"')
        segments = seg.segment_block("test", block, text)
        dialogue_segs = [s for s in segments if s.segment_type == "dialogue"]
        assert len(dialogue_segs) >= 2


class TestHeadingSegmentation:
    def test_heading(self):
        seg = Segmenter()
        block, text = _make_block("# 案件摘要", "heading")
        segments = seg.segment_block("test", block, text)
        assert len(segments) == 1
        assert segments[0].segment_type == "heading"


class TestTableSegmentation:
    def test_table_rows(self):
        seg = Segmenter()
        text = "| A | B |\n|---|---|\n| 1 | 2 |"
        block, _ = _make_block(text, "table")
        segments = seg.segment_block("test", block, text)
        assert len(segments) >= 2  # header + separator + data row
        assert all(s.segment_type == "table_row" for s in segments)


class TestListSegmentation:
    def test_list_items(self):
        seg = Segmenter()
        text = "- item one\n- item two\n- item three"
        block, _ = _make_block(text, "list")
        segments = seg.segment_block("test", block, text)
        assert len(segments) == 3
        assert all(s.segment_type == "list_item" for s in segments)


class TestCodeSegmentation:
    def test_code_block(self):
        seg = Segmenter()
        text = "def hello():\n    print('hi')"
        block, _ = _make_block(text, "code_block")
        segments = seg.segment_block("test", block, text)
        assert len(segments) == 1
        assert segments[0].segment_type == "raw"


class TestLegalClauseSegmentation:
    def test_clause_markers(self):
        seg = Segmenter()
        block, text = _make_block(
            "第一条 本法适用于所有公民。第二条 违法者将受处罚。"
        )
        segments = seg.segment_block("test", block, text)
        assert len(segments) >= 2


class TestSegmentIntegrity:
    def test_segment_ids_sequential(self):
        seg = Segmenter()
        block, text = _make_block("第一句。第二句。第三句。")
        segments = seg.segment_block("test", block, text)
        for i, s in enumerate(segments, 1):
            assert s.id == f"test_seg_{i:04d}"

    def test_segment_hashes_consistent(self):
        seg = Segmenter()
        block, text = _make_block("这是一段测试文本。包含两个句子。")
        segments = seg.segment_block("test", block, text)
        for s in segments:
            assert s.hash.startswith("sha256:")

    def test_offsets_within_block(self):
        seg = Segmenter()
        block, text = _make_block("第一句。第二句。")
        segments = seg.segment_block("test", block, text)
        for s in segments:
            assert s.start_offset >= block.start_offset
            assert s.end_offset <= block.end_offset

    def test_dialogue_between_text_offsets_accurate(self):
        """Fix #1: text between dialogue spans must have correct offsets after strip()."""
        text = "你好。  他说「你好」。再见。"
        block = Block(
            id="test_blk_0000", doc_id="test", index=0,
            block_type="paragraph", start_offset=0, end_offset=len(text),
            text_slice=text, hash=_sha256(text),
        )
        seg = Segmenter()
        segments = seg.segment_block("test", block, text)
        for s in segments:
            assert text[s.start_offset:s.end_offset] == s.text_slice, (
                f"Offset mismatch for segment {s.id}: "
                f"expected '{text[s.start_offset:s.end_offset]}', got '{s.text_slice}'"
            )

    def test_dialogue_after_text_offsets_accurate(self):
        """Fix #1: text after last dialogue span must have correct offsets after strip()."""
        text = "「你好」。  再见。"
        block = Block(
            id="test_blk_0000", doc_id="test", index=0,
            block_type="paragraph", start_offset=0, end_offset=len(text),
            text_slice=text, hash=_sha256(text),
        )
        seg = Segmenter()
        segments = seg.segment_block("test", block, text)
        for s in segments:
            assert text[s.start_offset:s.end_offset] == s.text_slice


class TestSpeakerDialogueMerge:
    """P1-1: speaker attribution + dialogue merge."""

    def test_speaker_merged_with_dialogue(self):
        """他说：「你好啊。」→ 1 个 dialogue segment (说话人+对话合并)"""
        seg = Segmenter()
        text = '他说：「你好啊。」她回答：「我很好。」'
        block, _ = _make_block(text)
        segments = seg.segment_block("test", block, text)
        dialogue_segs = [s for s in segments if s.segment_type == "dialogue"]
        assert len(dialogue_segs) == 2
        # 说话人应包含在对话 segment 中
        assert '他说' in dialogue_segs[0].text_slice
        assert '你好啊' in dialogue_segs[0].text_slice
        assert '她回答' in dialogue_segs[1].text_slice

    def test_no_attribution_dialogue_still_works(self):
        """「你好啊。」再见。→ dialogue + sentence，单 dialogue 也能正确识别"""
        seg = Segmenter()
        text = '「你好啊。」再见。'
        block, _ = _make_block(text)
        segments = seg.segment_block("test", block, text)
        types = [s.segment_type for s in segments]
        assert "dialogue" in types
        assert "sentence" in types

    def test_colon_not_attribution(self):
        """注意：这是重点。→ 不合并（'注意：' 不匹配说话人模式）"""
        seg = Segmenter()
        text = '注意：这是重点。'
        block, _ = _make_block(text)
        segments = seg.segment_block("test", block, text)
        # 不应有 dialogue 类型（只有 sentence）
        assert all(s.segment_type != "dialogue" for s in segments)

    def test_multiple_speaker_dialogue_pairs(self):
        """他说：「你好。」她答：「我很好。」→ 2 个合并后的 dialogue"""
        seg = Segmenter()
        text = '他说：「你好。」她答：「我很好。」'
        block, _ = _make_block(text)
        segments = seg.segment_block("test", block, text)
        dialogue_segs = [s for s in segments if s.segment_type == "dialogue"]
        assert len(dialogue_segs) == 2

    def test_merged_offset_integrity(self):
        """合并后 text_slice 与 offset 一致"""
        seg = Segmenter()
        text = '那僧道：「大师，弟子蠢物，不能礼佛。」'
        block, _ = _make_block(text)
        segments = seg.segment_block("test", block, text)
        for s in segments:
            assert text[s.start_offset:s.end_offset] == s.text_slice, (
                f"Offset mismatch: expected '{text[s.start_offset:s.end_offset]}', "
                f"got '{s.text_slice}'"
            )

    def test_merged_hash_correct(self):
        """合并后 hash 正确"""
        seg = Segmenter()
        text = '宝玉笑道：「林妹妹，你放心。」'
        block, _ = _make_block(text)
        segments = seg.segment_block("test", block, text)
        for s in segments:
            expected = _sha256(s.text_slice)
            assert s.hash == expected

    def test_speaker_with_modifier(self):
        """笑着说道：→ 合并（'着' 修饰语匹配）"""
        seg = Segmenter()
        text = '她笑着说道：「我很好。」他嚷：「走开！」'
        block, _ = _make_block(text)
        segments = seg.segment_block("test", block, text)
        dialogue_segs = [s for s in segments if s.segment_type == "dialogue"]
        assert len(dialogue_segs) == 2
        assert '笑着说道' in dialogue_segs[0].text_slice

    def test_speaker_pattern_variants(self):
        """各种说话人模式：道/说/问/喊 — 需要两个 dialogue span 触发合并路径"""
        seg = Segmenter()
        variants = [
            ('子兴道：「贾府如今不如从前。」冷子兴笑道：「确实如此。」', '子兴道'),
            ('雨村说：「此事我已知。」贾政说：「你且说来。」', '雨村说'),
            ('黛玉问：「你怎么来了？」宝玉问：「你为何在此？」', '黛玉问'),
        ]
        for text, speaker in variants:
            block, _ = _make_block(text)
            segments = seg.segment_block("test", block, text)
            dialogue_segs = [s for s in segments if s.segment_type == "dialogue"]
            assert len(dialogue_segs) >= 1, f"No dialogue for {text}"
            assert speaker in dialogue_segs[0].text_slice, (
                f"Speaker '{speaker}' not in dialogue text: {dialogue_segs[0].text_slice}"
            )


class TestCase001Integration:
    def test_case_001_segmentation(self, case_001_path, case_001_text):
        cm = CorpusManager()
        doc, text = cm.ingest(case_001_path)
        blocks = cm.create_blocks(doc, text)
        seg = Segmenter()
        all_segments = []
        for block in blocks:
            block_text = cm.get_block_text(doc, block, text)
            segments = seg.segment_block(doc.id, block, block_text)
            all_segments.extend(segments)

        assert len(all_segments) >= 10  # case_001 has substantial content
        # All segments should have valid hashes
        for s in all_segments:
            assert s.hash.startswith("sha256:")
