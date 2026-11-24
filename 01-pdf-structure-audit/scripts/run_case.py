#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_case.py — 平台入口：读 /input，跑完整流水线，把 result.json 写到 /app/output。

为什么要有这一层（而不是让 Agent 自己拼 python 命令）：
1) 运行时契约只保证给了 `/input/case.json` 和 `/input/task.md`，**没有保证 case.json 里
   文件字段叫什么**。不同案例可能用 `files` / `materials` / `attachments` / `pdf` / `input`。
   所以这里做"键名不敏感"的查找：先按已知键名找，找不到就递归找 `/input` 下唯一的 PDF，
   再找不到才报错。报错也要落一份 result.json（status=blocked），不能只往 stderr 打一行。
2) 一次调用跑完六步，避免 Agent 在多轮里手工传中间文件——预算只有 64 次请求 / 900 秒，
   中间多一轮就可能超时。
3) 任何一步抛异常都要**先落已得的部分结果**再退出：契约明确要求"先存诚实的部分结果"。
   所以这里用分步 try：版面成功但表格失败，仍输出 document.json + status=partial。
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import make_result                 # noqa: E402

PDF_KEYS = ("pdf", "pdf_path", "file", "files", "material", "materials", "attachment",
            "attachments", "document", "documents", "input", "inputs", "source")


def _load_build():
    """延迟导入解析器，把"缺依赖"变成一条可读的 result.json 而不是 ImportError 栈。

    为什么要这么写：契约只声明镜像里有 scientific-python 一类工具，没有逐条保证 PyMuPDF
    的版本或是否安装。缺依赖时如果直接崩在 import，调用方只会看到 traceback，既不知道自己
    该装什么，也拿不到结构化结果。这里把 ImportError 转成 status=blocked + 安装提示。
    """
    try:
        import build as mod
        return mod, None
    except Exception as e:      # ImportError 及其它导入期异常
        return None, f"{type(e).__name__}: {e}"


def find_pdf(input_dir: Path, case: dict) -> Path | None:
    """按"已知键名 → 递归扫描"的顺序找输入 PDF。"""
    cands: list[Path] = []

    def push(v):
        if isinstance(v, str) and v.lower().endswith(".pdf"):
            p = Path(v)
            cands.append(p if p.is_absolute() else input_dir / p)
        elif isinstance(v, dict):
            for vv in v.values():
                push(vv)
        elif isinstance(v, list):
            for vv in v:
                push(vv)

    for k in PDF_KEYS:
        if k in case:
            push(case[k])
    for k, v in case.items():
        if "pdf" in k.lower():
            push(v)
    for p in cands:
        if p.exists():
            return p
    found = sorted(p for p in input_dir.rglob("*") if p.suffix.lower() == ".pdf")
    return found[0] if found else None


def write_blocked(outdir: Path, case: dict, reason: str, detail: str = "") -> dict:
    """失败也要交一份结构完整的 result.json，写明原因和人工接管位置。"""
    case_id = case.get("case_id") or case.get("id") or "unknown"
    contract = case.get("output_contract") or case.get("outputContract") or {}
    result = {
        "case_id": case_id,
        "status": "blocked",
        "task": "literature_pdf_parsing",
        "reason": reason,
        "detail": detail,
        "sources": [],
        "uncertainty": [reason] + ([detail] if detail else []),
        "changes": [{"type": "blocked", "detail": reason}],
        "handover": {"needs_human": True, "where": [reason, detail],
                     "suggest": "确认 /input 下有可读的 PDF 且 case.json 指向它；"
                                "若 PDF 有打开密码，需人工提供密码"},
        "output_contract": {k: None for k in contract} if isinstance(contract, dict) else {},
    }
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
    return result


def main() -> int:
    ap = argparse.ArgumentParser(
        description="科研 PDF 结构解析：读 /input 下的 case.json 与 PDF，产出 /app/output/result.json")
    ap.add_argument("--input", default="/input", help="输入目录（默认 /input）")
    ap.add_argument("--output", default="/app/output", help="产物目录（默认 /app/output）")
    ap.add_argument("--pdf", default=None, help="直接指定 PDF（覆盖自动查找）")
    ap.add_argument("--case", default=None, help="直接指定 case.json")
    ap.add_argument("--no-render", action="store_true", help="不导出公式区域 PNG（省时间）")
    args = ap.parse_args()

    input_dir = Path(args.input)
    outdir = Path(args.output)
    outdir.mkdir(parents=True, exist_ok=True)

    case_path = Path(args.case) if args.case else input_dir / "case.json"
    case = {}
    if case_path.exists():
        try:
            case = json.loads(case_path.read_text(encoding="utf-8"))
        except Exception as e:
            case = {}
            print(f"[warn] case.json 解析失败：{e}", file=sys.stderr)

    pdf = Path(args.pdf) if args.pdf else find_pdf(input_dir, case)
    if not pdf or not Path(pdf).exists():
        res = write_blocked(outdir, case, "输入中找不到 PDF 文件",
                            f"已查找 {input_dir}（含子目录）与 case.json 的文件字段")
        print(json.dumps({"status": res["status"], "reason": res["reason"]}, ensure_ascii=False))
        return 2

    # 第一步：版面 + 结构 + 表格 + 公式 + 锚点（build.run 内部按序执行六步）
    build_mod, dep_err = _load_build()
    if build_mod is None:
        res = write_blocked(outdir, case, "缺少运行依赖 PyMuPDF（import pymupdf 失败）",
                            f"{dep_err}；请先 pip install 'pymupdf>=1.23'")
        print(json.dumps({"status": res["status"], "reason": res["reason"]}, ensure_ascii=False))
        return 4
    try:
        built = build_mod.run(str(pdf), outdir, render=not args.no_render)
    except Exception:
        tb = traceback.format_exc(limit=6)
        res = write_blocked(outdir, case, "解析流水线异常中止", tb.strip().splitlines()[-1])
        (outdir / "traceback.txt").write_text(tb, encoding="utf-8")
        print(json.dumps({"status": "blocked", "reason": res["reason"]}, ensure_ascii=False))
        return 3

    if built.get("status") == "blocked":
        res = write_blocked(outdir, case, built["doc"].get("reason") or "PDF 无法打开",
                            "空密码尝试失败")
        print(json.dumps({"status": "blocked", "reason": res["reason"]}, ensure_ascii=False))
        return 2

    # 第二步：按 output_contract 组装 result.json
    doc = built["doc"]
    (outdir / "document.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1),
                                          encoding="utf-8")
    result = make_result.build(doc, case, outdir)
    result["inputs"] = {
        "case_json": str(case_path) if case_path.exists() else None,
        "pdf": str(pdf),
        "output_dir": str(outdir),
    }
    (outdir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1),
                                        encoding="utf-8")

    print(json.dumps({
        "status": result["status"],
        "case_id": result["case_id"],
        "pages": doc.get("page_count"),
        "counts": (doc.get("meta") or {}).get("counts"),
        "anchor_pass_rate": (doc.get("anchors") or {}).get("pass_rate"),
        "coverage_missing": [c["key"] for c in (doc.get("meta") or {}).get("coverage") or []
                             if not c["present"]],
        "contract_fields": result.get("output_contract_fields"),
        "uncertainty": len(result["uncertainty"]),
        "result": str(outdir / "result.json"),
    }, ensure_ascii=False, indent=1))
    return 0 if result["status"] in ("ok", "partial") else 1


if __name__ == "__main__":
    raise SystemExit(main())
