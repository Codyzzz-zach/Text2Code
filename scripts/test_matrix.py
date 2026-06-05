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
