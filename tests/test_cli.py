"""Tests for the public t2c compile CLI."""
from __future__ import annotations

import json
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path


from t2c.cli import compile_command
from t2c.pipeline import PipelineResult


def test_compile_without_mode_returns_guidance(tmp_path):
    raw = tmp_path / "case_001.txt"
    raw.write_text("爱丽丝在火车站。\n\n「你来了，」她说。\n", encoding="utf-8")
    out = tmp_path / "case_001"

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "t2c.cli",
            "compile",
            str(raw),
            "--output",
            str(out),
            "--json",
        ],
        cwd=Path(__file__).resolve().parent.parent,
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["status"] == "error"
    assert "requires --llm" in payload["error"]
    assert not out.exists()


def test_compile_text_only_writes_importable_preflight_package(tmp_path):
    raw = tmp_path / "case_001.txt"
    raw.write_text("爱丽丝在火车站。\n\n「你来了，」她说。\n", encoding="utf-8")
    out = tmp_path / "case_001"

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "t2c.cli",
            "compile",
            str(raw),
            "--output",
            str(out),
            "--text-only",
            "--json",
        ],
        cwd=Path(__file__).resolve().parent.parent,
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr + proc.stdout
    payload = json.loads(proc.stdout)
    assert payload["status"] == "ok"
    assert payload["mode"] == "text_only"
    assert payload["semantic_compile"] is False
    assert payload["llm"] is False
    assert payload["counts"]["segments"] >= 2
    assert (out / "__init__.py").exists()
    assert (out / "text.py").exists()
    assert (out / "coverage.py").exists()


def test_compile_cli_default_llm_config_is_deepseek(tmp_path):
    raw = tmp_path / "case_001.txt"
    raw.write_text("爱丽丝在火车站。", encoding="utf-8")
    out = tmp_path / "case_001"

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "t2c.cli",
            "compile",
            str(raw),
            "--output",
            str(out),
            "--llm",
            "--cache-mode",
            "read_only",
            "--json",
        ],
        cwd=Path(__file__).resolve().parent.parent,
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["status"] == "error"
    assert "Cache miss" in payload["error"]


def test_compile_llm_validation_failure_does_not_write_package(tmp_path, monkeypatch):
    raw = tmp_path / "case_001.txt"
    raw.write_text("爱丽丝在火车站。", encoding="utf-8")
    out = tmp_path / "case_001"

    class FakeExtractor:
        pass

    class FakePipeline:
        def __init__(self, **_):
            pass

        def process_text(self, **_):
            return PipelineResult(
                valid=False,
                errors=["dangling reference"],
                rejected_count=1,
            )

    monkeypatch.setattr("t2c.cli.LLMExtractor", lambda **_: FakeExtractor())
    monkeypatch.setattr("t2c.cli.Pipeline", FakePipeline)

    args = SimpleNamespace(
        raw_path=raw,
        output=out,
        doc_id=None,
        llm=True,
        text_only=False,
        provider="deepseek",
        model=None,
        base_url=None,
        api_key=None,
        max_tokens=None,
        thinking_budget=None,
        cache_mode="read_only",
        cache_dir=str(tmp_path / "cache"),
        protocol=None,
        max_repair_attempts=0,
        chapter_num=1,
        chapter_title="",
        no_verify=False,
        json=True,
    )

    try:
        compile_command(args)
    except RuntimeError as exc:
        assert "Validation failed" in str(exc)
    else:
        raise AssertionError("compile_command should fail on invalid pipeline result")

    assert not (out / "text.py").exists()
    assert not (out / "__init__.py").exists()


def test_compile_verify_failure_does_not_write_package(tmp_path, monkeypatch):
    raw = tmp_path / "case_001.txt"
    raw.write_text("爱丽丝在火车站。", encoding="utf-8")
    out = tmp_path / "case_001"

    def fail_compile(*_, **__):
        raise RuntimeError("synthetic verify failure")

    monkeypatch.setattr("t2c.cli.py_compile.compile", fail_compile)

    args = SimpleNamespace(
        raw_path=raw,
        output=out,
        doc_id=None,
        llm=False,
        text_only=True,
        provider=None,
        model=None,
        base_url=None,
        api_key=None,
        max_tokens=None,
        thinking_budget=None,
        cache_mode=None,
        cache_dir=None,
        protocol=None,
        max_repair_attempts=0,
        chapter_num=1,
        chapter_title="",
        no_verify=False,
        json=True,
    )

    try:
        compile_command(args)
    except RuntimeError as exc:
        assert "synthetic verify failure" in str(exc)
    else:
        raise AssertionError("compile_command should fail when package verification fails")

    assert not out.exists()


def test_compile_refuses_to_overwrite_user_file(tmp_path):
    raw = tmp_path / "case_001.txt"
    raw.write_text("爱丽丝在火车站。", encoding="utf-8")
    out = tmp_path / "case_001"
    out.mkdir()
    (out / "text.py").write_text("# user-owned file\nVALUE = 1\n", encoding="utf-8")

    args = SimpleNamespace(
        raw_path=raw,
        output=out,
        doc_id=None,
        llm=False,
        text_only=True,
        provider=None,
        model=None,
        base_url=None,
        api_key=None,
        max_tokens=None,
        thinking_budget=None,
        cache_mode=None,
        cache_dir=None,
        protocol=None,
        max_repair_attempts=0,
        chapter_num=1,
        chapter_title="",
        no_verify=False,
        json=True,
    )

    try:
        compile_command(args)
    except RuntimeError as exc:
        assert "Refusing to overwrite non-T2C file" in str(exc)
    else:
        raise AssertionError("compile_command should refuse non-generated output files")

    assert (out / "text.py").read_text(encoding="utf-8").startswith("# user-owned file")
