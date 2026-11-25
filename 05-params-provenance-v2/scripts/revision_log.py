#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""revision_log.py —— 回改回路的质量账（返修轮次数字）。

按 gaps 回改是 v2 的增益来源：写完一轮 finish 读 gaps.md，改完再 finish，
本脚本比较任意两轮 result.json，把"编造数值 / 数值不符 / 材料参数漏写 / 阻断缺口"
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
    fwd = _nested(res, "alignment", "forward", default={}) or {}
    bwd = _nested(res, "alignment", "backward", default={}) or {}
    gaps_sum = _nested(res, "gaps", "by_severity", default={}) or {}
    return {
        "invented": len(fwd.get("invented", [])),
        "mismatch": len(fwd.get("mismatch", [])),
        "not_written": len(bwd.get("not_written", [])),
        "trace_rate": round(float(fwd.get("trace_rate", 0.0)), 4),
        "blocking": gaps_sum.get("blocking", 0),
        "gaps_total": len(_nested(res, "gaps", "gaps", default=[]) or []),
    }


def delta(before: dict, after: dict) -> dict:
    b, a = metrics(before), metrics(after)
    keys = ["invented", "mismatch", "not_written", "blocking", "gaps_total"]
    d = {k: a[k] - b[k] for k in keys}
    d["trace_rate"] = round(a["trace_rate"] - b["trace_rate"], 4)
    return {"before": b, "after": a, "delta": d,
            "improved": all(a[k] <= b[k] for k in ("invented", "mismatch", "not_written", "blocking"))
            and (a["trace_rate"] >= b["trace_rate"])}


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
