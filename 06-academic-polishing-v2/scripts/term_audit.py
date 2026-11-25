#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""term_audit.py —— 学术文本术语一致性审计

抓三类漂移，都是脚本能确定、模型容易疏忽的：
  1) 同一个英文概念的大小写/连字符/单复数变体（sea fog / Sea-Fog / sea-fogs）
  2) 中英对照不一致（能见度（visibility）与 能见度（Visibility）混用）
  3) 同一缩写的首次定义重复或全称不一致（LSTM 定义了两次、两次全称不同）

输出可直接当术语表用；润色后用同一份表回扫，即可发现"改着改着术语漂移了"。

只用标准库，Python 3.8+ 可直接运行。

用法：
  python3 term_audit.py --input draft.txt --out terms_before.json                 # 建表
  python3 term_audit.py --input revised.txt --glossary terms_before.json --out terms_after.json   # 回扫
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

WORD_RE = re.compile(r"[A-Za-z][A-Za-z\-]{1,}")
ABBR_DEF_RE = re.compile(r"([A-Z][A-Za-z][A-Za-z\s\-]{3,60}?)\s*[（(]\s*([A-Z][A-Za-z0-9\-]{1,12})\s*[)）]")
ZH_EN_PAIR_RE = re.compile(r"([\u4e00-\u9fa5]{2,10})\s*[（(]\s*([A-Za-z][A-Za-z\s\-]{1,40})\s*[)）]")

STOP_EN = set("""the and for with that this these those from into using used was were are is be been being
has have had not all any can may might will would could should than then there their they our we you your
which while where when what how also more most such other same both each between among during about after
before above below under over only very much many some one two three within without onto upon via per
study studies results result method methods data table figure fig section introduction discussion
conclusion however therefore thus moreover furthermore al et eq equation respectively due both
than that's it its as at by in on of to an a or if but so we our""".split())

STOP_ZH = set("""研究 结果 方法 数据 分析 本文 我们 可以 进行 具有 通过 以及 并且 但是 因此 由于 其中
这些 如图 如表 所示 显著 相关 影响 变化 情况 问题 过程 方面 作用 水平 程度 主要 重要 同时 不同
相同 进一步 一个 两个 三个 这项 该文 本章 去年 今年 近年 目前 已经 需要 能够 得到 给出 采用 基于""".split())


def read_text(path):
    raw = Path(path).read_bytes()
    for enc in ("utf-8", "utf-8-sig", "gb18030", "utf-16"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def norm_key(term):
    """归一化：小写，去掉空格与连字符，压平单复数（末位 s）。"""
    k = re.sub(r"[\s\-_]+", "", term.lower())
    if len(k) > 4 and k.endswith("s"):
        k = k[:-1]
    return k


def latin_terms(text):
    """重叠 n-gram（n=1,2），返回 {key: Counter(原始写法)} 与首次行号。"""
    tokens = [(m.start(), m.group(0)) for m in WORD_RE.finditer(text)]
    variants = defaultdict(Counter)
    first_line = {}
    for i, (pos, w) in enumerate(tokens):
        if w.lower() in STOP_EN:
            continue
        for n in (1, 2):
            seq = tokens[i:i + n]
            if len(seq) < n:
                continue
            words = [s[1] for s in seq]
            # 单词条要求 >=4 字符（滤掉 the/data 类）；二元组只要求各 >=2 字符，
            # 否则 sea fog 这类短词术语永远抓不到。短词用 continue 而非 break。
            min_len = 4 if n == 1 else 2
            if any(x.lower() in STOP_EN or len(x) < min_len for x in words):
                continue
            raw = " ".join(words)
            k = norm_key(raw)
            variants[k][raw] += 1
            first_line.setdefault(k, text[:pos].count("\n") + 1)
    return variants, first_line


def zh_en_pairs(text):
    """中英对照：同一英文被配了不同中文，或同一中文被配了不同英文。"""
    pairs = []
    for m in ZH_EN_PAIR_RE.finditer(text):
        zh, en = m.group(1).strip(), re.sub(r"\s+", " ", m.group(2)).strip()
        pairs.append({"zh": zh, "en": en, "line": text[: m.start()].count("\n") + 1})
    by_en = defaultdict(set)
    by_zh = defaultdict(set)
    for p in pairs:
        by_en[norm_key(p["en"])].add(p["zh"])
        by_zh[p["zh"]].add(p["en"].lower())
    issues = []
    for k, zhs in by_en.items():
        if len(zhs) > 1:
            issues.append({"kind": "en_to_zh_inconsistent", "en": k, "zh_forms": sorted(zhs),
                           "detail": "同一英文术语对应了多个中文写法"})
    for zh, ens in by_zh.items():
        if len(ens) > 1:
            issues.append({"kind": "zh_to_en_inconsistent", "zh": zh, "en_forms": sorted(ens),
                           "detail": "同一中文术语对应了多个英文写法"})
    return pairs, issues


def abbreviations(text):
    found = []
    for m in ABBR_DEF_RE.finditer(text):
        found.append({"abbreviation": m.group(2).strip(),
                      "defined_as": re.sub(r"\s+", " ", m.group(1)).strip(),
                      "line": text[: m.start()].count("\n") + 1})
    grouped = defaultdict(list)
    for f in found:
        grouped[f["abbreviation"]].append(f)
    conflicts = []
    for abbr, items in grouped.items():
        if len(items) > 1:
            forms = {i["defined_as"].lower() for i in items}
            conflicts.append({
                "abbreviation": abbr,
                "definitions": [i["defined_as"] for i in items],
                "lines": [i["line"] for i in items],
                "reason": "同一定义重复" if len(forms) == 1 else "同一缩写被定义为不同全称",
            })
    return found, conflicts


def build(text, min_count):
    variants, first_line = latin_terms(text)
    terms = []
    for k, forms in variants.items():
        total = sum(forms.values())
        if total < min_count:
            continue
        ranked = sorted(forms.items(), key=lambda x: (-x[1], not x[0][:1].isupper(), x[0]))
        terms.append({
            "concept": k,
            "preferred": ranked[0][0],
            "variants_found": sorted(forms),
            "count": total,
            "first_line": first_line.get(k),
            "status": "inconsistent" if len(forms) > 1 else "single_form",
        })
    terms.sort(key=lambda t: (t["status"] != "inconsistent", -t["count"], t["concept"]))
    pairs, pair_issues = zh_en_pairs(text)
    abbr, abbr_conflicts = abbreviations(text)
    return terms, pairs, pair_issues, abbr, abbr_conflicts


def rescan(text, glossary_terms):
    variants, first_line = latin_terms(text)
    report = []
    for t in glossary_terms:
        k = t.get("concept")
        # 只允许"首选写法"本身：其它历史变体若仍留在文本里，说明没统一，应继续报 drift
        preferred = t.get("preferred")
        allowed = {preferred} if preferred else set(t.get("variants_found") or [])
        found = variants.get(k, Counter())
        drift = sorted(f for f in found if f and f not in allowed)
        if drift:
            status = "drift"
        elif not found:
            status = "missing"
        else:
            status = "ok"
        report.append({
            "concept": k,
            "preferred": t.get("preferred"),
            "variants_found": sorted(found),
            "drift": drift,
            "count": sum(found.values()),
            "first_line": first_line.get(k),
            "status": status,
        })
    return report


def main():
    ap = argparse.ArgumentParser(description="术语一致性审计")
    ap.add_argument("--input", required=True)
    ap.add_argument("--glossary", help="已有术语表 JSON（rescan 模式）")
    ap.add_argument("--out")
    ap.add_argument("--min-count", type=int, default=2)
    ap.add_argument("--max-terms", type=int, default=60, help="输出条数上限，按频次排序")
    args = ap.parse_args()

    text = read_text(args.input)
    pairs, pair_issues = zh_en_pairs(text)
    abbr, abbr_conflicts = abbreviations(text)

    if args.glossary:
        g = json.loads(Path(args.glossary).read_text(encoding="utf-8"))
        base = g.get("terms", [])
        report = rescan(text, base)
        drift = [r for r in report if r["status"] == "drift"]
        result = {
            "tool": "term_audit", "version": "1.1", "mode": "rescan",
            "input": str(args.input), "glossary": str(args.glossary),
            "verdict": "pass" if not drift and not abbr_conflicts and not pair_issues else "review",
            "terms": report,
            "drift_count": len(drift),
            "zh_en_pairs": pairs,
            "zh_en_issues": pair_issues,
            "abbreviations": abbr,
            "abbreviation_conflicts": abbr_conflicts,
            "note": "status=drift 表示出现术语表未登记的写法，应回改；missing 表示首选写法消失。",
        }
    else:
        terms, pairs, pair_issues, abbr, abbr_conflicts = build(text, args.min_count)
        terms = terms[: args.max_terms]
        inconsistent = [t for t in terms if t["status"] == "inconsistent"]
        result = {
            "tool": "term_audit", "version": "1.1", "mode": "build",
            "input": str(args.input),
            "verdict": "pass" if not inconsistent and not abbr_conflicts and not pair_issues else "review",
            "terms": terms,
            "inconsistent_count": len(inconsistent),
            "zh_en_pairs": pairs,
            "zh_en_issues": pair_issues,
            "abbreviations": abbr,
            "abbreviation_conflicts": abbr_conflicts,
            "note": "preferred 为按频次推荐的首选写法，需人工按学科惯例确认后再全篇替换。",
        }

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = {
        "verdict": result["verdict"],
        "inconsistent_count": result.get("inconsistent_count", result.get("drift_count", 0)),
        "zh_en_issues": len(result["zh_en_issues"]),
        "abbreviation_conflicts": len(result["abbreviation_conflicts"]),
        "sample": [t for t in result["terms"] if t["status"] in ("inconsistent", "drift")][:8],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if result["verdict"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
