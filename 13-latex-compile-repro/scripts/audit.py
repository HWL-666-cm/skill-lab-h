#!/usr/bin/env python3
"""Source-level correctness audit on the FINAL (post-fix) source.

diagnose.py is log-driven and runs at compile time.  This module reads the
final .tex / .bib source and checks structural correctness that a *successful*
compile does not guarantee — the "改得对 / 交得可用" half of the task:

1. citation   : \\cite* keys vs .bib entry keys (missing / unused / near-miss typo)
2. cross_ref  : \\label keys vs \\ref/\\eqref/\\pageref/\\autoref (undefined / unused)
3. layout     : visual-fragility patterns that compile clean but produce
                wrong or hard-to-maintain output (shrink-to-fit, tiny table
                font, label-before-caption, forced float placement)

Every finding carries a location (file:line) and a concrete suggestion.  These
are evidence for the reviewer, not a licence to edit scientific content: the
audit only *reports*; it never rewrites the manuscript.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

# --- citation / reference command families ---------------------------------
_CITE_RE = re.compile(
    r"\\(?:cite|citet|citep|textcite|parencite|autocite|citeauthor|citeyear|"
    r"fullcite|supercite|footcite)(?:\*)?(?:\s*\[[^\]]*\])*\s*\{([^}]+)\}")
_BIB_ENTRY_RE = re.compile(r"@[A-Za-z]+\s*\{\s*([^,\s]+)\s*,")
_LABEL_RE = re.compile(r"\\label\s*\{([^}]+)\}")
_REF_RE = re.compile(
    r"\\(?:eqref|ref|pageref|autoref|cref|Cref|nameref|vref)(?:\*)?\s*\{([^}]+)\}")

# --- visual-fragility layout patterns --------------------------------------
# resizebox/adjustbox hard-shrinks a table/figure: major.  scalebox is often a
# legitimate TikZ/overlay node scaling, so it is downgraded to minor.
_SHRINK_RE = re.compile(r"\\(?:resizebox|adjustbox)\s*[\[{]")
_SCALEBOX_RE = re.compile(r"\\scalebox\s*[\[{]")
_TINY_TABLE_RE = re.compile(r"\\(?:tiny|scriptsize|footnotesize)\b")
_FLOAT_BEGIN_RE = re.compile(r"\\begin\{(figure|table)\*?\}")
_LABEL_RE_BODY = re.compile(r"\\label\s*\{[^}]*\}")
_CAPTION_RE_BODY = re.compile(r"\\caption\s*[\[{]")
_FORCED_FLOAT_RE = re.compile(r"\\begin\{(?:figure|table)\}\s*\[\s*[H!]")

_SEV = {"missing": "major", "undefined": "major", "shrink_to_fit": "major",
        "label_before_caption": "major", "unused": "minor", "near_miss": "minor",
        "tiny_table_font": "minor", "forced_float": "minor",
        "scalebox_scaling": "minor"}


def _tex_files(prof: dict) -> list[Path]:
    """Main .tex plus every \\input / \\include'd file (one level deep is enough)."""
    out: list[Path] = []
    main = prof.get("main_tex")
    if not main or not Path(main).exists():
        return out
    out.append(Path(main))
    root = Path(prof.get("root") or Path(main).parent)
    text = Path(main).read_text(encoding="utf-8", errors="replace")
    for m in re.finditer(r"\\(?:input|include)\s*\{([^}]+)\}", text):
        name = m.group(1)
        for cand in (root / name, root / (name + ".tex")):
            if cand.exists():
                out.append(cand)
    return out


def _bib_files(prof: dict) -> list[Path]:
    out: list[Path] = []
    root = Path(prof.get("root") or (Path(prof["main_tex"]).parent
                                     if prof.get("main_tex") else Path(".")))
    for f in _tex_files(prof):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in re.finditer(r"\\(?:bibliography|addbibresource)\s*\{([^}]+)\}", text):
            for name in m.group(1).split(","):
                name = name.strip()
                if not name:
                    continue
                for cand in (root / name, root / (name + ".bib")):
                    if cand.exists():
                        out.append(cand)
    return out


def _all_source_text(prof: dict) -> tuple[str, list[tuple[Path, int]]]:
    """Concatenated source + a per-character offset table mapping index -> (file, line)."""
    text_parts: list[str] = []
    offsets: list[tuple[Path, int]] = []
    for f in _tex_files(prof):
        try:
            t = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for ln, line in enumerate(t.splitlines(keepends=True), start=1):
            text_parts.append(line)
            offsets.extend([(f, ln)] * len(line))
        text_parts.append("\n")  # separator between files
        offsets.append((f, -1))
    return "".join(text_parts), offsets


def _locate(offsets: list[tuple[Path, int]], pos: int) -> str:
    """Map a character offset in the concatenated text to 'file:line'."""
    idx = min(pos, len(offsets) - 1) if offsets else 0
    f, ln = offsets[idx]
    if ln == -1:  # a separator newline; fall back to the previous real line
        for i in range(idx, -1, -1):
            if offsets[i][1] != -1:
                f, ln = offsets[i]
                break
    return f"{Path(f).name}:{ln}"


def _near_miss(key: str, candidates: set[str]) -> str | None:
    """Return the closest candidate if within edit distance 1 (same length) or 2."""
    if key in candidates:
        return None
    best, best_d = None, 3
    for c in candidates:
        if abs(len(c) - len(key)) > 2:
            continue
        d = _lev(key, c)
        if d < best_d:
            best, best_d = c, d
    return best if best_d <= 2 else None


def _lev(a: str, b: str) -> int:
    if abs(len(a) - len(b)) > 2:
        return 99
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(cur[-1] + 1, prev[j] + 1,
                           prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _findings_citation(prof: dict) -> list[dict]:
    src, offs = _all_source_text(prof)
    cited: dict[str, str] = {}
    for m in _CITE_RE.finditer(src):
        for k in m.group(1).split(","):
            k = k.strip()
            if k and k not in cited:
                cited[k] = _locate(offs, m.start())
    bib_keys: set[str] = set()
    for bf in _bib_files(prof):
        try:
            bt = bf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        bib_keys |= set(_BIB_ENTRY_RE.findall(bt))
    out: list[dict] = []
    for k, loc in cited.items():
        if k not in bib_keys:
            miss = _near_miss(k, bib_keys)
            out.append({
                "id": f"CITE-{k}", "check": "citation", "kind": "missing",
                "severity": _SEV["missing"], "location": loc,
                "detail": f"\\cite 键 '{k}' 在 .bib 中没有对应条目",
                "suggestion": (f"可能是 '{miss}' 的拼写错误，或需在 .bib 中补该条目"
                               if miss else "在 .bib 中补该条目，或修正 \\cite 键"),
            })
    for k in sorted(bib_keys):
        if k not in cited:
            out.append({
                "id": f"CITE-UNUSED-{k}", "check": "citation", "kind": "unused",
                "severity": _SEV["unused"], "location": ".bib",
                "detail": f".bib 条目 '{k}' 从未被正文引用",
                "suggestion": "确认是否需要引用；不需要可从 .bib 删除（或保留并说明用途）",
            })
    return out


def _findings_cross_ref(prof: dict) -> list[dict]:
    src, offs = _all_source_text(prof)
    labels = {m.group(1): _locate(offs, m.start()) for m in _LABEL_RE.finditer(src)}
    refs: dict[str, str] = {}
    for m in _REF_RE.finditer(src):
        for k in re.split(r"\s*,\s*", m.group(1)):
            if k and k not in refs:
                refs[k] = _locate(offs, m.start())
    out: list[dict] = []
    for k, loc in refs.items():
        if k not in labels:
            miss = _near_miss(k, set(labels))
            out.append({
                "id": f"REF-{k}", "check": "cross_ref", "kind": "undefined",
                "severity": _SEV["undefined"], "location": loc,
                "detail": f"\\ref/\\eqref 指向不存在的 \\label '{k}'（最终产物会显示 '??'）",
                "suggestion": (f"可能是 '{miss}' 的拼写错误，或补 \\label{{{k}}}"
                               if miss else f"补 \\label{{{k}}}，或修正引用键"),
            })
    for k, loc in labels.items():
        if k not in refs:
            out.append({
                "id": f"LABEL-UNUSED-{k}", "check": "cross_ref", "kind": "unused",
                "severity": _SEV["unused"], "location": loc,
                "detail": f"\\label '{k}' 从未被 \\ref 引用",
                "suggestion": "确认是否需要保留该标签",
            })
    return out


def _findings_layout(prof: dict) -> list[dict]:
    out: list[dict] = []
    for f in _tex_files(prof):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines = text.splitlines()
        in_table = False
        for i, ln in enumerate(lines, start=1):
            if "\\begin{tabular" in ln or "\\begin{longtable" in ln or \
               "\\begin{tabularx" in ln:
                in_table = True
            elif "\\end{tabular" in ln or "\\end{longtable" in ln or \
                 "\\end{tabularx" in ln:
                in_table = False
            loc = f"{Path(f).name}:{i}"
            if _SHRINK_RE.search(ln):
                out.append({
                    "id": f"SHRINK-{i}", "check": "layout", "kind": "shrink_to_fit",
                    "severity": _SEV["shrink_to_fit"], "location": loc,
                    "detail": "用 \\resizebox/\\adjustbox 硬缩放表格或图",
                    "suggestion": "用 tabularx 的 X 列、p{} 定宽列或减小 \\tabcolsep，"
                                  "保持字号与线宽一致",
                })
            if _SCALEBOX_RE.search(ln):
                out.append({
                    "id": f"SCALE-{i}", "check": "layout", "kind": "scalebox_scaling",
                    "severity": _SEV["scalebox_scaling"], "location": loc,
                    "detail": "用 \\scalebox 缩放（TikZ/覆盖层里缩放节点常见，一般无害）",
                    "suggestion": "若缩放的是整张表/整图请改用 tabularx 或定宽列；"
                                  "缩放单个节点则无需处理",
                })
            if in_table and _TINY_TABLE_RE.search(ln):
                out.append({
                    "id": f"TINY-{i}", "check": "layout", "kind": "tiny_table_font",
                    "severity": _SEV["tiny_table_font"], "location": loc,
                    "detail": "表格内用 \\tiny/\\scriptsize 缩字号",
                    "suggestion": "优先重排列宽，字号统一到 \\small 及以上",
                })
            if _FORCED_FLOAT_RE.search(ln):
                out.append({
                    "id": f"FLOAT-{i}", "check": "layout", "kind": "forced_float",
                    "severity": _SEV["forced_float"], "location": loc,
                    "detail": "用 [H]/[!h] 强行固定浮动体位置",
                    "suggestion": "让 TeX 自己决定位置，用 \\ref 交叉引用",
                })

        # label-before-caption must be checked inside a whole float, not per line:
        # the canonical form puts \\label and \\caption on SEPARATE lines.
        for m in _FLOAT_BEGIN_RE.finditer(text):
            kind = m.group(1)
            end = re.search(rf"\\end\{{{kind}\*?\}}", text[m.end():])
            body_end = m.end() + (end.start() if end else len(text) - m.end())
            body = text[m.end():body_end]
            lab = _LABEL_RE_BODY.search(body)
            cap = _CAPTION_RE_BODY.search(body)
            if lab and cap and lab.start() < cap.start():
                line_no = text[:m.end() + lab.start()].count("\n") + 1
                out.append({
                    "id": f"LBC-{line_no}", "check": "layout",
                    "kind": "label_before_caption", "severity": _SEV["label_before_caption"],
                    "location": f"{Path(f).name}:{line_no}",
                    "detail": "浮动体里 \\label 出现在 \\caption 之前（\\ref 会编号错）",
                    "suggestion": "把 \\label 移到 \\caption 之后",
                })
    return out


def audit_source(prof: dict) -> dict:
    findings = (_findings_citation(prof) + _findings_cross_ref(prof)
                + _findings_layout(prof))
    counts = {"major": 0, "minor": 0}
    for f in findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    return {
        "findings": findings,
        "counts": counts,
        "status": "clean" if counts.get("major", 0) == 0 else "issues",
        "note": ("源码级正确性审计，只报告不改写；major 项会使 result 标 partial，"
                 "因为这些是最终产物里的真实缺陷"),
    }


if __name__ == "__main__":
    import sys as _s
    _s.path.insert(0, str(Path(__file__).resolve().parent))
    import profile as _p
    prof = _p.profile(Path(_s.argv[1]), Path(_s.argv[2]) if len(_s.argv) > 2 else Path("/tmp/audit-work"))
    print(json.dumps(audit_source(prof), ensure_ascii=False, indent=2))
