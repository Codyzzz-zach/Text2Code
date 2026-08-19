#!/usr/bin/env python3
"""verify_codegraph.py — CodeGraph capability acceptance for T2C packages.

Implements the v6.0 acceptance contract (spec/t2c_design_v6.0.md §4) using
only the Python standard library (SCIP/Pyright are independent re-checks,
not required for these gates):

  C1  every generated file parses (py_compile + ast.parse)
  C2  every object is a top-level assignment; package-wide symbols unique;
      every object self-declares symbol='<its own name>'
  C4  every cross-file import is live (imported name referenced in-file)
  ARR every *_symbol kwarg value is an ast.Name (or list of Names) that
      resolves to an in-package definition — string literals count as misses
  C7  `from <pkg> import <symbol>` resolves for every symbol (sampled)
  C10 --break-symbol SYM: deleting SYM's definition must break the import
  C11 Claim/Event evidence_refs non-empty rate (data gate)
  C12 hash replay: sha256(segment.text_slice[start:end]) == quote_hash

Usage:
  python scripts/verify_codegraph.py <package_dir> [--json]
  python scripts/verify_codegraph.py <package_dir> --break-symbol <symbol>
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib
import json
import py_compile
import shutil
import sys
import tempfile
from pathlib import Path

SYMBOL_KWARGS = {
    "subject_symbol", "object_symbol", "segment_symbol",
    "claim_symbol", "participant_symbols",
}

PACKAGE_FILES = {
    "__init__.py", "text.py", "entities.py", "events.py",
    "claims.py", "residuals.py", "derived.py", "coverage.py",
}


def _hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _package_files(pkg: Path) -> dict[str, Path]:
    return {p.name: p for p in sorted(pkg.glob("*.py")) if p.is_file()}


def _collect_definitions(tree: ast.Module) -> dict[str, int]:
    """symbol name → lineno of top-level assignment."""
    defs: dict[str, int] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                defs[target.id] = node.lineno
    return defs


def _collect_imports(tree: ast.Module) -> list[tuple[str, str, int]]:
    """(module, name, lineno) for `from .mod import name` (level=1)."""
    out = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.level > 0:
            for alias in node.names:
                out.append((node.module or "", alias.name, node.lineno))
    return out


def _name_usages(tree: ast.Module) -> dict[str, int]:
    """Count ast.Name load occurrences per name (excluding import lines)."""
    counts: dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            counts[node.id] = counts.get(node.id, 0) + 1
    return counts


def _check_arr(tree: ast.Module, defined_or_imported: set[str]) -> tuple[int, int, list[str]]:
    """Return (resolved_refs, total_refs, problems) for *_symbol kwargs."""
    resolved = 0
    total = 0
    problems: list[str] = []

    def check_value(value: ast.expr, where: str) -> None:
        nonlocal resolved, total
        if isinstance(value, ast.Name):
            total += 1
            if value.id in defined_or_imported:
                resolved += 1
            else:
                problems.append(f"{where}: Name {value.id!r} not defined in package")
        elif isinstance(value, ast.List):
            for elt in value.elts:
                check_value(elt, where)
        elif isinstance(value, ast.Constant) and isinstance(value.value, str):
            total += 1
            problems.append(
                f"{where}: string literal {value.value!r} instead of bare Name"
            )
        # None / empty list → field would not be emitted; ignore

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg in SYMBOL_KWARGS:
                check_value(kw.value, f"{kw.arg}@line{node.lineno}")
    return resolved, total, problems


def _check_self_declaration(tree: ast.Module) -> list[str]:
    """Every `sym = Constructor(...)` must carry symbol='sym' when the
    constructor supports it (all except Document/Block/CoverageReport)."""
    problems = []
    no_symbol_field = {"Document", "Block", "CoverageReport"}
    for node in tree.body:
        if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)):
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        ctor = node.value.func
        ctor_name = ctor.id if isinstance(ctor, ast.Name) else ""
        if ctor_name in no_symbol_field:
            continue
        sym_kw = next(
            (kw for kw in node.value.keywords if kw.arg == "symbol"), None
        )
        if sym_kw is None:
            problems.append(f"{target.id} ({ctor_name}): missing symbol= self-declaration")
        elif not (
            isinstance(sym_kw.value, ast.Constant)
            and sym_kw.value.value == target.id
        ):
            problems.append(f"{target.id}: symbol= does not match assignment name")
    return problems


def _import_package(pkg: Path) -> tuple[bool, str]:
    parent = str(pkg.parent.resolve())
    name = pkg.name
    if not name.isidentifier():
        return False, f"package name {name!r} is not a Python identifier"
    sys.path.insert(0, parent)
    try:
        importlib.invalidate_caches()
        for key in list(sys.modules):
            if key == name or key.startswith(f"{name}."):
                sys.modules.pop(key, None)
        importlib.import_module(name)
        return True, ""
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    finally:
        sys.path.pop(0)
        for key in list(sys.modules):
            if key == name or key.startswith(f"{name}."):
                sys.modules.pop(key, None)


def _check_replay(pkg: Path, sample_limit: int = 50) -> tuple[int, int, list[str]]:
    """C12: re-hash evidence quote spans against segment text in the package."""
    parent = str(pkg.parent.resolve())
    name = pkg.name
    sys.path.insert(0, parent)
    checked = 0
    ok = 0
    problems: list[str] = []
    try:
        importlib.invalidate_caches()
        for key in list(sys.modules):
            if key == name or key.startswith(f"{name}."):
                sys.modules.pop(key, None)
        text_mod = importlib.import_module(f"{name}.text")
        seg_by_symbol = {
            sym: obj
            for sym, obj in vars(text_mod).items()
            if type(obj).__name__ == "Segment"
        }
        for mod_name in ("entities", "events", "claims", "derived", "residuals"):
            try:
                mod = importlib.import_module(f"{name}.{mod_name}")
            except ModuleNotFoundError:
                continue
            for obj in vars(mod).values():
                erefs = getattr(obj, "evidence_refs", None)
                if not erefs:
                    continue
                for eref in erefs:
                    sym = getattr(eref, "segment_symbol", None)
                    seg = seg_by_symbol.get(sym) if sym else None
                    if seg is None:
                        problems.append(
                            f"{getattr(obj, 'id', '?')}: segment_symbol {sym!r} "
                            f"not found in text.py"
                        )
                        continue
                    quote = seg.text_slice[eref.start:eref.end]
                    checked += 1
                    if _hash(quote) == eref.quote_hash:
                        ok += 1
                    else:
                        problems.append(
                            f"{getattr(obj, 'id', '?')}: quote_hash mismatch at "
                            f"{sym}[{eref.start}:{eref.end}]"
                        )
                    if checked >= sample_limit:
                        return ok, checked, problems
        return ok, checked, problems
    finally:
        sys.path.pop(0)
        for key in list(sys.modules):
            if key == name or key.startswith(f"{name}."):
                sys.modules.pop(key, None)


def _check_evidence_presence(pkg: Path) -> tuple[int, int]:
    """C11 data gate: (with_evidence, total) over Claim/Event objects."""
    parent = str(pkg.parent.resolve())
    name = pkg.name
    sys.path.insert(0, parent)
    total = 0
    with_ev = 0
    try:
        importlib.invalidate_caches()
        for key in list(sys.modules):
            if key == name or key.startswith(f"{name}."):
                sys.modules.pop(key, None)
        for mod_name in ("claims", "events"):
            try:
                mod = importlib.import_module(f"{name}.{mod_name}")
            except ModuleNotFoundError:
                continue
            for obj in vars(mod).values():
                if type(obj).__name__ in ("Claim", "Event"):
                    total += 1
                    if getattr(obj, "evidence_refs", None):
                        with_ev += 1
        return with_ev, total
    finally:
        sys.path.pop(0)
        for key in list(sys.modules):
            if key == name or key.startswith(f"{name}."):
                sys.modules.pop(key, None)


def _break_symbol(pkg: Path, symbol: str) -> tuple[bool, str]:
    """C10 negative test: removing `symbol`'s definition must break import."""
    with tempfile.TemporaryDirectory(prefix="t2c_break_") as tmp:
        broken_pkg = Path(tmp) / pkg.name
        shutil.copytree(pkg, broken_pkg)
        removed = False
        for path in broken_pkg.glob("*.py"):
            if path.name == "__init__.py":
                continue
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            for node in tree.body:
                if (
                    isinstance(node, ast.Assign)
                    and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id == symbol
                ):
                    lines = source.splitlines(keepends=True)
                    start = node.lineno - 1
                    end = node.end_lineno or node.lineno
                    del lines[start:end]
                    path.write_text("".join(lines), encoding="utf-8")
                    removed = True
                    break
            if removed:
                break
        if not removed:
            return False, f"symbol {symbol!r} definition not found in package"
        ok, err = _import_package(broken_pkg)
        if ok:
            return False, (
                f"package still imports after removing {symbol!r} — "
                f"import-as-validation is NOT in effect"
            )
        return True, f"import failed as expected after removing {symbol!r} ({err})"


def _check_zero_dangling(trees: dict[str, ast.Module]) -> list[str]:
    """Artifact-level zero-dangling gate (M3): every segment id referenced
    anywhere in the package (segment_id / source_segment_ids /
    requires_raw_fallback kwargs) must be defined by a Segment in text.py.

    This catches cross-namespace pollution (e.g. cached objects carrying
    another document's segment ids) that string-based references allow.
    """
    seg_ids: set[str] = set()
    text_tree = trees.get("text.py")
    if text_tree is None:
        return ["no text.py in package"]
    for node in ast.walk(text_tree):
        if isinstance(node, ast.Call):
            ctor = node.func
            if isinstance(ctor, ast.Name) and ctor.id == "Segment":
                for kw in node.keywords:
                    if kw.arg == "id" and isinstance(kw.value, ast.Constant):
                        seg_ids.add(kw.value.value)

    def check_value(value: ast.expr, where: str, problems: list[str]) -> None:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            if value.value not in seg_ids:
                problems.append(f"{where}: dangling segment id {value.value!r}")
        elif isinstance(value, ast.List):
            for elt in value.elts:
                check_value(elt, where, problems)

    problems: list[str] = []
    watched = {"segment_id", "source_segment_ids", "requires_raw_fallback"}
    for fname, tree in trees.items():
        if fname == "__init__.py":
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                if kw.arg in watched:
                    check_value(kw.value, f"{fname}:{kw.arg}@line{node.lineno}", problems)
    return problems


def _check_pyright(pkg: Path) -> tuple[bool, object]:
    """C8: Pyright must report 0 errors on the generated package."""
    exe = shutil.which("pyright")
    if exe is None:
        return False, "pyright not installed (pip install pyright)"
    import subprocess

    proc = subprocess.run(
        [exe, "--outputjson", str(pkg)],
        capture_output=True, text=True, timeout=600,
        cwd=str(pkg.parent),
    )
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return False, f"pyright produced no JSON: {proc.stderr[:500]}"
    summary = data.get("summary", {})
    errors = summary.get("errorCount", -1)
    diags = [
        f"{d.get('file', '?')}:{d.get('range', {}).get('start', {}).get('line', '?')}: {d.get('message', '')[:120]}"
        for d in data.get("generalDiagnostics", [])
        if d.get("severity") == "error"
    ][:10]
    return errors == 0, {"error_count": errors, "sample_errors": diags}


def verify_package(pkg: Path, *, with_pyright: bool = False) -> dict:
    pkg = pkg.resolve()
    report: dict = {"package": str(pkg), "checks": {}, "ok": True}

    def record(name: str, ok: bool, detail: object) -> None:
        report["checks"][name] = {"ok": ok, "detail": detail}
        if not ok:
            report["ok"] = False

    files = _package_files(pkg)
    missing = PACKAGE_FILES - set(files)
    record("C1_files_present", not missing, {"missing": sorted(missing)})

    trees: dict[str, ast.Module] = {}
    parse_errors = []
    for fname, path in files.items():
        try:
            py_compile.compile(str(path), doraise=True)
            trees[fname] = ast.parse(path.read_text(encoding="utf-8"))
        except (py_compile.PyCompileError, SyntaxError) as exc:
            parse_errors.append(f"{fname}: {exc}")
    record("C1_parse", not parse_errors, parse_errors)

    # C2: definitions unique package-wide; self-declaration consistent
    definitions: dict[str, str] = {}  # symbol → file
    dupes = []
    decl_problems = []
    for fname, tree in trees.items():
        for sym, _lineno in _collect_definitions(tree).items():
            if sym in definitions and fname != "__init__.py":
                dupes.append(f"{sym} in {definitions[sym]} and {fname}")
            definitions.setdefault(sym, fname)
        if fname != "__init__.py":
            decl_problems.extend(_check_self_declaration(tree))
    record("C2_unique_definitions", not dupes, dupes)
    record("C2_self_declaration", not decl_problems, decl_problems[:10])

    # C4: live imports (each imported name used in-file)
    dead_imports = []
    for fname, tree in trees.items():
        if fname == "__init__.py":
            continue  # __init__ imports ARE the package surface
        usages = _name_usages(tree)
        for mod, name, lineno in _collect_imports(tree):
            if usages.get(name, 0) < 1:
                dead_imports.append(f"{fname}:{lineno} from .{mod} import {name}")
    record("C4_live_imports", not dead_imports, dead_imports)

    # ARR: *_symbol kwargs are bare Names resolvable in-package
    all_names = set(definitions)
    for tree in trees.values():
        for _mod, name, _ln in _collect_imports(tree):
            all_names.add(name)
    arr_resolved = 0
    arr_total = 0
    arr_problems: list[str] = []
    for fname, tree in trees.items():
        if fname in ("__init__.py", "coverage.py"):
            continue
        r, t, problems = _check_arr(tree, all_names)
        arr_resolved += r
        arr_total += t
        arr_problems.extend(f"{fname}: {p}" for p in problems[:5])
    arr = arr_resolved / arr_total if arr_total else 1.0
    record("ARR", arr == 1.0, {
        "ast_reference_rate": round(arr, 4),
        "resolved": arr_resolved,
        "total": arr_total,
        "problems": arr_problems,
    })

    # M3: artifact-level zero-dangling gate — every referenced segment id
    # must be defined in this package's own text.py.
    dangling = _check_zero_dangling(trees)
    record("REF_zero_dangling", not dangling, {
        "dangling_count": len(dangling),
        "samples": dangling[:10],
    })

    # C7: package-level import surface
    ok, err = _import_package(pkg)
    record("C7_package_import", ok, err)
    if ok:
        parent = str(pkg.parent.resolve())
        sys.path.insert(0, parent)
        try:
            importlib.invalidate_caches()
            module = importlib.import_module(pkg.name)
            all_list = getattr(module, "__all__", [])
            missing_syms = [s for s in all_list if not hasattr(module, s)]
            record("C7_all_exports_resolve", not missing_syms, {
                "exported": len(all_list), "missing": missing_syms[:10],
            })
        finally:
            sys.path.pop(0)
            for key in list(sys.modules):
                if key == pkg.name or key.startswith(f"{pkg.name}."):
                    sys.modules.pop(key, None)

    # C11: evidence presence for Claim/Event (data gate; threshold reported)
    with_ev, ev_total = _check_evidence_presence(pkg)
    ev_rate = with_ev / ev_total if ev_total else 1.0
    record("C11_evidence_presence", ev_total == 0 or with_ev > 0, {
        "claim_event_with_evidence": with_ev,
        "claim_event_total": ev_total,
        "rate": round(ev_rate, 4),
    })

    # C12: hash replay against segment text
    ok_n, checked, replay_problems = _check_replay(pkg)
    record("C12_hash_replay", ok_n == checked, {
        "checked": checked, "ok": ok_n, "problems": replay_problems[:10],
    })

    # C8: Pyright type check (independent re-verification; opt-in)
    if with_pyright:
        ok, detail = _check_pyright(pkg)
        record("C8_pyright", ok, detail)

    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify a T2C package against the v6.0 codegraph contract")
    ap.add_argument("package", type=Path, help="Generated package directory")
    ap.add_argument("--json", action="store_true", help="Machine-readable output")
    ap.add_argument("--break-symbol", default=None, help="Run C10 negative test on this symbol")
    ap.add_argument("--pyright", action="store_true", help="Also run Pyright (C8) — fails if pyright is not installed")
    args = ap.parse_args()

    report = verify_package(args.package, with_pyright=args.pyright)

    if args.break_symbol:
        ok, msg = _break_symbol(args.package.resolve(), args.break_symbol)
        report["checks"]["C10_break_symbol"] = {"ok": ok, "detail": msg}
        if not ok:
            report["ok"] = False

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for name, check in report["checks"].items():
            mark = "PASS" if check["ok"] else "FAIL"
            print(f"[{mark}] {name}: {check['detail']}")
        print(f"\nOverall: {'PASS' if report['ok'] else 'FAIL'}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
