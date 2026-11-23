#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_selftest.py —— 一条命令验证本 Skill 的审计脚本是否真的能抓错

做的三件事：
  1) 对每个用例，用"已知改坏的版本"跑审计，检查是否报出预期的问题（漏报 = 失败）
  2) 用"改好的版本"跑审计，检查是否误报（误报 = 失败）
  3) 术语用例额外验证"建表 → 回扫"的漂移检出能力

用法：
  python3 scripts/run_selftest.py            # 全部用例
  python3 scripts/run_selftest.py --verbose  # 打印每条用例的详细输出

退出码 0 = 全部通过；1 = 有失败项（可直接接进 CI）。
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
CASES = SKILL / "tests" / "cases.json"


def run(cmd):
    p = subprocess.run([sys.executable, *cmd], capture_output=True, text=True, encoding="utf-8")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def audit(script, original, revised, out):
    return run([str(HERE / script), "--original", original, "--revised", revised, "--out", out, "--quiet"])


def term_build(inp, out):
    return run([str(HERE / "term_audit.py"), "--input", inp, "--out", out])


def term_rescan(inp, glossary, out):
    return run([str(HERE / "term_audit.py"), "--input", inp, "--glossary", glossary, "--out", out])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    data = json.loads(CASES.read_text(encoding="utf-8"))
    cases = data["cases"]
    tmp = Path(tempfile.mkdtemp(prefix="skill-selftest-"))

    rows, failures = [], 0

    for c in cases:
        cid = c["id"]
        d = tmp / cid
        d.mkdir(parents=True, exist_ok=True)
        (d / "orig.txt").write_text(c["original"], encoding="utf-8")
        (d / "bad.txt").write_text(c["bad"], encoding="utf-8")
        (d / "good.txt").write_text(c["good"], encoding="utf-8")

        if c["check"] == "hedge":
            audit("hedge_audit.py", str(d / "orig.txt"), str(d / "bad.txt"), str(d / "bad.json"))
            audit("hedge_audit.py", str(d / "orig.txt"), str(d / "good.txt"), str(d / "good.json"))
            bad_r = json.loads((d / "bad.json").read_text(encoding="utf-8"))
            good_r = json.loads((d / "good.json").read_text(encoding="utf-8"))

            got = {f["kind"] for f in bad_r["flags"]}
            want = set(c["expect_bad_flags"])
            caught = want <= got
            clean = good_r["verdict"] == c["expect_good_verdict"]

            rows.append({
                "case": cid,
                "检出(应报的都报了)": "PASS" if caught else "FAIL",
                "误报(改好的未报警)": "PASS" if clean else "FAIL",
                "实际 flags": ",".join(sorted(got)) or "-",
            })
            if not (caught and clean):
                failures += 1
                if args.verbose:
                    print(f"\n[{cid}] 期望 {sorted(want)}，实际 {sorted(got)}；good verdict={good_r['verdict']}")
                    print(json.dumps(bad_r["flags"], ensure_ascii=False, indent=2))

        elif c["check"] == "term":
            term_build(str(d / "orig.txt"), str(d / "terms.json"))
            term_rescan(str(d / "bad.txt"), str(d / "terms.json"), str(d / "bad_t.json"))
            term_rescan(str(d / "good.txt"), str(d / "terms.json"), str(d / "good_t.json"))
            bad_t = json.loads((d / "bad_t.json").read_text(encoding="utf-8"))
            good_t = json.loads((d / "good_t.json").read_text(encoding="utf-8"))
            drift_bad = bad_t["drift_count"] > 0
            drift_good = good_t["drift_count"] > 0

            ok1 = drift_bad == c["expect_rescan_drift"]
            ok2 = drift_good == c["expect_rescan_drift_after_good"]
            rows.append({
                "case": cid,
                "检出(应报的都报了)": "PASS" if ok1 else "FAIL",
                "误报(改好的未报警)": "PASS" if ok2 else "FAIL",
                "实际 flags": f"drift_bad={bad_t['drift_count']}, drift_good={good_t['drift_count']}",
            })
            if not (ok1 and ok2):
                failures += 1
                if args.verbose:
                    print(f"\n[{cid}] drift_bad={bad_t['drift_count']} drift_good={good_t['drift_count']}")
                    print(json.dumps(bad_t.get("terms", []), ensure_ascii=False, indent=2)[:1200])

    w1 = max(len(r["case"]) for r in rows + [{"case": "case"}])
    print(f"\n{'case'.ljust(w1)}  {'检出':<6}{'误报':<6}  实际 flags")
    print("-" * (w1 + 44))
    for r in rows:
        print(f"{r['case'].ljust(w1)}  {r['检出(应报的都报了)']:<6}{r['误报(改好的未报警)']:<6}  {r['实际 flags']}")
    print("-" * (w1 + 44))
    total = len(rows)
    print(f"用例 {total} 条，通过 {total - failures} 条，失败 {failures} 条")
    print(f"临时目录：{tmp}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
