#!/usr/bin/env python3
"""Emit draft, claim ledger, coverage, validation and contract-compliant result."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import contract as contract_mod
from gaps import markdown as gaps_markdown

SECTION_LABEL = {"background": "研究背景", "related_work": "相关工作",
                 "gap": "研究空白", "contribution": "贡献"}
SECTION_ORDER = ["background", "related_work", "gap", "contribution"]


def _write(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(obj, str):
        path.write_text(obj, encoding="utf-8", newline="\n")
    else:
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8", newline="\n")


def draft_from_ledger(al: dict, cands: dict, case_raw: dict) -> str:
    """Rule-only floor.  It is honest but mechanical: the Harness is expected
    to write the real prose; this is the fallback when it cannot."""
    rows = al.get("forward", {}).get("rows", [])
    by: dict[str, list[str]] = {}
    for r in rows:
        sec = r.get("claim_type") if r.get("claim_type") in SECTION_LABEL else "other"
        if sec != "other":
            by.setdefault(sec, []).append(r.get("sentence", ""))
    title = str(case_raw.get("title") or case_raw.get("task") or "引言与相关工作")[:120]
    lines = [f"# {title}", "", "> 规则生成底稿（机械复述，非最终成稿）；证据锚点见断言台账。", ""]
    for sec in SECTION_ORDER:
        lines.append(f"## {SECTION_LABEL[sec]}")
        items = by.get(sec, [])
        if items:
            for s in items[:12]:
                lines.append(f"- {s}")
        else:
            lines.append("- [材料不足：此部分未从材料中找到可复述的锚点，需人工补写]")
        lines.append("")
    return "\n".join(lines)


def build_coverage(cands: dict, al: dict, draft: str) -> dict:
    cov: dict[str, dict] = {}
    for sec in SECTION_ORDER:
        rows = [r for r in al.get("forward", {}).get("rows", []) if r.get("claim_type") == sec]
        anchored = sum(1 for r in rows if r.get("status") in ("anchored", "loose"))
        cov[sec] = {"state": "written" if rows else ("material_only" if cands.get("structure", {}).get("section_hits", {}).get(sec) else "missing"),
                    "sentences": len(rows), "anchored": anchored}
    refs = cands.get("references", [])
    cov["citation_coverage"] = {
        "state": "written" if refs else "missing",
        "references_in_material": len(refs),
        "key_works": len(cands.get("key_works", [])),
        "works_written": sum(1 for r in al.get("backward", {}).get("rows", [])
                             if r.get("kind") == "key_work" and r.get("status") == "written"),
    }
    return cov


def build_contribution_map(al: dict) -> list[dict]:
    """每条贡献 -> 章节/图表/引用锚点（贡献与正文对齐的可核对映射表）。"""
    out: list[dict] = []
    for r in al.get("forward", {}).get("rows", []):
        if r.get("claim_type") != "contribution":
            continue
        out.append({
            "claim": r.get("sentence", "")[:300],
            "figures": [f.get("raw", "") for f in r.get("figures", [])],
            "citations": [c.get("raw", "") for c in r.get("citations", [])],
            "verbatim_source": r.get("verbatim_source", ""),
            "anchored": bool(r.get("figures") or r.get("citations") or r.get("verbatim_source")),
        })
    return out


def build_result(case_id: str, pack: dict, cands: dict, al: dict, gp: dict,
                 report: dict, status: str, draft: str, extra: list[str] | None = None,
                 schema: dict | None = None) -> dict:
    extra = extra or []
    cov = build_coverage(cands, al, draft)
    uncertainty: list[str] = []
    if not cands.get("references"):
        uncertainty.append("材料中没有可解析的参考文献表；引用元数据只能对照正文引用编号，无法验证文献真实存在")
    if any(u.get("kind") == "pdf" for u in pack.get("files", [])):
        uncertainty.append("材料含 PDF：文本由解析器抽取，图表与引用锚点可能不完整")
    if not draft.strip():
        uncertainty.append("未提供成稿；本次只做材料扫描与锚点抽取")
    uncertainty.extend(extra)

    ledger_rows = []
    for i, r in enumerate(al.get("forward", {}).get("rows", []), 1):
        ledger_rows.append({
            "claim_id": f"c{i:04d}", "claim_type": r.get("claim_type", ""),
            "text": r.get("sentence", ""), "section": r.get("section", ""),
            "status": r.get("status", ""),
            "evidence": {
                "citations": r.get("citations", []),
                "figures": r.get("figures", []),
                "verbatim_source": r.get("verbatim_source", ""),
            },
            "scope": {"hedge": r.get("hedge_terms", []),
                      "overclaim": r.get("overclaim_terms", []),
                      "explicit_judgement": r.get("explicit_judgement", False)},
            "metadata_mismatch": r.get("metadata_mismatch", []),
        })

    result: dict[str, Any] = {
        "case_id": case_id,
        "status": status,
        "intro_related_work_markdown": draft,
        "claim_ledger": {"rows": ledger_rows, "by_status": al.get("forward", {}).get("by_status", {}),
                         "trace_rate": al.get("forward", {}).get("trace_rate", 0)},
        "citation_check": {"references_in_material": cands.get("references", []),
                           "key_works": cands.get("key_works", []),
                           "mismatch_count": al.get("counts", {}).get("metadata_mismatch", 0),
                           "unverifiable_count": al.get("forward", {}).get("by_status", {}).get("unverified", 0)},
        "coverage": cov,
        "contribution_map": build_contribution_map(al),
        "alignment": {"forward": al.get("forward", {}), "backward": al.get("backward", {})},
        "validation": {"status": report.get("status", ""), "counts": report.get("counts", {}),
                       "checks": report.get("checks", []), "top_failures": report.get("top_failures", [])},
        "gaps": gp.get("gaps", []),
        "gaps_summary": {"by_severity": gp.get("by_severity", {}), "by_type": gp.get("by_type", {})},
        "sources": [{"path": f.get("source", ""), "kind": f.get("kind", ""),
                     "reader": f.get("reader", ""), "units": f.get("units", 0),
                     "note": f.get("note", "")} for f in pack.get("files", [])],
        "uncertainty": uncertainty,
        "change_log": [],
    }
    if status == "partial":
        result["limits"] = [u for u in uncertainty] or ["partial result: see validation.top_failures"]
    return result


def write_all(out_dir: Path, result: dict, cands: dict, al: dict, gp: dict) -> list[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    drafts = result.get("intro_related_work_markdown", "")
    _write(out_dir / "intro_related_work.md", drafts or "[no draft supplied]"); written.append("intro_related_work.md")
    _write(out_dir / "claim_ledger.json", result["claim_ledger"]); written.append("claim_ledger.json")
    _write(out_dir / "citation_check.json", result["citation_check"]); written.append("citation_check.json")
    _write(out_dir / "coverage.json", result["coverage"]); written.append("coverage.json")
    _write(out_dir / "alignment.json", result["alignment"]); written.append("alignment.json")
    _write(out_dir / "validation.json", result["validation"]); written.append("validation.json")
    _write(out_dir / "gaps.md", gaps_markdown(gp, result.get("case_id", ""))); written.append("gaps.md")
    _write(out_dir / "result.json", result); written.append("result.json")
    return written


def finalise(case_raw: dict, result: dict, pack: dict | None = None) -> dict:
    result, _rep = contract_mod.apply(result, case_raw.get("output_contract"), pack)
    return result
