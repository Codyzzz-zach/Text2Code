"""T2C Parser — parse .t2c.py files with strict AST grammar enforcement.

v3.3: supports assignment-based symbol definitions and symbol references,
making generated code codegraph-native.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from t2c.ontology import ONTOLOGY_CLASSES


ALLOWED_MODULES: frozenset[str] = frozenset({"t2c.ontology"})
ALLOWED_CONSTRUCTORS: frozenset[str] = frozenset(ONTOLOGY_CLASSES.keys())

# Symbol ref marker used internally to distinguish symbol refs from string values.
_SYM_MARKER = "__symbol__"


@dataclass
class T2CParseError(Exception):
    """Error raised when .t2c.py violates grammar rules."""
    line: int
    message: str

    def __str__(self) -> str:
        return f"Line {self.line}: {self.message}"


class T2CParser:
    """Parse .t2c.py into a list of {type, data, symbol?, __symbol_refs__?} dicts.

    v3.3 extensions:
    - Top-level assignment: symbol = Constructor(...)
    - Symbol references: ast.Name values that match previously defined symbols
    - Relative imports: from .<module> import <symbol> (allowed for cross-file refs)
    - External symbol index: resolves imported symbols to IDs
    - Backward compatible: old top-level Constructor(...) calls still parse

    Only allows:
    - import/from imports of allowed modules (t2c.ontology + relative .*)
    - Top-level constructor calls or assignments to constructors
    - Values: str, int, float, bool, None, list, dict, symbol ref (ast.Name)
    - Nested constructor calls (e.g. EvidenceRef inside evidence_refs)
    - Comments
    """

    def __init__(self, external_symbols: dict[str, dict[str, str]] | None = None) -> None:
        """external_symbols: {symbol_name: {"type": type_name, "id": object_id}}.

        Provides ID resolution for symbols imported from other files.
        """
        self._external_symbols: dict[str, dict[str, str]] = external_symbols or {}

    def parse_file(self, path: Path) -> list[dict]:
        """Parse a .t2c.py file, return list of {type: str, symbol?: str, data: dict}."""
        source = path.read_text(encoding="utf-8")
        return self.parse_string(source)

    def parse_string(self, source: str) -> list[dict]:
        """Parse .t2c.py source string."""
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            raise T2CParseError(line=e.lineno or 0, message=f"Python syntax error: {e.msg}") from e

        self._validate_ast(tree)
        return self._extract_objects(tree)

    # -- AST grammar validation ------------------------------------------

    def _validate_ast(self, tree: ast.Module) -> None:
        """Walk AST, enforce strict grammar rules.

        v3.3: also allows ast.Assign (symbol = Constructor(...)).
        """
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                self._validate_import(node)
            elif isinstance(node, ast.Expr):
                self._validate_expr(node.value)
            elif isinstance(node, ast.Assign):
                self._validate_assignment(node)
            else:
                raise T2CParseError(
                    line=getattr(node, "lineno", 0),
                    message=f"Disallowed statement: {type(node).__name__}",
                )

    def _validate_import(self, node: ast.Import | ast.ImportFrom) -> None:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name not in ALLOWED_MODULES:
                    raise T2CParseError(
                        line=node.lineno,
                        message=f"Import from disallowed module: {alias.name}",
                    )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            # Allow t2c.ontology and relative imports (level > 0 means from .xxx)
            if module in ALLOWED_MODULES or node.level > 0:
                return
            raise T2CParseError(
                line=node.lineno,
                message=f"Import from disallowed module: {module}",
            )

    def _validate_assignment(self, node: ast.Assign) -> None:
        """Validate a top-level assignment: symbol = Constructor(...).

        - target must be a single ast.Name
        - value must be an allowed constructor call
        - no multiple targets (a = b = ...)
        - no augmented assignment
        """
        if len(node.targets) != 1:
            raise T2CParseError(
                line=node.lineno,
                message="Assignment must have exactly one target",
            )
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            raise T2CParseError(
                line=node.lineno,
                message=f"Assignment target must be a simple name, got {type(target).__name__}",
            )
        if not isinstance(node.value, ast.Call):
            raise T2CParseError(
                line=node.lineno,
                message="Assignment value must be a constructor call",
            )
        self._validate_call(node.value)

    def _validate_expr(self, node: ast.expr) -> None:
        """Validate a top-level expression — must be an allowed constructor call."""
        if not isinstance(node, ast.Call):
            raise T2CParseError(
                line=getattr(node, "lineno", 0),
                message=f"Top-level expression must be a constructor call, got {type(node).__name__}",
            )
        self._validate_call(node)

    def _validate_call(self, node: ast.Call) -> None:
        """Validate a constructor call."""
        func = node.func
        if isinstance(func, ast.Name):
            if func.id not in ALLOWED_CONSTRUCTORS:
                raise T2CParseError(
                    line=node.lineno,
                    message=f"Unknown constructor: {func.id}",
                )
        else:
            raise T2CParseError(
                line=node.lineno,
                message=f"Constructor must be a simple name, got {type(func).__name__}",
            )

        if node.args:
            raise T2CParseError(
                line=node.lineno,
                message="Positional arguments are not allowed — use keyword args only",
            )

        for kw in node.keywords:
            self._validate_keyword(kw)

    def _validate_keyword(self, kw: ast.keyword) -> None:
        """Validate a keyword argument value."""
        if kw.arg is None:
            raise T2CParseError(
                line=kw.value.lineno if hasattr(kw.value, "lineno") else 0,
                message="**kwargs syntax is not allowed",
            )
        self._validate_value(kw.value)

    def _validate_value(self, node: ast.expr) -> None:
        """Recursively validate that a value node is an allowed literal, constructor, or symbol ref."""
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (str, int, float, bool, type(None))):
                return
            raise T2CParseError(
                line=node.lineno,
                message=f"Unsupported constant type: {type(node.value).__name__}",
            )
        if isinstance(node, ast.Name):
            # Symbol reference — validated during extraction (must be defined)
            return
        if isinstance(node, ast.List):
            for elt in node.elts:
                self._validate_value(elt)
            return
        if isinstance(node, ast.Dict):
            for key in node.keys:
                if key is not None:
                    self._validate_value(key)
            for val in node.values:
                self._validate_value(val)
            return
        if isinstance(node, ast.Call):
            self._validate_call(node)
            return
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            if isinstance(node.operand, ast.Constant) and isinstance(node.operand.value, (int, float)):
                return
        raise T2CParseError(
            line=getattr(node, "lineno", 0),
            message=f"Disallowed value expression: {type(node).__name__}",
        )

    # -- Object extraction -----------------------------------------------

    def _extract_objects(self, tree: ast.Module) -> list[dict]:
        """Extract {type, symbol?, data, __symbol_refs__?} dicts from validated AST.

        v3.3: handles both old top-level calls and new assignment format.
        Tracks defined symbols, resolves symbol refs to IDs, and records
        symbol ref paths for codegen.

        Import statements register external symbols before extraction begins.
        """
        objects: list[dict] = []
        # Track defined symbols: symbol_name → {"type": type_name, "id": object_id}
        self._defined_symbols: dict[str, dict[str, str]] = {}

        # Phase 1: register imported symbols from external index
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.level > 0:
                for alias in node.names:
                    sym_name = alias.asname or alias.name
                    if sym_name in self._external_symbols:
                        self._defined_symbols[sym_name] = self._external_symbols[sym_name]
                    else:
                        # External symbol without index entry — register as "external"
                        self._defined_symbols[sym_name] = {"type": "external", "id": f"ext:{sym_name}"}

        # Phase 2: extract assignments and constructor calls
        for node in tree.body:
            if isinstance(node, ast.Assign):
                obj = self._extract_assignment(node)
                objects.append(obj)
            elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                obj = self._extract_call(node.value)
                objects.append(obj)

        return objects

    def _extract_assignment(self, node: ast.Assign) -> dict:
        """Extract from symbol = Constructor(...).

        Resolves symbol refs to IDs so the canonical data is clean.
        """
        target = node.targets[0]
        symbol_name = target.id  # type: ignore[union-attr]

        # Check for duplicate symbol
        if symbol_name in self._defined_symbols:
            raise T2CParseError(
                line=node.lineno,
                message=f"Symbol '{symbol_name}' is already defined",
            )

        call = node.value
        type_name = call.func.id  # type: ignore[union-attr]

        # Extract data with symbol ref resolution
        data: dict = {}
        symbol_refs: dict[str, str] = {}
        for kw in call.keywords:
            assert kw.arg is not None
            data[kw.arg] = self._extract_value(kw.value, symbol_refs, f"{kw.arg}")

        # Register symbol AFTER extraction (so self-references are possible)
        obj_id = data.get("id", symbol_name)
        self._defined_symbols[symbol_name] = {"type": type_name, "id": str(obj_id)}

        result: dict = {"type": type_name, "symbol": symbol_name, "data": data}
        if symbol_refs:
            result["__symbol_refs__"] = symbol_refs
        return result

    def _extract_call(self, node: ast.Call, symbol_refs: dict[str, str] | None = None, prefix: str = "") -> dict:
        """Extract type name and keyword data from a constructor call.

        When called from _extract_assignment, symbol_refs tracks all symbol
        references found in this call tree.
        """
        if symbol_refs is None:
            symbol_refs = {}
        type_name = node.func.id  # type: ignore[union-attr]
        data: dict = {}
        for kw in node.keywords:
            assert kw.arg is not None
            data[kw.arg] = self._extract_value(kw.value, symbol_refs, f"{prefix}.{kw.arg}" if prefix else kw.arg)
        result: dict = {"type": type_name, "data": data}
        return result

    def _extract_value(self, node: ast.expr, symbol_refs: dict[str, str], path: str) -> Any:
        """Extract a Python value from an AST node.

        v3.3: ast.Name values are treated as symbol references.
        When a symbol ref is encountered, the parser resolves it to the
        referenced object's ID and records the path → symbol_name mapping
        in symbol_refs for codegen.
        """
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            # Symbol reference — resolve to ID
            symbol_name = node.id
            if symbol_name not in self._defined_symbols:
                raise T2CParseError(
                    line=node.lineno,
                    message=f"Undefined symbol reference: '{symbol_name}'",
                )
            symbol_refs[path] = symbol_name
            # Return the resolved ID as the canonical value
            return self._defined_symbols[symbol_name]["id"]
        if isinstance(node, ast.List):
            result: list = []
            for i, elt in enumerate(node.elts):
                elt_path = f"{path}[{i}]"
                result.append(self._extract_value(elt, symbol_refs, elt_path))
            return result
        if isinstance(node, ast.Dict):
            keys = [self._extract_value(k, symbol_refs, f"{path}.<key>") if k is not None else None for k in node.keys]
            values = [self._extract_value(v, symbol_refs, f"{path}.<value>") for v in node.values]
            return dict(zip(keys, values))
        if isinstance(node, ast.Call):
            # Nested constructor call; extract with nested path tracking
            nested_data: dict = {}
            type_name = node.func.id  # type: ignore[union-attr]
            for kw in node.keywords:
                assert kw.arg is not None
                kw_path = f"{path}.{kw.arg}" if path else kw.arg
                nested_data[kw.arg] = self._extract_value(kw.value, symbol_refs, kw_path)
            return {"type": type_name, "data": nested_data}
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            if isinstance(node.operand, ast.Constant) and isinstance(node.operand.value, (int, float)):
                return -node.operand.value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.UAdd):
            if isinstance(node.operand, ast.Constant) and isinstance(node.operand.value, (int, float)):
                return +node.operand.value
        raise T2CParseError(
            line=getattr(node, "lineno", 0),
            message=f"Cannot extract value from: {type(node).__name__}",
        )
