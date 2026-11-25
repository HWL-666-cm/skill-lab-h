#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
validate_translation.py — 译文核验与术语强制回填（阅读03｜文献翻译 Skill）

这是"术语表被真正执行"的核心：翻译完成后由确定性代码逐段校验，
不依赖模型自觉。校验项：
  1. 占位符完整：源段每个 {{P_n}} 在译文中恰好出现一次且未被篡改；
  2. 必译术语在位：源段出现的术语，译文中出现其已核准译名（或屈折形式）；
  3. 禁用译名缺席：译文中不得出现术语表声明的 forbidden_alternatives；
  4. 强制回填：把译文中的禁用译名/明显偏离译名替换为核准译名（可配置）。
输出结构化校验报告，供 Agent 决定"接受 / 带违规重译 / 交人工确认"。
"""

import json
import re
import sys


def _norm(s: str):
    return re.sub(r"\s+", " ", s or "").strip()


def check_placeholder_integrity(source_map: dict, target: str):
    """源占位符是否在译文中恰好出现一次。返回违规列表。"""
    issues = []
    for token in source_map:
        cnt = target.count(token)
        if cnt == 0:
            issues.append({"token": token, "problem": "missing",
                           "detail": "占位符在译文中缺失"})
        elif cnt > 1:
            issues.append({"token": token, "problem": "duplicated",
                           "detail": "占位符在译文中出现 %d 次" % cnt})
    return issues


def check_terms(source: str, target: str, termbase: list):
    """
    术语校验：
      - 若 source 含 term 的源词，target 应含其核准译名；
      - target 不得含 forbidden_alternatives 中的任何禁用译名。
    返回 (missing_terms, forbidden_hits)。
    """
    missing = []
    forbidden = []
    src_norm = _norm(source)
    tgt_norm = _norm(target)
    for tb in termbase:
        src_term = tb.get("source", "")
        if not src_term:
            continue
        # 源词是否出现在原文（词边界匹配，大小写不敏感）
        if re.search(r'(?i)\b' + re.escape(src_term) + r'\b', src_norm):
            approved = tb.get("target", "")
            do_not_translate = tb.get("do_not_translate", False)
            if do_not_translate:
                # 不译术语应在译文中原样保留
                if not re.search(re.escape(src_term), tgt_norm):
                    missing.append({"source": src_term, "expect": src_term,
                                    "reason": "do_not_translate 术语未保留"})
            elif approved:
                if not re.search(re.escape(approved), tgt_norm):
                    missing.append({"source": src_term, "expect": approved,
                                    "reason": "核准译名未出现"})
        # 禁用译名（无论源词是否出现，译文里都不该有）
        for alt in tb.get("forbidden_alternatives", []):
            if alt and re.search(re.escape(alt), tgt_norm):
                forbidden.append({"source": src_term, "forbidden": alt})
    return missing, forbidden


def force_backfill(target: str, termbase: list):
    """把译文中的禁用译名/替代译名替换为核准译名（确定性修正）。"""
    corrected = target
    changes = []
    for tb in termbase:
        approved = tb.get("target", "")
        for alt in tb.get("forbidden_alternatives", []):
            if alt and alt != approved and alt in corrected:
                corrected = corrected.replace(alt, approved)
                changes.append({"forbidden": alt, "replaced_with": approved})
    return corrected, changes


def validate_segment(seg: dict, translated: str, termbase: list):
    """校验单个段落，返回结构化报告。"""
    src_map = seg.get("protection_map", {})
    source = seg.get("source", "")
    report = {
        "id": seg.get("id"),
        "kind": seg.get("kind", "text"),
        "placeholder_issues": check_placeholder_integrity(src_map, translated),
        "missing_terms": [],
        "forbidden_hits": [],
        "backfill_changes": [],
    }
    if seg.get("do_not_translate"):
        # 公式段：译文必须原样等于原文
        if _norm(translated) != _norm(source):
            report["placeholder_issues"].append(
                {"token": "(formula)", "problem": "altered",
                 "detail": "公式段译文与原文不一致"})
        report["final_text"] = source
        report["status"] = "accepted" if not report["placeholder_issues"] else "failed"
        return report

    missing, forbidden = check_terms(source, translated, termbase)
    report["missing_terms"] = missing
    report["forbidden_hits"] = forbidden

    corrected, changes = force_backfill(translated, termbase)
    report["backfill_changes"] = changes
    report["final_text"] = corrected

    ok = (not report["placeholder_issues"] and not report["missing_terms"]
          and not report["forbidden_hits"])
    report["status"] = "accepted" if ok else "needs_review"
    return report


def validate_all(job: dict, translations: dict, termbase: list):
    """
    translations: {segment_id: 译文文本}
    返回完整校验报告 + 汇总统计。
    """
    results = []
    for seg in job.get("segments", []):
        sid = seg.get("id")
        translated = translations.get(str(sid)) or translations.get(sid) or ""
        results.append(validate_segment(seg, translated, termbase))

    n_total = len(results)
    n_accepted = sum(1 for r in results if r["status"] == "accepted")
    n_needs_review = n_total - n_accepted
    n_missing_terms = sum(len(r["missing_terms"]) for r in results)
    n_forbidden = sum(len(r["forbidden_hits"]) for r in results)
    n_ph = sum(len(r["placeholder_issues"]) for r in results)

    return {
        "summary": {
            "total_segments": n_total,
            "accepted": n_accepted,
            "needs_review": n_needs_review,
            "placeholder_issues": n_ph,
            "missing_terms": n_missing_terms,
            "forbidden_hits": n_forbidden,
        },
        "segments": results,
    }


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法: python3 validate_translation.py <job.json> <translations.json> [termbase.json]")
        sys.exit(1)
    job = json.load(open(sys.argv[1], encoding="utf-8"))
    translations = json.load(open(sys.argv[2], encoding="utf-8"))
    termbase = []
    if len(sys.argv) >= 4:
        termbase = json.load(open(sys.argv[3], encoding="utf-8"))
    elif job.get("termbase"):
        termbase = job["termbase"]
    report = validate_all(job, translations, termbase)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
