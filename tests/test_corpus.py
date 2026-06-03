"""Tests for t2c/corpus.py — CorpusManager."""
from pathlib import Path

from t2c.corpus import CorpusManager, compute_hash


class TestComputeHash:
    def test_deterministic(self):
        h1 = compute_hash("hello")
        h2 = compute_hash("hello")
        assert h1 == h2

    def test_different_inputs(self):
        h1 = compute_hash("hello")
        h2 = compute_hash("world")
        assert h1 != h2

    def test_prefix(self):
        assert compute_hash("x").startswith("sha256:")


class TestCorpusManager:
    def test_ingest_file(self, case_001_path, case_001_text):
        cm = CorpusManager()
        doc, text = cm.ingest(case_001_path)
        assert doc.id == "case_001"
        assert doc.raw_text_hash == compute_hash(case_001_text)
        assert doc.total_length == len(case_001_text)
        assert text == case_001_text

    def test_ingest_text(self):
        cm = CorpusManager()
        doc, text = cm.ingest_text("Hello world", "test_doc")
        assert doc.id == "test_doc"
        assert doc.total_length == 11
        assert doc.raw_text_hash == compute_hash("Hello world")

    def test_verify_hash(self, case_001_path, case_001_text):
        cm = CorpusManager()
        doc, text = cm.ingest(case_001_path)
        assert cm.verify_hash(doc, text)
        assert not cm.verify_hash(doc, "tampered text")

    def test_create_blocks_paragraph(self):
        cm = CorpusManager()
        text = "First paragraph.\n\nSecond paragraph."
        doc, _ = cm.ingest_text(text, "test")
        blocks = cm.create_blocks(doc, text)
        assert len(blocks) >= 2
        assert blocks[0].block_type == "paragraph"
        assert "First paragraph" in blocks[0].text_slice

    def test_create_blocks_heading(self):
        cm = CorpusManager()
        text = "# Title\n\nSome content."
        doc, _ = cm.ingest_text(text, "test")
        blocks = cm.create_blocks(doc, text)
        heading_blocks = [b for b in blocks if b.block_type == "heading"]
        assert len(heading_blocks) >= 1

    def test_create_blocks_table(self):
        cm = CorpusManager()
        text = "| A | B |\n|---|---|\n| 1 | 2 |"
        doc, _ = cm.ingest_text(text, "test")
        blocks = cm.create_blocks(doc, text)
        table_blocks = [b for b in blocks if b.block_type == "table"]
        assert len(table_blocks) >= 1

    def test_create_blocks_list(self):
        cm = CorpusManager()
        text = "- item one\n- item two\n- item three"
        doc, _ = cm.ingest_text(text, "test")
        blocks = cm.create_blocks(doc, text)
        list_blocks = [b for b in blocks if b.block_type == "list"]
        assert len(list_blocks) >= 1

    def test_block_offsets_accurate(self):
        cm = CorpusManager()
        text = "Hello world"
        doc, _ = cm.ingest_text(text, "test")
        blocks = cm.create_blocks(doc, text)
        for block in blocks:
            assert text[block.start_offset:block.end_offset] == block.text_slice

    def test_block_hash_matches(self):
        cm = CorpusManager()
        text = "Hello world"
        doc, _ = cm.ingest_text(text, "test")
        blocks = cm.create_blocks(doc, text)
        for block in blocks:
            assert block.hash == compute_hash(block.text_slice)

    def test_block_indices_sequential(self):
        cm = CorpusManager()
        doc, text = CorpusManager().ingest_text("Para one.\n\nPara two.\n\nPara three.", "test")
        blocks = cm.create_blocks(doc, text)
        for i, block in enumerate(blocks):
            assert block.index == i

    def test_case_001_blocks(self, case_001_path, case_001_text):
        cm = CorpusManager()
        doc, text = cm.ingest(case_001_path)
        blocks = cm.create_blocks(doc, text)
        assert len(blocks) >= 5  # multiple paragraphs, heading, table, list, legal
        # Verify all text_slice match actual text
        for block in blocks:
            assert text[block.start_offset:block.end_offset] == block.text_slice

    def test_get_block_text(self):
        cm = CorpusManager()
        text = "Hello world"
        doc, _ = cm.ingest_text(text, "test")
        blocks = cm.create_blocks(doc, text)
        for block in blocks:
            assert cm.get_block_text(doc, block, text) == block.text_slice