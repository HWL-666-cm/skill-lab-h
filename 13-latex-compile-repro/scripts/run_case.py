#!/usr/bin/env python3
"""Main entry point: profile -> build/diagnose/repair -> manifest -> reproduce -> emit.

    full      run the whole pipeline (default)
    profile   only write project_profile.json
    build     compile + diagnose + repair, no manifest/emit
    reproduce run build then verify, no emit

Exit codes: 0 complete/pass, 1 partial/fail (a result is still written), 2 blocked/bad input.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build as B          # noqa: E402
import contract as C       # noqa: E402
import diagnose as D       # noqa: E402
import emit                # noqa: E402
import manifest as M       # noqa: E402
import profile as P        # noqa: E402
import repair as R         # noqa: E402
import validate as V       # noqa: E402


def _read(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")


def prepare_inline(profile: dict, case_raw: dict, work: Path) -> dict:
    """If the case supplies LaTeX inline, materialise it as a real .tex file.

    Without this, profile sees source but build.py cannot stage a missing file,
    and the result would be blocked for a case that is actually solvable.
    """
    if profile.get("main_tex") or not profile.get("inline_source_present"):
        return profile
    text = ""
    for key in ("latex", "tex", "source", "latex_source", "tex_source"):
        v = case_raw.get(key)
        if isinstance(v, str) and "\\documentclass" in v:
            text = v
            break
    if not text:
        return profile
    d = work / "inline_root"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "main.tex"
    p.write_text(text, encoding="utf-8", newline="\n")
    profile["main_tex"] = str(p)
    profile["root"] = str(d)
    profile.setdefault("files", []).append({
        "path": str(p), "name": "main.tex", "kind": "main_tex",
        "role": "root document (materialised from inline source)",
        "bytes": p.stat().st_size,
    })
    return profile


def blocked(out: Path, case_id: str, reason: str, detail: str = "") -> dict:
    payload = {
        "case_id": case_id, "status": "blocked", "reason": reason, "detail": detail,
        "project_profile": {}, "sources": [], "artifacts": [],
        "error_ledger": {"findings": [], "counts": {}, "build_ok": False, "status": "fail"},
        "changes": [], "build_manifest": {}, "reproduce": {"verdict": "failed"},
        "validation": {"status": "fail", "checks": [], "counts": {},
                       "top_failures": [reason]},
        "uncertainty": [reason], "limits": [reason],
    }
    _write_json(out / "result.json", payload)
    (out / "changes.md").write_text(
        f"# 修复台账 —— {case_id}\n\n运行被阻断：{reason}\n\n{detail}\n",
        encoding="utf-8", newline="\n")
    return payload


def main() -> int:
    ap = argparse.ArgumentParser(description="LaTeX compile-error + reproducible build")
    ap.add_argument("--case", required=True, help="case.json or project directory")
    ap.add_argument("--out", required=True)
    ap.add_argument("--lexicon", required=True)
    ap.add_argument("--schema", required=True)
    ap.add_argument("--work", default="", help="scratch directory (default: <out>/_work)")
    ap.add_argument("--engine", default="auto", choices=["auto", "pdflatex", "xelatex", "lualatex"])
    ap.add_argument("--strategy", default="auto", choices=["auto", "latexmk", "sequence"])
    ap.add_argument("--stage", default="full",
                    choices=["full", "profile", "build", "reproduce"])
    ap.add_argument("--max-rounds", type=int, default=3)
    ap.add_argument("--timeout", type=int, default=90)
    ap.add_argument("--deterministic", action="store_true")
    a = ap.parse_args()

    started = time.time()
    case_path, out = Path(a.case), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    work = Path(a.work).resolve() if a.work else (out / "_work").resolve()
    work.mkdir(parents=True, exist_ok=True)
    lexicon, schema = _read(a.lexicon), _read(a.schema)
    raw, _root, case_id = P.resolve_case(case_path)

    prof = P.profile(case_path, work)
    prof = prepare_inline(prof, raw, work)
    _write_json(work / "project_profile.json", prof)

    if a.stage == "profile":
        print(json.dumps({"case_id": case_id, "main_tex": prof.get("main_tex"),
                          "engine": prof.get("engine"), "issues": prof.get("issues")},
                         ensure_ascii=False, indent=2))
        return 0 if prof.get("main_tex") else 2

    if not prof.get("main_tex"):
        blocked(out, case_id, "no LaTeX source",
                "case supplied neither a .tex with \\documentclass nor inline source")
        print(json.dumps({"status": "blocked", "reason": "no LaTeX source"},
                         ensure_ascii=False))
        return 2

    if a.engine != "auto":
        prof["engine"] = a.engine

    if a.stage == "build":
        rep = R.repair(prof, work, lexicon, a.max_rounds, a.timeout)
        _write_json(work / "repair_result.json", rep)
        print(json.dumps({"ok": rep["final_build"].get("ok"),
                          "status": rep["final_ledger"]["status"],
                          "changes": len(rep["changes"])}, ensure_ascii=False, indent=2))
        return 0 if rep["final_build"].get("ok") else 1

    # build.py already detects a broken latexmk wrapper and falls back to an
    # explicit sequence internally; no second fallback here (it would double-run).
    rep = R.repair(prof, work, lexicon, a.max_rounds, a.timeout)
    _write_json(work / "repair_result.json", rep)
    man = M.build_manifest(prof, work, rep)
    repro = M.verify(prof, work, man, lexicon, a.timeout)

    if a.stage == "reproduce":
        print(json.dumps({"verdict": repro["verdict"], "checks": repro["checks"]},
                         ensure_ascii=False, indent=2))
        return 0 if repro["verdict"] in ("verified", "verified_failure", "partial") else 1

    provisional = emit.build_result(case_id, prof, rep, man, repro,
                                    {"status": "pending", "checks": []},
                                    raw, time.time() - started, work, out)
    gate = V.validate(provisional, schema, work, out)
    provisional["validation"] = gate
    _write_json(out / "validation.json", gate)
    emit.write_all(out, provisional, rep, raw)
    # write_all re-applies the contract to the saved result; validation already
    # saw the core fields, so the on-disk file is the authoritative one.

    print(json.dumps({
        "case_id": case_id,
        "status": provisional["status"],
        "validation": gate["status"],
        "build_ok": bool(rep["final_build"].get("ok")),
        "reproduction": repro["verdict"],
        "findings": rep["final_ledger"]["counts"],
        "changes_applied": sum(1 for c in rep["changes"] if c.get("applied")),
        "changes_proposed": sum(1 for c in rep["changes"] if not c.get("applied")),
        "written": sorted(p.name for p in out.iterdir() if p.is_file()),
    }, ensure_ascii=False, indent=2))
    return 0 if provisional["status"] == "complete" and gate["status"] in ("pass", "warn") else 1


if __name__ == "__main__":
    raise SystemExit(main())
