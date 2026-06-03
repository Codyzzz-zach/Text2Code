"""T2C Ontology — core Pydantic models for the Text2Code knowledge representation."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class EvidenceRef(BaseModel):
    """Evidence reference — nested inside semantic objects' evidence_refs lists."""
    segment_id: str
    start: int
    end: int
    quote_hash: str


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


class Entity(BaseModel):
    id: str
    name: str
    kind: str
    aliases: list[str] = []
    evidence_refs: list[EvidenceRef] = []
    source_segment_ids: list[str] = []


class Event(BaseModel):
    id: str
    name: str
    kind: str
    participants: list[str] = []
    time: str | None = None
    location: str | None = None
    evidence_refs: list[EvidenceRef] = []
    source_segment_ids: list[str] = []


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


class Relation(BaseModel):
    id: str
    subject: str
    predicate: str
    object: str
    claim_id: str
    evidence_refs: list[EvidenceRef] = []


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


class IgnoreSegment(BaseModel):
    id: str
    segment_id: str
    reason: str
    evidence_refs: list[EvidenceRef] = []


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
