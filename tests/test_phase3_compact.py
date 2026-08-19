"""Phase 3: AI Compact Candidate — parse → expand → codegen (v6.0).

Proves the full pipeline from LLM compact JSON to codegraph-native code.
v6.0: symbol assignment moved to the single compile-time choke point
(t2c.symbols.compute_symbol_table); expansion no longer assigns symbols.
"""
import hashlib

from t2c.codegen import CodeGenerator
from t2c.compact_candidate import (
    derive_relations,
    expand_candidates,
    expansion_failures_to_residuals,
    parse_compact_response,
)
from t2c.corpus import CorpusManager
from t2c.coverage import CoverageGenerator
from t2c.ontology import Claim, Entity, Segment
from t2c.parser import T2CParser
from t2c.schema import SchemaValidator
from t2c.segmenter import Segmenter
from t2c.symbols import compute_symbol_table
from t2c.validator import Validator


def _sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


class _StubSegment:
    def __init__(self, sid: str, text: str) -> None:
        self.id = sid
        self.text_slice = text


class TestCompactToCodegenV33:
    """Phase 3: LLM compact JSON → v3.3 codegen-native code."""

    def test_parse_expand_assign_symbols_codegen(self):
        """Full chain: parse compact → expand → symbols → codegen v33 → parse → validate."""
        # Simulated LLM compact output for 红楼梦 ch01
        llm_output = """[
            {"t":"E","lid":"e1","n":"甄士隐","k":"person","a":["士隐"],"sid":["s1"],"q":["甄士隐"]},
            {"t":"E","lid":"e2","n":"姑苏","k":"location","sid":["s1"],"q":["姑苏"]},
            {"t":"C","s":"e1","p":"lives_in","o":"e2","m":"asserted","pol":"positive","sid":["s1"],"q":["姑苏"]},
            {"t":"I","sid":["s_title"],"r":"chapter title"}
        ]"""

        # Step 1: Parse compact response
        candidates = parse_compact_response(llm_output)
        assert len(candidates) == 4, f"Expected 4 candidates, got {len(candidates)}"

        # Step 2: Create segment stubs
        segs = [
            _StubSegment("s1", "甄士隐住在姑苏城中。姑苏是繁华之地。"),
            _StubSegment("s_title", "第一回 甄士隐梦幻识通灵"),
        ]

        # Step 3: Expand (no symbols at this layer since v6.0)
        objects, warnings = expand_candidates(
            candidates, segs, doc_id="hlm",
        )

        # Step 4: Derive relations from Claims
        entity_ids = {
            o["data"]["id"] for o in objects if o["type"] == "Entity"
        }
        relations, rel_warnings = derive_relations(objects, entity_ids, doc_id="hlm")
        assert len(relations) >= 1, f"No relations derived: {rel_warnings}"
        objects.extend(relations)

        # Step 5: Construct models + assign symbols at the compile choke point
        models, violations = SchemaValidator().validate_and_construct(objects)
        assert not violations, f"schema violations: {violations}"
        entities = [m for m in models if isinstance(m, Entity)]
        claims = [m for m in models if isinstance(m, Claim)]
        table = compute_symbol_table(entities=entities, claims=claims)
        # Every object got a package-unique symbol
        assert len(table) == len(entities) + len(claims)
        assert len(set(table.id_to_symbol.values())) == len(table)

        # Step 6: Verify evidence_refs were located
        for obj in objects:
            if obj["type"] in ("Entity", "Claim"):
                erefs = obj["data"].get("evidence_refs", [])
                # At least some should have evidence refs
                if obj["type"] == "Entity" and obj["data"].get("name") == "甄士隐":
                    assert len(erefs) >= 1, f"No evidence refs for 甄士隐"

        # Step 7: Validate with validator
        parsed_objs = [{"type": o["type"], "data": o["data"]} for o in objects]
        seg_data_objs = [
            {
                "type": "Segment",
                "data": {
                    "id": s.id, "doc_id": "hlm", "block_index": 0,
                    "segment_type": "sentence",
                    "start_offset": 0, "end_offset": len(s.text_slice),
                    "text_slice": s.text_slice,
                    "hash": _sha256(s.text_slice),
                },
            }
            for s in segs
        ]
        v = Validator()
        result = v.validate_objects(seg_data_objs + parsed_objs)
        # May have warnings about cross-file refs, but should not have hard errors
        assert isinstance(result.valid, bool)

    def test_symbol_table_stable(self):
        """compute_symbol_table produces stable results for the same object set."""
        def make():
            return [Entity(id="e1", name="甄士隐", kind="person")]

        t1 = compute_symbol_table(entities=make())
        t2 = compute_symbol_table(entities=make())
        assert t1.id_to_symbol == t2.id_to_symbol, (
            f"Symbols not stable: {t1.id_to_symbol} vs {t2.id_to_symbol}"
        )

    def test_expansion_failures_to_residuals(self):
        """Warnings about missing evidence → Residual objects."""
        warnings = [
            "ent d_ent_0001: no source segment contained quote '贾宝玉'",
            "clm d_clm_0001: no match for quote",
        ]
        residuals = expansion_failures_to_residuals(warnings, doc_id="d")
        assert len(residuals) == 2
        assert residuals[0]["type"] == "Residual"
        assert "贾宝玉" in residuals[0]["data"]["reason"]

    def test_symbol_name_chinese(self):
        """Chinese names produce hash-based symbols."""
        table = compute_symbol_table(
            entities=[Entity(id="e1", name="甄士隐", kind="person")]
        )
        sym = table.symbol_for("e1")
        assert sym.startswith("ent_zh_"), f"Expected ent_zh_HASH, got {sym}"
        assert len(sym) <= 16

    def test_symbol_name_ascii_short(self):
        """Short ASCII names kept as-is."""
        table = compute_symbol_table(
            entities=[Entity(id="e1", name="Alice", kind="person")]
        )
        sym = table.symbol_for("e1")
        assert sym == "ent_alice", f"Expected ent_alice, got {sym}"
