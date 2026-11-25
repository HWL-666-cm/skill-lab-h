#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""number_audit.py —— 数字守恒审计（事实与来源映射的确定性一侧）。

改写学术文本时最容易的"悄悄改坏"是把事实数字改掉：90% 变 92%、样本量 n 变掉。
本脚本抽事实底稿与改写稿的事实数字集合，报「删掉/改动的源数字」和「新增数字」，
防止改写过程夹带数据改动。只抽**事实数字**（百分比、小数、n=/p= 值），不把
正文引用编号 [1][2] 当事实数字。

用法：
  python3 number_audit.py --source 事实底稿.md --revised 改写稿.md --out numbers.json
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

# 事实数字：百分比 / 小数 / n= / p< 值。不含孤立整数（避免引用编号误报）。
FACT_NUM = re.compile(
    r"\d+(?:\.\d+)?\s*[%％]|\d+\.\d+|n\s*=\s*\d+|p\s*[<>=]\s*\d+(?:\.\d+)?", re.I)


def extract(text: str) -> list[str]:
    out = []
    for m in FACT_NUM.finditer(text):
        t = re.sub(r"\s+", "", m.group(0)).replace("％", "%")
        out.append(t)
    return out


def number_diff(source_text: str, revised_text: str) -> dict:
    src = extract(source_text)
    rev = extract(revised_text)
    sc, rc = Counter(src), Counter(rev)
    removed = sorted(n for n in sc if sc[n] > rc.get(n, 0))
    added = sorted(n for n in rc if rc[n] > sc.get(n, 0))
    # 一处改动通常表现为"一个源数字消失 + 一个新数字出现"，
    # 用 max 计漂移处数，避免把 90%->92% 记成两次。
    changed = max(len(removed), len(added))
    return {
        "source_numbers": sorted(sc.elements()),
        "revised_numbers": sorted(rc.elements()),
        "removed": removed,
        "added": added,
        "changed_count": changed,
        "preserved": changed == 0,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="数字守恒审计")
    ap.add_argument("--source", required=True, help="事实底稿")
    ap.add_argument("--revised", required=True, help="改写稿")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    src = Path(args.source).read_text(encoding="utf-8")
    rev = Path(args.revised).read_text(encoding="utf-8")
    report = number_diff(src, rev)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("changed_count", "removed", "added", "preserved")},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
