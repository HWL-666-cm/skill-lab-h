#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""register_audit.py —— 语域/中式英语/冗余名词化 审计（"说得像"与"中英文表达质量"）

hedge_audit.py 守的是"没改坏"（原意、限定强度、数字、引用不被动）；本脚本守的
是反向的一侧：改后文本是否真的"说得像"同行写的学术文本，而不是口语腔、宣传腔、
直译腔，或把动词压成名词的官僚腔。

四类问题，全部按固定模式穷举（不依赖模型语感），命中即报并给出改法：

  colloquial       口语/宣传腔（very / a lot of / more and more / 众所周知 / 不言而喻）
  translationese   直译腔（with the development of / there has a / the reason is because）
  nominalization   冗余名词化（make an analysis of -> analyze / in the process of -> during）
  filler           空话套话（It is worth noting that / with regard to / 在当今社会）

severity 分两档：error（硬错误，应当改）与 style（语域问题，建议改，但少数语境可保留）。
输出 JSON，供 SKILL.md 的 change_log 引用，也可直接作为评审证据。

用法：
  python3 register_audit.py --input revised.txt --out register.json
  python3 register_audit.py --original src.txt --revised out.txt --out register.json  # 对比净变化
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------- pattern table
# 每个 pattern：category / pattern(regex) / suggestion / severity
PATTERNS: list[dict] = [
    # ---- colloquial 口语/宣传腔 ----
    {"category": "colloquial", "pattern": r"\b(?:a lot of|lots of|a bunch of)\b",
     "suggestion": "many / numerous / 具体数量", "severity": "style"},
    {"category": "colloquial", "pattern": r"\b(?:really|actually|basically|nowadays)\b",
     "suggestion": "删除或改为具体表述", "severity": "style"},
    {"category": "colloquial", "pattern": r"\b(?:very|quite|pretty) (?:important|significant|large|high|low|good|many)\b",
     "suggestion": "用更精确的形容词或具体数值代替程度副词", "severity": "style"},
    {"category": "colloquial", "pattern": r"\bmore and more\b|\bless and less\b",
     "suggestion": "increasingly / progressively / 具体趋势", "severity": "style"},
    {"category": "colloquial", "pattern": r"\bget(?:s|ting)?\b(?! [a-z]*\d)",
     "suggestion": "obtain / become（按语境）", "severity": "style"},
    {"category": "colloquial", "pattern": r"众所周知|不言而喻|众所周知地|众所周知的是",
     "suggestion": "删除，或改为引用具体文献支撑", "severity": "style"},

    # ---- translationese 直译腔/中式英语 ----
    {"category": "translationese", "pattern": r"\bwith the (?:rapid )?development of\b",
     "suggestion": "删除开场白，直接陈述现象", "severity": "style"},
    {"category": "translationese", "pattern": r"\bwith the (?:continuous )?improvement of\b",
     "suggestion": "删除开场白，直接陈述现象", "severity": "style"},
    {"category": "translationese", "pattern": r"\bthere has a\b|\bthere have a\b|\bthere has an\b|\bthere have an\b",
     "suggestion": "there is / there are（there be 句型的主谓一致）", "severity": "error"},
    {"category": "translationese", "pattern": r"\bthe reason is because\b|\bthe reason why .* is because\b",
     "suggestion": "the reason is that ...，或直接 because", "severity": "error"},
    {"category": "translationese", "pattern": r"\bcombine .* together\b|\bcombine together\b",
     "suggestion": "combine（together 冗余）", "severity": "error"},
    {"category": "translationese", "pattern": r"\baccording to (?:my|our|their) (?:opinion|view)\b",
     "suggestion": "删除（学术写作无需「据我看来」这类表述），或改为 we argue / we find", "severity": "style"},
    {"category": "translationese", "pattern": r"\bplay(?:s|ed)? an? (?:important|key|vital|crucial|significant) role in\b",
     "suggestion": "改为具体作用，如 is essential for / drives / accounts for", "severity": "style"},
    {"category": "translationese", "pattern": r"\battracted more and more attention\b|\bhas attracted (?:much|wide) attention\b",
     "suggestion": "删除热度开场白，直接陈述研究现状与缺口", "severity": "style"},
    {"category": "translationese", "pattern": r"随着.{0,12}(?:的)?(?:发展|进步|提高)|在.{0,10}方面",
     "suggestion": "删除直译开场，改为直接陈述", "severity": "style"},

    # ---- nominalization 冗余名词化 ----
    {"category": "nominalization", "pattern": r"\b(?:make|made|makes|making) an? (?:analysis|comparison|assessment|evaluation) (?:of|with|to|between)\b",
     "suggestion": "analyze / compare / assess / evaluate（动词直接作谓语）", "severity": "error"},
    {"category": "nominalization", "pattern": r"\b(?:give|gave|given|giving) (?:an? )?(?:description|explanation|account) of\b",
     "suggestion": "describe / explain（动词直接作谓语）", "severity": "error"},
    {"category": "nominalization", "pattern": r"\b(?:carry|carried|carries|carrying) out (?:an? )?(?:investigation|analysis|study|examination)\b",
     "suggestion": "investigate / analyze / study / examine（动词直接作谓语）", "severity": "error"},
    {"category": "nominalization", "pattern": r"\b(?:conduct|conducted|conducts|conducting) (?:an? )?(?:investigation|analysis|study) (?:of|on)\b",
     "suggestion": "investigate / analyze / study（动词直接作谓语）", "severity": "error"},
    {"category": "nominalization", "pattern": r"\b(?:perform|performed|performs|performing) (?:an? )?(?:analysis|evaluation|calculation) (?:of|on)\b",
     "suggestion": "analyze / evaluate / calculate（动词直接作谓语）", "severity": "error"},
    {"category": "nominalization", "pattern": r"\bin the process of\b",
     "suggestion": "during / while + 动词", "severity": "style"},
    {"category": "nominalization", "pattern": r"\bfor the purpose of\b|\bwith the aim of\b",
     "suggestion": "to / in order to（动词不定式）", "severity": "style"},

    # ---- filler 空话套话 ----
    {"category": "filler", "pattern": r"\bit is (?:worth|important|necessary) (?:noting|to note) that\b",
     "suggestion": "删除，或把真正值得强调的点写成主句", "severity": "style"},
    {"category": "filler", "pattern": r"\bit should be noted that\b|\bit must be noted that\b|\bit needs to be noted that\b",
     "suggestion": "删除，或把要点写成主句", "severity": "style"},
    {"category": "filler", "pattern": r"\b(?:as is well known|it is well known that|it goes without saying|needless to say)\b",
     "suggestion": "删除（宣称「众所周知」却不给引用，属语域问题）", "severity": "style"},
    {"category": "filler", "pattern": r"\bwith regard to\b|\bwith respect to\b",
     "suggestion": "regarding / about / for", "severity": "style"},
    {"category": "filler", "pattern": r"在当今社会|在当前.{0,6}(?:形势|背景下)|具有重要的(?:理论|现实|应用)意义",
     "suggestion": "删除空话，改为具体贡献", "severity": "style"},
]

_WORD = re.compile(r"[A-Za-z\u4e00-\u9fff]")


def read_text(path: str) -> str:
    p = Path(path)
    for enc in ("utf-8", "utf-8-sig", "gb18030"):
        try:
            return p.read_text(encoding=enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return p.read_text(encoding="utf-8", errors="replace")


def audit(text: str) -> dict:
    findings: list[dict] = []
    for spec in PATTERNS:
        for m in re.finditer(spec["pattern"], text, re.I):
            findings.append({
                "category": spec["category"],
                "severity": spec["severity"],
                "text": m.group(0),
                "span": [m.start(), m.end()],
                "suggestion": spec["suggestion"],
            })
    findings.sort(key=lambda f: f["span"][0])
    counts = {"colloquial": 0, "translationese": 0, "nominalization": 0, "filler": 0,
              "error": 0, "style": 0}
    for f in findings:
        counts[f["category"]] += 1
        counts[f["severity"]] += 1
    verdict = "issues" if findings else "clean"
    return {
        "verdict": verdict,
        "counts": counts,
        "findings": findings,
        "chars": len(text),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="语域/中式英语/冗余名词化审计")
    ap.add_argument("--input", help="要审计的文本文件（单文件模式）")
    ap.add_argument("--original", help="改前文本（对比模式）")
    ap.add_argument("--revised", help="改后文本（对比模式）")
    ap.add_argument("--out", required=True, help="输出 JSON 路径")
    args = ap.parse_args()

    if args.input:
        text = read_text(args.input)
        report = audit(text)
        report["mode"] = "single"
    elif args.original and args.revised:
        before = read_text(args.original)
        after = read_text(args.revised)
        rb = audit(before)
        ra = audit(after)
        # 净变化：改后仍有/新增的才算，改前有而改后没有的是"已消除"
        after_spans = {(f["category"], f["text"].lower()) for f in ra["findings"]}
        before_spans = {(f["category"], f["text"].lower()) for f in rb["findings"]}
        remaining = [f for f in ra["findings"]
                     if (f["category"], f["text"].lower()) in before_spans]
        new = [f for f in ra["findings"]
               if (f["category"], f["text"].lower()) not in before_spans]
        resolved = [f for f in rb["findings"]
                    if (f["category"], f["text"].lower()) not in after_spans]
        report = {
            "mode": "diff",
            "verdict": "issues" if remaining or new else "clean",
            "counts": {"before": rb["counts"], "after": ra["counts"],
                       "resolved": len(resolved), "remaining": len(remaining), "new": len(new)},
            "resolved": resolved, "remaining": remaining, "new": new,
        }
    else:
        print("需要 --input，或同时给 --original 与 --revised", file=sys.stderr)
        return 2

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8", newline="\n")
    print(json.dumps(report["counts"], ensure_ascii=False))
    return 0 if report["verdict"] == "clean" else 1


if __name__ == "__main__":
    sys.exit(main())
