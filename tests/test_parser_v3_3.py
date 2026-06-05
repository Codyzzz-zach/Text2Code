"""Tests for t2c/parser.py — v3.3 assignment + symbol ref parsing."""
import pytest

from t2c.parser import T2CParseError, T2CParser


def _sha256(text: str) -> str:
    import hashlib
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.fixture
def parser():
    return T2CParser()


class TestAssignmentParsing:
    """v3.3: symbol = Constructor(...) assignments."""

    def test_parse_segment_assignment(self, parser):
        source = f'''\
from t2c.ontology import Segment

seg_0001 = Segment(
    id="seg1",
    doc_id="doc1",
    block_index=0,
    segment_type="sentence",
    start_offset=0,
    end_offset=5,
    text_slice="Hello",
    hash="{_sha256("Hello")}",
)
'''
        objects = parser.parse_string(source)
        assert len(objects) == 1
        assert objects[0]["type"] == "Segment"
        assert objects[0]["symbol"] == "seg_0001"
        assert objects[0]["data"]["id"] == "seg1"

    def test_parse_entity_assignment(self, parser):
        source = '''\
from t2c.ontology import Entity

ent_test = Entity(
    id="ent1",
    name="Test",
    kind="person",
)
'''
        objects = parser.parse_string(source)
        assert len(objects) == 1
        assert objects[0]["type"] == "Entity"
        assert objects[0]["symbol"] == "ent_test"

    def test_parse_multiple_assignments(self, parser):
        source = f'''\
from t2c.ontology import Segment

seg_0001 = Segment(
    id="seg1",
    doc_id="doc1",
    block_index=0,
    segment_type="sentence",
    start_offset=0,
    end_offset=5,
    text_slice="Hello",
    hash="{_sha256("Hello")}",
)
seg_0002 = Segment(
    id="seg2",
    doc_id="doc1",
    block_index=0,
    segment_type="sentence",
    start_offset=5,
    end_offset=10,
    text_slice="World",
    hash="{_sha256("World")}",
)
'''
        objects = parser.parse_string(source)
        assert len(objects) == 2
        assert objects[0]["symbol"] == "seg_0001"
        assert objects[1]["symbol"] == "seg_0002"


class TestSymbolReferences:
    """v3.3: symbol refs inside constructor calls."""

    def test_parse_evidence_ref_with_symbol_ref(self, parser):
        source = f'''\
from t2c.ontology import Segment, EvidenceRef

seg_0001 = Segment(
    id="seg1",
    doc_id="doc1",
    block_index=0,
    segment_type="sentence",
    start_offset=0,
    end_offset=5,
    text_slice="Hello",
    hash="{_sha256("Hello")}",
)
seg_0002 = Segment(
    id="seg2",
    doc_id="doc1",
    block_index=0,
    segment_type="sentence",
    start_offset=5,
    end_offset=10,
    text_slice="World",
    hash="{_sha256("World")}",
    evidence=EvidenceRef(
        segment=seg_0001,
        start=0,
        end=3,
        quote_hash="{_sha256("Hel")}",
    ),
)
'''
        objects = parser.parse_string(source)
        assert len(objects) == 2
        # seg_0002 has evidence with symbol ref to seg_0001
        data = objects[1]["data"]
        assert "evidence" in data
        evidence = data["evidence"]
        assert evidence["type"] == "EvidenceRef"
        # Symbol ref resolved to the segment's ID
        assert evidence["data"]["segment"] == "seg1"
        assert "__symbol_refs__" in objects[1]
        assert objects[1]["__symbol_refs__"]["evidence.segment"] == "seg_0001"

    def test_parse_entity_with_evidence_ref_symbol(self, parser):
        source = f'''\
from t2c.ontology import Segment, Entity, EvidenceRef

seg_0009 = Segment(
    id="seg9",
    doc_id="doc1",
    block_index=0,
    segment_type="sentence",
    start_offset=0,
    end_offset=5,
    text_slice="hello",
    hash="{_sha256("hello")}",
)
ent_test = Entity(
    id="ent1",
    name="Test",
    kind="person",
    evidence_refs=[
        EvidenceRef(
            segment=seg_0009,
            start=0,
            end=3,
            quote_hash="{_sha256("hel")}",
        )
    ],
)
'''
        objects = parser.parse_string(source)
        assert len(objects) == 2
        ent = objects[1]
        assert ent["symbol"] == "ent_test"
        assert "__symbol_refs__" in ent
        assert "evidence_refs[0].segment" in ent["__symbol_refs__"]
        assert ent["__symbol_refs__"]["evidence_refs[0].segment"] == "seg_0009"

    def test_parse_claim_subject_symbol_ref(self, parser):
        source = f'''\
from t2c.ontology import Segment, Entity, Claim, EvidenceRef

seg_0009 = Segment(
    id="seg9",
    doc_id="doc1",
    block_index=0,
    segment_type="sentence",
    start_offset=0,
    end_offset=10,
    text_slice="hello world",
    hash="{_sha256("hello world")}",
)
ent_zhen = Entity(
    id="ent1",
    name="甄士隐",
    kind="person",
)
claim_1 = Claim(
    id="clm1",
    subject=ent_zhen,
    predicate="lives_in",
    object="姑苏",
    modality="asserted",
    polarity="positive",
    evidence_refs=[
        EvidenceRef(
            segment=seg_0009,
            start=0,
            end=3,
            quote_hash="{_sha256("hel")}",
        )
    ],
)
'''
        objects = parser.parse_string(source)
        assert len(objects) == 3
        claim = objects[2]
        assert "__symbol_refs__" in claim
        assert claim["__symbol_refs__"]["subject"] == "ent_zhen"
        # Symbol ref resolved to entity ID
        assert claim["data"]["subject"] == "ent1"

    def test_parse_event_participant_symbol_ref(self, parser):
        source = f'''\
from t2c.ontology import Segment, Entity, Event, EvidenceRef

seg_0009 = Segment(
    id="seg9",
    doc_id="doc1",
    block_index=0,
    segment_type="sentence",
    start_offset=0,
    end_offset=10,
    text_slice="hello world",
    hash="{_sha256("hello world")}",
)
ent_a = Entity(
    id="ent_a",
    name="Alice",
    kind="person",
)
evt_1 = Event(
    id="evt1",
    name="Meeting",
    kind="occurrence",
    participants=[ent_a],
    evidence_refs=[
        EvidenceRef(
            segment=seg_0009,
            start=0,
            end=3,
            quote_hash="{_sha256("hel")}",
        )
    ],
)
'''
        objects = parser.parse_string(source)
        assert len(objects) == 3
        evt = objects[2]
        assert "__symbol_refs__" in evt
        assert evt["__symbol_refs__"]["participants[0]"] == "ent_a"
        # Symbol ref resolved to entity ID
        assert evt["data"]["participants"][0] == "ent_a"


class TestDuplicateSymbolRejection:
    """v3.3: symbol names must be unique."""

    def test_reject_duplicate_symbol(self, parser):
        source = f'''\
from t2c.ontology import Segment

seg_0001 = Segment(
    id="seg1", doc_id="doc1", block_index=0,
    segment_type="sentence", start_offset=0, end_offset=5,
    text_slice="Hello", hash="{_sha256("Hello")}",
)
seg_0001 = Segment(
    id="seg2", doc_id="doc1", block_index=0,
    segment_type="sentence", start_offset=5, end_offset=10,
    text_slice="World", hash="{_sha256("World")}",
)
'''
        with pytest.raises(T2CParseError, match="already defined"):
            parser.parse_string(source)


class TestUndefinedSymbolRef:
    """v3.3: symbol refs must reference previously defined symbols."""

    def test_reject_undefined_symbol_ref(self, parser):
        source = f'''\
from t2c.ontology import Segment, EvidenceRef

seg_0001 = Segment(
    id="seg1", doc_id="doc1", block_index=0,
    segment_type="sentence", start_offset=0, end_offset=5,
    text_slice="Hello", hash="{_sha256("Hello")}",
    evidence=EvidenceRef(
        segment=undefined_seg,
        start=0,
        end=3,
        quote_hash="{_sha256("Hel")}",
    ),
)
'''
        with pytest.raises(T2CParseError, match="Undefined symbol reference"):
            parser.parse_string(source)

    def test_reject_forward_reference(self, parser):
        """Symbol ref must appear AFTER the symbol definition."""
        source = f'''\
from t2c.ontology import Segment, EvidenceRef

seg_0002 = Segment(
    id="seg2", doc_id="doc1", block_index=0,
    segment_type="sentence", start_offset=5, end_offset=10,
    text_slice="World", hash="{_sha256("World")}",
    evidence=EvidenceRef(
        segment=seg_0001,
        start=0,
        end=3,
        quote_hash="{_sha256("Hel")}",
    ),
)
seg_0001 = Segment(
    id="seg1", doc_id="doc1", block_index=0,
    segment_type="sentence", start_offset=0, end_offset=5,
    text_slice="Hello", hash="{_sha256("Hello")}",
)
'''
        with pytest.raises(T2CParseError, match="Undefined symbol reference"):
            parser.parse_string(source)


class TestBannedConstructsV33:
    """v3.3: banned constructs still rejected."""

    def test_reject_function_definition(self, parser):
        source = '''\
from t2c.ontology import Document
def foo():
    pass
'''
        with pytest.raises(T2CParseError, match="Disallowed statement"):
            parser.parse_string(source)

    def test_reject_if_statement(self, parser):
        source = '''\
from t2c.ontology import Document
if True:
    pass
'''
        with pytest.raises(T2CParseError, match="Disallowed statement"):
            parser.parse_string(source)

    def test_reject_arbitrary_function_call(self, parser):
        source = '''\
from t2c.ontology import Document
print("hello")
'''
        with pytest.raises(T2CParseError, match="Unknown constructor"):
            parser.parse_string(source)

    def test_reject_non_name_assignment_target(self, parser):
        source = f'''\
from t2c.ontology import Segment
x.attr = Segment(
    id="seg1", doc_id="doc1", block_index=0,
    segment_type="sentence", start_offset=0, end_offset=5,
    text_slice="Hello", hash="{_sha256("Hello")}",
)
'''
        with pytest.raises(T2CParseError, match="must be a simple name"):
            parser.parse_string(source)

    def test_reject_reassignment_to_non_constructor(self, parser):
        source = f'''\
from t2c.ontology import Segment

seg_0001 = Segment(
    id="seg1", doc_id="doc1", block_index=0,
    segment_type="sentence", start_offset=0, end_offset=5,
    text_slice="Hello", hash="{_sha256("Hello")}",
)
x = 1
'''
        with pytest.raises(T2CParseError, match="Assignment value must be a constructor call"):
            parser.parse_string(source)


class TestBackwardCompatV33:
    """v3.3: old format still works."""

    def test_old_top_level_call_still_works(self, parser):
        source = f'''\
from t2c.ontology import Segment

Segment(
    id="seg1",
    doc_id="doc1",
    block_index=0,
    segment_type="sentence",
    start_offset=0,
    end_offset=5,
    text_slice="Hello",
    hash="{_sha256("Hello")}",
)
'''
        objects = parser.parse_string(source)
        assert len(objects) == 1
        assert objects[0]["type"] == "Segment"
        assert objects[0].get("symbol") is None

    def test_old_entity_call_still_works(self, parser):
        source = f'''\
from t2c.ontology import Entity, EvidenceRef

Entity(
    id="ent1",
    name="Alice",
    kind="person",
    evidence_refs=[
        EvidenceRef(
            segment_id="seg1",
            start=0,
            end=5,
            quote_hash="{_sha256("Hello")}",
        )
    ],
)
'''
        objects = parser.parse_string(source)
        assert len(objects) == 1
        assert objects[0]["type"] == "Entity"
        assert objects[0].get("symbol") is None
        # Old format: segment_id as string, no symbol ref
        eref = objects[0]["data"]["evidence_refs"][0]
        assert eref["data"]["segment_id"] == "seg1"

    def test_mixed_old_and_new_format(self, parser):
        """Mix of old top-level calls and new assignments."""
        source = f'''\
from t2c.ontology import Segment, Entity

seg_0001 = Segment(
    id="seg1",
    doc_id="doc1",
    block_index=0,
    segment_type="sentence",
    start_offset=0,
    end_offset=5,
    text_slice="Hello",
    hash="{_sha256("Hello")}",
)
Entity(
    id="ent1",
    name="Alice",
    kind="person",
)
'''
        objects = parser.parse_string(source)
        assert len(objects) == 2
        assert objects[0]["symbol"] == "seg_0001"
        assert objects[1].get("symbol") is None
        assert objects[1]["type"] == "Entity"


class TestRelativeImportV33:
    """v3.3: relative imports allowed for cross-file symbol refs."""

    def test_relative_import_allowed(self, parser):
        source = f'''\
from t2c.ontology import Entity, EvidenceRef
from .text import seg_0001, seg_0002

ent_test = Entity(
    id="ent1",
    name="Test",
    kind="person",
)
'''
        objects = parser.parse_string(source)
        assert len(objects) == 1
        assert objects[0]["symbol"] == "ent_test"
