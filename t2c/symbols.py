"""v6.0 single-point symbol assignment (M1).

One package-wide symbol table computed once at the compile choke point
(``compile_to_knowledge_code``). Symbols are package-globally unique so that
``__init__.py`` can re-export every symbol without collision (capability C7).

Determinism contract (rebuild gate): symbols depend only on
(type, id, name/key) — the same object set always produces the same table.
Callers must sort by id before assignment; this module does it internally so
caller order never leaks into the output.

Naming rules (supersede the two diverged historical implementations
``codegen._compute_symbol_names`` and ``compact_candidate.assign_symbols``):

  Document:      doc_<sanitized id>
  Block:         blk_<index:04d>
  Segment:       seg_<id 中 _seg_ 后缀>
  Entity/Event:  {ent|evt}_<ascii_norm> 或 {ent|evt}_zh_<sha256(name+id)[:6]>
  Claim:         claim_<norm>(≤30) 或 claim_zh_<sha256(key+id)[:6]>
  Relation:      rel_clm_<NNNN>（id 含 _rel_clm_ 时）或 rel_<i:04d>
  Residual:      res_<seg_sym>，segment 不在表 → res_<i:04d>
  IgnoreSegment: ign_<seg_sym>，segment 不在表 → ign_<i:04d>
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any


class CodegenSymbolError(ValueError):
    """Raised when the symbol table cannot be built consistently."""


# Fixed module homes — the import DAG (text ← entities ← {events,claims}
# ← derived; text ← residuals) is enforced by this table.
TYPE_TO_MODULE: dict[str, str] = {
    "Document": ".text",
    "Block": ".text",
    "Segment": ".text",
    "Entity": ".entities",
    "Event": ".events",
    "Claim": ".claims",
    "Residual": ".residuals",
    "IgnoreSegment": ".residuals",
    "Relation": ".derived",
}


@dataclass
class SymbolTable:
    """Package-wide symbol assignment.

    id_to_symbol:   object id → assigned symbol
    symbol_to_module: symbol → defining module (e.g. ".text")
    """

    id_to_symbol: dict[str, str] = field(default_factory=dict)
    symbol_to_module: dict[str, str] = field(default_factory=dict)

    def symbol_for(self, obj_id: str) -> str | None:
        return self.id_to_symbol.get(obj_id)

    def module_of(self, symbol: str) -> str | None:
        return self.symbol_to_module.get(symbol)

    def __len__(self) -> int:
        return len(self.id_to_symbol)


def _normalize_name(name: str) -> str | None:
    """Produce a Python-safe identifier fragment from a name, if possible.

    Pure ASCII → normalized slug. Mixed names contribute their ASCII runs
    (e.g. "爱丽丝 (Alice)" → "alice"). Pure non-ASCII → None (hash fallback).
    """
    if not name:
        return None
    if name.isascii() and name.replace("_", "").isalnum():
        return name.lower().replace(" ", "_").replace("-", "_")
    parts = re.findall(r"[A-Za-z0-9]+", name)
    if parts:
        slug = "_".join(parts).lower()
        if slug:
            return slug
    return None


def _zh_hash(text: str, prefix: str) -> str:
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()[:6]
    return f"{prefix}_zh_{h}"


def _claim_key(obj: Any) -> str:
    subject = getattr(obj, "subject", "") or ""
    predicate = getattr(obj, "predicate", "") or ""
    obj_val = getattr(obj, "object", "") or ""
    return f"{subject}_{predicate}_{obj_val}"


def compute_symbol_table(
    *,
    doc: Any = None,
    blocks: list[Any] | None = None,
    segments: list[Any] | None = None,
    entities: list[Any] | None = None,
    events: list[Any] | None = None,
    claims: list[Any] | None = None,
    relations: list[Any] | None = None,
    residuals: list[Any] | None = None,
    ignores: list[Any] | None = None,
) -> SymbolTable:
    """Assign package-globally-unique symbols to all objects, deterministically.

    Objects are processed in a fixed type order, sorted by id within each
    type, so the output depends only on the object set — never on caller
    ordering.
    """
    table = SymbolTable()
    used: set[str] = set()
    seen_ids: dict[str, str] = {}  # id → type (duplicate-id defense)

    def claim_name(base: str, obj_id: str) -> str:
        name = base
        suffix = 0
        while name in used:
            suffix += 1
            name = f"{base}_{suffix}"
        used.add(name)
        prev_type = seen_ids.get(obj_id)
        if prev_type is not None:
            raise CodegenSymbolError(
                f"object id {obj_id!r} appears as both {prev_type} and another type"
            )
        table.id_to_symbol[obj_id] = name
        return name

    def sorted_by_id(objects: list[Any]) -> list[Any]:
        return sorted(objects, key=lambda o: getattr(o, "id", ""))

    # --- Document ---
    if doc is not None:
        doc_id = getattr(doc, "id", "doc")
        base = f"doc_{doc_id.replace('.', '_').replace('-', '_')}"
        sym = claim_name(base, doc_id)
        table.symbol_to_module[sym] = TYPE_TO_MODULE["Document"]

    # --- Block ---
    for block in sorted_by_id(blocks or []):
        base = f"blk_{getattr(block, 'index', 0):04d}"
        sym = claim_name(base, block.id)
        table.symbol_to_module[sym] = TYPE_TO_MODULE["Block"]

    # --- Segment (before Residual/IgnoreSegment: they derive from seg syms) ---
    for seg in sorted_by_id(segments or []):
        seg_id = seg.id
        if "_seg_" in seg_id:
            base = "seg_" + seg_id.rsplit("_seg_", 1)[-1]
        else:
            base = _zh_hash(seg_id, "seg")
        sym = claim_name(base, seg_id)
        table.symbol_to_module[sym] = TYPE_TO_MODULE["Segment"]

    # --- Entity ---
    for ent in sorted_by_id(entities or []):
        norm = _normalize_name(getattr(ent, "name", ""))
        base = f"ent_{norm}" if norm else _zh_hash(ent.name + ent.id, "ent")
        sym = claim_name(base, ent.id)
        table.symbol_to_module[sym] = TYPE_TO_MODULE["Entity"]

    # --- Event ---
    for evt in sorted_by_id(events or []):
        norm = _normalize_name(getattr(evt, "name", ""))
        base = f"evt_{norm}" if norm else _zh_hash(evt.name + evt.id, "evt")
        sym = claim_name(base, evt.id)
        table.symbol_to_module[sym] = TYPE_TO_MODULE["Event"]

    # --- Claim ---
    for clm in sorted_by_id(claims or []):
        key = _claim_key(clm)
        norm = _normalize_name(key)
        if norm and len(norm) <= 30:
            base = f"claim_{norm}"
        else:
            # v6.0 decision ②: hash includes the id — identical (s,p,o)
            # triples from different claims no longer collide into suffixes.
            base = _zh_hash(key + clm.id, "claim")
        sym = claim_name(base, clm.id)
        table.symbol_to_module[sym] = TYPE_TO_MODULE["Claim"]

    # --- Relation ---
    for i, rel in enumerate(sorted_by_id(relations or [])):
        if "_rel_clm_" in rel.id:
            base = "rel_clm_" + rel.id.rsplit("_rel_clm_", 1)[-1]
        else:
            base = f"rel_{i:04d}"
        sym = claim_name(base, rel.id)
        table.symbol_to_module[sym] = TYPE_TO_MODULE["Relation"]

    # --- Residual / IgnoreSegment (symbol derives from their segment's) ---
    for i, res in enumerate(sorted_by_id(residuals or [])):
        seg_sym = table.id_to_symbol.get(getattr(res, "segment_id", ""))
        base = f"res_{seg_sym}" if seg_sym else f"res_{i:04d}"
        sym = claim_name(base, res.id)
        table.symbol_to_module[sym] = TYPE_TO_MODULE["Residual"]

    for i, ign in enumerate(sorted_by_id(ignores or [])):
        seg_sym = table.id_to_symbol.get(getattr(ign, "segment_id", ""))
        base = f"ign_{seg_sym}" if seg_sym else f"ign_{i:04d}"
        sym = claim_name(base, ign.id)
        table.symbol_to_module[sym] = TYPE_TO_MODULE["IgnoreSegment"]

    return table


__all__ = [
    "CodegenSymbolError",
    "SymbolTable",
    "TYPE_TO_MODULE",
    "compute_symbol_table",
]
