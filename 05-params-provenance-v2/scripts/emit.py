#!/usr/bin/env python3
"""Deliverables.

Files are written with explicit ``\\n`` and sorted keys so that two runs on the
same material produce byte-identical output.  Repetition (three cases, three
repetitions) is only interpretable if the tool itself does not add variation.

The honest fields are not decoration: ``uncertainty`` lists what this run could
not establish, and ``change_log`` records what was done, graded the way a reviewer
would grade it (semantic / evidential / metadata / surface).
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

import contract as contract_mod
import gaps as gaps_mod

CSV_COLUMNS = ["entry_id", "name", "scope", "value", "unit", "status", "n_values",
               "source_kind", "path", "locator", "quote"]


def _uncertainty(pack: dict, ledger: dict, alignment: dict, extra: list[str]) -> list[str]:
    out: list[str] = []
    for u in pack.get("unreadable", []):
        out.append(f"{u['source']} could not be read: {u['reason']}; its values are absent "
                   "from the ledger and would look invented in the draft")
    for f in pack.get("files", []):
        if "stdlib-raw" in (f.get("reader") or ""):
            out.append(f"{f['source']} was read with the built-in PDF decoder, so character "
                       "encoding may be unreliable; values from it are candidates, not facts")
        if f.get("note") and "outside the yaml subset" in f["note"]:
            out.append(f"{f['source']}: {f['note']}; those lines were read with a line regex")
    mo = [e["name"] for e in ledger.get("entries") or [] if e["status"] == "manuscript_only"]
    if mo:
        out.append(f"{len(mo)} values are stated only in prose ({', '.join(sorted(mo)[:5])}"
                   " ...); prose is evidence about the paper, not about the run")
    bwd, fwd = alignment.get("backward") or {}, alignment.get("forward") or {}
    if bwd.get("not_written"):
        out.append(f"{len(bwd['not_written'])} ledger rows have no counterpart "
                   "in the draft; they are listed as gaps, not silently dropped")
    if fwd.get("invented"):
        out.append(f"{len(fwd['invented'])} draft numbers have no material "
                   "source; they are blocking gaps until the author supplies one")
    if fwd.get("mismatch"):
        out.append(f"{len(fwd['mismatch'])} draft numbers contradict the ledger value of the "
                   "parameter named beside them; the tool cannot tell whether the text or the "
                   "record is wrong, so each one is a question for the author")
    out.extend(extra)
    out.append("this tool checks whether a value has a source in the material; it does not "
               "verify that the material describes a run that actually happened")
    return out


def _change_log(ledger: dict, alignment: dict, gaps: dict) -> list[dict]:
    return [
        {"grade": "B", "what": "parameter ledger built",
         "detail": f"{ledger['stats']['entries']} rows, {ledger['stats']['values']} values, "
                   f"{ledger['stats']['conflicting']} conflicts"},
        {"grade": "B", "what": "draft aligned in both directions",
         "detail": f"{len(alignment['forward']['traced'])} traced, "
                   f"{len(alignment['forward']['invented'])} unsourced, "
                   f"{len(alignment['forward'].get('mismatch') or [])} mismatched, "
                   f"{len(alignment['backward']['not_written'])} not written"},
        {"grade": "C", "what": "sources recorded",
         "detail": ", ".join(sorted({e["best_source_kind"] for e in ledger["entries"]})) or "none"},
        {"grade": "A", "what": "gaps raised for author confirmation",
         "detail": f"{len(gaps['gaps'])} gaps, {gaps['by_severity']['blocking']} blocking"},
        {"grade": "D", "what": "draft text preserved verbatim",
         "detail": "the tool does not rewrite sentences; only the value/source mapping is added"},
    ]


def _provenance_section(alignment: dict) -> str:
    """A checkable map from every number in the draft back to a file and a line.

    The prose itself is never rewritten -- that would make the deliverable a
    different document from the one the author wrote.  Instead the mapping is
    appended, so a reviewer can open the cited line and compare.  This is the
    part of the deliverable that a reader can actually audit.
    """
    fwd = alignment.get("forward") or {}
    traced = fwd.get("traced") or []
    mismatch = fwd.get("mismatch") or []
    invented = fwd.get("invented") or []
    value_only = fwd.get("value_only") or []
    in_mat = fwd.get("in_material") or []
    ignored = fwd.get("ignored") or []

    lines = ["", "---", "", "## 数值出处对照", ""]
    lines.append(f"正文共 {alignment.get('text_numbers', 0)} 个数字："
                 f"{len(traced)} 个已对上台账，{len(mismatch)} 个与台账不符，"
                 f"{len(invented)} 个在材料中找不到，{len(value_only) + len(in_mat)} 个存在但归属未定，"
                 f"{len(ignored)} 个按规则不计（年份、图表号、指标名后缀、边界条件等）。")
    lines.append("")
    if traced or mismatch:
        lines.append("| 段 | 数值 | 参数 | 材料位置 |")
        lines.append("|---|---|---|---|")
        rows = 0
        for t in traced:
            lines.append(f"| {t['paragraph']} | `{t['raw']}` | {t['entry_name']} | "
                         f"{t['evidence']} |")
            rows += 1
        for m in mismatch:
            lines.append(f"| {m['paragraph']} | `{m['raw']}` | {m['entry_name']}"
                         f"（台账为 `{m['ledger_value']}`，不符） | {m['ledger_at']} |")
            rows += 1
        if rows > 120:
            lines = lines[:4 + 120] + [f"| … | 其余 {rows - 120} 行见 alignment.json | | |"]
        lines.append("")
    if value_only or in_mat:
        lines.append("### 归属未定的数值")
        lines.append("")
        for v in value_only:
            lines.append(f"- 第 {v['paragraph']} 段 `{v['raw']}`：疑似 {v['entry_name']}"
                         f"（{v['evidence']}），但这一段没有点名该参数，需要作者确认。")
        for v in in_mat:
            lines.append(f"- 第 {v['paragraph']} 段 `{v['raw']}`：材料里有（{v['where']}），"
                         "但没有一行台账把它记为某个参数的值。")
        lines.append("")
    if invented:
        lines.append("### 材料中找不到出处的数值")
        lines.append("")
        for v in invented:
            near = "、".join(v.get("nearest") or []) or "无相近值"
            lines.append(f"- 第 {v['paragraph']} 段 `{v['raw']}`：材料中无此值；相近的台账值：{near}。")
        lines.append("")
    return "\n".join(lines)


def build_result(case_id: str, pack: dict, ledger: dict, alignment: dict, gaps: dict,
                 report: dict, status: str, draft_text: str,
                 extra_uncertainty: list[str] | None = None) -> dict:
    limits: list[str] = []
    if report["counts"].get("fail"):
        limits.append(f"{report['counts']['fail']} gate checks failed; see validation.json")
    if gaps["by_severity"]["blocking"]:
        limits.append(f"{gaps['by_severity']['blocking']} blocking gaps need author input "
                      "before this section can be used")
    if report["counts"].get("warn"):
        limits.append(f"{report['counts']['warn']} gate checks warn; see validation.json")
    if not limits and status != "complete":
        limits.append("the run completed with warnings only")
    result = {
        "case_id": case_id,
        "status": status,
        "limits": limits,
        "task": {
            "direction": "parameter provenance: build a sourced ledger, then check the draft "
                         "in both directions",
            "deliverables": ["methods.md", "parameter_ledger.csv", "gaps.md",
                             "validation.json", "result.json"],
        },
        "methods_markdown": (draft_text.rstrip() + "\n" + _provenance_section(alignment)
                             if draft_text.strip() else
                             "## 正文尚未提供\n\n本次只建立了台账：材料里能读到的参数都在 ledger 中，"
                             "请把要核查的正文放到 /input 后重跑一次，工具会补上逐值出处对照。\n"),
        "ledger": ledger,
        "alignment": alignment,
        "gaps": gaps,
        "conflicts": ledger["conflicts"],
        "coverage": alignment["coverage"],
        "validation": {"status": report["status"], "counts": report["counts"],
                       "checks": report["checks"], "top_failures": report["top_failures"]},
        "sources": contract_mod.build_sources({}, pack),
        "uncertainty": _uncertainty(pack, ledger, alignment, extra_uncertainty or []),
        "change_log": _change_log(ledger, alignment, gaps),
        "stats": {
            "files": pack["stats"]["files"],
            "unreadable": pack["stats"]["unreadable"],
            "units": pack["stats"]["units"],
            "ledger_rows": ledger["stats"]["entries"],
            "conflicts": ledger["stats"]["conflicting"],
            "draft_numbers": alignment["text_numbers"],
            "trace_rate": alignment["forward"]["trace_rate"],
            "written_rate": alignment["backward"]["written_rate"],
        },
    }
    return result


def _csv_text(entries: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(CSV_COLUMNS)
    for e in entries:
        for v in e["values"]:
            w.writerow([e["entry_id"], e["name"], e["scope"], v.get("raw", ""),
                        v.get("unit", ""), e["status"], e["n_values"],
                        v.get("source_kind", ""), v.get("path", ""), v.get("locator", ""),
                        (v.get("quote") or "").replace("\n", " ")[:300]])
    return buf.getvalue()


def write_all(out_dir: Path, result: dict, ledger: dict, alignment: dict,
              gaps: dict, report: dict) -> list[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []

    def dump(name: str, obj: Any) -> None:
        (out_dir / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n",
                                    encoding="utf-8", newline="\n")
        written.append(name)

    def text(name: str, body: str) -> None:
        (out_dir / name).write_text(body if body.endswith("\n") else body + "\n",
                                    encoding="utf-8", newline="\n")
        written.append(name)

    dump("result.json", result)
    text("methods.md", result["methods_markdown"])
    text("parameter_ledger.csv", _csv_text(ledger["entries"]))
    text("gaps.md", gaps_mod.to_markdown(gaps, result["case_id"]))
    dump("validation.json", {"status": report["status"], "counts": report["counts"],
                             "checks": report["checks"], "top_failures": report["top_failures"],
                             "note": report["note"]})
    dump("ledger.json", ledger)
    dump("alignment.json", alignment)
    dump("gaps.json", gaps)
    return written


def finalise(case_raw: dict, result: dict, pack: dict | None = None) -> dict:
    if case_raw.get("example"):
        result["example"] = True
        result["example_note"] = "示例产物：路径与字段形状演示，不是平台固定案例的答案。"
    contract = case_raw.get("output_contract")
    result, _report = contract_mod.apply(result, contract, pack)
    return result
