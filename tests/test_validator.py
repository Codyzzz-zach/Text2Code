"""Tests for t2c/validator.py — validation pipeline."""
import pytest

from t2c.codegen import CodeGenerator
from t2c.corpus import CorpusManager
from t2c.parser import T2CParser
from t2c.segmenter import Segmenter
from t2c.validator import Validator


def _sha256(text: str) -> str:
    import hashlib
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


class TestSchemaValidation:
    def test_valid_document(self):
        validator = Validator()
        source = f'''\
from t2c.ontology import Document

Document(
    id="test",
    source_path="test.txt",
    raw_text_hash="{_sha256("test")}",
    total_length=100,
    block_count=1,
    created_at="2026-05-27T10:00:00Z",
)
'''
        result = validator.validate_string(source)
        assert result.valid

    def test_missing_required_field(self):
        validator = Validator()
        source = '''\
from t2c.ontology import Document

Document(
    id="test",
)
'''
        result = validator.validate_string(source)
        assert not result.valid
        assert any("Schema violation" in e for e in result.errors)

    def test_wrong_type_field(self):
        validator = Validator()
        source = f'''\
from t2c.ontology import Block

Block(
    id="test_blk_0000",
    doc_id="test",
    index="not_a_number",
    block_type="paragraph",
    start_offset=0,
    end_offset=10,
    text_slice="Hello",
    hash="{_sha256("Hello")}",
)
'''
        result = validator.validate_string(source)
        assert not result.valid

    def test_invalid_block_type(self):
        validator = Validator()
        source = f'''\
from t2c.ontology import Block

Block(
    id="test_blk_0000",
    doc_id="test",
    index=0,
    block_type="invalid_type",
    start_offset=0,
    end_offset=10,
    text_slice="Hello",
    hash="{_sha256("Hello")}",
)
'''
        result = validator.validate_string(source)
        assert not result.valid


class TestEvidenceValidation:
    def test_valid_evidence_with_raw_text(self):
        raw_text = "Hello world"
        validator = Validator(raw_text_store={"test": raw_text})
        source = '''\
from t2c.ontology import Block

Block(
    id="test_blk_0000",
    doc_id="test",
    index=0,
    block_type="paragraph",
    start_offset=0,
    end_offset=11,
    text_slice="Hello world",
    hash="sha256:64ec88ca00b268e5ba1a35678a1b5316d212f4f366b2477232534a8aeca37f3c",
)
'''
        result = validator.validate_string(source)
        assert result.valid

    def test_tampered_text_slice(self):
        raw_text = "Hello world"
        validator = Validator(raw_text_store={"test": raw_text})
        source = f'''\
from t2c.ontology import Block

Block(
    id="test_blk_0000",
    doc_id="test",
    index=0,
    block_type="paragraph",
    start_offset=0,
    end_offset=11,
    text_slice="Tampered text",
    hash="{_sha256("Tampered text")}",
)
'''
        result = validator.validate_string(source)
        assert not result.valid
        assert any("text_slice does not match" in e for e in result.errors)

    def test_tampered_hash(self):
        raw_text = "Hello world"
        validator = Validator(raw_text_store={"test": raw_text})
        source = '''\
from t2c.ontology import Block

Block(
    id="test_blk_0000",
    doc_id="test",
    index=0,
    block_type="paragraph",
    start_offset=0,
    end_offset=11,
    text_slice="Hello world",
    hash="sha256:wrong_hash",
)
'''
        result = validator.validate_string(source)
        assert not result.valid
        assert any("hash does not match" in e for e in result.errors)


class TestCase001Validation:
    def test_case_001_document_valid(self, case_001_path, case_001_text):
        cm = CorpusManager()
        doc, text = cm.ingest(case_001_path)
        blocks = cm.create_blocks(doc, text)

        gen = CodeGenerator()
        code = gen.generate_document_code(doc, blocks)

        validator = Validator(raw_text_store={doc.id: text})
        result = validator.validate_string(code)
        assert result.valid

    def test_case_001_segments_valid(self, case_001_path, case_001_text):
        cm = CorpusManager()
        doc, text = cm.ingest(case_001_path)
        blocks = cm.create_blocks(doc, text)
        seg = Segmenter()
        all_segments = []
        for block in blocks:
            block_text = cm.get_block_text(doc, block, text)
            all_segments.extend(seg.segment_block(doc.id, block, block_text))

        gen = CodeGenerator()
        code = gen.generate_segments_code(all_segments)

        validator = Validator(raw_text_store={doc.id: text})
        result = validator.validate_string(code)
        assert result.valid