#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_result.py —— 把结构化笔记、章节骨架与锚点核验报告组装成 result.json

输出契约见 SKILL.md 第 5 节。平台 output_contract 若声明字段，以其为准；
字段名不同但语义相同的用别名补一份；必需字段补不出则 status 降为 partial。

用法：
  python3 make_result.py --case-id case-01 --case-json /input/case.json \
    --notes /app/work/notes.json --extracted /app/work/extracted.json \
    --audit /app/work/anchor_audit.json --out /app/output/result.json
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

# 平台 output_contract 字段名 -> 默认字段。语义相同但名字不同，按契约补一份。
CONTRACT_ALIASES = {
    "case_id": "case_id", "status": "status",
    "claims": "claim_notes", "notes": "claim_notes", "findings": "claim_notes",
    "results": "claim_notes", "knowledge_points": "claim_notes",
    "structured_notes": "claim_notes", "answers": "claim_notes",
    "sections": "section_outline", "outline": "section_outline",
    "chapter_outline": "section_outline", "structure": "section_outline",
    "sources": "source_map", "evidence": "source_map", "anchors": "source_map",
    "citations": "source_map", "provenance": "source_map",
    "uncertainties": "uncertainties", "uncertainty": "uncertainties",
    "limits": "limitations", "limitations": "limitations",
    "assumptions": "assumptions", "task_coverage": "task_coverage",
    "audit": "audit", "card": "paper_card", "paper_card": "paper_card",
}


def load_json(path):
    if not path or not Path(path).exists():
        return {}
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}


def parse_contract(case_path):
    case = load_json(case_path)
    c = case.get("output_contract") or {}
    return c if isinstance(c, dict) else {}


def synth_case_id(notes_path):
    h = hashlib.sha1(Path(notes_path).read_bytes()).hexdigest()[:8]
    return f"synth-{h}"


def main() -> int:
    ap = argparse.ArgumentParser(description="组装 03 的 result.json")
    ap.add_argument("--case-id", default=None)
    ap.add_argument("--case-json", default=None)
    ap.add_argument("--notes", required=True, help="结构化笔记 JSON（含 claims）")
    ap.add_argument("--extracted", default=None, help="pdf_extract.py 的输出")
    ap.add_argument("--audit", default=None, help="anchor_audit.py 的报告")
    ap.add_argument("--task-items", default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--note", default=None)
    args = ap.parse_args()

    notes = load_json(args.notes)
    ex = load_json(args.extracted)
    audit = load_json(args.audit)
    case_id = args.case_id or notes.get("case_id") or synth_case_id(args.notes)

    claims = notes.get("claims", []) if isinstance(notes, dict) else []
    audit_results = audit.get("results", []) if isinstance(audit, dict) else []
    by_id = {r.get("id"): r for r in audit_results}
    # 逐条把 verdict 合并回 claim，便于第三方核对
    enriched = []
    for c in claims:
        row = dict(c)
        a = by_id.get(c.get("id"), {})
        row["anchor_verdict"] = a.get("verdict", "not_checked")
        row["anchor_flags"] = a.get("flags", [])
        enriched.append(row)

    source_map = [{
        "source": ex.get("source", "not_available"),
        "extraction": ex.get("extraction", "not_available"),
        "page_count": ex.get("page_count", 0),
        "issue_pages": [i["page"] for i in ex.get("issues", []) if i.get("type") == "garbled_or_formula"],
        "page_map": notes.get("page_map", {}),
    }] if ex else []

    audit_counts = audit.get("counts", {}) if isinstance(audit, dict) else {}
    weak = audit_counts.get("weak", 0)
    mismatch = audit_counts.get("mismatch", 0)

    status = "ok"
    limitations = []
    if mismatch:
        status = "partial"
        limitations.append(f"锚点核验发现 {mismatch} 条 mismatch（原文找不到对应内容），需人工核对。")
    if weak:
        status = "partial" if status != "failed" else status
        limitations.append(f"锚点核验发现 {weak} 条 weak（缺页码/粒度不足），已标注但未补齐。")
    if not audit:
        limitations.append("未运行 anchor_audit，锚点可核验性未经脚本确认。")
    if ex.get("issues"):
        limitations.append(
            "论文存在 " + ", ".join(f"p{i['page']}({i['type']})" for i in ex["issues"])
            + "，相关页只锚到页、不做逐字核验。")
    if args.note:
        limitations.append(args.note)

    paper_card = notes.get("paper_card", {}) or {}
    result = {
        "case_id": case_id,
        "status": status,
        "paper_card": paper_card,
        "section_outline": ex.get("sections", []),
        "claim_notes": enriched,
        "source_map": source_map,
        "uncertainties": notes.get("uncertainties", []),
        "assumptions": notes.get("assumptions", []),
        "limitations": limitations,
        "audit": {
            "anchor": audit_counts,
            "overall": audit.get("overall", "not_run"),
            "extraction_source": ex.get("extraction", "not_available"),
        },
        "task_coverage": notes.get("task_coverage", []),
        "provenance": {
            "generator": "make_result.py v1.0",
            "notes_source": str(args.notes),
            "audit_source": str(args.audit) if args.audit else "not_provided",
        },
    }

    # 平台契约对齐
    contract = parse_contract(args.case_json)
    filled, missing_required = [], []
    if contract:
        for field, spec in contract.items():
            required = spec.get("required", True) if isinstance(spec, dict) else True
            if field in result:
                continue
            key = CONTRACT_ALIASES.get(field)
            value = result.get(key) if key else None
            if value is None:
                if required:
                    missing_required.append(field)
            else:
                result[field] = value
                filled.append(field)
        result["output_contract_alignment"] = {
            "source": str(args.case_json),
            "declared_fields": sorted(contract),
            "filled_from_aliases": filled,
            "missing_required": missing_required,
        }
        if missing_required:
            result["status"] = "partial" if enriched else "failed"
            result["limitations"].append(
                "平台 output_contract 必需字段缺失：" + ", ".join(missing_required))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    # 可编辑产物：笔记 CSV，便于第三方逐条核对
    with open(out.parent / "notes.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["id", "field", "value", "page", "section",
                                          "quote", "anchor_verdict", "anchor_flags"])
        w.writeheader()
        for c in enriched:
            a = c.get("anchor", {}) or {}
            w.writerow({
                "id": c.get("id"), "field": c.get("field"), "value": c.get("value"),
                "page": a.get("page"), "section": a.get("section"), "quote": a.get("quote"),
                "anchor_verdict": c.get("anchor_verdict"),
                "anchor_flags": ";".join(c.get("anchor_flags", [])),
            })

    print(json.dumps({
        "written": str(out),
        "status": result["status"],
        "claim_count": len(enriched),
        "audit_counts": audit_counts,
        "limitations": limitations,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
