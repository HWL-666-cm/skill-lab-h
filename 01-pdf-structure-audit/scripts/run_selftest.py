#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_selftest.py — 自测：生成合成 PDF → 跑完整流水线 → 逐条断言 → 打一张表。

为什么要有这一层：赛后读这份代码的人（或评审）不该靠"作者说它能处理扫描件"来判断，
应该能自己跑一条命令，看到"扫描件 → status=partial、needs_ocr 页数=2、正文 0 段"。
断言写死的都是**行为**（状态、页数、锚点通过率、栏模式），不是具体文字，
所以不会因为改文案而误报。

用法：
    python scripts/run_selftest.py                 # 生成到临时目录并跑全部
    python scripts/run_selftest.py --keep DIR      # 保留生成的 PDF 与产物，便于人工核对
    python scripts/run_selftest.py --only two_column
退出码：全部通过 0，有失败 1。
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tests"))

import build as build_mod      # noqa: E402
import pdfcore                 # noqa: E402
import make_result             # noqa: E402


def _run_units(unit_specs: list[dict]) -> list[dict]:
    out = []
    for u in unit_specs:
        fn = u["fn"]
        try:
            if fn == "norm_text":
                got = pdfcore.norm_text(u["input"])
                ok = got == u["expect"]
            elif fn == "dehyphenate":
                a, b = u["input"].split("|")
                got = pdfcore.dehyphenate(a, b)
                ok = got == u["expect"]
            elif fn == "garbled_ratio_gt":
                got = round(pdfcore.garbled_ratio(u["input"]), 3)
                ok = got >= u["expect"]
            else:
                got, ok = f"未知断言 {fn}", False
        except Exception as e:
            got, ok = f"异常 {e}", False
        out.append({"id": u["id"], "what": u["what"], "ok": ok,
                    "got": got, "expect": u["expect"]})
    return out


def _run_case(spec: dict, pdf: Path, outdir: Path) -> dict:
    exp = spec["expect"]
    t0 = time.time()
    detail, ok = {}, True

    if exp.get("status") == ["blocked"]:
        doc = build_mod.layout.analyze(str(pdf)) if hasattr(build_mod, "layout") else None
        # 加密件走同一入口，确认它不会抛异常而是如实返回 blocked
        try:
            built = build_mod.run(str(pdf), outdir, render=False)
            status = built.get("status")
            reason = (built.get("doc") or {}).get("reason")
        except Exception:
            status, reason = "exception", traceback.format_exc(limit=2)
        detail = {"status": status, "reason": reason}
        ok = status in exp["status"] and (bool(reason) if exp.get("has_reason") else True)
        return {"id": spec["id"], "ok": ok, "detail": detail,
                "seconds": round(time.time() - t0, 2)}

    try:
        built = build_mod.run(str(pdf), outdir, render=False)
    except Exception:
        return {"id": spec["id"], "ok": False, "seconds": round(time.time() - t0, 2),
                "detail": {"exception": traceback.format_exc(limit=3)}}

    doc = built.get("doc") or {}
    meta = built.get("meta") or {}
    anchors = doc.get("anchors") or {}
    triage = doc.get("triage") or {}
    pages = doc.get("pages") or []
    modes = [pg["layout"]["mode"] for pg in pages]
    fm = doc.get("front_matter") or {}
    seconds = round(time.time() - t0, 2)

    # 走 make_result，确认契约层也能拿到 case_id/status（自测顺手覆盖这一层）
    result = make_result.build(dict(doc), {"case_id": spec["id"], "output_contract": {}}, outdir)

    detail = {
        "status": result["status"],
        "pages": doc.get("page_count"),
        "paragraphs": len(doc.get("body_paragraphs") or []),
        "sections": len(doc.get("sections") or []),
        "tables": len(doc.get("tables") or []),
        "layout_modes": sorted(set(modes)),
        "anchor": anchors.get("pass_rate"),
        "ocr_pages": triage.get("needs_ocr_pages"),
        "seconds": seconds,
    }

    def check(cond, why):
        nonlocal ok
        if not cond:
            ok = False
            detail.setdefault("failed", []).append(why)

    if "status" in exp:
        check(result["status"] in exp["status"], f"status={result['status']} 不在 {exp['status']}")
    if "layout_modes" in exp:
        bad = [m for m in set(modes) if m not in exp["layout_modes"]]
        check(not bad, f"出现非预期栏模式 {bad}（期望 {exp['layout_modes']}）")
    if "min_sections" in exp:
        check(len(doc.get("sections") or []) >= exp["min_sections"],
              f"章节 {len(doc.get('sections') or [])} < {exp['min_sections']}")
    if "min_tables" in exp:
        check(len(doc.get("tables") or []) >= exp["min_tables"],
              f"表格 {len(doc.get('tables') or [])} < {exp['min_tables']}")
    if "min_anchor" in exp:
        a = anchors.get("pass_rate")
        check(a is not None and a >= exp["min_anchor"], f"锚点通过率 {a} < {exp['min_anchor']}")
    if exp.get("max_paragraphs") is not None:
        n = len(doc.get("body_paragraphs") or [])
        check(n <= exp["max_paragraphs"], f"段落 {n} > {exp['max_paragraphs']}（疑似串栏切碎）")
    if exp.get("no_table_false_positive"):
        check(not (doc.get("tables") or []), f"误检出 {len(doc.get('tables') or [])} 张表（正文被当表格）")
    if exp.get("zero_paragraphs"):
        check(not (doc.get("body_paragraphs") or []), "无文字层的页不应产出正文")
    if exp.get("all_pages_ocr"):
        ocr = triage.get("needs_ocr_pages") or []
        check(len(ocr) == doc.get("page_count"), f"只有 {len(ocr)}/{doc.get('page_count')} 页路由 OCR")
    if exp.get("min_pages"):
        check((doc.get("page_count") or 0) >= exp["min_pages"],
              f"页数 {doc.get('page_count')} < {exp['min_pages']}")
    if exp.get("max_seconds"):
        check(seconds <= exp["max_seconds"], f"耗时 {seconds}s > {exp['max_seconds']}s")
    if exp.get("title_contains"):
        check(exp["title_contains"] in (fm.get("title") or ""),
              f"标题未识别：{fm.get('title')!r}")
    if exp.get("text_contains"):
        md = (outdir / "document.md")
        txt = md.read_text(encoding="utf-8") if md.exists() else ""
        check(exp["text_contains"] in txt, f"输出里没有 {exp['text_contains']!r}")
    if exp.get("order_no_backtrack"):
        import layout as layout_mod
        m = layout_mod.reading_order_metrics(doc)
        detail["backward_jumps"] = m.get("backward_jumps")
        detail["adjacent_pairs"] = m.get("adjacent_pairs")
        check(m.get("backward_jumps") == 0,
              f"阅读顺序出现 {m.get('backward_jumps')} 次回跳（串栏交错）")
    return {"id": spec["id"], "ok": ok, "detail": detail, "seconds": seconds}


def main() -> int:
    ap = argparse.ArgumentParser(description="合成用例自测")
    ap.add_argument("--cases", default=str(ROOT / "tests" / "cases.json"))
    ap.add_argument("--keep", default=None, help="保留生成物到此目录")
    ap.add_argument("--only", default=None, help="只跑指定 case（逗号分隔）")
    args = ap.parse_args()

    import make_cases  # noqa: E402

    spec = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    wanted = args.only.split(",") if args.only else [c["id"] for c in spec["cases"]]
    if args.keep:
        work = Path(args.keep)
        work.mkdir(parents=True, exist_ok=True)
        tmp_ctx = None
    else:
        tmp_ctx = tempfile.TemporaryDirectory(prefix="pdfskill_selftest_")
        work = Path(tmp_ctx.name)

    print("== 单元断言 ==")
    unit = _run_units(spec.get("unit_expect") or [])
    for u in unit:
        print(f"  [{'PASS' if u['ok'] else 'FAIL'}] {u['id']}: {u['got']!r}")

    print("== 合成件端到端 ==")
    runs = []
    for case in spec["cases"]:
        if case["id"] not in wanted:
            continue
        pdf = work / f"{case['id']}.pdf"
        if not pdf.exists():
            make_cases.BUILDERS[case["id"]](pdf)
        outdir = work / f"out_{case['id']}"
        r = _run_case(case, pdf, outdir)
        runs.append(r)
        print(f"  [{'PASS' if r['ok'] else 'FAIL'}] {r['id']}  {json.dumps(r['detail'], ensure_ascii=False)}")

    failed = [u for u in unit if not u["ok"]] + [r for r in runs if not r["ok"]]
    print(f"\n合计 {len(unit) + len(runs)} 项，通过 {len(unit) + len(runs) - len(failed)}，失败 {len(failed)}")
    if failures := [f["id"] for f in failed]:
        print("失败项：" + ", ".join(failures))
    if tmp_ctx is not None:
        tmp_ctx.cleanup()
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
