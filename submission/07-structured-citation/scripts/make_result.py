#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_result.py —— 把引用审计结果组装为平台 result.json。

复用 06/03 已验证的 output_contract 适配规则：平台声明什么字段就补什么字段；
语义相同但名称不同的用别名补一份；必需字段补不出则 status 降为 partial。

用法：
  python3 make_result.py --case-id case-01 --case-json /input/case.json \
    --manuscript /app/work/manuscript.md --bib /app/work/references.json \
    --audit /app/work/audit.json --out /app/output/result.json
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

CONTRACT_ALIASES = {
    "case_id": "case_id", "status": "status",
    "manuscript": "edited_manuscript", "edited_manuscript": "edited_manuscript",
    "revised_text": "edited_manuscript", "target_artifact": "edited_manuscript",
    "output": "edited_manuscript", "result": "edited_manuscript",
    "issues": "citation_issues", "problems": "citation_issues",
    "audit_findings": "citation_issues", "findings": "citation_issues",
    "audit": "audit_report", "citation_audit": "audit_report",
    "validation": "audit_report", "checks": "audit_report",
    "numbering": "numbering_plan", "renumber_plan": "numbering_plan",
    "citation_numbering": "numbering_plan",
    "duplicates": "dedup_decisions", "dedup": "dedup_decisions",
    "merge_decisions": "dedup_decisions",
    "bibliography": "bibliography", "references": "bibliography",
    "reference_list": "bibliography", "bib": "bibliography",
    "entries": "bibliography",
    "sources": "source_map", "evidence": "source_map",
    "provenance": "source_map", "source_map": "source_map",
    "changes": "change_log", "change_log": "change_log",
    "modifications": "change_log",
    "uncertainties": "uncertainties", "uncertainty": "uncertainties",
    "limits": "limitations", "limitations": "limitations",
    "assumptions": "assumptions", "task_coverage": "task_coverage",
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


def synth_case_id(path):
    h = hashlib.sha1(Path(path).read_bytes()).hexdigest()[:8]
    return f"synth-{h}"


def main() -> int:
    ap = argparse.ArgumentParser(description="组装 07 的 result.json")
    ap.add_argument("--case-id", default=None)
    ap.add_argument("--case-json", default=None)
    ap.add_argument("--manuscript", required=True, help="输入稿件 .md/.txt")
    ap.add_argument("--revised", default=None, help="修订后稿件（可选；无则输出原稿+改动建议）")
    ap.add_argument("--bib", required=True, help="文献库 .json")
    ap.add_argument("--audit", required=True, help="citation_audit.py 的报告")
    ap.add_argument("--task-items", default=None, help="任务项 JSON（可选，含 pending 则降 partial）")
    ap.add_argument("--out", required=True)
    ap.add_argument("--note", default=None)
    args = ap.parse_args()

    audit = load_json(args.audit)
    case_id = args.case_id or audit.get("case_id") or synth_case_id(args.manuscript)
    bib = load_json(args.bib)
    if isinstance(bib, dict):
        bib = bib.get("entries") or bib.get("bibliography") or bib.get("references") or list(bib.values())
    if not isinstance(bib, list):
        bib = []

    manuscript_text = Path(args.manuscript).read_text(encoding="utf-8")
    revised_text = Path(args.revised).read_text(encoding="utf-8") if args.revised and Path(args.revised).exists() else manuscript_text

    issues = audit.get("issues", []) if isinstance(audit, dict) else []
    counts = audit.get("counts", {}) if isinstance(audit, dict) else {}
    errors = counts.get("errors", 0)
    warnings = counts.get("warnings", 0)

    source_map = [{
        "manuscript": str(args.manuscript),
        "bibliography": str(args.bib),
        "bibliography_entries": len(bib),
        "citation_marks": counts.get("citation_marks", 0),
        "citation_style": (audit.get("inputs", {}) or {}).get("citation_style", "not_detected"),
        "has_reference_section": (audit.get("inputs", {}) or {}).get("has_reference_section", False),
        "audit_report": str(args.audit),
    }]

    status = "ok"
    limitations = []
    if errors:
        status = "partial"
        limitations.append(f"引用审计发现 {errors} 处硬错误（悬空引用/编号冲突/预印本误标等），已在 citation_issues 逐条列出。")
    if warnings:
        limitations.append(f"引用审计发现 {warnings} 处警告（未用条目/弱引用位置/去重待确认等），需人工确认。")
    if not audit:
        status = "partial"
        limitations.append("未运行 citation_audit，引用一致性未经脚本确认。")
    if not args.revised:
        limitations.append("未提供修订后稿件；edited_manuscript 为输入原稿，改动建议见 change_log，平台应据建议自行修订。")
    if args.note:
        limitations.append(args.note)

    task_items = load_json(args.task_items)
    pending = []
    if isinstance(task_items, dict):
        pending = [k for k, v in task_items.items() if v == "pending"]
    elif isinstance(task_items, list):
        pending = [x.get("item", str(i)) for i, x in enumerate(task_items)
                   if isinstance(x, dict) and x.get("status") == "pending"]
    if pending:
        status = "partial"
        limitations.append("以下任务项仍待处理：" + ", ".join(map(str, pending)))

    result = {
        "case_id": case_id,
        "status": status,
        "edited_manuscript": revised_text,
        "citation_issues": issues,
        "audit_report": {
            "verdict": audit.get("verdict", "not_run"),
            "counts": counts,
            "version": audit.get("version", "not_available"),
            "notes": audit.get("notes", []),
        },
        "numbering_plan": audit.get("numbering", {}),
        "dedup_decisions": audit.get("duplicate_decisions", []),
        "bibliography": bib,
        "source_map": source_map,
        "uncertainties": [i for i in issues if i.get("severity") == "warning"],
        "assumptions": [
            "输入稿件中的 [n] 为顺序编码制引用；\\cite{key} 为键式引用；两者混用时按各自规则核验。",
            "文献库快照是唯一权威来源；DOI 相同且元数据无冲突时判为同一条，冲突时保留两条。",
        ],
        "limitations": limitations,
        "change_log": audit.get("change_log", []),
        "task_coverage": task_items if task_items else [],
        "provenance": {
            "generator": "make_result.py v1.0",
            "manuscript_source": str(args.manuscript),
            "bibliography_source": str(args.bib),
            "audit_source": str(args.audit),
            "revised_source": str(args.revised) if args.revised else "not_provided",
        },
    }

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
            result["status"] = "partial" if issues else "failed"
            result["limitations"].append(
                "平台 output_contract 必需字段缺失：" + ", ".join(missing_required))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (out.parent / "edited_manuscript.md").write_text(revised_text, encoding="utf-8")
    with open(out.parent / "change_log.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["id", "issue_id", "action", "reason"])
        w.writeheader()
        for c in result["change_log"]:
            w.writerow({"id": c.get("id"), "issue_id": c.get("issue_id"),
                        "action": c.get("action", ""), "reason": c.get("reason", "")})

    print(json.dumps({
        "written": str(out), "status": result["status"],
        "issue_count": len(issues), "counts": counts,
        "limitations": limitations,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
