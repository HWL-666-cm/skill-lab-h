#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_selftest.py v2 —— 自测：build_report 13 条 + render + claim_recall + status 修复。

分组：
  A. citation_audit.build_report  13 条（tests/cases.json）
  B. render.py                     GB/T 7714 / APA 渲染正确性（2 条）
  C. claim_recall.py               论断句规则召回（1 条）
  D. make_result.py                status 只依据修订稿（1 条）
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from citation_audit import build_report  # noqa: E402
from render import render_apa, render_gbt, _type_code  # noqa: E402
from claim_recall import recall  # noqa: E402
from number_audit import number_diff  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def group_a() -> tuple[int, list[str]]:
    with open(os.path.join(BASE, "tests", "cases.json"), encoding="utf-8") as f:
        data = json.load(f)
    passed, failed = 0, []
    for case in data["cases"]:
        r = build_report(case["manuscript"], case["bib"],
                         f"selftest:{case['id']}", "selftest-bib")
        types = {i["type"] for i in r["issues"]}
        missing = [t for t in case["expect_types"] if t not in types]
        leaked = [t for t in case["expect_absent"] if t in types]
        ok = not missing and not leaked and r["verdict"] == case["expect_verdict"]
        if ok:
            passed += 1
        else:
            failed.append(f"{case['id']}(missing={missing}, leaked={leaked}, "
                          f"verdict={r['verdict']})")
        print(f"[{'PASS' if ok else 'FAIL'}] A/{case['id']} {case['name']}")
    return passed, failed


def group_b() -> tuple[int, list[str]]:
    passed, failed = 0, []
    e4 = {"key": "k1", "type": "J", "title": "Sea fog prediction with WRF",
          "authors": ["Zhang San", "Li Si", "Wang Wu", "Zhao Liu"], "year": "2018",
          "journal": "J Marine Sci", "volume": "45", "issue": "3", "pages": "200-210",
          "doi": "10.1000/jms.2018.001"}
    g = render_gbt(e4)
    ok1 = "et al." in g and "et al.." not in g and "[J]" in g and "45(3)" in g and "200-210" in g
    passed += ok1
    failed += [] if ok1 else ["B/gbt-etal"]
    print(f"[{'PASS' if ok1 else 'FAIL'}] B/gbt-etal  四人以上等/et al. + 卷(期):页 无重复句点 → {g}")

    e2 = {"key": "k2", "type": "J", "title": "Deep learning for nowcasting",
          "authors": ["Smith A", "Jones B"], "year": "2020",
          "journal": "Weather and Forecasting", "volume": "35", "pages": "800-815",
          "doi": "10.1000/waf.2020.002"}
    a = render_apa(e2)
    ok2 = "Smith, A." in a and "Jones, B." in a and "(2020)" in a and "doi.org/10.1000" in a
    passed += ok2
    failed += [] if ok2 else ["B/apa-authors"]
    print(f"[{'PASS' if ok2 else 'FAIL'}] B/apa-authors  作者 + 年 + DOI 前缀 → {a}")

    ok3 = _type_code({"type": "M"}) == "M" and _type_code({"publisher": "x"}) == "M" and _type_code({"journal": "y"}) == "J"
    passed += ok3
    failed += [] if ok3 else ["B/type-infer"]
    print(f"[{'PASS' if ok3 else 'FAIL'}] B/type-infer  文献类型标识推断")
    return passed, failed


def group_c() -> tuple[int, list[str]]:
    text = ("研究表明，海雾预报准确率可达 92%。\n"
            "我们采用 CNN-LSTM 混合结构。\n"
            "该方法将均方误差降低 15% [1]。")
    claims = recall(text)
    ok = (len(claims) >= 2
          and any("has_number" in c["reasons"] and c["needs_review"] for c in claims)
          and all("我们采用" not in c["sentence"] for c in claims))
    passed, failed = int(ok), [] if ok else ["C/claim-recall"]
    print(f"[{'PASS' if ok else 'FAIL'}] C/claim-recall  候选 {len(claims)} 句，方法自述已排除，未带引用被召回")
    return passed, failed


def group_d() -> tuple[int, list[str]]:
    # status 只依据修订稿：原稿 3 处硬错误，修订稿修干净后 status 不应是 partial
    with tempfile.TemporaryDirectory() as td:
        orig = os.path.join(td, "orig.md")
        rev = os.path.join(td, "rev.md")
        bib = os.path.join(td, "bib.json")
        out = os.path.join(td, "result.json")
        open(orig, "w", encoding="utf-8").write("结论 A [5]。\n方法句。\n")
        open(rev, "w", encoding="utf-8").write("结论 A [1]。\n方法句。\n")
        json.dump([{"key": "a", "order": 1, "type": "J", "title": "T", "year": "2020",
                    "authors": ["X"], "journal": "J", "doi": "https://doi.org/10.1/x"}],
                  open(bib, "w", encoding="utf-8"))
        # 先生成原稿审计（含 dangling_citation）
        ajson = os.path.join(td, "audit.json")
        subprocess.run([sys.executable, os.path.join(BASE, "scripts", "citation_audit.py"),
                        "--manuscript", orig, "--bib", bib, "--out", ajson],
                       check=True, capture_output=True)
        r = subprocess.run([sys.executable, os.path.join(BASE, "scripts", "make_result.py"),
                            "--case-id", "st", "--manuscript", orig, "--revised", rev,
                            "--bib", bib, "--audit", ajson, "--out", out],
                           check=True, capture_output=True, text=True)
        result = json.load(open(out, encoding="utf-8"))
        input_err = result["issues_found_in_input"]["errors"]
        sm = len(result["source_map"])
        ok = (input_err >= 1 and result["status"] != "partial" and sm >= 1
              and all("resolved_entry" in s and "match_basis" in s for s in result["source_map"]))
        passed, failed = int(ok), [] if ok else ["D/status-fix"]
        print(f"[{'PASS' if ok else 'FAIL'}] D/status-fix  原稿错误={input_err} → status={result['status']}"
              f"（旧版会 partial），source_map={sm} 条逐条可回溯")
    return passed, failed


def group_e() -> tuple[int, list[str]]:
    # 数字守恒：事实底稿 90% 被改成 92% 应报漂移；还原后应 0 漂移
    src = "准确率已达 90% 以上，误差降低 15%。"
    bad = "准确率已达 92% 以上，误差降低 15%。"
    good = "准确率已达 90% 以上，误差降低 15%。"
    d_bad = number_diff(src, bad)
    d_good = number_diff(src, good)
    ok = (d_bad["changed_count"] == 1 and "90%" in d_bad["removed"] and "92%" in d_bad["added"]
          and d_good["changed_count"] == 0 and d_good["preserved"])
    passed, failed = int(ok), [] if ok else ["E/number-audit"]
    print(f"[{'PASS' if ok else 'FAIL'}] E/number-audit  90%→92% 报 1 处漂移，还原后 0 处")
    return passed, failed


def main() -> int:
    total = passed = 0
    all_failed = []
    for name, fn in [("A", group_a), ("B", group_b), ("C", group_c), ("D", group_d), ("E", group_e)]:
        p, f = fn()
        passed += p
        total += p + len(f)
        all_failed += f
    print(f"\n{passed}/{total} passed")
    if all_failed:
        print("FAILED: " + "; ".join(all_failed))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
