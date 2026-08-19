"""v3.3 multi-file codegraph-native pipeline roundtrip test.

Proves: codegen (multi-file) → parser (with external symbols) → validator
All three files (text.py, entities.py, claims.py) must parse and validate.
"""
import hashlib

from t2c.codegen import CodeGenerator
from t2c.ontology import (
    Claim,
    Document,
    Entity,
    EvidenceRef,
    Segment,
)
from t2c.parser import T2CParser
from t2c.validator import Validator


def _sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_multi_file_codegen_parser_validator_roundtrip():
    """Full pipeline: codegen → parser → validator across text/entities/claims."""
    gen = CodeGenerator()

    # --- Build text code ---
    doc = Document(
        id="doc1", source_path="t.txt",
        raw_text_hash=_sha256("hello"), total_length=100,
        block_count=1, created_at="2026-01-01T00:00:00Z",
    )
    seg_text = "甄士隐住在姑苏城中。"
    seg = Segment(
        id="seg1", doc_id="doc1", block_index=0,
        segment_type="sentence", start_offset=0,
        end_offset=len(seg_text), text_slice=seg_text,
        hash=_sha256(seg_text),
    )
    eref = EvidenceRef(
        segment_id=seg.id,
        start=0, end=3, quote_hash=_sha256(seg_text[:3]),
    )
    ent_zhen = Entity(id="ent1", name="甄士隐", kind="person", evidence_refs=[eref])
    ent_gusu = Entity(id="ent2", name="姑苏", kind="location")
    claim = Claim(
        id="clm1", subject="ent1", predicate="lives_in", object="ent2",
        modality="asserted", polarity="positive",
        evidence_refs=[eref],
    )

    # v6.0: one symbol table drives all files
    from t2c.symbols import compute_symbol_table
    table = compute_symbol_table(
        doc=doc, segments=[seg], entities=[ent_zhen, ent_gusu], claims=[claim],
    )
    text_files = gen.generate_text_code_v33(doc, [], [seg], symbols=table)
    entities_code = gen._generate_type_file_v33(
        ".entities", [ent_zhen, ent_gusu], ["Entity", "EvidenceRef"], table,
    )
    claims_code = gen._generate_type_file_v33(
        ".claims", [claim], ["Claim", "EvidenceRef"], table,
    )

    # --- Parse text.py to get segment symbols ---
    text_parser = T2CParser()
    text_objects = text_parser.parse_string(text_files["text.py"])
    ext_index: dict[str, dict[str, str]] = {}
    for obj in text_objects:
        sym = obj.get("symbol")
        if sym and obj.get("type") == "Segment":
            ext_index[sym] = {"type": "Segment", "id": obj["data"]["id"]}
    assert len(ext_index) >= 1, "No segment symbols found in text.py"

    # --- Parse entities.py with external symbol index ---
    entities_parser = T2CParser(external_symbols=ext_index)
    entities_objects = entities_parser.parse_string(entities_code)
    assert len(entities_objects) >= 2, f"Expected >=2 entities, got {len(entities_objects)}"

    # Build entity symbol index for claims.py
    for obj in entities_objects:
        sym = obj.get("symbol")
        if sym and obj.get("type") == "Entity":
            ext_index[sym] = {"type": "Entity", "id": obj["data"]["id"]}

    # --- Parse claims.py with both segment and entity external symbols ---
    claims_parser = T2CParser(external_symbols=ext_index)
    claims_objects = claims_parser.parse_string(claims_code)
    assert len(claims_objects) >= 1, f"Expected >=1 claim, got {len(claims_objects)}"

    # --- Verify symbol refs in parsed objects ---
    # v6.0: bare Names live in the *_symbol fields; FK fields stay strings
    claim_obj = claims_objects[0]
    assert claim_obj["type"] == "Claim"
    assert claim_obj["data"]["subject"] == "ent1"  # FK stays a string id
    refs = claim_obj.get("__symbol_refs__", {})
    assert "subject_symbol" in refs, f"No subject_symbol ref in claim: {refs}"
    assert "object_symbol" in refs, f"No object_symbol ref in claim: {refs}"

    # EvidenceRef should reference segment symbol
    entity_obj = entities_objects[0]
    entity_refs = entity_obj.get("__symbol_refs__", {})
    seg_ref_paths = [p for p in entity_refs if "segment_symbol" in p]
    assert seg_ref_paths, f"No segment symbol ref in entity: {entity_refs}"

    # --- Validate everything together ---
    all_objects = text_objects + entities_objects + claims_objects
    v = Validator()
    result = v.validate_objects(all_objects)
    assert result.valid, f"Validation errors: {result.errors}"


def test_codegen_v33_output_contains_symbol_refs():
    """Generated v6.0 code must contain real Python symbol references."""
    gen = CodeGenerator()
    seg = Segment(
        id="doc1_seg_0001", doc_id="doc1", block_index=0,
        segment_type="sentence", start_offset=0, end_offset=9,
        text_slice="甄士隐住在姑苏", hash=_sha256("甄士隐住在姑苏"),
    )

    doc = Document(
        id="doc1", source_path="t.txt", raw_text_hash=_sha256("x"),
        total_length=100, block_count=1, created_at="2026-01-01T00:00:00Z",
    )
    from t2c.symbols import compute_symbol_table
    text_files = gen.generate_text_code_v33(doc, [], [seg])

    # text.py must use assignment format
    assert "seg_0001 = Segment(" in text_files["text.py"]

    eref = EvidenceRef(segment_id="doc1_seg_0001",
                       start=0, end=3, quote_hash=_sha256("甄士隐"))
    ent = Entity(id="ent1", name="甄士隐", kind="person", evidence_refs=[eref])

    table = compute_symbol_table(doc=doc, segments=[seg], entities=[ent])
    entities_code = gen._generate_type_file_v33(
        ".entities", [ent], ["Entity", "EvidenceRef"], table,
    )

    # entities.py must import the segment symbol and use it as a bare Name
    assert "from .text import seg_0001" in entities_code
    assert "segment_symbol=seg_0001" in entities_code
    # FK field stays a string literal (data face)
    assert "segment_id='doc1_seg_0001'" in entities_code


def test_evidence_ref_keyword_maps_to_segment_id():
    """EvidenceRef(segment=SYM) must resolve to segment_id in canonical data."""
    code = '''\
from t2c.ontology import Segment, EvidenceRef

seg_0001 = Segment(
    id="seg1", doc_id="doc1", block_index=0,
    segment_type="sentence", start_offset=0, end_offset=5,
    text_slice="hello", hash="sha256:abc",
)
seg_0002 = Segment(
    id="seg2", doc_id="doc1", block_index=0,
    segment_type="sentence", start_offset=5, end_offset=10,
    text_slice="world", hash="sha256:def",
    evidence=EvidenceRef(
        segment=seg_0001,
        start=0,
        end=3,
        quote_hash="sha256:ghi",
    ),
)
'''
    parser = T2CParser()
    objects = parser.parse_string(code)
    # Find the segment with evidence
    seg2 = [o for o in objects if o.get("data", {}).get("id") == "seg2"][0]
    evidence = seg2["data"]["evidence"]
    # The EvidenceRef data should have the resolved segment_id
    eref_data = evidence.get("data", evidence)
    # Keyword 'segment' is in data with resolved ID; schema maps to segment_id
    assert "segment" in eref_data, f"Expected 'segment' key, got {list(eref_data.keys())}"
    # Resolved to segment ID
    assert eref_data["segment"] == "seg1"
