#!/usr/bin/env python3
"""Turn full LaTeX logs into a deduplicated, line-addressable error ledger.

The task explicitly warns against stopping at the first error.  We therefore
scan every round and every captured .log, then deduplicate by (category,
normalised cause) so the ledger is complete without repeating the same fault
once per compilation pass.  Warnings that are only meaningful after the final
pass (undefined citations/references) are kept but labelled as such.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

LINE_L = re.compile(r"^l\.(\d+)\s*(.*)$")
FILE_LINE = re.compile(r"(?:/[^:\s]+/)?([\w\-.]+\.tex):(\d+):\s*(.*)$")
LINES_RANGE = re.compile(r"at lines (\d+)--(\d+)")
INPUT_LINE = re.compile(r"on input line (\d+)")
SEV_ORDER = {"blocking": 0, "major": 1, "minor": 2, "info": 3}

# Categories where a mechanical fix is defensible.  Anything touching the
# scientific meaning of numbers/symbols stays human-only (see lexicon).
SCRIPT_SAFE = {
    "stale_aux": True,
    "engine_encoding": True,     # switch engine / add declared unicode char
    "table_overflow": True,      # resizebox -> tabularx / smaller tabcolsep
    "reference": "partial",      # extra passes are safe; inventing labels is not
    "package": "partial",        # installing a package is safe; guessing one is not
    "math": False,
    "template": False,
}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _load_lexicon(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _find_location(lines: list[str], idx: int) -> tuple[str, str]:
    """Look ahead a few lines for a source location, like TeX prints it."""
    for j in range(idx, min(idx + 10, len(lines))):
        tail = lines[j]
        m = FILE_LINE.search(tail)
        if m:
            return f"{m.group(1)}:{m.group(2)}", _norm(m.group(3))[:160]
        m = LINE_L.match(tail.strip())
        if m:
            return f"l.{m.group(1)}", _norm(m.group(2))[:160]
        m = LINES_RANGE.search(tail)
        if m:
            return f"lines {m.group(1)}--{m.group(2)}", ""
        m = INPUT_LINE.search(tail)
        if m:
            return f"input line {m.group(1)}", _norm(tail)[:160]
        # TeX wraps long warning lines, leaving "on input line" at EOL and the
        # number on the following line.  Look ahead for that bare number.
        if tail.rstrip().endswith("on input line"):
            for k in range(j + 1, min(j + 3, len(lines))):
                m2 = re.match(r"\s*(\d+)\b", lines[k])
                if m2:
                    return f"input line {m2.group(1)}", _norm(tail)[:160]
    return "", ""


def _pattern_hits(text: str, lexicon: dict) -> list[dict]:
    hits: list[dict] = []
    lines = text.splitlines()
    compiled: list[tuple[str, str, dict]] = []
    for cat, body in lexicon.get("categories", {}).items():
        for pat in body.get("patterns", []):
            try:
                compiled.append((cat, body.get("label", cat), pat))
            except Exception:
                continue
    for i, line in enumerate(lines):
        for cat, label, pat in compiled:
            if re.search(pat["re"], line, re.IGNORECASE):
                hits.append({
                    "category": cat,
                    "category_label": label,
                    "severity": pat.get("severity", "major"),
                    "hint": pat.get("hint", ""),
                    "line": line.strip(),
                    "line_no": i,
                })
    return hits


def diagnose(build_report: dict, lexicon: dict) -> dict:
    observations: list[dict] = []
    for rnd_i, rnd in enumerate(build_report.get("rounds", []), 1):
        for log in rnd.get("logs", []):
            text = log.get("text", "")
            lines = text.splitlines()
            for hit in _pattern_hits(text, lexicon):
                loc, src_line = _find_location(lines, hit["line_no"])
                observations.append({
                    "round": rnd_i,
                    "log": Path(log.get("path", "log")).name,
                    "location": loc,
                    "source_excerpt": src_line,
                    **{k: v for k, v in hit.items() if k != "line_no"},
                })

    # Deduplicate by category + normalised message.  Keep the most severe and
    # the earliest round so the ledger points at the first cause, not a cascade.
    groups: dict[str, list[dict]] = {}
    for o in observations:
        # Dedupe by message (+location when present), NOT by category: the same
        # log line can legitimately match several patterns (e.g. a missing .sty
        # hits both 'package' and 'template').  Two ledger rows for one fault
        # would inflate the counts and confuse the reader.
        key = (_norm(re.sub(r"[0-9]+", "#", o["line"]))[:140] + "|" + o["location"])
        groups.setdefault(key, []).append(o)

    # Multi-pass builds produce expected intermediate warnings ("No file
    # main.bbl", "Citation undefined") that disappear after bibtex/latex.  The
    # task explicitly says to judge warnings only after the final pass, so a
    # successful build keeps only findings visible in its last round.  A failed
    # build keeps every observation because early errors are the real cause.
    final_round = len(build_report.get("rounds", []))
    converged = bool(build_report.get("ok"))

    findings: list[dict] = []
    next_id = 1
    for key, raw_group in sorted(groups.items(),
                                 key=lambda kv: (min(SEV_ORDER.get(x["severity"], 9)
                                                    for x in kv[1]),
                                                 min(x["round"] for x in kv[1]))):
        group = [x for x in raw_group if x["round"] == final_round] if converged and final_round else raw_group
        if not group:
            continue
        n = next_id
        next_id += 1
        first = min(group, key=lambda x: (x["round"], SEV_ORDER.get(x["severity"], 9)))
        locs = sorted({x["location"] for x in group if x["location"]})
        safe = SCRIPT_SAFE.get(first["category"], False)
        findings.append({
            "id": f"E{n:03d}",
            "category": first["category"],
            "category_label": first["category_label"],
            "severity": first["severity"],
            "location": ", ".join(locs[:4]) if locs else first["location"],
            "log_excerpt": first["line"][:300],
            "source_excerpt": first.get("source_excerpt", ""),
            "root_cause": _norm(first["line"])[:300],
            "fix": first["hint"],
            "fixable_by_script": safe,
            "reverify": ("重编译并检查该 location 的错误是否消失；"
                         "引用类须在最后一轮之后判定"),
            "rounds_seen": sorted({x["round"] for x in group}),
            "occurrences": len(group),
        })

    counts = {s: sum(1 for f in findings if f["severity"] == s)
              for s in ("blocking", "major", "minor")}
    blocking = counts["blocking"]
    ok = bool(build_report.get("ok"))
    if not ok and not findings:
        findings.append({
            "id": "E999", "category": "unknown", "category_label": "未分类",
            "severity": "blocking", "location": "",
            "log_excerpt": "", "source_excerpt": "",
            "root_cause": "编译失败但日志中没有匹配到已知错误模式",
            "fix": "查看 build_report.json 各轮完整日志，人工定位",
            "fixable_by_script": False, "reverify": "修复后重编译",
            "rounds_seen": [], "occurrences": 1,
        })
        counts["blocking"] += 1
        blocking += 1

    return {
        "findings": findings,
        "counts": counts,
        "total_observations": len(observations),
        "build_ok": ok,
        "status": ("pass" if ok and blocking == 0 else
                   "warn" if ok else "fail"),
        "note": ("Diagnostics are read from all rounds.  Undefined citations "
                 "and references are normal intermediate states; judge them "
                 "only after the final pass."),
    }


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="classify LaTeX log errors")
    ap.add_argument("--build", required=True, help="build_report.json")
    ap.add_argument("--lexicon", required=True)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    br = json.loads(Path(a.build).read_text(encoding="utf-8"))
    led = diagnose(br, _load_lexicon(a.lexicon))
    if a.out:
        p = Path(a.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(led, ensure_ascii=False, indent=2) + "\n",
                     encoding="utf-8", newline="\n")
    print(json.dumps({"status": led["status"], "counts": led["counts"],
                      "findings": len(led["findings"])}, ensure_ascii=False, indent=2))
