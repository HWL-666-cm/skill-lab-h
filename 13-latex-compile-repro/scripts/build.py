#!/usr/bin/env python3
"""Run a real, reproducible LaTeX build in an isolated work directory.

Design notes (why it is written this way):
  * Sources are copied to a scratch tree; the original case files are never
    modified.  Repairs happen on copies only (see repair.py).
  * Stdout/stderr and every .log file are captured in full.  Stopping at the
    first error is exactly what the task says NOT to do.
  * Reproducibility is defined as (source sha256, exit codes, diagnostics),
    not PDF bytes: pdfTeX embeds a creation timestamp by default, so two
    correct builds legitimately differ byte-for-byte.  --deterministic pins
    SOURCE_DATE_EPOCH when a byte-identical PDF is actually required.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

AUX_PATTERNS = (".aux", ".bbl", ".bcf", ".blg", ".out", ".toc", ".lof", ".lot",
                ".fls", ".fdb_latexmk", ".synctex.gz", ".xdv", ".log")
COPY_SUFFIXES = {".tex", ".bib", ".cls", ".sty", ".bst", ".bbx", ".cbx", ".cfg",
                 ".def", ".fd", ".png", ".jpg", ".jpeg", ".pdf", ".eps", ".svg",
                 ".ttf", ".otf", ".md", ".txt", ".json", ".yaml", ".yml",
                 ".mk", ".latexmkrc"}


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def source_manifest(src_dir: Path) -> list[dict]:
    rows: list[dict] = []
    for p in sorted(src_dir.rglob("*"), key=lambda x: str(x).lower()):
        if not p.is_file() or p.suffix.lower() not in COPY_SUFFIXES:
            continue
        rel = p.relative_to(src_dir).as_posix()
        if rel.startswith("build/"):
            continue
        rows.append({"path": rel, "bytes": p.stat().st_size, "sha256": sha256_file(p)})
    return rows


def stage_sources(src_root: Path, work_dir: Path) -> Path:
    """Copy the project into <work_dir>/src; return that path."""
    src = work_dir / "src"
    if src.exists():
        shutil.rmtree(src)
    src.mkdir(parents=True)
    for p in sorted(src_root.rglob("*"), key=lambda x: str(x).lower()):
        if not p.is_file() or p.suffix.lower() not in COPY_SUFFIXES:
            continue
        if any(part in {"build", ".git", "__pycache__"} for part in p.parts):
            continue
        rel = p.relative_to(src_root)
        dst = src / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dst)
    return src


def clean_aux(build_dir: Path) -> None:
    if not build_dir.is_dir():
        return
    for p in list(build_dir.rglob("*")):
        if not p.is_file():
            continue
        name = p.name.lower()
        if any(name.endswith(ext) for ext in AUX_PATTERNS):
            try:
                p.unlink()
            except OSError:
                pass


def _cmd(which: str, args: list[str], cwd: Path, env: dict,
         timeout: int) -> dict:
    exe = shutil.which(which)
    if not exe:
        return {"command": [which] + args, "returncode": None,
                "stdout": "", "stderr": f"executable not found: {which}",
                "timed_out": False, "unavailable": True}
    try:
        cp = subprocess.run([exe] + args, cwd=str(cwd), env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=timeout)
        out = cp.stdout.decode("utf-8", "replace")
        err = cp.stderr.decode("utf-8", "replace")
        return {"command": [which] + args, "returncode": cp.returncode,
                "stdout": out, "stderr": err, "timed_out": False,
                "unavailable": False}
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b"").decode("utf-8", "replace") if isinstance(e.stdout, bytes) else str(e.stdout or "")
        err = (e.stderr or b"").decode("utf-8", "replace") if isinstance(e.stderr, bytes) else str(e.stderr or "")
        return {"command": [which] + args, "returncode": None,
                "stdout": out, "stderr": err, "timed_out": True,
                "unavailable": False}


def command_sequence(main_tex: str, engine: str, backend: str, strategy: str,
                     build_dir: Path, src: Path | None = None) -> list[tuple[str, list[str]]]:
    """Return ordered (executable, args) pairs.

    latexmk is preferred because it decides when citations/references have
    converged; the explicit sequence is a fallback for images without it.
    The backend matters: biblatex needs biber, natbib needs bibtex.  Mixing
    them is a documented failure mode, so we never guess once either is seen.
    """
    if strategy == "latexmk":
        args = [f"-{engine}", "-interaction=nonstopmode", "-file-line-error",
                "-outdir=" + str(build_dir), main_tex]
        return [("latexmk", args)]
    seq: list[tuple[str, list[str]]] = []
    base = ["-interaction=nonstopmode", "-file-line-error",
            "-output-directory=" + str(build_dir), main_tex]
    seq.append((engine, base))
    stem = Path(main_tex).stem
    # bibtex/biber are Perl-backed on Windows and refuse absolute paths with
    # non-ASCII characters (openout_any = p).  They run from build_dir with a
    # bare stem; run_build copies .bib files there first so everything they
    # need is local.  TeX engines still run from src.
    if backend == "biblatex":
        seq.append(("biber", [stem]))
    elif backend == "natbib":
        seq.append(("bibtex", [stem]))
    seq.append((engine, base))
    seq.append((engine, base))
    return seq


def cwd_for(exe: str, src: Path, build_dir: Path) -> Path:
    """Bibliography tools run from build_dir with bare names; TeX runs from src."""
    return build_dir if exe in ("bibtex", "biber") else src


def run_build(profile: dict, work_dir: str | Path, engine: str | None = None,
              strategy: str = "auto", deterministic: bool = False,
              timeout: int = 90, clean_aux_first: bool = True) -> dict:
    """Compile the staged source; return a build report with full logs."""
    work = Path(work_dir).resolve()
    work.mkdir(parents=True, exist_ok=True)
    src_root = Path(profile["root"])
    src = stage_sources(src_root, work)
    build_dir = work / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    if clean_aux_first:
        clean_aux(build_dir)
    # bibtex/biber run from build_dir with bare filenames; give them a local
    # copy of the bibliography so no absolute (possibly non-ASCII) path is used.
    for p in src.rglob("*.bib"):
        target = build_dir / p.name
        if not target.exists():
            shutil.copy2(p, target)

    eng = engine or profile.get("engine") or "pdflatex"
    backend = profile.get("bib_backend") or "none"
    main_abs = profile.get("main_tex") or ""
    if not main_abs:
        return {"ok": False, "reason": "no main .tex", "work_dir": str(work)}
    main_rel = ""
    try:
        main_rel = Path(main_abs).resolve().relative_to(src_root).as_posix()
    except ValueError:
        main_rel = Path(main_abs).name
    if not (src / main_rel).is_file():
        cand = src / Path(main_abs).name
        if cand.is_file():
            main_rel = cand.name
        else:
            return {"ok": False, "reason": f"main tex not staged: {main_abs}",
                    "work_dir": str(work)}

    # Strategy: latexmk if usable, else an explicit pdflatex/bibtex sequence.
    # "Installed" is not the same as "usable": on some Windows setups latexmk's
    # Perl wrapper dies on non-ASCII paths before TeX ever runs.  Detect that at
    # runtime and fall back, otherwise the log has no LaTeX error at all.
    if strategy == "auto":
        strategy = "latexmk" if shutil.which("latexmk") else "sequence"

    env = os.environ.copy()
    if deterministic:
        env["SOURCE_DATE_EPOCH"] = "946684800"  # 2000-01-01, fixed and documented

    def execute(seq: list[tuple[str, list[str]]]) -> list[dict]:
        out: list[dict] = []
        for exe, args in seq:
            rec = _cmd(exe, args, cwd_for(exe, src, build_dir), env, timeout)
            log_files = []
            for p in sorted(build_dir.rglob("*.log"), key=lambda x: x.name):
                log_files.append({"path": str(p), "sha256": sha256_file(p),
                                  "text": p.read_text(encoding="utf-8", errors="replace")})
            rec["logs"] = log_files
            rec["pdf"] = None
            pdf = build_dir / (Path(main_rel).stem + ".pdf")
            if pdf.is_file():
                rec["pdf"] = {"path": str(pdf), "bytes": pdf.stat().st_size,
                              "sha256": sha256_file(pdf)}
            out.append(rec)
            if rec.get("unavailable"):
                break
        return out

    rounds = execute(command_sequence(main_rel, eng, backend, strategy, build_dir, src))
    latexmk_note = ""
    if strategy == "latexmk":
        r0 = rounds[0] if rounds else {}
        blob = (r0.get("stdout", "") + "\n" + r0.get("stderr", "")).lower()
        wrapper_broken = any(s in blob for s in (
            "runscript.tlu", "perl.exe", "cannot write file", "cannot open",
            "no such file or directory", "falling back to a fallback locale"))
        no_tex_log = not any(x.get("logs") for x in rounds)
        if (r0.get("returncode") not in (0, None) and (wrapper_broken or no_tex_log)) \
                or r0.get("unavailable"):
            latexmk_note = ("latexmk wrapper failed at runtime "
                            "(Perl/path/locale); fell back to explicit sequence")
            clean_aux(build_dir)
            strategy = "sequence"
            rounds = execute(command_sequence(main_rel, eng, backend,
                                              "sequence", build_dir, src))

    final = rounds[-1] if rounds else {}
    logs = final.get("logs") or []
    all_log_text = "\n".join(x["text"] for x in logs)
    ok = bool(final.get("returncode") == 0 and "Output written on" in all_log_text)
    report = {
        "ok": ok,
        "work_dir": str(work),
        "source_dir": str(src),
        "build_dir": str(build_dir),
        "engine": eng,
        "backend": backend,
        "strategy": strategy,
        "deterministic": deterministic,
        "source_hashes": source_manifest(src),
        "rounds": rounds,
        "final_returncode": final.get("returncode"),
        "final_pdf": final.get("pdf"),
        "log_chars": len(all_log_text),
        "latexmk_note": latexmk_note,
        "reason": "" if ok else "build did not converge (see rounds/logs)",
    }
    (work / "build_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n")
    return report


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="run a real LaTeX build")
    ap.add_argument("--profile", required=True, help="project_profile.json")
    ap.add_argument("--work", required=True)
    ap.add_argument("--engine", default="")
    ap.add_argument("--strategy", default="auto", choices=["auto", "latexmk", "sequence"])
    ap.add_argument("--deterministic", action="store_true")
    ap.add_argument("--timeout", type=int, default=90)
    a = ap.parse_args()
    prof = json.loads(Path(a.profile).read_text(encoding="utf-8"))
    rep = run_build(prof, a.work, a.engine or None, a.strategy, a.deterministic, a.timeout)
    print(json.dumps({k: rep.get(k) for k in
                      ("ok", "engine", "strategy", "final_returncode", "log_chars", "reason")},
                     ensure_ascii=False, indent=2))
