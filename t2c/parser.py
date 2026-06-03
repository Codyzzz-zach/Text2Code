"""T2C Parser — parse .t2c.py files with strict AST grammar enforcement."""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from t2c.ontology import ONTOLOGY_CLASSES


ALLOWED_MODULES: frozenset[str] = frozenset({"t2c.ontology"})
ALLOWED_CONSTRUCTORS: frozenset[str] = frozenset(ONTOLOGY_CLASSES.keys())


@dataclass
class T2CParseError(Exception):
    """Error raised when .t2c.py violates grammar rules."""
    line: int
    message: str

    def __str__(self) -> str:
        return f"Line {self.line}: {self.message}"


class T2CParser:
    """Parse .t2c.py into a list of {type, data} dicts.

    Only allows:
    - import/from imports of allowed modules
    - Top-level constructor calls with keyword args
    - Values: str, int, float, bool, None, list, dict
    - Nested constructor calls (e.g. EvidenceRef inside evidence_refs)
    - Comments
    """

    def parse_file(self, path: Path) -> list[dict]:
        """Parse a .t2c.py file, return list of {type: str, data: dict}."""
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
        """Walk AST, enforce strict grammar rules."""
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                self._validate_import(node)
            elif isinstance(node, ast.Expr):
                self._validate_expr(node.value)
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
            if node.module not in ALLOWED_MODULES:
                raise T2CParseError(
                    line=node.lineno,
                    message=f"Import from disallowed module: {node.module}",
                )

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
        """Recursively validate that a value node is an allowed literal or constructor."""
        if isinstance(node, ast.Constant):
            # str, int, float, bool, None — all OK
            if isinstance(node.value, (str, int, float, bool, type(None))):
                return
            raise T2CParseError(
                line=node.lineno,
                message=f"Unsupported constant type: {type(node.value).__name__}",
            )
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
            # Nested constructor call (e.g. EvidenceRef)
            self._validate_call(node)
            return
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            # Negative numbers: -1, +1
            if isinstance(node.operand, ast.Constant) and isinstance(node.operand.value, (int, float)):
                return
        raise T2CParseError(
            line=getattr(node, "lineno", 0),
            message=f"Disallowed value expression: {type(node).__name__}",
        )

    # -- Object extraction -----------------------------------------------

    def _extract_objects(self, tree: ast.Module) -> list[dict]:
        """Extract {type, data} dicts from validated AST."""
        objects: list[dict] = []
        for node in tree.body:
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                obj = self._extract_call(node.value)
                objects.append(obj)
        return objects

    def _extract_call(self, node: ast.Call) -> dict:
        """Extract type name and keyword data from a constructor call."""
        type_name = node.func.id  # type: ignore[union-attr]
        data: dict = {}
        for kw in node.keywords:
            assert kw.arg is not None  # validated above
            data[kw.arg] = self._extract_value(kw.value)
        return {"type": type_name, "data": data}

    def _extract_value(self, node: ast.expr) -> object:
        """Extract a Python value from an AST node."""
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.List):
            return [self._extract_value(elt) for elt in node.elts]
        if isinstance(node, ast.Dict):
            keys = [self._extract_value(k) if k is not None else None for k in node.keys]
            values = [self._extract_value(v) for v in node.values]
            return dict(zip(keys, values))
        if isinstance(node, ast.Call):
            return self._extract_call(node)
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