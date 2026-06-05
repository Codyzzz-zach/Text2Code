#!/usr/bin/env python3
"""Run standardized T2C test profiles and emit comparable metrics."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


PROFILES: dict[str, list[str]] = {
    "smoke": [
        "tests/test_ontology.py",
        "tests/test_parser.py",
        "tests/test_codegen.py",
        "tests/test_claim_safety.py",
    ],
    "validator": [
        "tests/test_ontology.py",
        "tests/test_parser.py",
        "tests/test_validator.py",
        "tests/test_validator_v3_3.py",
        "tests/test_claim_safety.py",
    ],
    "textmap": [
        "tests/test_corpus.py",
        "tests/test_segmenter.py",
        "tests/test_codegen.py",
        "tests/test_parser.py",
    ],
    "graph": [
        "tests/test_object_store.py",
        "tests/test_coverage.py",
        "tests/test_graph.py",
        "tests/test_claim_safety.py",
    ],
    "core": [
        "tests/test_claim_safety.py",
        "tests/test_codegen.py",
        "tests/test_corpus.py",
        "tests/test_coverage.py",
        "tests/test_graph.py",
        "tests/test_object_store.py",
        "tests/test_ontology.py",
        "tests/test_parser.py",
        "tests/test_pipeline.py",
        "tests/test_segmenter.py",
        "tests/test_validator.py",
        "tests/test_validator_v3_3.py",
    ],
    "regression": [
        "tests/test_claim_safety.py",
        "tests/test_codegen.py",
        "tests/test_corpus.py",
        "tests/test_coverage.py",
        "tests/test_e2e_hongloumeng.py",
        "tests/test_graph.py",
        "tests/test_object_store.py",
        "tests/test_ontology.py",
        "tests/test_parser.py",
        "tests/test_pipeline.py",
        "tests/test_segmenter.py",
        "tests/test_validator.py",
        "tests/test_validator_v3_3.py",
    ],
    "e2e": [
        "tests/test_e2e_hongloumeng.py",
    ],
    "extractor": [
        "tests/test_extractor.py",
    ],
    "full": [
        "tests",
    ],
    "quality": [
        # Quality profile runs quality_check.py --json and fails under threshold
    ],
}


PROFILE_PURPOSES: dict[str, str] = {
    "smoke": "Fast feedback after ordinary code edits.",
    "validator": "Reference, schema, evidence, and claim-safety hardening.",
    "textmap": "Raw text, block, segment, codegen, and AST roundtrip changes.",
    "graph": "Store, coverage, graph projection, and graph query changes.",
    "core": "Non-LLM deterministic core regression suite.",
    "regression": "All non-extractor tests, including Hongloumeng e2e.",
    "e2e": "Hongloumeng end-to-end pipeline regression.",
    "extractor": "LLM extractor parsing, prompt, and mocked API behavior.",
    "full": "Everything pytest can collect and run.",
}


@dataclass
class TestRun:
    profile: str
    purpose: str
    status: str
    returncode: int
    duration_seconds: float
    command: list[str]
    tests: dict[str, int | None]
    stdout_tail: str
    stderr_tail: str


def build_command(profile: str, extra_pytest_args: list[str]) -> list[str]:
    if profile not in PROFILES:
        known = ", ".join(sorted(PROFILES))
        raise SystemExit(f"Unknown profile '{profile}'. Known profiles: {known}")
    return [sys.executable, "-m", "pytest", "-q", *PROFILES[profile], *extra_pytest_args]


def parse_test_counts(output: str) -> dict[str, int | None]:
    counts: dict[str, int | None] = {
        "passed": 0,
        "failed": 0,
        "errors": 0,
        "skipped": 0,
        "warnings": 0,
    }
    summary_lines = [line.strip() for line in output.splitlines() if " in " in line or line.startswith("=")]
    text = "\n".join(summary_lines[-8:])
    for key in counts:
        marker = f" {key}"
        for token in text.replace(",", " ").split():
            if token.endswith(key):
                number = token[: -len(key)]
                if number.isdigit():
                    counts[key] = int(number)
            elif marker in text:
                parts = text.split(marker, 1)[0].split()
                if parts and parts[-1].isdigit():
                    counts[key] = int(parts[-1])
    return counts


def tail(text: str, max_chars: int = 4000) -> str:
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def run_profile(profile: str, extra_pytest_args: list[str]) -> TestRun:
    # Quality profile runs quality_check.py directly, not pytest
    if profile == "quality":
        start = time.perf_counter()
        quality_script = PROJECT_ROOT / "scripts" / "quality_check.py"

        # Default thresholds for quality gate
        quality_thresholds = {
            "grounding_rate_min": 0.70,
            "reference_issue_max": 10,
            "entity_conflict_max": 5,
        }

        proc = subprocess.run(
            [sys.executable, str(quality_script), "--json"],
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        duration = time.perf_counter() - start

        # Parse JSON metrics from output
        passed = 0
        failed = 0
        metrics: dict = {}
        try:
            # Try parsing entire stdout as JSON first
            metrics = json.loads(proc.stdout.strip())
        except json.JSONDecodeError:
            # Try extracting JSON block (may have text prefix)
            for line in proc.stdout.split("\n"):
                stripped = line.strip()
                if stripped.startswith("{"):
                    try:
                        metrics = json.loads(stripped)
                        if "grounding_rate" in metrics:
                            break
                    except json.JSONDecodeError:
                        pass
            if not metrics:
                # Try from first { to end
                idx = proc.stdout.find("{")
                if idx >= 0:
                    try:
                        metrics = json.loads(proc.stdout[idx:])
                    except json.JSONDecodeError:
                        pass

        if not metrics or "grounding_rate" not in metrics:
            return TestRun(
                profile=profile,
                purpose="Quality metrics check (grounding, references, coverage).",
                status="fail",
                returncode=1,
                duration_seconds=round(duration, 2),
                command=[sys.executable, "scripts/quality_check.py", "--json"],
                tests={"passed": 0, "failed": 1, "errors": 1, "skipped": 0, "warnings": 0},
                stdout_tail=tail(proc.stdout),
                stderr_tail=tail(proc.stderr),
            )

        # Evaluate thresholds
        failures = []
        gr = metrics.get("grounding_rate", 0)
        ri = metrics.get("reference_issue_count", 999)
        ec = metrics.get("entity_conflict_count", 999)

        if gr < quality_thresholds["grounding_rate_min"]:
            failures.append(f"grounding_rate {gr:.2%} < {quality_thresholds['grounding_rate_min']:.0%}")
        if ri > quality_thresholds["reference_issue_max"]:
            failures.append(f"reference_issue_count {ri} > {quality_thresholds['reference_issue_max']}")
        if ec > quality_thresholds["entity_conflict_max"]:
            failures.append(f"entity_conflict_count {ec} > {quality_thresholds['entity_conflict_max']}")

        passed = 1 if len(failures) == 0 else 0
        failed = len(failures)
        status = "pass" if len(failures) == 0 else "fail"
        returncode = 0 if len(failures) == 0 else 1

        combined = f"{proc.stdout}\n--- thresholds ---\n"
        if failures:
            combined += "FAILURES:\n" + "\n".join(failures) + "\n"
        else:
            combined += "All thresholds met.\n"

        return TestRun(
            profile=profile,
            purpose=f"Quality gate: grounding≥{quality_thresholds['grounding_rate_min']:.0%}, refs≤{quality_thresholds['reference_issue_max']}, conflicts≤{quality_thresholds['entity_conflict_max']}.",
            status=status,
            returncode=returncode,
            duration_seconds=round(duration, 2),
            command=[sys.executable, "scripts/quality_check.py", "--json"],
            tests={"passed": passed, "failed": failed, "errors": 0, "skipped": 0, "warnings": 0},
            stdout_tail=tail(combined),
            stderr_tail=tail(proc.stderr),
        )

    command = build_command(profile, extra_pytest_args)
    start = time.perf_counter()
    proc = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    duration = time.perf_counter() - start
    combined = f"{proc.stdout}\n{proc.stderr}"
    status = "pass" if proc.returncode == 0 else "fail"
    return TestRun(
        profile=profile,
        purpose=PROFILE_PURPOSES[profile],
        status=status,
        returncode=proc.returncode,
        duration_seconds=round(duration, 2),
        command=command,
        tests=parse_test_counts(combined),
        stdout_tail=tail(proc.stdout),
        stderr_tail=tail(proc.stderr),
    )


def print_human(result: TestRun) -> None:
    print(f"Profile: {result.profile}")
    print(f"Purpose: {result.purpose}")
    print(f"Status: {result.status}")
    print(f"Duration: {result.duration_seconds:.2f}s")
    print(f"Command: {' '.join(result.command)}")
    print(f"Counts: {result.tests}")
    if result.stdout_tail:
        print("\n--- stdout tail ---")
        print(result.stdout_tail.rstrip())
    if result.stderr_tail:
        print("\n--- stderr tail ---")
        print(result.stderr_tail.rstrip())


def main() -> int:
    parser = argparse.ArgumentParser(description="Run standardized T2C test profiles.")
    parser.add_argument("profile", choices=sorted(PROFILES), help="Test profile to run.")
    parser.add_argument("--json", action="store_true", help="Print JSON metrics.")
    parser.add_argument(
        "--save",
        type=Path,
        help="Write JSON metrics to this file.",
    )
    args, extra_args = parser.parse_known_args()

    if extra_args and extra_args[0] == "--":
        extra_args = extra_args[1:]

    result = run_profile(args.profile, extra_args)
    payload = asdict(result)

    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print_human(result)

    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
