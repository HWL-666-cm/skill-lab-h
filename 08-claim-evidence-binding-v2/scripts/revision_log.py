#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""revision_log.py —— 回改回路的质量账（返修轮次数字）。

按缺口回改是 v2 的增益来源：写完一轮 finish 读 gaps.md，改完再 finish，
本脚本比较任意两轮 result.json，把"未锚定句数 / 缺口数 / 阻断数 / 未覆盖关键工作数"
的前后变化算成可复核的数字。这样"比基线好多少"不是自述，是机器算的。

用法：
  python3 revision_log.py --before /app/work/r1/result.json \
                          --after  /app/work/r2/result.json --out /app/output/revision_delta.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _nested(d: dict, *keys, default=0):
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k, default)
    return cur


def metrics(res: dict) -> dict:
    by = _nested(res, "alignment", "forward", "by_status", default={}) or {}
    gaps_sum = _nested(res, "gaps_summary", "by_severity", default={}) or {}
    cov = _nested(res, "coverage", "citation_coverage", default={}) or {}
    key_works = _nested(res, "coverage", "citation_coverage", "key_works", default=0)
    works_written = cov.get("works_written", 0)
    return {
        "unanchored": by.get("unanchored", 0) + by.get("unverified", 0) + by.get("overclaimed", 0),
        "overclaimed": by.get("overclaimed", 0),
        "gaps_total": len(_nested(res, "gaps", default=[]) or []),
        "blocking": gaps_sum.get("blocking", 0),
        "major": gaps_sum.get("major", 0),
        "warn": gaps_sum.get("warn", 0),
        "key_works_unwritten": max(0, key_works - works_written),
    }


def delta(before: dict, after: dict) -> dict:
    b, a = metrics(before), metrics(after)
    keys = ["unanchored", "overclaimed", "gaps_total", "blocking", "major", "warn", "key_works_unwritten"]
    d = {k: a[k] - b[k] for k in keys}
    return {"before": b, "after": a, "delta": d,
            "improved": all(d[k] <= 0 for k in ("unanchored", "blocking", "gaps_total")) and any(d[k] < 0 for k in ("unanchored", "blocking", "gaps_total"))}


def main() -> int:
    ap = argparse.ArgumentParser(description="回改轮次质量账")
    ap.add_argument("--before", required=True)
    ap.add_argument("--after", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    before = json.loads(Path(args.before).read_text(encoding="utf-8"))
    after = json.loads(Path(args.after).read_text(encoding="utf-8"))
    rep = delta(before, after)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(rep, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
    print(json.dumps(rep, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
