"""v3.3 Symbol Analyzer — count definitions and references in generated code.

Uses Python stdlib ast to verify generated code is analyzable by standard
code intelligence tools (CodeGraph, Pyright, tree-sitter, etc.).
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field


@dataclass
class SymbolStats:
    """Per-symbol statistics from a generated .t2c.py file."""
    symbol_name: str
    constructor_type: str
    definition_line: int
    reference_count: int = 0
    referenced_by: list[str] = field(default_factory=list)


@dataclass
class FileAnalysis:
    """Analysis result for a single generated file."""
    filename: str
    total_definitions: int
    total_references: int
    symbols: list[SymbolStats]
    imported_symbols: list[str] = field(default_factory=list)
    cross_file_ref_count: int = 0
    parse_errors: list[str] = field(default_factory=list)


def analyze_file(source: str, filename: str = "<code>") -> FileAnalysis:
    """Analyze a generated v3.3 file for symbol definitions and references.

    Returns FileAnalysis with per-symbol statistics suitable for
    codegraph integration verification.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return FileAnalysis(
            filename=filename,
            total_definitions=0,
            total_references=0,
            symbols=[],
            parse_errors=[f"SyntaxError at line {e.lineno}: {e.msg}"],
        )

    # Build symbol map: name → (type, line)
    definitions: dict[str, tuple[str, int]] = {}
    imported_names: set[str] = set()  # from .text import seg_0001
    # Track references: (ref_name, context_symbol)
    references: list[tuple[str, str | None]] = []

    class _Visitor(ast.NodeVisitor):
        def __init__(self):
            self.current_symbol: str | None = None

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            for alias in node.names:
                name = alias.asname or alias.name
                imported_names.add(name)
            self.generic_visit(node)

        def visit_Assign(self, node: ast.Assign) -> None:
            if isinstance(node.targets[0], ast.Name) and isinstance(node.value, ast.Call):
                sym = node.targets[0].id
                func = node.value.func
                if isinstance(func, ast.Name):
                    definitions[sym] = (func.id, node.lineno)
                    self.current_symbol = sym
                    # Visit the call's keyword args to find references
                    for kw in node.value.keywords:
                        self.visit(kw)
                    self.current_symbol = None
            else:
                self.generic_visit(node)

        def visit_Name(self, node: ast.Name) -> None:
            # A Name node used as a value (Load context) inside an assignment
            # → reference to another symbol (defined here or imported)
            if isinstance(node.ctx, ast.Load) and self.current_symbol:
                if node.id in definitions or node.id in imported_names:
                    references.append((node.id, self.current_symbol))
            self.generic_visit(node)

    _Visitor().visit(tree)

    # Build per-symbol stats
    symbols: list[SymbolStats] = []
    for sym_name, (ctor_type, line) in definitions.items():
        ref_count = sum(1 for rn, _ in references if rn == sym_name)
        refs_by = [ctx for rn, ctx in references if rn == sym_name]
        symbols.append(SymbolStats(
            symbol_name=sym_name,
            constructor_type=ctor_type,
            definition_line=line,
            reference_count=ref_count,
            referenced_by=list(set(refs_by)),
        ))

    # Cross-file references: imported symbols that appear as reference targets
    all_ref_targets = {rn for rn, _ in references}
    cross_refs = len(all_ref_targets & imported_names)

    return FileAnalysis(
        filename=filename,
        total_definitions=len(definitions),
        total_references=len(references),
        symbols=symbols,
        imported_symbols=list(imported_names),
        cross_file_ref_count=cross_refs,
    )


def analyze_multi_file(files: dict[str, str]) -> list[FileAnalysis]:
    """Analyze a set of generated v3.3 files."""
    results: list[FileAnalysis] = []
    for fname, source in files.items():
        results.append(analyze_file(source, fname))
    return results


def cross_file_reference_count(analyses: list[FileAnalysis]) -> int:
    """Count cross-file references across all analyzed files."""
    return sum(a.cross_file_ref_count for a in analyses)
