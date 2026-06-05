"""Tests for t2c/compact_candidate.py — short-key JSON parser and expander."""
from __future__ import annotations

import json

import pytest

from t2c.compact_candidate import (
    COMPACT_TYPE_CLAIM,
    COMPACT_TYPE_ENTITY,
    COMPACT_TYPE_EVENT,
    COMPACT_TYPE_IGNORE,
    CompactCandidate,
    build_evidence_refs,
    derive_relations,
    expand_candidates,
    locate_quote,
    parse_compact_response,
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class _StubSegment:
    def __init__(self, sid: str, text: str) -> None:
        self.id = sid
        self.text_slice = text


def _segs(*pairs: tuple[str, str]) -> list[_StubSegment]:
    return [_StubSegment(sid, text) for sid, text in pairs]


# ---------------------------------------------------------------------------
# parse_compact_response
# ---------------------------------------------------------------------------


class TestParseCompactResponse:
    def test_parse_clean_array(self):
        text = '[{"t":"E","lid":"e1","n":"x","k":"person","sid":["s1"]}]'
        cands = parse_compact_response(text)
        assert len(cands) == 1
        assert cands[0].type == COMPACT_TYPE_ENTITY
        assert cands[0].fields["name"] == "x"
        assert cands[0].fields["kind"] == "person"

    def test_parse_fenced(self):
        text = "```json\n[{\"t\":\"E\",\"n\":\"x\"}]\n```"
        cands = parse_compact_response(text)
        assert len(cands) == 1

    def test_parse_with_surrounding_text(self):
        text = 'Here is the JSON:\n[{"t":"E","n":"x","sid":["s1"]}]\nThanks.'
        cands = parse_compact_response(text)
        assert len(cands) == 1

    def test_parse_empty(self):
        assert parse_compact_response("") == []
        assert parse_compact_response("not json") == []

    def test_parse_ignores_unknown_types(self):
        text = '[{"t":"Z","n":"x"},{"t":"E","n":"y","sid":["s1"]}]'
        cands = parse_compact_response(text)
        # Unknown 'Z' is kept as a candidate with a parse warning, so the
        # downstream expander can decide what to do. The valid 'E' is also
        # kept; the parser does not silently drop things.
        assert len(cands) == 2
        z = next(c for c in cands if c.type == "Z")
        assert any("unknown" in w for w in z.parse_warnings)
        assert any(c.type == COMPACT_TYPE_ENTITY for c in cands)

    def test_parse_normalizes_modality(self):
        text = '[{"t":"C","s":"e1","p":"x","o":"e2","m":"BOGUS","pol":"x","sid":["s1"]}]'
        cands = parse_compact_response(text)
        assert cands[0].fields["modality"] == "asserted"
        assert cands[0].fields["polarity"] == "positive"
        # parse_warnings should mention both
        joined = " ".join(cands[0].parse_warnings)
        assert "BOGUS" in joined
        assert "polarity" in joined

    def test_parse_claim_object_can_be_null(self):
        text = '[{"t":"C","s":"e1","p":"says","o":null,"m":"asserted","pol":"positive","sid":["s1"]}]'
        cands = parse_compact_response(text)
        assert cands[0].fields["object"] is None

    def test_parse_recovers_partial_from_truncated(self):
        # Missing closing brackets → brace-balanced recovery should find at
        # least one complete candidate.
        text = '[{"t":"E","lid":"e1","n":"x","k":"person","sid":["s1"]}, {"t":"E","lid":"e2"'
        cands = parse_compact_response(text)
        # First object should be fully recovered
        assert any(c.fields.get("name") == "x" for c in cands)


# ---------------------------------------------------------------------------
# locate_quote + build_evidence_refs
# ---------------------------------------------------------------------------


class TestLocateQuote:
    def test_unique_match(self):
        s, e = locate_quote("甄士隐住在姑苏。", "甄士隐")
        assert (s, e) == (0, 3)

    def test_no_match(self):
        assert locate_quote("甄士隐住在姑苏。", "贾宝玉") is None

    def test_empty_quote(self):
        assert locate_quote("hello", "") is None

    def test_ambiguous_match_takes_first(self):
        s, e = locate_quote("甄士隐和甄士隐", "甄士隐")
        assert (s, e) == (0, 3)


class TestBuildEvidenceRefs:
    def test_no_quotes_no_refs(self):
        refs, warns = build_evidence_refs([], {"s1": _StubSegment("s1", "x")}, ["s1"])
        assert refs == []
        assert warns == []

    def test_unique_quote_creates_ref(self):
        seg = _StubSegment("s1", "甄士隐住在姑苏。")
        refs, warns = build_evidence_refs(
            ["甄士隐"], {"s1": seg}, ["s1"],
        )
        assert len(refs) == 1
        ref = refs[0]
        assert ref["segment_id"] == "s1"
        assert ref["start"] == 0
        assert ref["end"] == 3
        assert ref["quote_hash"].startswith("sha256:")
        assert warns == []

    def test_quote_not_in_segment_records_warning(self):
        seg = _StubSegment("s1", "甄士隐住在姑苏。")
        refs, warns = build_evidence_refs(
            ["贾宝玉"], {"s1": seg}, ["s1"],
        )
        assert refs == []
        assert any("贾宝玉" in w for w in warns)

    def test_dedup_identical_refs(self):
        seg = _StubSegment("s1", "甄士隐甄士隐")
        refs, _ = build_evidence_refs(
            ["甄士隐", "甄士隐"], {"s1": seg}, ["s1"],
        )
        # Two identical spans (first match); should dedup to one ref
        assert len(refs) == 1


# ---------------------------------------------------------------------------
# expand_candidates
# ---------------------------------------------------------------------------


class TestExpandCandidates:
    def test_expand_entity_assigns_canonical_id(self):
        cands = [
            CompactCandidate(
                type=COMPACT_TYPE_ENTITY,
                fields={"local_id": "e1", "name": "甄士隐", "kind": "person",
                        "aliases": ["士隐"], "source_segment_ids": ["s1"],
                        "quotes": ["甄士隐"]},
            ),
        ]
        segs = _segs(("s1", "甄士隐住在姑苏。"))
        objs, warns = expand_candidates(cands, segs, doc_id="d")
        assert len(objs) == 1
        e = objs[0]["data"]
        assert e["id"] == "d_ent_0001"
        assert e["name"] == "甄士隐"
        assert e["kind"] == "person"
        assert "士隐" in e["aliases"]
        assert e["source_segment_ids"] == ["s1"]
        assert len(e["evidence_refs"]) == 1

    def test_expand_claim_resolves_local_ids(self):
        cands = [
            CompactCandidate(type=COMPACT_TYPE_ENTITY,
                fields={"local_id": "e1", "name": "甄士隐", "kind": "person",
                        "source_segment_ids": ["s1"], "quotes": []}),
            CompactCandidate(type=COMPACT_TYPE_ENTITY,
                fields={"local_id": "e2", "name": "姑苏", "kind": "location",
                        "source_segment_ids": ["s1"], "quotes": []}),
            CompactCandidate(type=COMPACT_TYPE_CLAIM,
                fields={"subject": "e1", "predicate": "lives_in", "object": "e2",
                        "modality": "asserted", "polarity": "positive",
                        "source_segment_ids": ["s1"], "quotes": []}),
        ]
        segs = _segs(("s1", "甄士隐住在姑苏。"))
        objs, _ = expand_candidates(cands, segs, doc_id="d")
        claim = next(o for o in objs if o["type"] == "Claim")
        assert claim["data"]["subject"] == "d_ent_0001"
        assert claim["data"]["object"] == "d_ent_0002"

    def test_expand_event_participants_resolved(self):
        cands = [
            CompactCandidate(type=COMPACT_TYPE_ENTITY,
                fields={"local_id": "e1", "name": "甄士隐", "kind": "person",
                        "source_segment_ids": ["s1"], "quotes": []}),
            CompactCandidate(type=COMPACT_TYPE_EVENT,
                fields={"name": "做梦", "kind": "occurrence", "participants": ["e1"],
                        "source_segment_ids": ["s2"], "quotes": []}),
        ]
        segs = _segs(("s1", "甄士隐"), ("s2", "他做了一个梦。"))
        objs, _ = expand_candidates(cands, segs, doc_id="d")
        evt = next(o for o in objs if o["type"] == "Event")
        assert evt["data"]["participants"] == ["d_ent_0001"]

    def test_expand_ignore_segment(self):
        cands = [
            CompactCandidate(type=COMPACT_TYPE_IGNORE,
                fields={"source_segment_ids": ["s1"], "reason": "chapter title"}),
        ]
        segs = _segs(("s1", "第1回"))
        objs, _ = expand_candidates(cands, segs, doc_id="d")
        assert objs[0]["type"] == "IgnoreSegment"
        assert objs[0]["data"]["segment_id"] == "s1"
        assert objs[0]["data"]["reason"] == "chapter title"

    def test_expand_id_counters_increment(self):
        cands = [
            CompactCandidate(type=COMPACT_TYPE_ENTITY,
                fields={"local_id": "a", "name": "A", "kind": "person",
                        "source_segment_ids": ["s1"], "quotes": []}),
            CompactCandidate(type=COMPACT_TYPE_ENTITY,
                fields={"local_id": "b", "name": "B", "kind": "person",
                        "source_segment_ids": ["s1"], "quotes": []}),
            CompactCandidate(type=COMPACT_TYPE_ENTITY,
                fields={"local_id": "c", "name": "C", "kind": "person",
                        "source_segment_ids": ["s1"], "quotes": []}),
        ]
        segs = _segs(("s1", "A B C"))
        objs, _ = expand_candidates(cands, segs, doc_id="d")
        ids = [o["data"]["id"] for o in objs]
        assert ids == ["d_ent_0001", "d_ent_0002", "d_ent_0003"]


# ---------------------------------------------------------------------------
# derive_relations
# ---------------------------------------------------------------------------


class TestDeriveRelations:
    def _entity_obj(self, eid: str, name: str) -> dict:
        return {"type": "Entity", "data": {"id": eid, "name": name, "kind": "person"}}

    def _claim_obj(self, cid: str, subj: str, obj: str, modality: str = "asserted",
                   polarity: str = "positive",
                   evidence: list | None = None,
                   source_segs: list | None = None) -> dict:
        return {
            "type": "Claim",
            "data": {
                "id": cid, "subject": subj, "predicate": "lives_in",
                "object": obj, "modality": modality, "polarity": polarity,
                "evidence_refs": evidence or [],
                "source_segment_ids": source_segs or [],
            },
        }

    def test_asserted_positive_derives_relation(self):
        objs = [
            self._entity_obj("e1", "A"),
            self._entity_obj("e2", "B"),
            self._claim_obj("c1", "e1", "e2",
                            evidence=[{"segment_id": "s1", "start": 0,
                                       "end": 1, "quote_hash": "h"}]),
        ]
        rels, warns = derive_relations(objs, {"e1", "e2"}, doc_id="d")
        assert len(rels) == 1
        assert rels[0]["data"]["claim_id"] == "c1"
        assert rels[0]["data"]["subject"] == "e1"
        assert rels[0]["data"]["object"] == "e2"

    def test_reported_claim_no_relation(self):
        objs = [
            self._entity_obj("e1", "A"),
            self._entity_obj("e2", "B"),
            self._claim_obj("c1", "e1", "e2", modality="reported",
                            evidence=[{"segment_id": "s1", "start": 0,
                                       "end": 1, "quote_hash": "h"}]),
        ]
        rels, warns = derive_relations(objs, {"e1", "e2"}, doc_id="d")
        assert rels == []
        assert any("modality" in w for w in warns)

    def test_uncertain_claim_no_relation(self):
        objs = [
            self._entity_obj("e1", "A"),
            self._entity_obj("e2", "B"),
            self._claim_obj("c1", "e1", "e2", modality="uncertain",
                            evidence=[{"segment_id": "s1", "start": 0,
                                       "end": 1, "quote_hash": "h"}]),
        ]
        rels, warns = derive_relations(objs, {"e1", "e2"}, doc_id="d")
        assert rels == []

    def test_negative_claim_no_relation(self):
        objs = [
            self._entity_obj("e1", "A"),
            self._entity_obj("e2", "B"),
            self._claim_obj("c1", "e1", "e2", polarity="negative",
                            evidence=[{"segment_id": "s1", "start": 0,
                                       "end": 1, "quote_hash": "h"}]),
        ]
        rels, warns = derive_relations(objs, {"e1", "e2"}, doc_id="d")
        assert rels == []

    def test_claim_with_literal_object_no_relation(self):
        objs = [
            self._entity_obj("e1", "A"),
            self._claim_obj("c1", "e1", "姑苏",  # not in entity_ids
                            evidence=[{"segment_id": "s1", "start": 0,
                                       "end": 2, "quote_hash": "h"}]),
        ]
        rels, warns = derive_relations(objs, {"e1"}, doc_id="d")
        assert rels == []
        assert any("object" in w for w in warns)

    def test_claim_with_no_evidence_no_relation(self):
        objs = [
            self._entity_obj("e1", "A"),
            self._entity_obj("e2", "B"),
            self._claim_obj("c1", "e1", "e2",
                            evidence=[], source_segs=[]),
        ]
        rels, warns = derive_relations(objs, {"e1", "e2"}, doc_id="d")
        assert rels == []
        assert any("no evidence" in w for w in warns)

    def test_claim_with_source_segments_only_passes(self):
        objs = [
            self._entity_obj("e1", "A"),
            self._entity_obj("e2", "B"),
            self._claim_obj("c1", "e1", "e2",
                            evidence=[],
                            source_segs=["s1"]),
        ]
        rels, _ = derive_relations(objs, {"e1", "e2"}, doc_id="d")
        assert len(rels) == 1

    def test_claim_subject_not_entity_no_relation(self):
        objs = [
            self._entity_obj("e1", "A"),
            self._entity_obj("e2", "B"),
            self._claim_obj("c1", "missing_eid", "e2",
                            evidence=[{"segment_id": "s1", "start": 0,
                                       "end": 1, "quote_hash": "h"}]),
        ]
        rels, warns = derive_relations(objs, {"e1", "e2"}, doc_id="d")
        assert rels == []
        assert any("subject" in w for w in warns)

    def test_multiple_eligible_claims_create_multiple_relations(self):
        objs = [
            self._entity_obj("e1", "A"),
            self._entity_obj("e2", "B"),
            self._claim_obj("c1", "e1", "e2",
                            evidence=[{"segment_id": "s1", "start": 0,
                                       "end": 1, "quote_hash": "h"}]),
            self._claim_obj("c2", "e1", "e2",
                            evidence=[{"segment_id": "s2", "start": 0,
                                       "end": 1, "quote_hash": "h"}]),
        ]
        rels, _ = derive_relations(objs, {"e1", "e2"}, doc_id="d")
        assert len(rels) == 2
