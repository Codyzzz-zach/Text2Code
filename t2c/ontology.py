"""T2C Ontology — core Pydantic models for the Text2Code knowledge representation.

v6.0 (M1): objects carry a self-declared `symbol` field so generated code can
emit `sym = Entity(..., symbol='ent_zh_abc123')`. The `*_symbol` reference
fields accept either a symbol string (pipeline/parse direction) or the
referenced model object itself as a bare Name (generated-code direction);
a before-validator unwraps model objects to their `.symbol` string at import
time. This makes the generated package import-validated: a dangling reference
is an ImportError, not a silent string.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, field_validator


def _unwrap_symbol_value(v: Any) -> Any:
    """Import-time bridge for generated code's bare-Name symbol references.

    `subject_symbol=ent_zh_692c5f` passes the referenced model object; we store
    its `.symbol` string so the field stays a plain string after validation.
    Strings (pipeline/parse direction) and None pass through untouched. Lists
    are unwrapped element-wise (Event.participant_symbols).
    """
    if isinstance(v, BaseModel):
        return getattr(v, "symbol", None)
    if isinstance(v, list):
        return [_unwrap_symbol_value(item) for item in v]
    return v


class Document(BaseModel):
    id: str
    source_path: str
    raw_text_hash: str
    total_length: int
    block_count: int
    created_at: str


class Block(BaseModel):
    id: str
    doc_id: str
    index: int
    block_type: Literal["paragraph", "heading", "table", "code_block", "list", "quote", "raw"]
    start_offset: int
    end_offset: int
    text_slice: str
    hash: str


class Segment(BaseModel):
    id: str
    doc_id: str
    block_index: int
    segment_type: Literal["sentence", "clause", "dialogue", "table_row", "heading", "list_item", "raw"]
    start_offset: int
    end_offset: int
    text_slice: str
    hash: str
    # v6.0: self-declared codegen symbol (populated only in generated code)
    symbol: str | None = None


class EvidenceRef(BaseModel):
    """Evidence reference — nested inside semantic objects' evidence_refs lists."""
    segment_id: str | None = None
    # Accepts the referenced Segment as a bare Name in generated code.
    segment_symbol: str | Segment | None = None
    start: int
    end: int
    quote_hash: str

    _unwrap_segment_symbol = field_validator("segment_symbol", mode="before")(
        lambda cls, v: _unwrap_symbol_value(v)
    )


class Entity(BaseModel):
    id: str
    name: str
    kind: str
    aliases: list[str] = []
    evidence_refs: list[EvidenceRef] = []
    source_segment_ids: list[str] = []
    symbol: str | None = None


class Event(BaseModel):
    id: str
    name: str
    kind: str
    participants: list[str] = []
    time: str | None = None
    location: str | None = None
    evidence_refs: list[EvidenceRef] = []
    source_segment_ids: list[str] = []
    symbol: str | None = None
    # v3.3/v6.0: symbol reference field for codegraph-native code
    participant_symbols: list[str | Entity] = []

    _unwrap_participant_symbols = field_validator("participant_symbols", mode="before")(
        lambda cls, v: _unwrap_symbol_value(v)
    )


class Claim(BaseModel):
    id: str
    subject: str
    predicate: str
    object: str | None = None
    modality: Literal[
        "asserted", "reported", "claimed_by_source",
        "uncertain", "hypothetical", "conditional", "inferred",
    ]
    polarity: Literal["positive", "negative"]
    confidence: float = 1.0
    source: str | None = None
    derived_from: list[str] = []
    evidence_refs: list[EvidenceRef] = []
    source_segment_ids: list[str] = []
    symbol: str | None = None
    # v3.3/v6.0: symbol reference fields for codegraph-native code
    subject_symbol: str | Entity | None = None
    object_symbol: str | Entity | None = None

    _unwrap_subject_symbol = field_validator("subject_symbol", mode="before")(
        lambda cls, v: _unwrap_symbol_value(v)
    )
    _unwrap_object_symbol = field_validator("object_symbol", mode="before")(
        lambda cls, v: _unwrap_symbol_value(v)
    )


class Relation(BaseModel):
    id: str
    subject: str
    predicate: str
    object: str
    claim_id: str
    evidence_refs: list[EvidenceRef] = []
    symbol: str | None = None
    # v3.3/v6.0: symbol reference fields for codegraph-native code
    subject_symbol: str | Entity | None = None
    object_symbol: str | Entity | None = None
    claim_symbol: str | Claim | None = None

    _unwrap_subject_symbol = field_validator("subject_symbol", mode="before")(
        lambda cls, v: _unwrap_symbol_value(v)
    )
    _unwrap_object_symbol = field_validator("object_symbol", mode="before")(
        lambda cls, v: _unwrap_symbol_value(v)
    )
    _unwrap_claim_symbol = field_validator("claim_symbol", mode="before")(
        lambda cls, v: _unwrap_symbol_value(v)
    )


class Residual(BaseModel):
    id: str
    segment_id: str
    category: Literal[
        "structural", "stylistic", "pragmatic",
        "modal", "interpersonal", "cultural", "implication", "other",
    ]
    importance: Literal["medium", "high"]
    reason: str
    evidence_refs: list[EvidenceRef] = []
    symbol: str | None = None
    # v6.0: symbol channel for the segment_id FK (decision ①)
    segment_symbol: str | Segment | None = None

    _unwrap_segment_symbol = field_validator("segment_symbol", mode="before")(
        lambda cls, v: _unwrap_symbol_value(v)
    )


class IgnoreSegment(BaseModel):
    id: str
    segment_id: str
    reason: str
    evidence_refs: list[EvidenceRef] = []
    symbol: str | None = None
    segment_symbol: str | Segment | None = None

    _unwrap_segment_symbol = field_validator("segment_symbol", mode="before")(
        lambda cls, v: _unwrap_symbol_value(v)
    )


class CoverageReport(BaseModel):
    id: str
    doc_id: str
    total_segments: int
    status_counts: dict[str, int]
    requires_raw_fallback: list[str]
    generated_at: str


ONTOLOGY_CLASSES: dict[str, type[BaseModel]] = {
    "EvidenceRef": EvidenceRef,
    "Document": Document,
    "Block": Block,
    "Segment": Segment,
    "Entity": Entity,
    "Event": Event,
    "Claim": Claim,
    "Residual": Residual,
    "IgnoreSegment": IgnoreSegment,
    "CoverageReport": CoverageReport,
    "Relation": Relation,
}
