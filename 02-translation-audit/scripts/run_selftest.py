#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_selftest.py — 跑 tests/cases.json 的合成用例，断言审计结果"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from translation_audit import audit  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / "tests" / "cases.json"


def main() -> int:
    data = json.loads(CASES.read_text(encoding="utf-8"))
    cases = data["cases"]
    passed = failed = 0
    fails = []

    for c in cases:
        paras_data = {"paragraphs": c["paras"]}
        glossary = {"concepts": c.get("concepts", [])}
        translation = {int(k): v for k, v in c["translation"].items()}
        report = audit(paras_data, glossary, translation)

        types = {i["type"] for i in report["issues"]}
        ok = True
        reasons = []

        for t in c.get("expect_present", []):
            if t not in types:
                ok = False
                reasons.append(f"缺少预期问题 {t}")
        for t in c.get("expect_absent", []):
            if t in types:
                ok = False
                reasons.append(f"出现不该有的问题 {t}")
        exp_v = c.get("expect_verdict")
        if exp_v and report["verdict"] != exp_v:
            ok = False
            reasons.append(f"verdict 期望 {exp_v} 实际 {report['verdict']}")

        if ok:
            passed += 1
            print(f"PASS {c['id']} {c['name'][:44]}")
        else:
            failed += 1
            fails.append((c["id"], reasons, sorted(types)))
            print(f"FAIL {c['id']} {c['name'][:44]} :: {'; '.join(reasons)}")
            print(f"     实际 issues: {sorted(types)}")

    print(f"\n{passed}/{passed+failed} 通过")
    if fails:
        print("失败详情:")
        for cid, reasons, types in fails:
            print(f"  {cid}: {reasons} | issues={types}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
