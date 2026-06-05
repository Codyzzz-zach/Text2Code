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
    # v3.3 mode: emit symbol refs in EvidenceRef (opt-in via flag)
    gen = CodeGenerator(version="v3.3-flash", emit_symbol_refs=True)

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
    text_files = gen.generate_text_code_v33(doc, [], [seg])
    text_code = text_files["text.py"]

    # --- Parse text.py to get segment symbols ---
    text_parser = T2CParser()
    text_objects = text_parser.parse_string(text_code)
    # Build external symbol index: symbol_name → {type, id}
    ext_index: dict[str, dict[str, str]] = {}
    for obj in text_objects:
        sym = obj.get("symbol")
        if sym and obj.get("type") == "Segment":
            ext_index[sym] = {"type": "Segment", "id": obj["data"]["id"]}
    # Verify segment symbol was captured
    assert len(ext_index) >= 1, "No segment symbols found in text.py"
    seg_symbol = list(ext_index.keys())[0]
    seg_id = ext_index[seg_symbol]["id"]

    # --- Build semantic code (entities + claims) ---
    eref = EvidenceRef(
        segment_id=seg_id, segment_symbol=seg_symbol,
        start=0, end=3, quote_hash=_sha256(seg_text[:3]),
    )
    ent_zhen = Entity(id="ent1", name="甄士隐", kind="person", evidence_refs=[eref])
    ent_gusu = Entity(id="ent2", name="姑苏", kind="location")
    claim = Claim(
        id="clm1", subject="ent1", predicate="lives_in", object="ent2",
        modality="asserted", polarity="positive",
        evidence_refs=[eref],
    )
    semantic_files = gen.generate_semantic_code_v33(
        [ent_zhen, ent_gusu, claim],
        external_symbols={seg_id: seg_symbol},
        external_file=".text",
    )

    # --- Parse entities.py with external symbol index ---
    entities_code = semantic_files.get("entities.py", "")
    assert entities_code, "entities.py not generated"
    entities_parser = T2CParser(external_symbols=ext_index)
    entities_objects = entities_parser.parse_string(entities_code)
    assert len(entities_objects) >= 2, f"Expected >=2 entities, got {len(entities_objects)}"

    # Build entity symbol index for claims.py
    for obj in entities_objects:
        sym = obj.get("symbol")
        if sym and obj.get("type") == "Entity":
            ext_index[sym] = {"type": "Entity", "id": obj["data"]["id"]}

    # --- Parse claims.py with both segment and entity external symbols ---
    claims_code = semantic_files.get("claims.py", "")
    assert claims_code, "claims.py not generated"
    claims_parser = T2CParser(external_symbols=ext_index)
    claims_objects = claims_parser.parse_string(claims_code)
    assert len(claims_objects) >= 1, f"Expected >=1 claim, got {len(claims_objects)}"

    # --- Verify symbol refs in parsed objects ---
    # Claims should have __symbol_refs__ for subject and object
    claim_obj = claims_objects[0]
    assert claim_obj["type"] == "Claim"
    refs = claim_obj.get("__symbol_refs__", {})
    assert "subject" in refs, f"No subject symbol ref in claim: {refs}"
    assert "object" in refs, f"No object symbol ref in claim: {refs}"

    # EvidenceRef should reference segment symbol
    entity_obj = entities_objects[0]
    entity_refs = entity_obj.get("__symbol_refs__", {})
    seg_ref_paths = [p for p in entity_refs if "segment" in p]
    assert seg_ref_paths, f"No segment symbol ref in entity: {entity_refs}"

    # --- Validate everything together ---
    all_objects = text_objects + entities_objects + claims_objects
    v = Validator()
    result = v.validate_objects(all_objects)
    assert result.valid, f"Validation errors: {result.errors}"


def test_codegen_v33_output_contains_symbol_refs():
    """Generated v3.3 code must contain real Python symbol references."""
    # v3.3 mode: emit symbol refs in EvidenceRef (opt-in via flag)
    gen = CodeGenerator(version="v3.3-flash", emit_symbol_refs=True)
    seg = Segment(
        id="seg1", doc_id="doc1", block_index=0,
        segment_type="sentence", start_offset=0, end_offset=9,
        text_slice="甄士隐住在姑苏", hash=_sha256("甄士隐住在姑苏"),
    )

    doc = Document(
        id="doc1", source_path="t.txt", raw_text_hash=_sha256("x"),
        total_length=100, block_count=1, created_at="2026-01-01T00:00:00Z",
    )
    text_files = gen.generate_text_code_v33(doc, [], [seg])
    text_code = text_files["text.py"]

    # text.py must use assignment format
    assert " = Segment(" in text_code, "text.py missing segment assignment"

    # Parse text.py to get actual segment symbol
    text_parser = T2CParser()
    text_objs = text_parser.parse_string(text_code)
    seg_sym = None
    seg_id = None
    for o in text_objs:
        if o.get("type") == "Segment":
            seg_sym = o["symbol"]
            seg_id = o["data"]["id"]
            break
    assert seg_sym, "No segment symbol found"
    assert seg_id, "No segment ID found"

    eref = EvidenceRef(segment_id=seg_id, segment_symbol=seg_sym,
                       start=0, end=3, quote_hash=_sha256("甄士隐"))
    ent = Entity(id="ent1", name="甄士隐", kind="person", evidence_refs=[eref])

    sem_files = gen.generate_semantic_code_v33(
        [ent], external_symbols={seg_id: seg_sym}, external_file=".text",
    )
    entities_code = sem_files.get("entities.py", "")

    # entities.py must import segment symbol and use it in EvidenceRef
    assert f"from .text import {seg_sym}" in entities_code, f"Missing segment import for {seg_sym}"
    assert f"segment={seg_sym}" in entities_code, f"Missing segment symbol ref {seg_sym}"
    # id field must still be a string literal (not a symbol ref)
    assert "id=" in entities_code, "id field should be a string literal"


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
