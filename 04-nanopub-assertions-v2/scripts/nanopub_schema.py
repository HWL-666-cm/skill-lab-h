#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
nanopub_schema.py — Nanopublication 结构定义与「结构与词表校验」（阅读14）

职责（确定性，无模型调用）：
  1. 加载受控关系词表 predicates.json（读得懂：predicate 必须取自词表）；
  2. 定义 Nanopub 四图 schema（head/assertion/provenance/pubinfo）；
  3. 对 Agent 生成的断言做**结构与词表校验**（可复现、非语义）：
     - 字段缺失：主客体为空、predicate 为空、证据片段为空、无原文位置；
     - 结构启发：subject 含 and/or 并列连词（多主体混淆线索）；
     - 词表越界：predicate 不在受控词表；
     - 来源字段缺失：paper/year/identifier 缺项。

注意：本脚本**不判定语义质量**（如「断言是否真的过宽」「证据是否真的充分」），
这类判断需要理解内容，由 Agent 按 SKILL.md 的语义判据复核（见「语义质量判据」节）。
本脚本只做结构与词表校验，规则全部可复现、不依赖模型判断。
"""

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PREDICATES_PATH = os.path.join(HERE, "..", "resources", "predicates.json")


def load_predicates(path=PREDICATES_PATH):
    """返回受控关系名列表。新版 predicates.json 用 relations 字典（键即关系名），
    旧版用 predicates 列表；两者都兼容。"""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if "relations" in data:
            return sorted(data["relations"].keys())
        return [p.get("type") for p in data.get("predicates", [])]
    except Exception:
        return []


def predicate_types(predicates):
    return {p.upper() if isinstance(p, str) else (p.get("type") or "").upper()
            for p in predicates}


def _empty(s):
    return not (s or "").strip()


def validate_nanopub(np, predicates):
    """
    对单条 nanopub 做质量检查，返回 issue 列表。
    每个 issue: {"check": 检查项, "severity": "error|warning", "detail": 说明}
    """
    issues = []
    valid_types = predicate_types(predicates)

    a = np.get("assertion", {}) or {}
    e = np.get("evidence", {}) or {}
    p = np.get("pubinfo", {}) or {}
    pr = np.get("provenance", {}) or {}

    # 1) 结构校验：主客体字段是否为空（非语义的「断言过宽」判定）
    if not a.get("subject") and not a.get("object"):
        issues.append({"check": "subject_object_empty", "severity": "error",
                       "detail": "subject 与 object 皆为空（字段未填）"})
    elif not a.get("subject"):
        issues.append({"check": "subject_missing", "severity": "error",
                       "detail": "断言缺 subject"})
    elif not a.get("object"):
        issues.append({"check": "object_missing", "severity": "error",
                       "detail": "断言缺 object"})
    # 结构启发：subject 含并列连词（多主体混淆线索，非语义判定）
    if re.search(r"\band\b|\bor\b", a.get("subject", "") or "", re.I):
        issues.append({"check": "subject_conjunction", "severity": "warning",
                       "detail": "subject 含 and/or 并列连词，可能多主体，需复核是否拆多条"})

    # 2) 关系类型：predicate 必须在受控词表（大小写不敏感）
    pred = a.get("predicate", "")
    if not pred:
        issues.append({"check": "predicate_missing", "severity": "error",
                       "detail": "断言缺 predicate"})
    elif pred.upper() not in valid_types:
        issues.append({"check": "predicate_out_of_vocab", "severity": "error",
                       "detail": "predicate '%s' 不在受控词表，须从 predicates.json 选择" % pred})

    # 3) 结构校验：证据片段字段是否为空 + 原文位置是否缺失
    if not e.get("quote"):
        issues.append({"check": "evidence_quote_empty", "severity": "error",
                       "detail": "证据片段 quote 为空（字段未填）"})
    loc = e.get("location", {}) or {}
    if not loc.get("page") and not loc.get("section"):
        issues.append({"check": "evidence_location_missing", "severity": "error",
                       "detail": "证据缺原文位置（page/section 至少其一）"})

    # 4) 来源元数据
    if not p.get("paper"):
        issues.append({"check": "source_paper_missing", "severity": "warning",
                       "detail": "缺论文来源"})
    if not p.get("year"):
        issues.append({"check": "source_year_missing", "severity": "warning",
                       "detail": "缺年份"})
    if not p.get("identifier") and not p.get("doi"):
        issues.append({"check": "identifier_missing", "severity": "warning",
                       "detail": "缺标识符（DOI/arXiv/URL）"})

    return issues


def validate_all(nanopubs, predicates):
    results = []
    for np in nanopubs:
        issues = validate_nanopub(np, predicates)
        results.append({"id": np.get("id"), "issues": issues,
                        "status": "ok" if not issues else
                        ("error" if any(i["severity"] == "error" for i in issues)
                         else "warning")})
    n_ok = sum(1 for r in results if r["status"] == "ok")
    n_err = sum(1 for r in results if r["status"] == "error")
    n_warn = sum(1 for r in results if r["status"] == "warning")
    return {
        "summary": {"total": len(results), "ok": n_ok, "error": n_err, "warning": n_warn},
        "nanopubs": results,
    }


def empty_nanopub_template():
    """返回空 nanopub 结构模板（Agent 按此填）。"""
    return {
        "id": "",
        "assertion": {"subject": "", "predicate": "", "object": "",
                      "subject_type": "", "object_type": "",
                      "condition": "", "negation": False, "modality": "fact"},
        "evidence": {"quote": "", "location": {"section": "", "page": None, "line": None},
                     "evidence_type": "direct", "supports": True},
        "provenance": {"wasDerivedFrom": {"paper": "", "section": "", "page": None},
                       "method": "text-extraction"},
        "pubinfo": {"paper": "", "authors": [], "year": None, "version": "",
                    "identifier": ""},
        "confidence": {"basis": "", "level": ""},
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python3 nanopub_schema.py <nanopubs.json> [predicates.json]")
        sys.exit(1)
    nps = json.load(open(sys.argv[1], encoding="utf-8"))
    preds = load_predicates(sys.argv[2] if len(sys.argv) > 2 else PREDICATES_PATH)
    report = validate_all(nps, preds)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
