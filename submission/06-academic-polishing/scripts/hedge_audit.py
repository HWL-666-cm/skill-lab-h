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
import difflib
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

# 缩写首次定义：全称 + 括号内缩写，作为一个不可分割的原子事实。
# 改写时若把全称删掉、只留裸缩写，读者无从得知缩写含义，属于实质性损失。
ABBR_DEF_RE = re.compile(
    r"\b((?:[A-Za-z][A-Za-z\-']*\s+){1,4}[A-Za-z][A-Za-z\-']*)"
    r"\s*\(\s*([A-Z]{2,8})\s*\)"
)

# 边界/比较表达：这类是有限集合，可以穷举。它们把命题限定在某个范围，
# 一旦被删（如 less than or equal to 1 km → 1 km），结论的适用边界就消失了。
BOUNDARY_RE = re.compile(
    r"less than or equal to|greater than or equal to|no more than|no less than|"
    r"at least|at most|up to|fewer than|more than|less than|greater than|"
    r"no greater than|no fewer than|不超过|不少于|至少|至多|小于等于|大于等于|"
    r"[≤≥⩽⩾]|小于|大于|介于|在\s*\d",
    re.IGNORECASE,
)

# 技术断言锚点：这些短语承载"作者打算做什么""结论是什么"。
# 它们不是强度词表（强度词无限，靠留痕）；而是有限的主张骨架，丢一条即改变原意。
CLAIM_ANCHOR_RE = re.compile(
    r"aims?\s+to|intends?\s+to|seeks?\s+to|proposes?\s+to|"
    r"we\s+(?:propose|present|develop|investigate|evaluate|examine)|"
    r"this\s+(?:study|paper|work)\s+(?:aims?|proposes?|presents?|develops?|investigates?)|"
    r"the\s+(?:goal|purpose|aim)\s+of\s+this|"
    r"旨在|本研究|本文提出|本文旨在|我们提出|目的是",
    re.IGNORECASE,
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


def compact(m):
    """把匹配压成去空白的小写 key，便于跨空格差异比对。"""
    return re.sub(r"\s+", "", m.group(0)).lower()


def abbreviations(text):
    # key 用「缩写 -> 紧邻全称」的映射；比对时只看缩写是否仍有首次定义，
    # 避免全称前面的动词/连词变化造成假阳性。
    return Counter(
        m.group(2).upper() + ":" + re.sub(r"\s+", "", m.group(1)).lower()
        for m in ABBR_DEF_RE.finditer(text)
    )


def boundaries(text):
    return Counter(compact(m) for m in BOUNDARY_RE.finditer(text))


def claim_anchors(text):
    return Counter(compact(m) for m in CLAIM_ANCHOR_RE.finditer(text))


def diff_counter(before, after, name):
    missing = {k: before[k] for k in before if after.get(k, 0) < before[k]}
    added = {k: after[k] for k in after if before.get(k, 0) < after[k]}
    return {
        "checked": name,
        "missing": missing,
        "added": added,
        "ok": not missing and not added,
    }


# ------------------------------------------------- 层2：词级 diff + 留痕核对
# 功能词表：这些词的增删属于正常句法调整，不构成"改坏原意"，diff 时忽略。
# 只列真正无语义的虚词；限定/否定/强度词一律不在表内，必须留痕。
FUNCTION_WORDS = {
    "a", "an", "the", "of", "to", "in", "on", "at", "by", "for", "with",
    "and", "or", "as", "is", "are", "was", "were", "be", "been", "this",
    "that", "these", "those", "it", "its", "we", "our", "from", "than",
    "的", "了", "和", "与", "及", "在", "是", "有", "也", "而", "则", "之",
}

TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z\-']*|\d+(?:[.,]\d+)?|[\u4e00-\u9fff]|[^\s]")


def tokenize(text):
    """中英混排分词：英文按词、中文按字、数字整体、其余单字符。"""
    return [t for t in TOKEN_RE.findall(text) if t.strip()]


def content_blocks(before, after):
    """返回 (删除块, 新增块)。每块是连续实词片段的字符串。

    为什么要合并成块而不是逐词报：逐词会把 "not significant" 拆成两个孤立
    词，淹没在噪声里；合并后能定位到"哪一串内容被拿掉/加进来"，供人核对。
    """
    a, b = tokenize(before), tokenize(after)
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    removed, added = [], []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("delete", "replace"):
            seg = [t for t in a[i1:i2] if t.lower() not in FUNCTION_WORDS]
            if seg:
                removed.append("".join(seg) if any("\u4e00" <= c <= "\u9fff" for c in "".join(seg)) else " ".join(seg))
        if tag in ("insert", "replace"):
            seg = [t for t in b[j1:j2] if t.lower() not in FUNCTION_WORDS]
            if seg:
                added.append("".join(seg) if any("\u4e00" <= c <= "\u9fff" for c in "".join(seg)) else " ".join(seg))
    return removed, added


def load_changes(path):
    """读 change_log JSON，返回 [{original, revised, type, reason}]。"""
    if not path:
        return None
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("changes", data.get("change_log", data.get("changes_log", [])))
    return [c for c in data if isinstance(c, dict)] if isinstance(data, list) else []


def normalize(s):
    return re.sub(r"\s+", "", s).lower()


def check_attribution(removed, added, changes):
    """核对每个改动块是否在 change_log 里留下记录。

    changes=None 表示未提供 change_log：此时只产出待核对清单、不报错，
    保证未传 --changes 的老调用方式不被误伤。
    返回 (check_result, unjustified_flags)。
    """
    texts = []
    if changes is not None:
        for c in changes:
            for key in ("original", "revised", "before", "after", "source", "target"):
                if c.get(key):
                    texts.append(normalize(str(c[key])))
    rows = []
    for direction, blocks in (("removed", removed), ("added", added)):
        for blk in blocks:
            key = normalize(blk)
            explained = False
            if changes is not None:
                # 一个改动块只要在任一条记录的任一侧出现（或其子串被覆盖），即视为已留痕
                explained = any(key in t or t in key for t in texts if t)
            rows.append({"direction": direction, "block": blk, "explained": explained})
    unjustified = [r for r in rows if not r["explained"]]
    result = {
        "checked": "change_attribution",
        "change_log_provided": changes is not None,
        "total_blocks": len(rows),
        "unjustified_count": len(unjustified),
        "unjustified": unjustified,
        "all_explained": (len(unjustified) == 0),
        "note": (
            "未提供 change_log 时仅列出待核对块，不判定；提供后每个实词改动块必须能在某条记录的 original/revised 侧找到。"
            if changes is None else
            "实词改动块均已映射到 change_log；未映射的块说明改动没有留下理由。"
        ),
    }
    return result, unjustified


def main():
    ap = argparse.ArgumentParser(description="限定强度与硬事实守恒审计")
    ap.add_argument("--original", required=True, help="润色前文本")
    ap.add_argument("--revised", required=True, help="润色后文本")
    ap.add_argument("--out", help="结果 JSON 路径")
    ap.add_argument("--changes", help="change_log JSON 路径；提供后逐块核对改动是否留痕")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    before = read_text(args.original)
    after = read_text(args.revised)

    fam_b, tok_b = find_terms(before)
    fam_a, tok_a = find_terms(after)

    fam_report = {}
    flags = []
    limitations = []
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

    # 有限集合核对：数字、引用、缩写首次定义、边界表达。
    # 这些是可以穷举的原子事实，丢失即报，不依赖词表是否认识某个强度词。
    num_report = diff_counter(numbers(before), numbers(after), "numeric_values")
    cite_report = diff_counter(citations(before), citations(after), "citations_and_refs")
    abbr_report = diff_counter(abbreviations(before), abbreviations(after), "abbrev_definitions")
    bound_report = diff_counter(boundaries(before), boundaries(after), "boundary_expressions")

    for item in (num_report, cite_report, abbr_report, bound_report):
        for k in item["missing"]:
            flags.append({"kind": "fact_missing", "family": item["checked"], "value": k,
                          "detail": f"{k} 在改后文本中缺失或减少，必须逐字恢复"})
        for k in item["added"]:
            flags.append({"kind": "fact_added", "family": item["checked"], "value": k,
                          "detail": f"{k} 为改后文本新增，原文没有的事实不得新增"})

    # 层2：词级 diff + 留痕核对。不认词、只认"改动有没有记录"，换任何文档都成立。
    removed, added = content_blocks(before, after)
    try:
        changes = load_changes(args.changes)
    except (OSError, ValueError) as exc:
        changes = []
        limitations.append(f"change_log 读取失败，按未提供处理：{exc}")
    attr_report, unjustified = check_attribution(removed, added, changes)
    if changes is not None:
        for row in unjustified:
            flags.append({"kind": "unjustified_change", "family": "change_attribution",
                          "value": row["block"],
                          "detail": f"改文{row['direction']}了内容「{row['block']}」，change_log 中无对应记录"})

    # 层3：实质红线。主张骨架（作者意图/研究动作/结论方向）被动过，
    # 即使留痕齐全也必须人工确认——因为"有理由"不等于"改得对"：
    # aims to develop → develops 会把"打算做"变成"已经做到"，是命题性质的改变。
    claim_report = diff_counter(claim_anchors(before), claim_anchors(after), "claim_anchors")
    for k in claim_report["missing"]:
        flags.append({"kind": "substance_redline", "family": "claim_anchor_removed", "value": k,
                      "detail": f"主张骨架「{k}」在改文中消失，作者意图/研究动作可能被改变，必须人工确认"})
    for k in claim_report["added"]:
        flags.append({"kind": "substance_redline", "family": "claim_anchor_added", "value": k,
                      "detail": f"改文新增主张骨架「{k}」，原文没有此主张，必须人工确认"})

    verdict = "pass" if not flags else "review"

    result = {
        "tool": "hedge_audit",
        "version": "2.0",
        "original": str(args.original),
        "revised": str(args.revised),
        "verdict": verdict,
        "flag_count": len(flags),
        "hedge": fam_report,
        "numbers": num_report,
        "citations": cite_report,
        "abbreviations": abbr_report,
        "boundaries": bound_report,
        "claim_anchors": claim_report,
        "attribution": attr_report,
        "limitations": limitations,
        "flags": flags,
        "note": (
            "三层守恒：①有限集合（数字/引用/缩写定义/边界）丢失即报；"
            "②词级 diff 的实词改动块须在 change_log 中留痕；"
            "③hedge 家族加权强度 delta>0.5 视为净强化、<-0.5 为净削弱。"
            "强度词表只作辅助，不再作为唯一防线——换文档出现表外词时，靠①②兜底。"
        ),
    }

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    if not args.quiet:
        print(json.dumps({k: result[k] for k in
                          ("verdict", "flag_count", "flags", "numbers", "citations",
                           "abbreviations", "boundaries", "claim_anchors", "attribution")},
                         ensure_ascii=False, indent=2))
    return 0 if verdict == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
