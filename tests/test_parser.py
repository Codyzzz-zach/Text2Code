"""Tests for t2c/parser.py — AST parser with strict grammar enforcement."""
import pytest

from t2c.parser import T2CParseError, T2CParser


@pytest.fixture
def parser():
    return T2CParser()


class TestValidParsing:
    def test_parse_simple_document(self, parser):
        source = '''\
from t2c.ontology import Document

Document(
    id="test",
    source_path="test.txt",
    raw_text_hash="sha256:abc",
    total_length=100,
    block_count=1,
    created_at="2026-05-27T10:00:00Z",
)
'''
        objects = parser.parse_string(source)
        assert len(objects) == 1
        assert objects[0]["type"] == "Document"
        assert objects[0]["data"]["id"] == "test"

    def test_parse_multiple_objects(self, parser):
        source = '''\
from t2c.ontology import Document, Block

Document(
    id="test",
    source_path="test.txt",
    raw_text_hash="sha256:abc",
    total_length=100,
    block_count=1,
    created_at="2026-05-27T10:00:00Z",
)
Block(
    doc_id="test",
    index=0,
    block_type="paragraph",
    start_offset=0,
    end_offset=100,
    text_slice="Hello",
    hash="sha256:def",
)
'''
        objects = parser.parse_string(source)
        assert len(objects) == 2
        assert objects[0]["type"] == "Document"
        assert objects[1]["type"] == "Block"

    def test_parse_nested_evidence_ref(self, parser):
        source = '''\
from t2c.ontology import Segment, EvidenceRef

Segment(
    id="test_seg_0001",
    doc_id="test",
    block_index=0,
    segment_type="sentence",
    start_offset=0,
    end_offset=5,
    text_slice="Hello",
    hash="sha256:abc",
    evidence=EvidenceRef(
        segment_id="test_seg_0001",
        start=0,
        end=5,
        quote_hash="sha256:abc",
    ),
)
'''
        objects = parser.parse_string(source)
        assert len(objects) == 1
        assert objects[0]["type"] == "Segment"
        evidence = objects[0]["data"]["evidence"]
        assert isinstance(evidence, dict)
        assert evidence["type"] == "EvidenceRef"
        assert evidence["data"]["segment_id"] == "test_seg_0001"

    def test_parse_list_values(self, parser):
        source = '''\
from t2c.ontology import Entity, EvidenceRef

Entity(
    id="e1",
    name="Alice",
    kind="person",
    aliases=["Al", "Alicia"],
    evidence_refs=[EvidenceRef(
        segment_id="s1",
        start=0,
        end=5,
        quote_hash="sha256:abc",
    )],
)
'''
        objects = parser.parse_string(source)
        assert len(objects) == 1
        data = objects[0]["data"]
        assert data["aliases"] == ["Al", "Alicia"]
        assert isinstance(data["evidence_refs"], list)
        assert data["evidence_refs"][0]["type"] == "EvidenceRef"

    def test_parse_dict_value(self, parser):
        source = '''\
from t2c.ontology import CoverageReport

CoverageReport(
    doc_id="test",
    total_segments=10,
    status_counts={"covered": 5, "partial": 2},
    requires_raw_fallback=[],
    generated_at="2026-05-27T10:00:00Z",
)
'''
        objects = parser.parse_string(source)
        assert objects[0]["data"]["status_counts"] == {"covered": 5, "partial": 2}

    def test_parse_bool_none(self, parser):
        source = '''\
from t2c.ontology import Event

Event(
    id="evt_1",
    name="Meeting",
    kind="occurrence",
    participants=[],
    time=None,
)
'''
        objects = parser.parse_string(source)
        assert objects[0]["data"]["time"] is None

    def test_parse_negative_number(self, parser):
        source = '''\
from t2c.ontology import Block

Block(
    doc_id="test",
    index=-1,
    block_type="raw",
    start_offset=0,
    end_offset=10,
    text_slice="test",
    hash="sha256:abc",
)
'''
        objects = parser.parse_string(source)
        assert objects[0]["data"]["index"] == -1


class TestBannedConstructs:
    def test_variable_assignment(self, parser):
        source = '''\
from t2c.ontology import Document
x = 1
'''
        with pytest.raises(T2CParseError, match="Disallowed statement"):
            parser.parse_string(source)

    def test_function_definition(self, parser):
        source = '''\
from t2c.ontology import Document
def foo():
    pass
'''
        with pytest.raises(T2CParseError, match="Disallowed statement"):
            parser.parse_string(source)

    def test_if_statement(self, parser):
        source = '''\
from t2c.ontology import Document
if True:
    pass
'''
        with pytest.raises(T2CParseError, match="Disallowed statement"):
            parser.parse_string(source)

    def test_for_loop(self, parser):
        source = '''\
from t2c.ontology import Document
for x in [1]:
    pass
'''
        with pytest.raises(T2CParseError, match="Disallowed statement"):
            parser.parse_string(source)

    def test_try_except(self, parser):
        source = '''\
from t2c.ontology import Document
try:
    pass
except:
    pass
'''
        with pytest.raises(T2CParseError, match="Disallowed statement"):
            parser.parse_string(source)

    def test_disallowed_import(self, parser):
        source = '''\
import os
'''
        with pytest.raises(T2CParseError, match="disallowed module"):
            parser.parse_string(source)

    def test_disallowed_from_import(self, parser):
        source = '''\
from os import path
'''
        with pytest.raises(T2CParseError, match="disallowed module"):
            parser.parse_string(source)

    def test_unknown_constructor(self, parser):
        source = '''\
from t2c.ontology import Document
BadConstructor(id="x")
'''
        with pytest.raises(T2CParseError, match="Unknown constructor"):
            parser.parse_string(source)

    def test_positional_args(self, parser):
        source = '''\
from t2c.ontology import Document
Document("test")
'''
        with pytest.raises(T2CParseError, match="Positional arguments"):
            parser.parse_string(source)

    def test_fstring(self, parser):
        source = '''\
from t2c.ontology import Document
Document(id=f"test_{1}")
'''
        with pytest.raises(T2CParseError, match="Disallowed value"):
            parser.parse_string(source)

    def test_comprehension(self, parser):
        source = '''\
from t2c.ontology import Entity
Entity(id="e1", name="test", kind="person", aliases=[x for x in ["a"]])
'''
        with pytest.raises(T2CParseError, match="Disallowed value"):
            parser.parse_string(source)

    def test_lambda(self, parser):
        source = '''\
from t2c.ontology import Document
Document(id=lambda: "x")
'''
        with pytest.raises(T2CParseError, match="Disallowed value"):
            parser.parse_string(source)

    def test_class_definition(self, parser):
        source = '''\
from t2c.ontology import Document
class Foo:
    pass
'''
        with pytest.raises(T2CParseError, match="Disallowed statement"):
            parser.parse_string(source)

    def test_with_statement(self, parser):
        source = '''\
from t2c.ontology import Document
with open("f") as fh:
    pass
'''
        with pytest.raises(T2CParseError, match="Disallowed statement"):
            parser.parse_string(source)


class TestParseFile:
    def test_parse_generated_document(self, parser, case_001_path, case_001_text):
        """End-to-end: generate .t2c.py then parse it back."""
        from t2c.codegen import CodeGenerator
        from t2c.corpus import CorpusManager

        cm = CorpusManager()
        doc, text = cm.ingest(case_001_path)
        blocks = cm.create_blocks(doc, text)

        gen = CodeGenerator()
        code = gen.generate_document_code(doc, blocks)

        objects = parser.parse_string(code)
        assert len(objects) >= 2  # Document + at least one Block
        assert objects[0]["type"] == "Document"
        assert objects[1]["type"] == "Block"

    def test_parse_generated_segments(self, parser, case_001_path, case_001_text):
        """End-to-end: generate segments .t2c.py then parse it back."""
        from t2c.codegen import CodeGenerator
        from t2c.corpus import CorpusManager
        from t2c.segmenter import Segmenter

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
        objects = parser.parse_string(code)
        assert len(objects) == len(all_segments)
        assert all(obj["type"] == "Segment" for obj in objects)