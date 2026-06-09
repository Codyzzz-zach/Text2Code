"""Knowledge Code writer — multi-file Knowledge Code compilation target.

This module is the end-to-end entry point for "raw text → importable Python files on disk".

Public API:
    compile_to_knowledge_code(
        doc, blocks, segments,
        entities=[], events=[], claims=[], residuals=[], ignores=[], relations=[],
        coverage_report=None,
        output_dir=...,
    )
    → writes <output_dir>/{__init__.py, text.py, entities.py, ...}
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from t2c.codegen import CodeGenerator


def compile_to_knowledge_code(
    *,
    doc: Any,
    blocks: list[Any],
    segments: list[Any],
    entities: list[Any] | None = None,
    events: list[Any] | None = None,
    claims: list[Any] | None = None,
    residuals: list[Any] | None = None,
    ignores: list[Any] | None = None,
    relations: list[Any] | None = None,
    coverage_report: Any | None = None,
    output_dir: str | Path,
    version: str | None = None,
) -> dict[str, Path]:
    """End-to-end: ontology models → a Knowledge Code package on disk.

    Returns: {filename: absolute_path}
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    gen = CodeGenerator(version=version)
    files = gen.generate_multi_file_compilation(
        doc=doc,
        blocks=blocks,
        segments=segments,
        entities=entities or [],
        events=events or [],
        claims=claims or [],
        residuals=residuals or [],
        ignores=ignores or [],
        relations=relations or [],
        coverage_report=coverage_report,
    )

    written: dict[str, Path] = {}
    for filename, code in files.items():
        path = output_dir / filename
        path.write_text(code, encoding="utf-8")
        written[filename] = path
    return written


__all__ = ["compile_to_knowledge_code"]
