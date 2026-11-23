#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_result.py —— 把改稿、修改记录与审计报告组装成 result.json

输出契约见 SKILL.md 第 5 节。所有字段都会写出来，缺失的显式标记为空数组或
"not_available"，方便评审区分"没有"和"忘了写"。

用法：
  python3 make_result.py \
      --case-id case-01 \
      --revised /app/work/revised.txt \
      --changes /app/work/changes.json \
      --audit /app/work/facts_after.json \
      --terms /app/work/terms_after.json \
      --out /app/output/result.json [--partial] [--note "..."]
"""

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

REQUIRED_TYPES = {"grammar", "term", "register", "hedge", "logic", "format"}


def load_json(path):
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def read_text(path):
    raw = Path(path).read_bytes()
    for enc in ("utf-8", "utf-8-sig", "gb18030", "utf-16"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def synth_case_id(revised_path):
    h = hashlib.sha1(Path(revised_path).read_bytes()).hexdigest()[:8]
    return f"synth-{h}"


def normalize_changes(changes):
    """接受多种写法：顶层 list，或 {"changes": [...]}，或 {paragraph_no: [...]}。"""
    if isinstance(changes, list):
        items = changes
    elif isinstance(changes, dict):
        items = changes.get("changes")
        if items is None:
            items = []
            for k, v in changes.items():
                if isinstance(v, list):
                    for it in v:
                        if isinstance(it, dict):
                            it.setdefault("paragraph", k)
                            items.append(it)
    else:
        items = []
    out = []
    for i, it in enumerate(items, 1):
        if not isinstance(it, dict):
            continue
        t = str(it.get("type", "grammar")).lower().strip()
        out.append({
            "id": it.get("id") or f"C{i}",
            "paragraph": it.get("paragraph", "not_available"),
            "original": it.get("original", "not_available"),
            "revised": it.get("revised", "not_available"),
            "type": t if t in REQUIRED_TYPES else "grammar",
            "reason": it.get("reason", "not_available"),
            "risk": it.get("risk", "none"),
            "audit_ref": it.get("audit_ref", ""),
        })
    return out


def fact_map_from_audit(audit):
    """从 hedge_audit 报告推出 fact_map：数值与引用逐条列出，标是否被改动。"""
    out = []
    for key, label in (("numbers", "numeric_values"), ("citations", "citations_and_refs")):
        seg = (audit or {}).get(key) or {}
        for v, n in (seg.get("missing") or {}).items():
            out.append({"value": v, "kind": label, "where": "not_available",
                        "source": "原文", "changed": True, "issue": "missing"})
        for v, n in (seg.get("added") or {}).items():
            out.append({"value": v, "kind": label, "where": "not_available",
                        "source": "改文新增", "changed": True, "issue": "added"})
    return out


def term_table_from_terms(terms_report):
    out = []
    for t in (terms_report or {}).get("terms", []):
        out.append({
            "concept": t.get("concept"),
            "preferred": t.get("preferred"),
            "variants_found": t.get("variants_found", []),
            "first_occurrence": f"line {t.get('first_line')}" if t.get("first_line") else "not_available",
            "status": t.get("status", "auto"),
        })
    return out


def main():
    ap = argparse.ArgumentParser(description="组装 result.json")
    ap.add_argument("--case-id", default=None)
    ap.add_argument("--revised", required=True)
    ap.add_argument("--changes", default=None)
    ap.add_argument("--audit", default=None)
    ap.add_argument("--terms", default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--genre", default=None, help="目标文体；不给则记为假设")
    ap.add_argument("--partial", action="store_true", help="标记为 partial（有未处理项）")
    ap.add_argument("--note", default=None, help="写进 limitations 的说明")
    args = ap.parse_args()

    revised_text = read_text(args.revised)
    case_id = args.case_id or synth_case_id(args.revised)
    changes = normalize_changes(load_json(args.changes))
    audit = load_json(args.audit)
    terms = load_json(args.terms)

    flags = audit.get("flags") or []
    unresolved = [f for f in flags if f.get("kind") == "fact_missing"]

    status = "ok"
    limitations = []
    if args.partial or unresolved:
        status = "partial" if revised_text.strip() else "failed"
    if unresolved:
        limitations.append(
            f"审计发现 {len(unresolved)} 处原文事实在改稿中缺失，尚未回改，需人工确认。")
    if not changes:
        limitations.append("未提供结构化修改记录（changes.json 缺失或为空），可核验性不足。")
    if not audit:
        limitations.append("未运行 hedge_audit，限定强度与数字守恒未经脚本核验。")
    if args.note:
        limitations.append(args.note)

    result = {
        "case_id": case_id,
        "status": status,
        "target_deliverable": {
            "kind": "revised_text",
            "path": str(args.revised),
            "genre_assumption": args.genre or "期刊论文（输入未指定文体时的默认假设）",
            "char_count": len(revised_text),
        },
        "change_log": changes,
        "term_table": term_table_from_terms(terms),
        "fact_map": fact_map_from_audit(audit),
        "uncertainties": sorted({u for c in changes for u in
                                 ([c["reason"]] if c.get("risk") == "meaning" else [])}),
        "assumptions": [
            args.genre or "未指定文体，按期刊论文处理",
            "术语首选写法以术语表出现频次最高者为默认，需按学科惯例人工复核",
        ],
        "limitations": limitations,
        "audit": {
            "hedge": (audit or {}).get("hedge", {}),
            "flags": flags,
            "verdict": (audit or {}).get("verdict", "not_run"),
            "terms_verdict": (terms or {}).get("verdict", "not_run"),
        },
        "provenance": {
            "generator": "make_result.py v1.0",
            "audit_source": str(args.audit) if args.audit else "not_provided",
            "terms_source": str(args.terms) if args.terms else "not_provided",
        },
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    # 附带两份可编辑产物，便于第三方核对
    (out.parent / "changes.csv").write_text("", encoding="utf-8")
    with open(out.parent / "changes.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["id", "paragraph", "original", "revised",
                                          "type", "reason", "risk", "audit_ref"])
        w.writeheader()
        for c in changes:
            w.writerow(c)

    print(json.dumps({
        "written": str(out),
        "status": status,
        "change_count": len(changes),
        "flag_count": len(flags),
        "limitations": limitations,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
