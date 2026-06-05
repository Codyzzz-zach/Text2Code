"""Tests for t2c/residual_stage.py — second-pass routing interface."""
from __future__ import annotations

import pytest

from t2c.residual_stage import (
    ResidualStageResult,
    run_residual_stage,
    select_residual_candidates,
)


class _StubSegment:
    def __init__(self, sid: str, text: str = "x") -> None:
        self.id = sid
        self.text_slice = text


class TestSelectResidualCandidates:
    def test_uncovered_segments_selected(self):
        segs = [_StubSegment(f"s{i}") for i in range(5)]
        objs = [
            {"type": "Entity", "data": {"id": "e1", "source_segment_ids": ["s0"]}},
        ]
        picked = select_residual_candidates(
            all_segments=segs, objects=objs, errors=[],
        )
        # s0 is covered, s1..s4 are uncovered
        assert [s.id for s in picked] == ["s1", "s2", "s3", "s4"]

    def test_validator_error_segments_selected(self):
        segs = [_StubSegment(f"s{i}") for i in range(3)]
        objs = []
        errors = ["Reference error: s2 missing"]
        picked = select_residual_candidates(
            all_segments=segs, objects=objs, errors=errors,
        )
        assert "s2" in [s.id for s in picked]

    def test_residual_and_ignore_count_as_covered(self):
        segs = [_StubSegment("s0"), _StubSegment("s1"), _StubSegment("s2")]
        objs = [
            {"type": "Residual", "data": {"id": "r1", "segment_id": "s0"}},
            {"type": "IgnoreSegment", "data": {"id": "i1", "segment_id": "s1"}},
        ]
        picked = select_residual_candidates(
            all_segments=segs, objects=objs, errors=[],
        )
        # Only s2 uncovered
        assert [s.id for s in picked] == ["s2"]


class TestRunResidualStageDryRun:
    def test_dry_run_does_not_call_llm(self):
        segs = [_StubSegment(f"s{i}") for i in range(3)]
        objs = [
            {"type": "Entity", "data": {"id": "e1", "source_segment_ids": ["s0"]}},
        ]
        result = run_residual_stage(
            doc_id="d", chapter_num=1, chapter_title="t",
            all_segments=segs, objects=objs, errors=[],
            enabled=False,
        )
        assert isinstance(result, ResidualStageResult)
        assert result.enabled is False
        assert result.llm_calls == 0
        assert result.cache_hits == 0
        # Uncovered: s1, s2
        assert set(result.candidate_segments) == {"s1", "s2"}
        assert result.residual_objects == []

    def test_dry_run_with_all_covered(self):
        segs = [_StubSegment("s0")]
        objs = [
            {"type": "Entity", "data": {"id": "e1", "source_segment_ids": ["s0"]}},
        ]
        result = run_residual_stage(
            doc_id="d", chapter_num=1, chapter_title="t",
            all_segments=segs, objects=objs, errors=[],
            enabled=False,
        )
        assert result.candidate_segments == []

    def test_enabled_with_no_extractor_warns_and_returns(self):
        segs = [_StubSegment("s0"), _StubSegment("s1")]
        objs = []
        result = run_residual_stage(
            doc_id="d", chapter_num=1, chapter_title="t",
            all_segments=segs, objects=objs, errors=[],
            extractor=None, enabled=True,
        )
        # No LLM call, but candidates still surfaced
        assert result.enabled is True
        assert result.llm_calls == 0
        assert len(result.candidate_segments) == 2
