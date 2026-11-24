#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_result.py — 把翻译/术语/审计结果组装为平台 result.json + 可编辑产物

复用 06/03/07 已验证的 output_contract 适配规则：
- 平台声明什么字段就补什么字段；
- 语义相同但名称不同的用别名补一份；
- 声明为必需、却补不出的字段 → status 降为 partial，并写进 limitations（不假装成功）。

同时产出两份可编辑产物（题面要求"可继续编辑的稿件与文献表"的同类要求）：
- bilingual.md   段落级双语对照（每段带 pid / 页码 / 章节）
- glossary.csv   术语表（可被 Excel 打开继续维护）

用法：
  python3 make_result.py --case-id case-01 --case-json /input/case.json \
    --paras /app/work/paras.json --glossary /app/work/glossary.json \
    --translation /app/work/translation.json --audit /app/work/audit.json \
    --out /app/output/result.json
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

CONTRACT_ALIASES = {
    "case_id": "case_id", "status": "status",
    "translation": "translation", "translated_text": "translation",
    "bilingual": "translation", "bilingual_pairs": "translation",
    "target_text": "translation", "result": "translation",
    "output": "translation", "paragraphs": "translation",
    "glossary": "glossary", "terminology": "glossary",
    "term_table": "glossary", "terms": "glossary",
    "audit": "audit_report", "qa": "audit_report",
    "checks": "audit_report", "validation": "audit_report",
    "issues": "audit_report", "findings": "audit_report",
    "sources": "source_map", "evidence": "source_map",
    "provenance": "source_map", "source_map": "source_map",
    "locators": "source_map", "anchors": "source_map",
    "uncertainties": "uncertainties", "uncertainty": "uncertainties",
    "unknowns": "uncertainties", "needs_review": "uncertainties",
    "limits": "limitations", "limitations": "limitations",
    "changes": "change_log", "change_log": "change_log",
    "task_coverage": "task_coverage",
}


def load_json(path):
    if not path or not Path(path).exists():
        return {}
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}


def parse_translation(path):
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    raw = p.read_text(encoding="utf-8")
    if p.suffix.lower() == ".json":
        data = json.loads(raw)
        return {int(x["pid"]): (x.get("target") or x.get("text") or "")
                for x in data.get("paragraphs", []) if "pid" in x}
    import re
    out, cur, buf = {}, None, []
    for line in raw.splitlines():
        m = re.match(r"^\s*(?:#{1,6}\s*)?\[?P(\d+)\]?\s*[:：]?\s*(.*)$", line)
        if m:
            if cur is not None:
                out[cur] = "\n".join(buf).strip()
            cur, buf = int(m.group(1)), [m.group(2)]
        elif cur is not None:
            buf.append(line)
    if cur is not None:
        out[cur] = "\n".join(buf).strip()
    return out


def build(case_id, paras_data, glossary, translation, audit):
    paras = paras_data.get("paragraphs", [])
    body = [p for p in paras if p.get("kind") == "para"]

    pairs = []
    for p in body:
        pid = p["pid"]
        tgt = translation.get(pid, "")
        pairs.append({
            "pid": pid,
            "page": p.get("page"),
            "section": p.get("section", ""),
            "source": p["text"],
            "target": tgt,
            "status": "translated" if tgt.strip() else "missing",
        })

    source_map = [{"pid": p["pid"], "page": p.get("page"), "section": p.get("section", "")}
                  for p in body]

    glossary_rows = []
    for c in glossary.get("concepts", []):
        glossary_rows.append({
            "concept_id": c.get("concept_id"),
            "source": c.get("source"),
            "abbr": c.get("abbr", ""),
            "target": c.get("target", ""),
            "forbidden": c.get("forbidden", []),
            "occurrences": [{"pid": o["pid"], "page": o.get("page")} for o in c.get("occurrences", [])],
        })

    counts = audit.get("counts", {})
    verdict = audit.get("verdict", "unknown")
    missing = [p["pid"] for p in pairs if p["status"] == "missing"]
    unlocked = [g["concept_id"] for g in glossary_rows if not g["target"]]

    uncertainties = []
    for i in audit.get("issues", []):
        if i.get("severity") == "warning":
            uncertainties.append({
                "pid": i.get("pid"), "type": i.get("type"), "detail": i.get("detail"),
            })
    if unlocked:
        uncertainties.append({
            "type": "unlocked_terms",
            "detail": f"以下术语未定译名，未纳入一致性检查：{unlocked}",
        })

    limitations = [
        "脚本只能核验术语一致、段落覆盖、数字/单位/引用/否定等字面锚点，不能判定译文是否通顺或学术表达是否地道。",
        "术语候选由统计信号抽取（缩写定义/高频短语），可能带修饰语或误收动词，需 Agent 在 locked 前置审。",
        "公式块与表格碎片按类型隔离，不计入待译正文；若原文公式本身有排版错误，按原文保留，不在翻译中悄悄纠正。",
        "扫描件/无文本层 PDF 不在本脚本能力范围，遇到会标记需 OCR，不编造文本。",
    ]

    change_log = []
    if missing:
        change_log.append({"action": "flag_missing", "detail": f"{len(missing)} 段缺译文：{missing[:20]}"})
    for i in audit.get("issues", []):
        if i.get("severity") == "error":
            change_log.append({"action": i.get("type"), "pid": i.get("pid"), "detail": i.get("detail")})

    status = "ok"
    if verdict == "needs_revision" or missing:
        status = "partial"
    if counts.get("translated_paragraphs", 0) == 0:
        status = "failed"

    return {
        "case_id": case_id,
        "status": status,
        "translation": pairs,
        "glossary": glossary_rows,
        "audit_report": {
            "verdict": verdict,
            "counts": counts,
            "issues": audit.get("issues", []),
            "coverage": audit.get("coverage", {}),
        },
        "source_map": source_map,
        "task_coverage": {
            "paragraphs_total": len(body),
            "paragraphs_translated": len(body) - len(missing),
            "glossary_terms": len(glossary_rows),
            "glossary_locked": len(glossary_rows) - len(unlocked),
        },
        "uncertainties": uncertainties,
        "limitations": limitations,
        "change_log": change_log,
    }


def fill_contract(result, contract):
    """按 output_contract 补字段：平台声明的字段名，能映射就映射，映射不上就记录缺口。"""
    filled, missing_required = {}, []
    for field, spec in (contract or {}).items():
        target_key = CONTRACT_ALIASES.get(field, field)
        if target_key in result:
            if target_key != field:
                result[field] = result[target_key]
                filled[field] = target_key
        else:
            required = False
            if isinstance(spec, dict):
                required = bool(spec.get("required"))
            if required:
                missing_required.append(field)
    return filled, missing_required


def write_bilingual(path: Path, pairs, source_name):
    lines = [f"# 双语对照（段落级）", "", f"来源：{source_name}", ""]
    for p in pairs:
        lines.append(f"## P{p['pid']} · p{p['page']} · {p['section'] or '(front matter)'}")
        lines.append("")
        lines.append(f"**原文**：{p['source']}")
        lines.append("")
        lines.append(f"**译文**：{p['target'] if p['target'].strip() else '（未译，见审计报告）'}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_glossary_csv(path: Path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["concept_id", "source", "abbr", "target", "forbidden", "occurrence_pids"])
        for r in rows:
            w.writerow([r["concept_id"], r["source"], r["abbr"], r["target"],
                        ";".join(r["forbidden"]), ";".join(str(o["pid"]) for o in r["occurrences"])])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case-id", required=True)
    ap.add_argument("--case-json", default="")
    ap.add_argument("--paras", required=True)
    ap.add_argument("--glossary", required=True)
    ap.add_argument("--translation", required=True)
    ap.add_argument("--audit", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    paras_data = load_json(args.paras)
    glossary = load_json(args.glossary)
    translation = parse_translation(args.translation)
    audit = load_json(args.audit)

    result = build(args.case_id, paras_data, glossary, translation, audit)

    contract = {}
    if args.case_json:
        contract = load_json(args.case_json).get("output_contract") or {}
    filled, missing_required = fill_contract(result, contract)
    result["output_contract_alignment"] = {
        "contract_fields": list(contract.keys()),
        "filled_from_aliases": filled,
        "missing_required": missing_required,
    }
    if missing_required:
        result["status"] = "partial"
        result["limitations"].append(f"output_contract 必需字段无法生成：{missing_required}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    # 可编辑产物放同目录
    write_bilingual(out.parent / "bilingual.md", result["translation"],
                    paras_data.get("source", "unknown"))
    write_glossary_csv(out.parent / "glossary.csv", result["glossary"])

    print(json.dumps({
        "out": str(out),
        "status": result["status"],
        "paragraphs": result["task_coverage"]["paragraphs_total"],
        "translated": result["task_coverage"]["paragraphs_translated"],
        "glossary": result["task_coverage"]["glossary_terms"],
        "contract_missing": missing_required,
        "artifacts": ["bilingual.md", "glossary.csv"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
