"""Tests for scripts/quality_check.py — current Knowledge Code quality gate."""
import json
import subprocess
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent
QUALITY_SCRIPT = PROJECT_ROOT / "scripts" / "quality_check.py"
RAWTXT_PATH = PROJECT_ROOT / "data" / "rawtxt" / "红楼梦.txt"


def _has_rawtxt():
    return RAWTXT_PATH.exists()


def _extract_json(stdout: str) -> dict | None:
    """Extract JSON object from mixed text+JSON output.

    The JSON block starts at a line beginning with '{' after the human-readable text.
    """
    # Find the last occurrence of a line starting with '{'
    lines = stdout.split('\n')
    for i in range(len(lines) - 1, -1, -1):
        stripped = lines[i].strip()
        if stripped == '{':
            # This is the opening brace — join from here
            json_text = '\n'.join(lines[i:])
            try:
                return json.loads(json_text)
            except json.JSONDecodeError:
                pass
    return None


@pytest.mark.skipif(not _has_rawtxt(), reason="rawtxt/红楼梦.txt not available")
class TestQualityCheckJson:
    """quality_check --json returns machine-readable metrics."""

    def test_json_output_is_valid(self):
        """--json produces valid JSON."""
        proc = subprocess.run(
            [sys.executable, str(QUALITY_SCRIPT), "--json"],
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        data = _extract_json(proc.stdout)
        assert data is not None, f"No JSON found in output: {proc.stdout[:200]}"
        assert isinstance(data, dict)
        for key in ["grounding_rate", "reference_issue_count", "entity_conflict_count",
                    "coverage_rate", "total_issue_count"]:
            assert key in data, f"Missing metric: {key}"

    def test_json_metrics_are_numeric(self):
        """Metrics should be numeric values."""
        proc = subprocess.run(
            [sys.executable, str(QUALITY_SCRIPT), "--json"],
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        data = _extract_json(proc.stdout)
        assert data is not None
        assert isinstance(data["grounding_rate"], (int, float))
        assert isinstance(data["reference_issue_count"], int)
        assert isinstance(data["entity_conflict_count"], int)
        assert isinstance(data["coverage_rate"], (int, float))
        assert isinstance(data["total_issue_count"], int)

    def test_fail_under_high_threshold(self):
        """--fail-under 0.99 should fail (grounding rate unlikely to be 99%)."""
        proc = subprocess.run(
            [sys.executable, str(QUALITY_SCRIPT), "--json", "--fail-under", "0.99"],
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        data = _extract_json(proc.stdout)
        if data and data["grounding_rate"] < 0.99:
            assert proc.returncode != 0

    def test_fail_under_low_threshold(self):
        """--fail-under 0.0 should always pass."""
        proc = subprocess.run(
            [sys.executable, str(QUALITY_SCRIPT), "--json", "--fail-under", "0.0"],
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        assert proc.returncode == 0
