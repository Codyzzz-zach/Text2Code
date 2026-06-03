"""Shared test fixtures."""
from pathlib import Path

import pytest

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"
CORPUS_DIR = EXAMPLES_DIR / "corpus"
CASE_001 = CORPUS_DIR / "case_001.txt"


@pytest.fixture
def case_001_text() -> str:
    return CASE_001.read_text(encoding="utf-8")


@pytest.fixture
def case_001_path() -> Path:
    return CASE_001