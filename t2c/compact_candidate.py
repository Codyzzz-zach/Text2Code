"""Compact candidate protocol — short-key JSON the LLM emits, expanded to
verbose `{"type", "data"}` objects by this module.

Design (see spec/llm_cost_cache_design.md §2):

  LLM
    -> [{"t":"E","lid":"e1","n":"甄士隐","k":"person","a":["士隐"],
         "sid":["seg1"],"q":["甄士隐"]}, ...]
  CompactCandidateParser
    -> list[CompactCandidate] (typed, validated)
  CompactExpander
    -> list[{"type":"Entity","data":{...}}] (with EvidenceRef + Relation derived)

Field aliases:

  t   -> type      (E | EV | C | I)
  lid -> local id  (only valid within a single batch)
  n   -> name
  k   -> kind
  a   -> aliases
  sid -> source_segment_ids (always a list)
  q   -> quotes (list[str] used to locate EvidenceRef spans)
  s   -> subject (entity id or local id)
  p   -> predicate (Claim) or participants (Event)
  o   -> object  (entity id, local id, or literal)
  m   -> modality
  pol -> polarity
  r   -> reason (IgnoreSegment / Residual)

The LLM never emits `Relation` (`R`) or `EvidenceRef` directly:
  - Relation is derived from Claim by the program (see RelationDeriver)
  - EvidenceRef is computed from `q` quotes against Segment.text_slice
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

logger = logging.getLogger(__name__)


# The four candidate types the LLM is allowed to emit in v3.4.2.
COMPACT_TYPE_ENTITY = "E"
COMPACT_TYPE_EVENT = "EV"
COMPACT_TYPE_CLAIM = "C"
COMPACT_TYPE_IGNORE = "I"

VALID_COMPACT_TYPES = frozenset({
    COMPACT_TYPE_ENTITY,
    COMPACT_TYPE_EVENT,
    COMPACT_TYPE_CLAIM,
})

# Verbose type names used downstream by SchemaValidator / CodeGenerator.
_TYPE_TO_VERBOSE: dict[str, str] = {
    COMPACT_TYPE_ENTITY: "Entity",
    COMPACT_TYPE_EVENT: "Event",
    COMPACT_TYPE_CLAIM: "Claim",
    COMPACT_TYPE_IGNORE: "IgnoreSegment",
}

# Modality and polarity are not abbreviated: LLM has to spell them out
# because the rest of the system uses those literal strings directly.
VALID_MODALITIES = frozenset({
    "asserted", "reported", "claimed_by_source",
    "uncertain", "hypothetical", "conditional", "inferred",
})
VALID_POLARITIES = frozenset({"positive", "negative"})


@dataclass
class CompactCandidate:
    """A single compact candidate, post-parse but pre-expansion."""

    type: str  # one of VALID_COMPACT_TYPES
    fields: dict[str, Any] = field(default_factory=dict)
    raw_index: int = 0  # position in the LLM's array (for diagnostics)
    parse_warnings: list[str] = field(default_factory=list)

    @property
    def verbose_type(self) -> str:
        return _TYPE_TO_VERBOSE.get(self.type, "Unknown")


class CompactCandidateError(ValueError):
    """Raised when a candidate is structurally malformed."""


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
        return text.strip()
    return text


def parse_compact_response(response_text: str) -> list[CompactCandidate]:
    """Parse the LLM's compact-JSON response into a typed list.

    Accepts:
      - bare JSON array
      - ```json ... ``` fenced
      - JSON embedded in surrounding prose (we take the first [...] match)

    On JSON failure we attempt brace-matching recovery (same strategy as
    the verbose parser) so that truncated responses still salvage what
    they can. Recovered blocks must contain at least a `t` field and one
    of `n` (Entity/Event name) or `sid` (segment id) to be kept.
    """
    text = _strip_fences(response_text)
    parsed: Any = None
    if text:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\[[\s\S]*\]", text)
            if match:
                try:
                    parsed = json.loads(match.group())
                except json.JSONDecodeError:
                    parsed = None

    if parsed is None:
        # Fall back to brace-balanced recovery of complete {...} blocks.
        return _recover_from_text(text)

    if isinstance(parsed, dict):
        # Some models wrap the array in an object: {"candidates": [...]}.
        for key in ("candidates", "results", "data", "items"):
            if key in parsed and isinstance(parsed[key], list):
                parsed = parsed[key]
                break
        else:
            return []

    if not isinstance(parsed, list):
        return []

    out: list[CompactCandidate] = []
    for idx, item in enumerate(parsed):
        if not isinstance(item, dict):
            continue
        cand = _parse_single(item, idx)
        if cand is not None:
            out.append(cand)
    return out


def _parse_single(item: dict[str, Any], raw_index: int) -> CompactCandidate | None:
    """Validate and normalize one compact candidate dict.

    Unknown `t` values are dropped with a parse warning instead of raising
    — the LLM is allowed to occasionally invent types and we don't want a
    single bad object to abort the whole batch.
    """
    t = item.get("t")
    if not isinstance(t, str):
        return None
    if t not in VALID_COMPACT_TYPES:
        return CompactCandidate(
            type=t,
            raw_index=raw_index,
            parse_warnings=[f"unknown compact type {t!r}; dropped"],
        )

    fields: dict[str, Any] = {}
    warnings: list[str] = []

    # name
    if t in (COMPACT_TYPE_ENTITY, COMPACT_TYPE_EVENT):
        n = item.get("n")
        if not isinstance(n, str) or not n.strip():
            warnings.append("missing name")
        fields["name"] = n if isinstance(n, str) else ""

    # kind
    if t in (COMPACT_TYPE_ENTITY, COMPACT_TYPE_EVENT):
        k = item.get("k", "other")
        if not isinstance(k, str):
            k = str(k)
        fields["kind"] = k

    # local id
    lid = item.get("lid")
    if lid is not None:
        if not isinstance(lid, str):
            lid = str(lid)
        fields["local_id"] = lid

    # aliases (Entity only)
    if t == COMPACT_TYPE_ENTITY:
        a = item.get("a", [])
        if isinstance(a, list):
            fields["aliases"] = [x for x in a if isinstance(x, str)]
        else:
            fields["aliases"] = []

    # source_segment_ids (required for all but I-where-reason-is-empty)
    sid = item.get("sid")
    if isinstance(sid, str):
        fields["source_segment_ids"] = [sid]
    elif isinstance(sid, list):
        fields["source_segment_ids"] = [s for s in sid if isinstance(s, str)]
    else:
        fields["source_segment_ids"] = []

    # quotes (optional)
    q = item.get("q", [])
    if isinstance(q, str):
        fields["quotes"] = [q]
    elif isinstance(q, list):
        fields["quotes"] = [x for x in q if isinstance(x, str)]
    else:
        fields["quotes"] = []

    if t == COMPACT_TYPE_EVENT:
        # p here is participants
        p = item.get("p", [])
        if isinstance(p, list):
            fields["participants"] = [x for x in p if isinstance(x, (str,))]
        elif isinstance(p, str):
            fields["participants"] = [p]
        else:
            fields["participants"] = []
        # time / location
        if isinstance(item.get("time"), str):
            fields["time"] = item["time"]
        if isinstance(item.get("location"), str):
            fields["location"] = item["location"]

    if t == COMPACT_TYPE_CLAIM:
        s = item.get("s")
        o = item.get("o")
        p = item.get("p")
        if isinstance(s, str):
            fields["subject"] = s
        if isinstance(p, str):
            fields["predicate"] = p
        if o is None:
            fields["object"] = None
        elif isinstance(o, str):
            fields["object"] = o
        else:
            fields["object"] = str(o)
        m = item.get("m", None)
        if m is not None and isinstance(m, str) and m in VALID_MODALITIES:
            fields["modality"] = m
        elif m is not None:
            fields["modality"] = None  # let expand_candidates derive from segment_type
            warnings.append(f"unknown modality {m!r}; will derive from segment_type")
        # else: m is None → expand_candidates derives from segment_type
        pol = item.get("pol", "positive")
        if isinstance(pol, str) and pol in VALID_POLARITIES:
            fields["polarity"] = pol
        else:
            fields["polarity"] = "positive"
            warnings.append(f"unknown polarity {pol!r}; defaulted to 'positive'")

    return CompactCandidate(
        type=t,
        fields=fields,
        raw_index=raw_index,
        parse_warnings=warnings,
    )


def _recover_from_text(text: str) -> list[CompactCandidate]:
    """Brace-balanced recovery: salvage complete {...} blocks from a truncated
    response. Mirrors the strategy in extractor._recover_partial_objects but
    tailored for compact format (no `data` wrapper, flat `t`/`n`/etc.).
    """
    if not text:
        return []
    depth = 0
    start_idx = -1
    in_str = False
    escape = False
    blocks: list[str] = []
    for i, ch in enumerate(text):
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            if depth == 0:
                start_idx = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start_idx >= 0:
                    blocks.append(text[start_idx:i + 1])
                    start_idx = -1
    out: list[CompactCandidate] = []
    for raw_index, blk in enumerate(blocks):
        try:
            obj = json.loads(blk)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        # Recovery only keeps objects that look like candidates.
        if "t" in obj and "n" in obj or ("t" in obj and "sid" in obj):
            cand = _parse_single(obj, raw_index)
            if cand is not None:
                cand.parse_warnings.append("recovered from partial response")
                out.append(cand)
    return out


# ---------------------------------------------------------------------------
# Program expand
# ---------------------------------------------------------------------------


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _quote_hash(text: str) -> str:
    return "sha256:" + _sha256_hex(text)


def locate_quote(
    segment_text: str, quote: str
) -> tuple[int, int] | None:
    """Return (start, end) for `quote` inside `segment_text`, or None.

    Strategy: prefer the unique match; if there are multiple, prefer the
    shortest surrounding context window (i.e. the first occurrence); if
    there are zero, return None. We use `str.find` rather than regex so
    we don't have to think about escaping.

    v4.0: callers should use `locate_quote_with_ambiguity` to get an
    ambiguity flag — silent ambiguity is the kind of "looks like it
    works" bug we want to surface.
    """
    if not quote:
        return None
    idx = segment_text.find(quote)
    if idx < 0:
        return None
    return (idx, idx + len(quote))


def locate_quote_with_ambiguity(
    segment_text: str, quote: str
) -> tuple[tuple[int, int], bool] | None:
    """Like locate_quote, but also returns whether the match was ambiguous.

    Returns:
        None → no match
        ((start, end), False) → unique match
        ((start, end), True) → first match, but more matches exist
    """
    if not quote:
        return None
    idx = segment_text.find(quote)
    if idx < 0:
        return None
    second = segment_text.find(quote, idx + 1)
    return ((idx, idx + len(quote)), second >= 0)


def build_evidence_refs(
    quotes: Iterable[str],
    segments_by_id: dict[str, Any],
    source_segment_ids: list[str],
) -> tuple[list[dict], list[str]]:
    """Locate every quote against every source segment.

    Returns (refs, warnings):
      - refs: list of {"segment_id", "start", "end", "quote_hash"} dicts
              ready to plug into an Entity/Claim/Event payload.
      - warnings: human-readable notes (ambiguous quote, no source segment,
                  no match, etc.)
    """
    refs: list[dict] = []
    warnings: list[str] = []
    if not quotes or not source_segment_ids:
        return refs, warnings
    for q in quotes:
        placed = False
        for sid in source_segment_ids:
            seg = segments_by_id.get(sid)
            if seg is None:
                continue
            text = getattr(seg, "text_slice", None)
            if not text:
                continue
            result = locate_quote_with_ambiguity(text, q)
            if result is None:
                continue
            (start, end), ambiguous = result
            if ambiguous:
                warnings.append(
                    f"ambiguous quote (multiple matches) for sid={sid} q={q!r}; using first"
                )
            slice_ = text[start:end]
            if slice_ != q:
                warnings.append(
                    f"quote span mismatch for sid={sid} q={q!r}"
                )
                continue
            ref = {
                "segment_id": sid,
                "start": start,
                "end": end,
                "quote_hash": _quote_hash(slice_),
            }
            # Skip if we already have an identical ref (same sid+span+hash).
            if not any(
                r["segment_id"] == ref["segment_id"]
                and r["start"] == ref["start"]
                and r["end"] == ref["end"]
                for r in refs
            ):
                refs.append(ref)
            placed = True
        if not placed:
            warnings.append(f"no source segment contained quote {q!r}")
    return refs, warnings


def _make_local_id_map(candidates: list[CompactCandidate]) -> dict[str, str]:
    """Reserve canonical entity IDs for every Entity candidate that has a
    `local_id`. Returns a mapping local_id → canonical id.

    The actual id assignment is handled by the caller (which knows about
    cross-batch state and counters). This function just collects the
    `lid` values seen in the batch so we can resolve them later.
    """
    return {c.fields["local_id"]: c.fields["local_id"] for c in candidates
            if c.type == COMPACT_TYPE_ENTITY and "local_id" in c.fields}


def expand_candidates(
    candidates: list[CompactCandidate],
    segments: list[Any],
    doc_id: str,
    *,
    next_ent_idx: int = 1,
    next_evt_idx: int = 1,
    next_clm_idx: int = 1,
    next_ign_idx: int = 1,
) -> tuple[list[dict], list[str]]:
    """Expand compact candidates into verbose objects.

    Returns (objects, warnings):
      - objects: list of {"type": "Entity"|"Event"|"Claim"|"IgnoreSegment",
                           "data": {...}} dicts
      - warnings: aggregate of (a) per-candidate parse warnings and
                  (b) per-quote evidence-locator warnings

    Relation and EvidenceRef objects are NOT produced here. They are
    derived separately by RelationDeriver and build_evidence_refs in the
    downstream pipeline.
    """
    objects: list[dict] = []
    warnings: list[str] = []

    segments_by_id = {s.id: s for s in segments}

    # First pass: build local_id -> canonical entity id mapping for THIS batch.
    # Cross-batch entities (existing_entities passed in by the caller) are
    # already in canonical form, so the caller can pre-load them into the
    # local_id map by using a local_id that equals a global id. We keep
    # this method pure (no cross-batch state) — expansion callers wire it up.
    local_to_canonical: dict[str, str] = {}

    ent_counter = next_ent_idx
    evt_counter = next_evt_idx
    clm_counter = next_clm_idx
    ign_counter = next_ign_idx

    # Pass 1: entities — assign canonical ids first so claims can resolve.
    for c in candidates:
        if c.type != COMPACT_TYPE_ENTITY:
            continue
        for w in c.parse_warnings:
            warnings.append(f"ent#{c.raw_index}: {w}")
        name = c.fields.get("name", "")
        canonical_id = f"{doc_id}_ent_{ent_counter:04d}"
        ent_counter += 1
        local = c.fields.get("local_id")
        if local:
            local_to_canonical[local] = canonical_id

    # Pass 2: events / claims / ignores.
    for c in candidates:
        if c.type == COMPACT_TYPE_ENTITY:
            # Already emitted on pass 1; emit now for code simplicity.
            canonical_id = local_to_canonical.get(
                c.fields.get("local_id", ""), ""
            )
            if not canonical_id:
                # No local id was assigned (rare); assign one on the fly.
                canonical_id = f"{doc_id}_ent_{ent_counter:04d}"
                ent_counter += 1
            data: dict[str, Any] = {
                "id": canonical_id,
                "name": c.fields.get("name", ""),
                "kind": c.fields.get("kind", "other"),
                "aliases": list(c.fields.get("aliases", [])),
                "source_segment_ids": list(c.fields.get("source_segment_ids", [])),
            }
            refs, ref_warnings = build_evidence_refs(
                c.fields.get("quotes", []),
                segments_by_id,
                c.fields.get("source_segment_ids", []),
            )
            data["evidence_refs"] = refs
            for w in ref_warnings:
                warnings.append(f"ent {canonical_id}: {w}")
            objects.append({"type": "Entity", "data": data})
            continue

        for w in c.parse_warnings:
            warnings.append(f"cand#{c.raw_index}: {w}")

        if c.type == COMPACT_TYPE_EVENT:
            # Resolve participant local_ids → canonical entity ids. Unknown
            # ids are passed through unchanged; downstream validation will
            # flag them as dangling references.
            resolved_participants = [
                local_to_canonical.get(p, p)
                for p in c.fields.get("participants", [])
            ]
            data = {
                "id": f"{doc_id}_evt_{evt_counter:04d}",
                "name": c.fields.get("name", ""),
                "kind": c.fields.get("kind", "occurrence"),
                "participants": resolved_participants,
                "source_segment_ids": list(c.fields.get("source_segment_ids", [])),
            }
            if "time" in c.fields:
                data["time"] = c.fields["time"]
            if "location" in c.fields:
                data["location"] = c.fields["location"]
            refs, ref_warnings = build_evidence_refs(
                c.fields.get("quotes", []),
                segments_by_id,
                c.fields.get("source_segment_ids", []),
            )
            data["evidence_refs"] = refs
            for w in ref_warnings:
                warnings.append(f"evt {data['id']}: {w}")
            evt_counter += 1
            objects.append({"type": "Event", "data": data})

        elif c.type == COMPACT_TYPE_CLAIM:
            # Resolve subject/object: local_id → canonical id, else keep as-is
            # (caller may later fixup via post-processing or remove dangling).
            subj_raw = c.fields.get("subject", "")
            obj_raw = c.fields.get("object", None)
            subj_resolved = local_to_canonical.get(subj_raw, subj_raw)
            if obj_raw is not None:
                obj_resolved = local_to_canonical.get(obj_raw, obj_raw)
            else:
                obj_resolved = None
            # P2-1: modality 从 segment_type 程序化推导
            modality_raw = c.fields.get("modality", None)
            if modality_raw is None:
                seg_types = set()
                for sid in c.fields.get("source_segment_ids", []):
                    seg = segments_by_id.get(sid)
                    if seg:
                        seg_types.add(seg.segment_type)
                non_asserted = {"dialogue", "heading", "list_item", "table_row"}
                modality_raw = "reported" if seg_types & non_asserted else "asserted"
            data = {
                "id": f"{doc_id}_clm_{clm_counter:04d}",
                "subject": subj_resolved,
                "predicate": c.fields.get("predicate", "related_to"),
                "object": obj_resolved,
                "modality": modality_raw,
                "polarity": c.fields.get("polarity", "positive"),
                "source_segment_ids": list(c.fields.get("source_segment_ids", [])),
            }
            refs, ref_warnings = build_evidence_refs(
                c.fields.get("quotes", []),
                segments_by_id,
                c.fields.get("source_segment_ids", []),
            )
            data["evidence_refs"] = refs
            for w in ref_warnings:
                warnings.append(f"clm {data['id']}: {w}")
            clm_counter += 1
            objects.append({"type": "Claim", "data": data})

    return objects, warnings


# ---------------------------------------------------------------------------
# Relation derivation (program-side, see spec §3)
# ---------------------------------------------------------------------------


def derive_relations(
    objects: list[dict],
    entity_ids: set[str],
    *,
    next_rel_idx: int = 1,
    doc_id: str | None = None,
) -> tuple[list[dict], list[str]]:
    """Return (relations, warnings) — one Relation per eligible Claim.

    P3-1 enhancements:
      - Dedup: same (subject, predicate, object) only produces one Relation,
        with evidence_refs merged from all contributing Claims.
      - Stable ID: derived from claim_id when possible.

    Eligibility (must satisfy ALL):
      - Claim.modality == "asserted"
      - Claim.polarity == "positive"
      - Claim.subject ∈ entity_ids
      - Claim.object ∈ entity_ids (non-None and a known entity id)
      - Claim has at least one evidence_ref OR source_segment_ids
    """
    relations: list[dict] = []
    warnings: list[str] = []
    rel_counter = next_rel_idx

    # P3-1: dedup by (subject, predicate, object) triple
    rel_dedup: dict[tuple, int] = {}  # dedup_key → index in relations list

    # Pre-index claims for O(1) id lookup.
    claim_id_set: set[str] = set()
    for obj in objects:
        if obj.get("type") == "Claim":
            cid = obj.get("data", {}).get("id", "")
            if cid:
                claim_id_set.add(cid)

    for obj in objects:
        if obj.get("type") != "Claim":
            continue
        data = obj.get("data", {})
        cid = data.get("id", "")
        if not cid:
            continue
        if data.get("modality") != "asserted":
            warnings.append(
                f"skip relation: {cid} has modality={data.get('modality')!r}"
            )
            continue
        if data.get("polarity") != "positive":
            warnings.append(
                f"skip relation: {cid} has polarity={data.get('polarity')!r}"
            )
            continue
        subj = data.get("subject", "")
        obj_val = data.get("object", None)
        if subj not in entity_ids:
            warnings.append(
                f"skip relation: {cid} subject {subj!r} not an entity"
            )
            continue
        if obj_val is None or obj_val not in entity_ids:
            warnings.append(
                f"skip relation: {cid} object {obj_val!r} not an entity"
            )
            continue
        if not data.get("evidence_refs") and not data.get("source_segment_ids"):
            warnings.append(
                f"skip relation: {cid} has no evidence_refs and no source_segment_ids"
            )
            continue

        # P3-1: dedup check
        predicate = data.get("predicate", "related_to")
        dup_key = (subj, predicate, obj_val)
        if dup_key in rel_dedup:
            # Merge evidence_refs into existing relation
            existing_idx = rel_dedup[dup_key]
            existing_refs = relations[existing_idx]["data"].setdefault("evidence_refs", [])
            for ref in data.get("evidence_refs", []):
                if ref not in existing_refs:
                    existing_refs.append(ref)
            continue

        # P3-1: stable ID from claim_id
        if doc_id and "_clm_" in cid:
            rid = cid.replace("_clm_", "_rel_clm_", 1)
        else:
            rid = (
                f"{doc_id}_rel_{rel_counter:04d}" if doc_id
                else f"rel_{rel_counter:04d}"
            )
            rel_counter += 1

        rel_obj = {
            "type": "Relation",
            "data": {
                "id": rid,
                "subject": subj,
                "predicate": predicate,
                "object": obj_val,
                "claim_id": cid,
                "evidence_refs": list(data.get("evidence_refs", [])),
            },
        }
        rel_dedup[dup_key] = len(relations)
        relations.append(rel_obj)

    return relations, warnings


# ---------------------------------------------------------------------------
# v3.3 symbol assignment during expansion
# ---------------------------------------------------------------------------


def compute_symbol_name(type_name: str, name_or_key: str, object_id: str) -> str:
    """Compute a stable v3.3 Python symbol for an expanded candidate.

    Uses hash-based naming for Chinese/non-ASCII names, short ASCII names
    kept as-is (max 30 chars).
    """
    if type_name == "Entity":
        prefix = "ent"
    elif type_name == "Event":
        prefix = "evt"
    elif type_name == "Claim":
        prefix = "claim"
    else:
        prefix = "obj"

    key = name_or_key if name_or_key else object_id
    # Try ASCII-safe normalization
    if key.isascii() and key.replace("_", "").isalnum():
        norm = key.lower().replace(" ", "_").replace("-", "_")
        if len(norm) <= 30:
            return f"{prefix}_{norm}"
    # Fall back to hash
    h = hashlib.sha256(f"{key}{object_id}".encode("utf-8")).hexdigest()[:6]
    return f"{prefix}_zh_{h}"


def assign_symbols(
    objects: list[dict],
    *,
    existing_symbols: set[str] | None = None,
) -> dict[str, str]:
    """Assign v3.3 Python symbols to expanded candidate objects.

    Modifies each object dict in-place, adding a "symbol" key.
    Returns {object_id: symbol_name} for use as external_symbols index.
    Symbol naming is stable: same name/id → same symbol.
    """
    used: set[str] = set(existing_symbols or ())
    symbol_map: dict[str, str] = {}

    for obj in objects:
        type_name = obj.get("type", "")
        data = obj.get("data", {})
        obj_id = data.get("id", "")

        if type_name == "Entity":
            key = data.get("name", obj_id)
        elif type_name == "Event":
            key = data.get("name", obj_id)
        elif type_name == "Claim":
            subj = data.get("subject", "")
            pred = data.get("predicate", "")
            obj_val = data.get("object", "") or ""
            key = f"{subj}_{pred}_{obj_val}"
        else:
            key = obj_id

        base = compute_symbol_name(type_name, key, obj_id)
        sym = base
        suffix = 0
        while sym in used:
            suffix += 1
            sym = f"{base}_{suffix}"

        used.add(sym)
        obj["symbol"] = sym
        symbol_map[obj_id] = sym

    return symbol_map


def expand_and_assign_symbols(
    candidates: list[CompactCandidate],
    segments: list[Any],
    doc_id: str,
    *,
    existing_symbols: set[str] | None = None,
    next_ent_idx: int = 1,
    next_evt_idx: int = 1,
    next_clm_idx: int = 1,
    next_ign_idx: int = 1,
) -> tuple[list[dict], dict[str, str], list[str]]:
    """Expand compact candidates AND assign v3.3 symbols in one pass.

    Returns (objects, symbol_map, warnings):
      - objects: list of {"type", "symbol", "data"} dicts ready for codegen
      - symbol_map: {object_id: symbol_name}
      - warnings: aggregate warnings
    """
    objects, warnings = expand_candidates(
        candidates, segments, doc_id,
        next_ent_idx=next_ent_idx,
        next_evt_idx=next_evt_idx,
        next_clm_idx=next_clm_idx,
        next_ign_idx=next_ign_idx,
    )
    symbol_map = assign_symbols(objects, existing_symbols=existing_symbols)
    return objects, symbol_map, warnings


def expansion_failures_to_residuals(
    warnings: list[str],
    segment_id: str | None = None,
    doc_id: str | None = None,
    next_res_idx: int = 1,
) -> list[dict]:
    """Convert expansion warnings into Residual objects for coverage tracking.

    Only creates residuals for high-signal warnings (missing evidence,
    dangling refs, etc.), not routine parse warnings.
    """
    residuals: list[dict] = []
    important = {"missing name", "no source segment", "no match",
                 "dangling", "not an entity", "no evidence"}
    for w in warnings:
        if any(p in w.lower() for p in important):
            rid = f"{doc_id}_res_{next_res_idx:04d}" if doc_id else f"res_{next_res_idx:04d}"
            residuals.append({
                "type": "Residual",
                "data": {
                    "id": rid,
                    "segment_id": segment_id or "",
                    "category": "other",
                    "importance": "medium",
                    "reason": w,
                    "evidence_refs": [],
                },
            })
            next_res_idx += 1
    return residuals


__all__ = [
    "CompactCandidate",
    "CompactCandidateError",
    "COMPACT_TYPE_ENTITY",
    "COMPACT_TYPE_EVENT",
    "COMPACT_TYPE_CLAIM",
    "COMPACT_TYPE_IGNORE",
    "VALID_COMPACT_TYPES",
    "VALID_MODALITIES",
    "VALID_POLARITIES",
    "assign_symbols",
    "build_evidence_refs",
    "compute_symbol_name",
    "derive_relations",
    "expand_and_assign_symbols",
    "expand_candidates",
    "expansion_failures_to_residuals",
    "locate_quote",
    "parse_compact_response",
]
