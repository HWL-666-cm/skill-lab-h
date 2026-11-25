#!/usr/bin/env python3
"""Record build environment/dependencies and verify independent reproduction.

Reproducibility is deliberately defined in layers:
  * source sha256, exit code and diagnostics MUST agree (a real requirement);
  * PDF bytes agree only in --deterministic mode, because pdfTeX embeds a
    creation timestamp by default and identical correct builds differ.
Claiming byte-identical PDFs by default would be a fabrication.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import build as B
import diagnose as D


def _version(exe: str) -> str:
    p = shutil.which(exe)
    if not p:
        return "not installed"
    try:
        cp = subprocess.run([p, "--version"], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=15)
        first = cp.stdout.decode("utf-8", "replace").splitlines()
        return first[0].strip() if first else "unknown"
    except Exception:
        return "unknown"


def collect_versions(engine: str, backend: str) -> dict:
    return {
        "pdftex": _version("pdflatex"),
        "xetex": _version("xelatex"),
        "luatex": _version("lualatex"),
        "latexmk": _version("latexmk"),
        "bibtex": _version("bibtex"),
        "biber": _version("biber"),
        "engine_used": engine,
        "bibliography_backend": backend,
    }


def build_manifest(profile: dict, work: str | Path, repair_result: dict) -> dict:
    work = Path(work).resolve()
    src = work / "src"
    final_build = repair_result.get("final_build", {})
    engine = repair_result.get("engine_final") or profile.get("engine") or "pdflatex"
    backend = profile.get("bib_backend") or "none"
    strategy = final_build.get("strategy") or "auto"
    rounds = final_build.get("rounds") or []
    commands = []
    for r in rounds:
        cmd = _portable_command(r.get("command") or [])
        commands.append({"command": cmd, "returncode": r.get("returncode"),
                         "timed_out": r.get("timed_out", False)})
    return {
        "case_id": profile.get("case_id", ""),
        "distribution": _extract_distribution(_version("pdflatex")),
        "versions": collect_versions(engine, backend),
        "source_hashes": B.source_manifest(src),
        "main_tex": _relative_main(profile),
        "documentclass": profile.get("documentclass", ""),
        "engine": engine,
        "bibliography_backend": backend,
        "strategy": strategy,
        "build_ok": bool(final_build.get("ok")),
        "commands": commands,
        "rounds": len(rounds),
        "diagnostics_signature": _diag_signature(repair_result.get("final_ledger", {})),
        "deterministic_mode": bool(final_build.get("deterministic")),
        "output_pdf": (lambda p: {**{k: v for k, v in p.items() if k != "path"},
                                  "path": "build/" + Path(str(p.get("path", ""))).name}
                       if p else None)(final_build.get("final_pdf")),
        "notes": [
            "pdfTeX embeds a creation timestamp by default; PDF bytes may differ across runs.",
            "Reproducibility is verified on source hashes, exit codes and diagnostics.",
            "Package/font versions beyond the engine are recorded from the .log when available.",
        ],
    }


def _portable_command(cmd: list) -> list:
    """Keep command semantics but drop machine-specific build directories."""
    out = []
    for part in cmd:
        p = str(part)
        if p.startswith("-output-directory="):
            out.append("-output-directory=<build>")
        elif p.startswith("-outdir="):
            out.append("-outdir=<build>")
        else:
            out.append(p)
    return out


def _relative_main(profile: dict) -> str:
    """Portable path for the main source, independent of the build machine."""
    main = profile.get("main_tex", "")
    if not main:
        return ""
    try:
        return Path(main).resolve().relative_to(Path(profile["root"]).resolve()).as_posix()
    except (ValueError, KeyError):
        return Path(main).name


def _extract_distribution(version_line: str) -> str:
    if "TeX Live" in version_line:
        return version_line[version_line.find("TeX Live"):].strip(" ()")
    if version_line in ("not installed", "unknown"):
        return version_line
    return version_line


def _diag_signature(ledger: dict) -> dict:
    return {"status": ledger.get("status"), "counts": ledger.get("counts", {}),
            "categories": sorted({f.get("category", "") for f in ledger.get("findings", [])})}


def verify(profile: dict, work: str | Path, manifest: dict, lexicon: dict,
           timeout: int = 90) -> dict:
    """Rebuild from the FINAL sources in a separate tree and compare."""
    work = Path(work).resolve()
    final_src = work / "src"
    repro_work = work / "repro"
    if repro_work.exists():
        shutil.rmtree(repro_work)
    repro_work.mkdir(parents=True)
    repro_src = repro_work / "src"
    shutil.copytree(final_src, repro_src)
    build_dir = repro_work / "build"
    build_dir.mkdir(parents=True)
    for p in repro_src.rglob("*.bib"):
        target = build_dir / p.name
        if not target.exists():
            shutil.copy2(p, target)

    main_rel = ""
    try:
        main_rel = Path(profile["main_tex"]).resolve().relative_to(Path(profile["root"])).as_posix()
    except (ValueError, KeyError):
        main_rel = Path(profile.get("main_tex", "")).name
    if not (repro_src / main_rel).is_file():
        matches = list(repro_src.rglob(Path(main_rel).name))
        if matches:
            main_rel = matches[0].relative_to(repro_src).as_posix()

    engine = manifest.get("engine") or profile.get("engine") or "pdflatex"
    backend = manifest.get("bibliography_backend") or "none"
    strategy = manifest.get("strategy") or "auto"
    seq = B.command_sequence(main_rel, engine, backend, strategy, build_dir, repro_src)

    env = os.environ.copy()
    if manifest.get("deterministic_mode"):
        env["SOURCE_DATE_EPOCH"] = "946684800"

    # Snapshot .log after each pass: TeX overwrites main.log every round, so a
    # single final read loses the intermediate state and makes the reproduction
    # ledger incomparable with the original one.
    rounds: list[dict] = []
    for ri, (exe, args) in enumerate(seq, 1):
        rec = B._cmd(exe, args, B.cwd_for(exe, repro_src, build_dir), env, timeout)
        snap_dir = repro_work / f"logs_round_{ri}"
        snap_dir.mkdir(parents=True, exist_ok=True)
        snaps: list[dict] = []
        for p in sorted(build_dir.rglob("*.log")):
            dest = snap_dir / p.name
            shutil.copy2(p, dest)
            snaps.append({"path": str(dest),
                          "text": dest.read_text(encoding="utf-8", errors="replace")})
        rec["logs"] = snaps
        rounds.append(rec)
    final = rounds[-1] if rounds else {}
    all_log = "\n".join(x["text"] for r in rounds for x in r.get("logs", []))
    repro_ledger = D.diagnose({"ok": bool(final.get("returncode") == 0 and
                                          "Output written on" in all_log),
                               "rounds": rounds}, lexicon)

    src_before = B.source_manifest(final_src)
    src_after = B.source_manifest(repro_src)
    before = {x["path"]: x["sha256"] for x in src_before}
    after = {x["path"]: x["sha256"] for x in src_after}
    source_equal = before == after
    original_rc = None
    if manifest.get("commands"):
        original_rc = manifest["commands"][-1].get("returncode")
    rc_equal = original_rc == final.get("returncode")
    original_pdf = (manifest.get("output_pdf") or {}).get("sha256")
    pdf = build_dir / (Path(main_rel).stem + ".pdf")
    pdf_hash = B.sha256_file(pdf) if pdf.is_file() else None
    pdf_equal = bool(original_pdf and pdf_hash and original_pdf == pdf_hash)

    checks = {
        "source_hashes_equal": source_equal,
        "exit_code_equal": rc_equal,
        "diagnostics_equal": _diag_signature(repro_ledger) ==
                             manifest.get("diagnostics_signature", {}),
        "pdf_bytes_equal": pdf_equal,
    }
    core = all(checks[k] for k in ("source_hashes_equal", "exit_code_equal"))
    # A build can succeed even when an intermediate bibtex pass returned 2 for
    # a warning.  Trust the build report's own convergence flag first.
    original_ok = manifest.get("build_ok")
    if original_ok is None:
        original_ok = bool(manifest.get("commands")) and \
            all(c.get("returncode") == 0 for c in manifest["commands"])
    verdict = ("verified" if original_ok else "verified_failure") if core else "failed"
    if core and not checks["diagnostics_equal"]:
        verdict = "partial"
    if manifest.get("deterministic_mode") and not pdf_equal:
        verdict = "partial"

    return {
        "verdict": verdict,
        "checks": checks,
        "repro_dir": "repro",
        "repro_returncode": final.get("returncode"),
        "original_returncode": original_rc,
        "repro_pdf_sha256": pdf_hash,
        "original_pdf_sha256": original_pdf,
        "repro_diagnostics": _diag_signature(repro_ledger),
        "note": ("Core verdict compares sources + exit code.  PDF bytes are only "
                 "a check in deterministic mode; a timestamp difference is not "
                 "reported as a failure of the default build."),
    }


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="build manifest + reproduction check")
    ap.add_argument("--profile", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--repair", required=True, help="repair_result.json")
    ap.add_argument("--lexicon", required=True)
    a = ap.parse_args()
    prof = json.loads(Path(a.profile).read_text(encoding="utf-8"))
    rep = json.loads(Path(a.repair).read_text(encoding="utf-8"))
    lex = json.loads(Path(a.lexicon).read_text(encoding="utf-8"))
    man = build_manifest(prof, a.work, rep)
    ver = verify(prof, a.work, man, lex)
    print(json.dumps({"distribution": man["distribution"], "engine": man["engine"],
                      "verdict": ver["verdict"], "checks": ver["checks"]},
                     ensure_ascii=False, indent=2))
