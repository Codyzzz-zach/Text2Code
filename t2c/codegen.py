"""Code Generator — deterministic .t2c.py generation from ontology objects.

v6.0 (M1): single symbol table + bare-Name reference emission.

- Symbols come from ``t2c.symbols.compute_symbol_table`` (one package-wide
  assignment, computed once per compilation). This module never invents
  symbol names on its own.
- ``*_symbol`` fields are emitted as bare Names (real AST references), with
  matching live cross-file imports. The generated package is import-validated:
  a dangling reference is an ImportError (capability C10).
- Objects self-declare their symbol via the ``symbol='...'`` kwarg; the
  ontology's before-validators unwrap bare-Name references back to symbol
  strings at import time, so Pydantic always stores plain strings.
"""
from __future__ import annotations

import ast
from typing import Any

from pydantic import BaseModel

from t2c.ontology import (
    Block,
    CoverageReport,
    Document,
    Entity,
    Event,
    EvidenceRef,
    IgnoreSegment,
    Relation,
    Residual,
    Segment,
)
from t2c.symbols import CodegenSymbolError, SymbolTable, compute_symbol_table


# Module-level helpers used by multi-file generation.
# They scan generated .t2c.py source for symbol names + segment_id mappings
# so we can wire cross-file imports without re-running the model side.
def _scan_symbols(source: str) -> list[tuple[str, str]]:
    """Return [(symbol_name, constructor_type), ...] from generated source."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    out = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            target = node.targets[0]
            if isinstance(target, ast.Name):
                ctor = node.value.func
                if isinstance(ctor, ast.Name):
                    out.append((target.id, ctor.id))
    return out


def _scan_top_level_symbols(source: str) -> list[str]:
    """Return [symbol_name, ...] from generated source (assignments only)."""
    return [name for name, _ in _scan_symbols(source)]


def _extract_segment_id_symbol_map(source: str) -> dict[str, str]:
    """Return {segment_id: symbol_name} for Segment assignments.

    Walks the AST and pairs `seg_NNNN = Segment(id='hongloumeng_seg_0009', ...)`
    so the caller can build the `external_symbols` index for semantic code.
    """
    out: dict[str, str] = {}
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return out
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, ast.Call):
            continue
        ctor = node.value.func
        if not isinstance(ctor, ast.Name) or ctor.id != "Segment":
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        for kw in node.value.keywords:
            if kw.arg == "id" and isinstance(kw.value, ast.Constant):
                out[str(kw.value.value)] = target.id
    return out


# Field order for deterministic output per type
FIELD_ORDER: dict[str, list[str]] = {
    "EvidenceRef": ["segment_id", "segment_symbol", "start", "end", "quote_hash"],
    "Document": ["id", "source_path", "raw_text_hash", "total_length", "block_count", "created_at"],
    "Block": ["id", "doc_id", "index", "block_type", "start_offset", "end_offset", "text_slice", "hash"],
    "Segment": ["id", "symbol", "doc_id", "block_index", "segment_type", "start_offset", "end_offset",
                "text_slice", "hash"],
    "Entity": ["id", "symbol", "name", "kind", "aliases", "evidence_refs", "source_segment_ids"],
    "Event": ["id", "symbol", "name", "kind", "participants", "participant_symbols", "time", "location",
              "evidence_refs", "source_segment_ids"],
    "Claim": ["id", "symbol", "subject", "subject_symbol", "predicate", "object", "object_symbol",
              "modality", "polarity", "confidence",
              "source", "derived_from", "evidence_refs", "source_segment_ids"],
    "Relation": ["id", "symbol", "subject", "subject_symbol", "predicate", "object", "object_symbol",
                 "claim_id", "claim_symbol", "evidence_refs"],
    "Residual": ["id", "symbol", "segment_id", "segment_symbol", "category", "importance", "reason",
                 "evidence_refs"],
    "IgnoreSegment": ["id", "symbol", "segment_id", "segment_symbol", "reason", "evidence_refs"],
    "CoverageReport": ["id", "doc_id", "total_segments", "status_counts", "requires_raw_fallback", "generated_at"],
}

_DEFAULT_VERSION = "v6.0"

# _symbol fields derive their bare-Name references from FK fields.
# value = (fk_field, is_list)
_SYMBOL_DERIVATION: dict[str, tuple[str, bool]] = {
    "subject_symbol": ("subject", False),
    "object_symbol": ("object", False),
    "segment_symbol": ("segment_id", False),
    "claim_symbol": ("claim_id", False),
    "participant_symbols": ("participants", True),
}

# Fields whose FK must resolve to a known symbol. object_symbol is lenient:
# Claim.object may legitimately be a literal string (not an entity id).
_STRICT_SYMBOL_FIELDS = {
    "subject_symbol", "segment_symbol", "claim_symbol", "participant_symbols",
}

# Re-export order for __init__.py — must follow the import DAG.
_MODULE_DAG_ORDER = [".text", ".entities", ".events", ".claims", ".residuals", ".derived"]


def _looks_like_entity_id(value: str) -> bool:
    """Heuristic: does this Claim.object value intend to be an entity id?"""
    return "_ent_" in value


class CodeGenerator:
    """Deterministically generate .t2c.py from ontology objects."""

    def __init__(self, version: str | None = None) -> None:
        # Override the default version tag (used in file headers).
        self._version = version or _DEFAULT_VERSION

    # -- Legacy single-file generation (pre-v3.3, kept for compatibility) ---

    def generate_document_code(
        self,
        doc: Document,
        blocks: list[Block],
    ) -> str:
        """Generate case_xxx.document.t2c.py."""
        lines = [
            f"# Auto-generated by t2c {self._version} — DO NOT EDIT",
            "from t2c.ontology import Document, Block",
            "",
        ]
        lines.append(self._format_object(doc))
        for block in blocks:
            lines.append("")
            lines.append(self._format_object(block))
        return "\n".join(lines) + "\n"

    def generate_segments_code(
        self,
        segments: list[Segment],
    ) -> str:
        """Generate case_xxx.segments.t2c.py."""
        lines = [
            f"# Auto-generated by t2c {self._version} — DO NOT EDIT",
            "from t2c.ontology import Segment",
            "",
        ]
        for seg in segments:
            lines.append(self._format_object(seg))
            lines.append("")
        return "\n".join(lines) + "\n"

    def generate_knowledge_code(
        self,
        objects: list[BaseModel],
    ) -> str:
        """Generate case_xxx.knowledge.t2c.py from semantic objects."""
        type_names = sorted(set(obj.__class__.__name__ for obj in objects))
        # Add EvidenceRef if any object has evidence_refs
        if any(hasattr(obj, "evidence_refs") and obj.evidence_refs for obj in objects):
            if "EvidenceRef" not in type_names:
                type_names.append("EvidenceRef")
                type_names.sort()

        lines = [
            f"# Auto-generated by t2c {self._version} — DO NOT EDIT",
            f"from t2c.ontology import {', '.join(type_names)}",
            "",
        ]
        for obj in objects:
            lines.append(self._format_object(obj))
            lines.append("")
        return "\n".join(lines) + "\n"

    # -- Formatting helpers (legacy single-file path) ------------------------

    def _format_object(self, obj: BaseModel) -> str:
        """Format a Pydantic object as a constructor call string."""
        type_name = obj.__class__.__name__
        fields = FIELD_ORDER.get(type_name, list(obj.__class__.model_fields.keys()))
        kwargs: list[str] = []
        for field_name in fields:
            value = getattr(obj, field_name, None)
            # Skip None optional fields
            if value is None:
                continue
            # Skip empty defaults
            if isinstance(value, list) and not value and field_name not in ("participants", "evidence_refs"):
                continue
            formatted = self._format_value(value)
            kwargs.append(f"{field_name}={formatted}")

        if not kwargs:
            return f"{type_name}()"

        if len(kwargs) <= 4:
            return f"{type_name}({', '.join(kwargs)})"

        inner = ",\n    ".join(kwargs)
        return f"{type_name}(\n    {inner}\n)"

    def _format_value(self, value: Any) -> str:
        """Format a Python value as a .t2c.py literal."""
        if isinstance(value, str):
            return repr(value)
        if isinstance(value, bool):
            return "True" if value else "False"
        if isinstance(value, int):
            return str(value)
        if isinstance(value, float):
            return str(value)
        if value is None:
            return "None"
        if isinstance(value, BaseModel):
            return self._format_object(value)
        if isinstance(value, list):
            if not value:
                return "[]"
            # Check for nested BaseModel objects (e.g. EvidenceRef)
            if all(isinstance(v, BaseModel) for v in value):
                items = [self._format_object(v) for v in value]
                if len(items) == 1:
                    return f"[{items[0]}]"
                inner = ",\n        ".join(items)
                return f"[\n        {inner}\n    ]"
            items = [self._format_value(v) for v in value]
            return f"[{', '.join(items)}]"
        if isinstance(value, dict):
            if not value:
                return "{}"
            pairs = [f"{repr(k)}: {self._format_value(v)}" for k, v in value.items()]
            return "{" + ", ".join(pairs) + "}"
        # Enum-like with .value
        if hasattr(value, "value"):
            return repr(value.value)
        return repr(value)

    @staticmethod
    def _format_comment(obj: BaseModel) -> str:
        """Generate an inline comment for FTS5 searchability.

        Returns a human-readable summary appended after the assignment line
        so CodeGraph's tree-sitter captures it as part of the node's context,
        making the symbol findable via full-text search on Chinese names.
        """
        type_name = obj.__class__.__name__
        if type_name == "Entity":
            name = getattr(obj, "name", "")
            kind = getattr(obj, "kind", "")
            return f"# {name} ({kind})"
        if type_name == "Event":
            name = getattr(obj, "name", "")
            return f"# {name}"
        if type_name == "Claim":
            subj = getattr(obj, "subject", "")
            pred = getattr(obj, "predicate", "")
            obj_val = getattr(obj, "object", "") or ""
            parts = f"{subj} {pred} {obj_val}".rstrip()
            return f"# {parts}"
        if type_name == "Segment":
            text = getattr(obj, "text_slice", "")
            preview = text[:40]
            suffix = "..." if len(text) > 40 else ""
            return f"# {preview}{suffix}"
        if type_name == "Document":
            return f"# {getattr(obj, 'source_path', '')}"
        if type_name == "Block":
            return f"# block {getattr(obj, 'index', 0)}"
        if type_name == "Relation":
            subj = getattr(obj, "subject", "")
            pred = getattr(obj, "predicate", "")
            obj_val = getattr(obj, "object", "")
            return f"# {subj} {pred} {obj_val}"
        if type_name == "Residual":
            cat = getattr(obj, "category", "")
            reason = getattr(obj, "reason", "")[:40]
            return f"# {cat}: {reason}"
        if type_name == "IgnoreSegment":
            reason = getattr(obj, "reason", "")[:40]
            return f"# {reason}"
        if type_name == "CoverageReport":
            return f"# coverage: {getattr(obj, 'doc_id', '')}"
        return ""

    # -- v6.0 symbol-table-driven generation ---------------------------------

    def generate_text_code_v33(
        self,
        doc: Document,
        blocks: list[Block],
        segments: list[Segment],
        symbols: SymbolTable | None = None,
    ) -> dict[str, str]:
        """Generate the text layer (text.py) with assignment symbols.

        Returns dict with single key 'text.py' mapping to code string.
        Each Segment/Block/Document gets a Python symbol from the shared
        package-wide table (computed internally when not supplied).
        """
        table = symbols or compute_symbol_table(doc=doc, blocks=blocks, segments=segments)

        lines = [
            f"# Auto-generated by t2c {self._version} — DO NOT EDIT",
            "from t2c.ontology import Document, Block, Segment",
            "",
        ]

        for obj in [doc, *blocks, *segments]:
            sym = table.symbol_for(getattr(obj, "id", "")) or f"obj_{id(obj):x}"
            formatted, _ = self._format_object_v33(obj, table, ".text")
            comment = self._format_comment(obj)
            if comment:
                lines.append(f"{sym} = {formatted}  {comment}")
            else:
                lines.append(f"{sym} = {formatted}")
            lines.append("")

        return {"text.py": "\n".join(lines) + "\n"}

    def _generate_type_file_v33(
        self,
        module: str,
        objects: list[BaseModel],
        type_names: list[str],
        table: SymbolTable,
    ) -> str:
        """Generate one semantic type file with bare-Name refs + live imports.

        module: the file's own module (e.g. ".entities") — used to distinguish
        foreign symbols (need import) from same-file symbols (no import).
        """
        lines = [
            f"# Auto-generated by t2c {self._version} — DO NOT EDIT",
            f"from t2c.ontology import {', '.join(type_names)}",
        ]

        foreign: set[str] = set()
        body: list[str] = []
        for obj in objects:
            obj_id = getattr(obj, "id", "")
            sym = table.symbol_for(obj_id)
            if sym is None:
                raise CodegenSymbolError(
                    f"{obj.__class__.__name__} {obj_id!r} has no symbol in the table"
                )
            formatted, used = self._format_object_v33(obj, table, module)
            foreign |= used
            comment = self._format_comment(obj)
            if comment:
                body.append(f"{sym} = {formatted}  {comment}")
            else:
                body.append(f"{sym} = {formatted}")
            body.append("")

        # Live imports only: every imported symbol is used in this file (C4).
        by_module: dict[str, list[str]] = {}
        for sym in sorted(foreign):
            mod = table.module_of(sym)
            if mod is None or mod == module:
                continue
            by_module.setdefault(mod, []).append(sym)
        for mod in sorted(by_module):
            lines.append(f"from {mod} import {', '.join(by_module[mod])}")

        if by_module:
            lines.append("")
        lines.extend(body)
        return "\n".join(lines).rstrip() + "\n"

    def _format_object_v33(
        self,
        obj: BaseModel,
        table: SymbolTable,
        own_module: str,
    ) -> tuple[str, set[str]]:
        """Format an object as a constructor call; emit bare Names for refs.

        Returns (formatted_code, used_foreign_symbols) — the latter drives
        import generation. ``_symbol`` fields are derived from their FK fields
        via the symbol table; a strict field whose FK is missing from the
        table is a compile-time error (this is the codegen half of the
        dangling-reference gate).
        """
        type_name = obj.__class__.__name__
        fields = FIELD_ORDER.get(type_name, list(obj.__class__.model_fields.keys()))
        kwargs: list[str] = []
        foreign: set[str] = set()

        for field_name in fields:
            if field_name in _SYMBOL_DERIVATION:
                rendered, used = self._derive_symbol_kwarg(
                    obj, type_name, field_name, table, own_module
                )
                if rendered is not None:
                    kwargs.append(rendered)
                    foreign |= used
                continue

            if field_name == "symbol":
                # Self-declaration: only for models that carry the field.
                if "symbol" in obj.__class__.model_fields:
                    sym = table.symbol_for(getattr(obj, "id", ""))
                    if sym:
                        kwargs.append(f"symbol={sym!r}")
                continue

            value = getattr(obj, field_name, None)
            if value is None:
                continue
            if isinstance(value, list) and not value and field_name not in ("participants", "evidence_refs"):
                continue
            formatted, used = self._format_value_v33(value, table, own_module)
            foreign |= used
            kwargs.append(f"{field_name}={formatted}")

        if not kwargs:
            return f"{type_name}()", foreign

        if len(kwargs) <= 4:
            return f"{type_name}({', '.join(kwargs)})", foreign

        inner = ",\n    ".join(kwargs)
        return f"{type_name}(\n    {inner}\n)", foreign

    def _derive_symbol_kwarg(
        self,
        obj: BaseModel,
        type_name: str,
        field_name: str,
        table: SymbolTable,
        own_module: str,
    ) -> tuple[str | None, set[str]]:
        """Resolve one _symbol field from its FK field via the symbol table."""
        fk_field, is_list = _SYMBOL_DERIVATION[field_name]
        foreign: set[str] = set()

        if is_list:
            fk_values = getattr(obj, fk_field, []) or []
            names: list[str] = []
            for fk_value in fk_values:
                names.append(self._require_symbol(obj, type_name, field_name, fk_value, table))
            for name in names:
                if table.module_of(name) != own_module:
                    foreign.add(name)
            if not names:
                return None, foreign
            return f"{field_name}=[{', '.join(names)}]", foreign

        fk_value = getattr(obj, fk_field, None)
        if not fk_value:
            return None, foreign
        sym = table.symbol_for(fk_value)
        if sym is None:
            if field_name not in _STRICT_SYMBOL_FIELDS and not _looks_like_entity_id(fk_value):
                # e.g. Claim.object is a literal string — no symbol channel.
                return None, foreign
            raise CodegenSymbolError(
                f"{type_name} {getattr(obj, 'id', '?')}: {fk_field}={fk_value!r} "
                f"has no symbol in the table (dangling reference at codegen)"
            )
        if table.module_of(sym) != own_module:
            foreign.add(sym)
        return f"{field_name}={sym}", foreign

    def _require_symbol(
        self,
        obj: BaseModel,
        type_name: str,
        field_name: str,
        fk_value: str,
        table: SymbolTable,
    ) -> str:
        sym = table.symbol_for(fk_value)
        if sym is None:
            raise CodegenSymbolError(
                f"{type_name} {getattr(obj, 'id', '?')}: {field_name} value "
                f"{fk_value!r} has no symbol in the table (dangling reference at codegen)"
            )
        return sym

    def _format_value_v33(
        self,
        value: Any,
        table: SymbolTable,
        own_module: str,
    ) -> tuple[str, set[str]]:
        """Format a value; nested BaseModels (EvidenceRef) recurse with refs."""
        if isinstance(value, str):
            return repr(value), set()
        if isinstance(value, bool):
            return ("True" if value else "False"), set()
        if isinstance(value, int):
            return str(value), set()
        if isinstance(value, float):
            return str(value), set()
        if value is None:
            return "None", set()
        if isinstance(value, BaseModel):
            return self._format_object_v33(value, table, own_module)
        if isinstance(value, list):
            if not value:
                return "[]", set()
            if all(isinstance(v, BaseModel) for v in value):
                foreign: set[str] = set()
                items = []
                for v in value:
                    rendered, used = self._format_object_v33(v, table, own_module)
                    foreign |= used
                    items.append(rendered)
                if len(items) == 1:
                    return f"[{items[0]}]", foreign
                inner = ",\n        ".join(items)
                return f"[\n        {inner}\n    ]", foreign
            foreign = set()
            items = []
            for v in value:
                rendered, used = self._format_value_v33(v, table, own_module)
                foreign |= used
                items.append(rendered)
            return f"[{', '.join(items)}]", foreign
        if isinstance(value, dict):
            if not value:
                return "{}", set()
            foreign = set()
            pairs = []
            for k, v in value.items():
                rendered, used = self._format_value_v33(v, table, own_module)
                foreign |= used
                pairs.append(f"{repr(k)}: {rendered}")
            return "{" + ", ".join(pairs) + "}", foreign
        if hasattr(value, "value"):
            return repr(value.value), set()
        return repr(value), set()

    def generate_init_py(self, symbols: SymbolTable | dict[str, str]) -> str:
        """Generate __init__.py as the package's public symbol surface (C7).

        Re-exports every assigned symbol with explicit imports (DAG order)
        plus __all__, so `from <book> import ent_zh_xxx` resolves and
        codegraph tools see a package-level definition edge.
        """
        if isinstance(symbols, SymbolTable):
            by_module: dict[str, list[str]] = {}
            for sym, mod in symbols.symbol_to_module.items():
                by_module.setdefault(mod, []).append(sym)
        else:
            # Backward-compat: legacy callers passed {id: symbol} or
            # {symbol: module}; in that case we cannot re-export reliably.
            lines = [
                f"# Auto-generated by t2c {self._version} — DO NOT EDIT",
                f"# {len(symbols)} symbols across modules.",
                "",
            ]
            return "\n".join(lines)

        lines = [f"# Auto-generated by t2c {self._version} — DO NOT EDIT"]
        all_names: list[str] = []
        for mod in _MODULE_DAG_ORDER:
            syms = sorted(by_module.get(mod, []))
            if not syms:
                continue
            all_names.extend(syms)
            if len(syms) <= 3:
                lines.append(f"from {mod} import {', '.join(syms)}")
            else:
                inner = ",\n    ".join(syms)
                lines.append(f"from {mod} import (\n    {inner}\n)")
        lines.append("")
        lines.append("__all__ = [")
        for name in all_names:
            lines.append(f"    {name!r},")
        lines.append("]")
        return "\n".join(lines) + "\n"

    def generate_coverage_code(
        self,
        report: CoverageReport,
    ) -> str:
        """Generate coverage.py from a CoverageReport Pydantic model."""
        formatted = self._format_object(report)
        comment = self._format_comment(report)
        assignment = f"coverage_report = {formatted}"
        if comment:
            assignment = f"{assignment}  {comment}"
        lines = [
            f"# Auto-generated by t2c {self._version} — DO NOT EDIT",
            "from t2c.ontology import CoverageReport",
            "",
            assignment,
            "",
        ]
        return "\n".join(lines)

    def generate_multi_file_compilation(
        self,
        doc: Document,
        blocks: list[Block],
        segments: list[Segment],
        entities: list[Entity] | None = None,
        events: list[Event] | None = None,
        claims: list[Any] | None = None,
        residuals: list[Residual] | None = None,
        ignores: list[IgnoreSegment] | None = None,
        relations: list[Relation] | None = None,
        coverage_report: CoverageReport | None = None,
    ) -> dict[str, str]:
        """One-stop multi-file Knowledge Code generation.

        Returns dict mapping filename → code string:
          - text.py / entities.py / events.py / claims.py
          - residuals.py / derived.py / coverage.py / __init__.py

        All cross-file references are bare Names backed by real imports —
        codegraph navigable, import-validated.
        """
        entities = list(entities or [])
        events = list(events or [])
        claims = list(claims or [])
        residuals = list(residuals or [])
        ignores = list(ignores or [])
        relations = list(relations or [])

        table = compute_symbol_table(
            doc=doc,
            blocks=blocks,
            segments=segments,
            entities=entities,
            events=events,
            claims=claims,
            relations=relations,
            residuals=residuals,
            ignores=ignores,
        )

        files: dict[str, str] = {}

        files["text.py"] = self.generate_text_code_v33(doc, blocks, segments, symbols=table)["text.py"]

        files["entities.py"] = self._generate_type_file_v33(
            ".entities", entities, ["Entity", "EvidenceRef"], table,
        )
        files["events.py"] = self._generate_type_file_v33(
            ".events", events, ["Event", "EvidenceRef"], table,
        )
        files["claims.py"] = self._generate_type_file_v33(
            ".claims", claims, ["Claim", "EvidenceRef"], table,
        )

        res_ign = sorted([*residuals, *ignores], key=lambda o: getattr(o, "id", ""))
        res_type_names = ["Residual", "EvidenceRef"] + (["IgnoreSegment"] if ignores else [])
        files["residuals.py"] = self._generate_type_file_v33(
            ".residuals", res_ign, res_type_names, table,
        )

        files["derived.py"] = self._generate_type_file_v33(
            ".derived", relations, ["Relation", "EvidenceRef"], table,
        )

        if coverage_report is None:
            coverage_report = self._derive_static_coverage_report(
                doc=doc,
                segments=list(segments),
                semantic_objects=[*entities, *events, *claims, *relations],
                residuals=residuals,
                ignores=ignores,
            )
        files["coverage.py"] = self.generate_coverage_code(coverage_report)

        files["__init__.py"] = self.generate_init_py(table)

        return files

    @staticmethod
    def _derive_static_coverage_report(
        *,
        doc: Document,
        segments: list[Segment],
        semantic_objects: list[BaseModel],
        residuals: list[Residual],
        ignores: list[IgnoreSegment],
    ) -> CoverageReport:
        """Derive a conservative static CoverageReport when caller omitted one."""
        referenced: set[str] = set()
        for obj in semantic_objects:
            for sid in getattr(obj, "source_segment_ids", []) or []:
                referenced.add(sid)
            for eref in getattr(obj, "evidence_refs", []) or []:
                sid = getattr(eref, "segment_id", None)
                if sid:
                    referenced.add(sid)

        residual_by_segment: dict[str, list[Residual]] = {}
        for residual in residuals:
            residual_by_segment.setdefault(residual.segment_id, []).append(residual)
        ignored = {ignore.segment_id for ignore in ignores}

        status_counts = {"covered": 0, "partial": 0, "raw_only": 0, "ignored": 0, "uncovered": 0}
        requires_raw_fallback: list[str] = []

        for segment in segments:
            sid = segment.id
            has_semantic = sid in referenced
            has_residual = sid in residual_by_segment
            if sid in ignored:
                status = "ignored"
            elif has_semantic and not has_residual:
                status = "covered"
            elif has_semantic and has_residual:
                status = "partial"
            elif not has_semantic and has_residual:
                status = "raw_only"
            else:
                status = "uncovered"
            status_counts[status] += 1

            if status in ("partial", "raw_only", "uncovered"):
                requires_raw_fallback.append(sid)
                continue
            if any(res.importance == "high" for res in residual_by_segment.get(sid, [])):
                requires_raw_fallback.append(sid)

        return CoverageReport(
            id=f"{doc.id}_coverage",
            doc_id=doc.id,
            total_segments=len(segments),
            status_counts=status_counts,
            requires_raw_fallback=requires_raw_fallback,
            generated_at=doc.created_at,
        )
