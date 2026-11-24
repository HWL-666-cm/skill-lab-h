#!/usr/bin/env python3
"""自测：用合成用例验证 anchor_audit 能抓错，且正常锚点不误报。提交前必跑。"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from anchor_audit import audit_claim  # noqa: E402


def main() -> int:
    data = json.loads((HERE.parent / "tests" / "cases.json").read_text(encoding="utf-8"))
    pages = data["synthetic_pages"]
    sections = data["synthetic_sections"]
    passed = 0
    for case in data["cases"]:
        claims = case["notes"].get("claims", [])
        page_map = case["notes"].get("page_map", {})
        results = [audit_claim(c, pages, sections, page_map) for c in claims]
        r = results[0]
        flags = r["flags"]
        ok = True
        if "expected" in case:
            ok = ok and r["verdict"] == case["expected"]
        if "expected_verdict" in case:
            ok = ok and r["verdict"] == case["expected_verdict"]
        if "expected_flag" in case:
            want = case["expected_flag"]
            hit = want in flags or any(f.startswith(want.split(":")[0]) for f in flags)
            ok = ok and hit
        print(f"  [{'PASS' if ok else 'FAIL'}] {case['id']} {case['name']} "
              f"-> verdict={r['verdict']} flags={flags}")
        passed += int(ok)
    total = len(data["cases"])
    print(f"[selftest] {passed}/{total} passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
