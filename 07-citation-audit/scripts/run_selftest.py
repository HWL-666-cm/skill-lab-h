#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run all synthetic self-test cases against citation_audit.build_report."""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from citation_audit import build_report  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    with open(os.path.join(BASE, "tests", "cases.json"), encoding="utf-8") as f:
        data = json.load(f)
    passed = 0
    failed = []
    for case in data["cases"]:
        r = build_report(case["manuscript"], case["bib"],
                         f"selftest:{case['id']}", "selftest-bib")
        types = {i["type"] for i in r["issues"]}
        missing = [t for t in case["expect_types"] if t not in types]
        leaked = [t for t in case["expect_absent"] if t in types]
        verdict_ok = r["verdict"] == case["expect_verdict"]
        ok = not missing and not leaked and verdict_ok
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {case['id']} {case['name']}")
        print(f"       verdict={r['verdict']} (expect {case['expect_verdict']}) "
              f"issues={sorted(types)}")
        if missing:
            print(f"       MISSING: {missing}")
        if leaked:
            print(f"       UNEXPECTED: {leaked}")
        if ok:
            passed += 1
        else:
            failed.append(case["id"])
    total = len(data["cases"])
    print(f"\n{passed}/{total} passed")
    if failed:
        print("FAILED: " + ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
