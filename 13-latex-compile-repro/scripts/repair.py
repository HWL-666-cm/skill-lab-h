#!/usr/bin/env python3
"""Apply only defensible mechanical fixes, on copies, and record every change.

Why conservative: a wrong table width or a guessed formula symbol is worse
than an honest "needs human".  We auto-fix only three deterministic classes
(stale aux files, unicode-engine switch, missing *standard* packages).  For
everything else we emit a precise proposal with applied=false so the calling
agent can act with domain judgement.  Original case files are never edited.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

import build as B
import diagnose as D

SAFE_PACKAGES = {
    "amsmath", "amssymb", "amsthm", "graphicx", "booktabs", "tabularx",
    "geometry", "hyperref", "inputenc", "fontenc", "natbib", "biblatex",
    "array", "multicol", "caption", "subcaption", "float", "xcolor",
    "enumitem", "babel", "csquotes", "listings", "fancyhdr", "mathtools",
}
PKG_MISSING = re.compile(r"File [`']([^'`]+\.sty)' not found", re.IGNORECASE)
FILE_MISSING = re.compile(r"File [`']([^'`]+)' not found", re.IGNORECASE)
BEGIN_DOC = re.compile(r"\\begin\{document\}")


def _snapshot_originals(src: Path, snapshot: Path) -> None:
    if snapshot.exists():
        shutil.rmtree(snapshot)
    shutil.copytree(src, snapshot)


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return p.read_text(encoding="gb18030")


def _write(p: Path, text: str) -> None:
    p.write_text(text, encoding="utf-8", newline="\n")


def _fix_package(text: str, finding: dict) -> tuple[str, dict | None]:
    m = PKG_MISSING.search(finding.get("log_excerpt", ""))
    if not m:
        return text, None
    pkg = Path(m.group(1)).stem
    if pkg not in SAFE_PACKAGES:
        return text, None
    if re.search(r"\\usepackage\s*(?:\[[^\]]*\])?\s*\{[^}]*\b" + re.escape(pkg) + r"\b", text):
        return text, None
    if not BEGIN_DOC.search(text):
        return text, None
    new = BEGIN_DOC.sub(f"\\usepackage{{{pkg}}}\n\\begin{{document}}", text, count=1)
    return new, {
        "action": f"insert \\usepackage{{{pkg}}} before \\begin{{document}}",
        "reason": f"log reports missing standard package {pkg}; it is on the safe list",
        "applied": True,
    }


def _fix_stale_aux(work: Path) -> dict:
    B.clean_aux(work / "build")
    return {"action": "remove .aux/.bbl/.bcf/.out/... from build dir and rebuild from scratch",
            "reason": "stale auxiliary files cause false Undefined control sequence errors",
            "applied": True}


def repair_round(profile: dict, work: Path, ledger: dict,
                 engine_override: str | None, changes: list[dict]) -> tuple[bool, str | None]:
    """One repair pass.  Returns (changed, engine_override)."""
    src = work / "src"
    changed = False
    for f in ledger.get("findings", []):
        cat = f["category"]
        sev = f["severity"]
        if sev not in ("blocking", "major"):
            continue
        if cat == "stale_aux":
            changes.append({"id": f"C{len(changes)+1:03d}", "finding_id": f["id"],
                            "category": cat, "location": f.get("location", ""),
                            **_fix_stale_aux(work)})
            changed = True
            continue
        if cat == "engine_encoding":
            want = "xelatex"
            if engine_override != want:
                changes.append({
                    "id": f"C{len(changes)+1:03d}", "finding_id": f["id"],
                    "category": cat, "location": f.get("location", ""),
                    "action": f"switch engine to {want}",
                    "reason": "non-ASCII/CJK source cannot compile under pdflatex inputenc",
                    "applied": True,
                })
                engine_override = want
                changed = True
            continue
        if cat == "package":
            handled = False
            for p in sorted(src.rglob("*.tex")):
                text = _read(p)
                new, info = _fix_package(text, f)
                if info:
                    _write(p, new)
                    changes.append({
                        "id": f"C{len(changes)+1:03d}", "finding_id": f["id"],
                        "category": cat, "location": f.get("location", "") or p.name,
                        **info,
                    })
                    changed = True
                    handled = True
                    break
            if not handled:
                # Missing third-party/template packages cannot be guessed.  Still
                # leave a visible "needs human" record instead of silence.
                changes.append({
                    "id": f"C{len(changes)+1:03d}", "finding_id": f["id"],
                    "category": cat, "location": f.get("location", ""),
                    "action": f.get("fix", ""),
                    "reason": f.get("root_cause", ""),
                    "applied": False, "needs_human": True,
                })
            continue
        # Everything else: precise proposal, no blind edit.
        changes.append({
            "id": f"C{len(changes)+1:03d}", "finding_id": f["id"],
            "category": cat, "location": f.get("location", ""),
            "action": f.get("fix", ""),
            "reason": f.get("root_cause", ""),
            "applied": False,
            "needs_human": True,
        })
    return changed, engine_override


def repair(profile: dict, work: str | Path, lexicon: dict,
           max_rounds: int = 3, timeout: int = 90) -> dict:
    """Compile -> diagnose -> apply safe fixes -> recompile, up to max_rounds."""
    work = Path(work).resolve()
    src = work / "src"
    snapshot = work / "src_original"
    if src.is_dir() and not snapshot.is_dir():
        _snapshot_originals(src, snapshot)

    engine = profile.get("engine") or "pdflatex"
    changes: list[dict] = []
    history: list[dict] = []
    report = B.run_build(profile, work, engine=engine, strategy="auto", timeout=timeout)
    ledger = D.diagnose(report, lexicon)
    history.append({"round": 1, "build_ok": report.get("ok"),
                    "findings": ledger["counts"], "engine": engine})

    for rnd in range(2, max_rounds + 1):
        if report.get("ok") and ledger.get("status") == "pass":
            break
        changed, engine = repair_round(profile, work, ledger, engine, changes)
        # No safe mechanical fix left: stop instead of looping forever.
        any_applied = any(c.get("applied") for c in
                          [c for c in changes if c["id"] not in
                           {h.get("last_change_id", "") for h in history}])
        if not changed or not any_applied:
            break
        report = B.run_build(profile, work, engine=engine, strategy="auto", timeout=timeout)
        ledger = D.diagnose(report, lexicon)
        history.append({"round": rnd, "build_ok": report.get("ok"),
                        "findings": ledger["counts"], "engine": engine})
        history[-1]["last_change_id"] = changes[-1]["id"] if changes else ""

    original_hashes = B.source_manifest(snapshot) if snapshot.is_dir() else []
    final_hashes = B.source_manifest(src)
    diffs = []
    om = {x["path"]: x["sha256"] for x in original_hashes}
    for x in final_hashes:
        if om.get(x["path"]) != x["sha256"]:
            diffs.append(x["path"])

    return {
        "final_build": report,
        "final_ledger": ledger,
        "changes": changes,
        "history": history,
        "engine_final": engine,
        "source_diffs": diffs,
        "snapshot_dir": str(snapshot),
        "note": ("Only deterministic fixes were applied automatically. "
                 "Entries with applied=false need domain judgement by the calling agent."),
    }


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="repair a LaTeX build on copies")
    ap.add_argument("--profile", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--lexicon", required=True)
    ap.add_argument("--max-rounds", type=int, default=3)
    a = ap.parse_args()
    prof = json.loads(Path(a.profile).read_text(encoding="utf-8"))
    lex = json.loads(Path(a.lexicon).read_text(encoding="utf-8"))
    out = repair(prof, a.work, lex, a.max_rounds)
    print(json.dumps({"ok": out["final_build"].get("ok"),
                      "status": out["final_ledger"]["status"],
                      "changes": len(out["changes"]),
                      "applied": sum(1 for c in out["changes"] if c.get("applied")),
                      "diffs": out["source_diffs"]}, ensure_ascii=False, indent=2))
