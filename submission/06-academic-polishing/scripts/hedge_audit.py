#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hedge_audit.py —— 限定强度与硬事实守恒审计

用途：比较"润色前"与"润色后"两段学术文本，回答两个问题：
  1) 命题强度有没有被悄悄加强或削弱？（情态/限定/范围/否定）
  2) 数字、单位、百分比、引用编号、图表指向有没有被改动或丢失？

输出 JSON，供 SKILL.md 的 change_log / fact_map 引用，也可直接作为评审证据。

只用标准库，Python 3.8+ 可直接运行。

用法：
  python3 hedge_audit.py --original a.txt --revised b.txt --out report.json
  python3 hedge_audit.py --original a.txt --revised a.txt          # 基线自检
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

# ---------------------------------------------------------------- 词表
# 每个家族 = 一个语义维度。weight 表示该词的强度方向与幅度：
#   + 越大越"强"（断言、绝对、放大范围）
#   - 越小越"弱"（可能、限定、收窄范围）
# 家族内部比较用"加权强度"，跨家族不直接相加，避免把不同维度混为一谈。
LEXICON = {
    "possibility": {          # 可能性情态
        "may": -1, "might": -1, "could": -1, "can": -0.5,
        "possibly": -1, "perhaps": -1, "potentially": -1,
        "可能": -1, "或许": -1, "也许": -1, "有可能": -1,
    },
    "evidential": {           # 证据强度（弱断言动词）
        "suggest": -1, "suggests": -1, "suggested": -1,
        "indicate": -0.8, "indicates": -0.8, "indicated": -0.8,
        "appear": -1, "appears": -1, "seem": -1, "seems": -1,
        "tend to": -1, "tends to": -1,
        "提示": -0.8, "表明": +0.2, "暗示": -1, "似乎": -1, "倾向于": -1,
    },
    "certainty": {            # 断言强度（强断言动词）
        "demonstrate": +1, "demonstrates": +1, "showed": +0.8, "show": +0.8,
        "prove": +1.5, "proves": +1.5, "confirm": +1, "confirms": +1,
        "establish": +1, "establishes": +1,
        "证明": +1.5, "证实": +1, "确认": +1, "表明": +0.2,
    },
    "scope": {                # 适用范围 / 限定条件
        "in this cohort": -1.5, "in this study": -1.2, "in our sample": -1.5,
        "under these conditions": -1.2, "at present": -0.8, "currently": -0.8,
        "preliminary": -1.2, "limited to": -1.2, "only": -0.8,
        "generally": +1.2, "in general": +1.2, "universally": +2, "always": +1.5,
        "本队列": -1.5, "本研究": -1.2, "本样本": -1.5, "初步": -1.2,
        "仅": -0.8, "目前": -0.8, "普遍": +1.2, "始终": +1.5, "所有": +1.2,
        "十分常见": +1.5, "十分普遍": +1.5, "广泛存在": +1.2, "均如此": +1.2,
    },
    "approximation": {        # 数量精度（删掉"约"等于抬高精度）
        "about": -1, "approximately": -1, "roughly": -1, "around": -1,
        "circa": -1, "nearly": -0.5, "up to": -0.5, "~": -1,
        "约": -1, "大约": -1, "左右": -1,
    },
    "negation": {             # 否定与阴性结果（单独统计，强度不参与加权）
        "not significant": 0, "no significant": 0, "did not differ": 0,
        "non-significant": 0, "no difference": 0,
        "not statistically significant": 0, "no statistically significant": 0,
        "was not significantly": 0, "did not significantly differ": 0,
        "无显著": 0, "不显著": 0, "未见差异": 0,
        "站不住": 0, "不成立": 0, "尚不多见": 0, "仍然少见": 0,
        "鲜见": 0, "少见": 0, "尚未见": 0,
    },
}

# 数值 + 单位（覆盖常见科研量纲；单位可缺省）
NUM_RE = re.compile(
    r"(?<![\w.])"
    r"(\d+(?:[.,]\d+)?(?:\s*[×x]\s*10\s*\^?\s*[-−]?\d+)?)"
    r"\s*"
    r"(%(?![\w])|‰|°C|℃|km/h|km|cm|mm|µm|um|nm|kg|mg|µg|ug|g/L|mg/L|mol|mmol|hPa|kPa|Pa|"
    r"mL|ml|L|min|ms|s(?![\w])|h(?![\w])|d(?![\w])|Hz|kHz|MHz|GHz|eV|keV|MeV|K(?![\w])|"
    r"个|例|条|次|篇|年|月|天|小时|分钟)?"
)

CITE_RE = re.compile(
    r"\[\s*\d+(?:\s*[,–\-]\s*\d+)*\s*\]"          # [3] [3,5] [3-5]
    r"|\([A-Z][A-Za-z\-']+(?:\s+et\s+al\.?)?,?\s*\d{4}[a-z]?\)"  # (Smith, 2020)
    r"|\bFig(?:ure)?\.?\s*\d+[A-Za-z]?"            # Fig. 2
    r"|\bTable\s*\d+[A-Za-z]?"                     # Table 2
    r"|\bEq(?:uation)?\.?\s*\(?\d+\)?"             # Eq. (4)
    r"|式\s*\(?\d+\)?|图\s*\d+|表\s*\d+"           # 中文图表式
)


def read_text(path):
    p = Path(path)
    raw = p.read_bytes()
    for enc in ("utf-8", "utf-8-sig", "gb18030", "utf-16"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def find_terms(text):
    """返回 {families: {family: Counter}, tokens: Counter}，按词边界匹配。"""
    low = text.lower()
    out = {}
    tokens = Counter()
    for fam, table in LEXICON.items():
        c = Counter()
        for term in table:
            if re.match(r"^[a-z]", term):
                # 英文按词边界，且允许词形后缀（-s/-ed/-ing 已在表内单列，故用严格边界）
                pat = r"(?<![a-z])" + re.escape(term) + r"(?![a-z])"
            else:
                pat = re.escape(term)
            n = len(re.findall(pat, low))
            if n:
                c[term] = n
                tokens[term] = n
        out[fam] = c
    return out, tokens


def strength(family_counter):
    """家族加权强度 = Σ(词频 × 权重)。正值=整体更强，负值=整体更弱。"""
    total = 0.0
    for term, n in family_counter.items():
        total += LEXICON_weight(term) * n
    return round(total, 3)


def LEXICON_weight(term):
    for table in LEXICON.values():
        if term in table:
            return table[term]
    return 0.0


def numbers(text):
    c = Counter()
    for m in NUM_RE.finditer(text):
        num = m.group(1).replace(" ", "")
        unit = (m.group(2) or "").strip()
        c[f"{num}{unit}"] += 1
    return c


def citations(text):
    return Counter(m.group(0).replace(" ", "") for m in CITE_RE.finditer(text))


def diff_counter(before, after, name):
    missing = {k: before[k] for k in before if after.get(k, 0) < before[k]}
    added = {k: after[k] for k in after if before.get(k, 0) < after[k]}
    return {
        "checked": name,
        "missing": missing,
        "added": added,
        "ok": not missing and not added,
    }


def main():
    ap = argparse.ArgumentParser(description="限定强度与硬事实守恒审计")
    ap.add_argument("--original", required=True, help="润色前文本")
    ap.add_argument("--revised", required=True, help="润色后文本")
    ap.add_argument("--out", help="结果 JSON 路径")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    before = read_text(args.original)
    after = read_text(args.revised)

    fam_b, tok_b = find_terms(before)
    fam_a, tok_a = find_terms(after)

    fam_report = {}
    flags = []
    for fam in LEXICON:
        sb, sa = strength(fam_b[fam]), strength(fam_a[fam])
        delta = round(sa - sb, 3)
        entry = {
            "before": dict(fam_b[fam]),
            "after": dict(fam_a[fam]),
            "strength_before": sb,
            "strength_after": sa,
            "delta": delta,
            "status": "ok",
        }
        if fam == "negation":
            # 阴性结果按"出现次数"比，不按"词种类数"比：
            # 原文 not significant 出现 3 次、改文剩 1 次，两侧 key 数都是 1，
            # 若只比 len 就会漏报。阴性表述被削是"没改坏"最严重的错误，必须按频次守。
            count_b = sum(fam_b[fam].values())
            count_a = sum(fam_a[fam].values())
            entry["count_before"] = count_b
            entry["count_after"] = count_a
            if count_a < count_b:
                entry["status"] = "flag"
                flags.append({"kind": "negation_lost", "family": fam,
                              "detail": f"阴性/否定表述出现次数由 {count_b} 降为 {count_a}，需逐条恢复",
                              "removed_occurrences": count_b - count_a})
        else:
            if delta > 0.5:
                entry["status"] = "strengthened"
                flags.append({"kind": "hedge_strengthened", "family": fam,
                              "detail": f"命题强度净增强 {delta}，需回改或说明理由",
                              "removed": sorted(set(fam_b[fam]) - set(fam_a[fam])),
                              "introduced": sorted(set(fam_a[fam]) - set(fam_b[fam]))})
            elif delta < -0.5:
                entry["status"] = "weakened"
                flags.append({"kind": "hedge_weakened", "family": fam,
                              "detail": f"命题强度净削弱 {abs(delta)}，需回改或说明理由",
                              "removed": sorted(set(fam_b[fam]) - set(fam_a[fam])),
                              "introduced": sorted(set(fam_a[fam]) - set(fam_b[fam]))})
        fam_report[fam] = entry

    num_report = diff_counter(numbers(before), numbers(after), "numeric_values")
    cite_report = diff_counter(citations(before), citations(after), "citations_and_refs")

    for item in (num_report, cite_report):
        for k in item["missing"]:
            flags.append({"kind": "fact_missing", "family": item["checked"], "value": k,
                          "detail": f"{k} 在改后文本中缺失或减少，必须逐字恢复"})
        for k in item["added"]:
            flags.append({"kind": "fact_added", "family": item["checked"], "value": k,
                          "detail": f"{k} 为改后文本新增，原文没有的事实不得新增"})

    verdict = "pass" if not flags else "review"

    result = {
        "tool": "hedge_audit",
        "version": "1.0",
        "original": str(args.original),
        "revised": str(args.revised),
        "verdict": verdict,
        "flag_count": len(flags),
        "hedge": fam_report,
        "numbers": num_report,
        "citations": cite_report,
        "flags": flags,
        "note": "strength 为家族内加权和，跨家族不可相加；delta>0.5 视为净强化，<-0.5 视为净削弱。",
    }

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    if not args.quiet:
        print(json.dumps({k: result[k] for k in
                          ("verdict", "flag_count", "flags", "numbers", "citations")},
                         ensure_ascii=False, indent=2))
    return 0 if verdict == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
