#!/usr/bin/env python3
"""Profile a LaTeX project before compiling it.

Why this exists: the engine choice decides everything downstream.  A CJK or
unicode source compiled with pdflatex fails on inputenc before any real bug is
visible, so the compiler would keep 'fixing' the wrong thing.  We inspect the
actual source (not labels) to infer the engine, bib backend and file roles.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

SKIP_DIRS = {".git", "__pycache__", "node_modules", "tmp", "build", "out"}
TEXT_EXT = {".tex", ".bib", ".cls", ".sty", ".bst", ".bbx", ".cbx", ".cfg",
            ".mk", ".md", ".txt", ".json", ".yaml", ".yml", ".def", ".fd", ".tfm"}
TEX_EXT = {".tex"}
BIB_EXT = {".bib"}
CLASS_EXT = {".cls", ".sty", ".bst", ".bbx", ".cbx", ".def"}


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            return p.read_text(encoding="gb18030")
        except Exception:
            return ""
    except Exception:
        return ""


def resolve_case(case_path: Path) -> tuple[dict, Path, str]:
    """Return (case dict, material root, case_id)."""
    case_path = Path(case_path).resolve()
    if case_path.is_dir():
        for name in ("case.json", "input.json"):
            if (case_path / name).is_file():
                raw = json.loads(_read(case_path / name) or "{}")
                return raw, case_path, str(raw.get("case_id") or case_path.name)
        return {}, case_path, case_path.name
    raw = json.loads(_read(case_path) or "{}")
    base = case_path.parent
    for key in ("material_dir", "project_dir", "input_dir", "material_path"):
        v = raw.get(key)
        if isinstance(v, str) and v:
            p = Path(v)
            if not p.is_absolute():
                p = (base / p).resolve()
            if p.is_dir():
                return raw, p, str(raw.get("case_id") or base.name)
    for key in ("material_dirs", "project_dirs"):
        v = raw.get(key)
        if isinstance(v, list) and v:
            p = Path(v[0])
            if not p.is_absolute():
                p = (base / p).resolve()
            if p.is_dir():
                return raw, p, str(raw.get("case_id") or base.name)
    return raw, base, str(raw.get("case_id") or base.name)


def _iter_files(root: Path, extra_roots: list[Path]) -> list[Path]:
    out: list[Path] = []
    seen: set[Path] = set()
    for base in [root] + list(extra_roots):
        if not base or not base.is_dir():
            continue
        for p in base.rglob("*"):
            if not p.is_file():
                continue
            if any(part in SKIP_DIRS for part in p.parts):
                continue
            rp = p.resolve()
            if rp in seen:
                continue
            seen.add(rp)
            out.append(p)
    return sorted(out, key=lambda p: str(p).lower())


DOCCLASS_RE = re.compile(r"\\documentclass\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}")
INPUT_RE = re.compile(r"\\(?:input|include)\s*\{([^}]+)\}")
BIB_RE = re.compile(r"\\bibliography\s*\{([^}]+)\}")
ADDBIB_RE = re.compile(r"\\addbibresource\s*\{([^}]+)\}")
PKG_RE = re.compile(r"\\usepackage\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}")
CJK_CMD_RE = re.compile(r"\\usepackage\s*(?:\[[^\]]*\])?\s*\{(ctex|xeCJK|CJK|fontspec)")
NON_ASCII_RE = re.compile(r"[^\x00-\x7f]")


def profile(case_path: str | Path, out_dir: str | Path | None = None) -> dict:
    raw, root, case_id = resolve_case(Path(case_path))
    extra: list[Path] = []
    for key in ("material_dirs", "project_dirs"):
        vals = raw.get(key)
        if isinstance(vals, list):
            for v in vals:
                if not isinstance(v, str) or not v:
                    continue
                p = Path(v)
                if not p.is_absolute():
                    p = (root / p).resolve()
                if p.is_dir():
                    extra.append(p)

    files = _iter_files(root, extra)
    tex_files = [p for p in files if p.suffix.lower() in TEX_EXT]
    contents: dict[str, str] = {}
    for p in tex_files:
        contents[str(p)] = _read(p)

    main: Path | None = None
    for p in tex_files:
        if DOCCLASS_RE.search(contents.get(str(p), "")):
            main = p
            break
    if main is None and tex_files:
        main = tex_files[0]

    # Inline source in case.json is a valid fallback when no .tex file is on disk.
    inline = ""
    for key in ("latex", "tex", "source", "latex_source", "tex_source"):
        v = raw.get(key)
        if isinstance(v, str) and DOCCLASS_RE.search(v):
            inline = v
            break

    main_text = contents.get(str(main), "") if main else inline
    docclass = DOCCLASS_RE.search(main_text)
    packages = set()
    for m in PKG_RE.finditer(main_text):
        for token in m.group(1).split(","):
            packages.add(token.strip())

    cjk = bool(CJK_CMD_RE.search(main_text)) or bool(
        re.search(r"[一-鿿]", main_text))
    unicode_chars = NON_ASCII_RE.findall(main_text)
    # Filter out common punctuation that survived copy-paste but is harmless when
    # the engine is xelatex; any non-ascii still pushes us toward unicode engine.
    use_unicode_engine = bool(unicode_chars) or bool(packages & {"fontspec", "xeCJK", "ctex", "CJK"})
    engine = "xelatex" if use_unicode_engine else "pdflatex"
    reason = ("non-ASCII/CJK characters or unicode packages detected"
              if use_unicode_engine else "ASCII-only source with no fontspec/ctex")

    bib_backend = "none"
    if "biblatex" in packages or ADDBIB_RE.search(main_text):
        bib_backend = "biblatex"
    elif "natbib" in packages or BIB_RE.search(main_text):
        bib_backend = "natbib"

    sub_inputs: list[str] = []
    for m in INPUT_RE.finditer(main_text):
        sub_inputs.append(m.group(1))
    bib_names: list[str] = []
    for m in BIB_RE.finditer(main_text):
        bib_names.extend(x.strip() for x in m.group(1).split(","))
    for m in ADDBIB_RE.finditer(main_text):
        bib_names.append(m.group(1).strip())

    file_rows: list[dict] = []
    for p in files:
        ext = p.suffix.lower()
        if ext in CLASS_EXT:
            kind, role = "class_or_style", "template dependency"
        elif ext in BIB_EXT:
            kind, role = "bib", "bibliography database"
        elif ext in TEX_EXT:
            if main and p == main:
                kind, role = "main_tex", "root document"
            else:
                kind, role = "sub_tex", "included fragment"
        elif ext in {".png", ".jpg", ".jpeg", ".pdf", ".eps", ".svg"}:
            kind, role = "figure", "referenced figure"
        elif ext in {".ttf", ".otf"}:
            kind, role = "font", "referenced font"
        else:
            kind, role = "aux_file", "support file"
        file_rows.append({
            "path": str(p),
            "name": p.name,
            "kind": kind,
            "role": role,
            "bytes": p.stat().st_size,
        })

    result = {
        "case_id": case_id,
        "root": str(root),
        "main_tex": str(main) if main else "",
        "inline_source_present": bool(inline),
        "documentclass": docclass.group(1) if docclass else "",
        "engine": engine,
        "engine_reason": reason,
        "unicode_detected": bool(unicode_chars),
        "cjk_detected": cjk,
        "bib_backend": bib_backend,
        "packages": sorted(packages),
        "sub_inputs": sub_inputs,
        "bib_names": bib_names,
        "files": file_rows,
        "issues": [],
    }
    if not main and not inline:
        result["issues"].append("no .tex with \\documentclass and no inline source found")
    if not file_rows and not inline:
        result["issues"].append("no readable project files found under material root")

    if out_dir:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "project_profile.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8", newline="\n")
    return result


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="profile a LaTeX case project")
    ap.add_argument("--case", required=True)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    print(json.dumps(profile(a.case, a.out or None), ensure_ascii=False, indent=2))
