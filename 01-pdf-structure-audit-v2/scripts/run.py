#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run.py — 评测环境入口（阅读01｜文献文档解析 Skill）

评测约定（Harbor Runtime contract）：
  原始输入：/input/case.json  与  /input/task.md
  工作目录：/app/work（中间产物）
  最终结果：/app/output/result.json（含 case_id 与 case.json 中 output_contract 的全部字段）

本脚本职责：
  1. 读取 /input/case.json 与 /input/task.md；
  2. 定位案例输入材料（PDF 路径或材料描述）；
  3. 调用 extract_pdf.py 生成结构化解析结果；
  4. 生成 /app/output/result.json 草稿：case_id + output_contract 字段占位 +
     结构化解析 + 证据 + 状态 + 不确定性 + 变更记录。

重要：本脚本只做"确定性解析"，产出的 output_contract 字段为占位空值；
后续由加载本 Skill 的 Agent 依据题面与结构化结果填写真实答案并附证据定位。
不要用预制答案冒充正式案例结果。
"""

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone

INPUT_CASE = "/input/case.json"
INPUT_TASK = "/input/task.md"
WORK_DIR = "/app/work"
OUTPUT_DIR = "/app/output"
OUTPUT_JSON = "/app/output/result.json"
HERE = os.path.dirname(os.path.abspath(__file__))


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {"_error": f"无法读取 {path}: {e}"}


def find_material_path(case: dict) -> str:
    """
    从 case.json 中尽力定位输入材料（PDF 路径）。
    兼容多种字段命名，找不到时返回空字符串（由 Agent 后续判定）。
    """
    candidates = []
    # 常见字段名
    for key in ("material", "input", "pdf", "file", "files", "path", "document",
                "source", "resource", "url", "input_path", "material_path"):
        v = case.get(key)
        if isinstance(v, str):
            candidates.append(v)
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, str):
                    candidates.append(item)
                elif isinstance(item, dict):
                    for k2 in ("path", "file", "url", "material"):
                        if isinstance(item.get(k2), str):
                            candidates.append(item[k2])
    # 从 /input 目录找 PDF
    for c in candidates:
        if c.lower().endswith(".pdf") and os.path.exists(c):
            return c
        joined = os.path.join("/input", c) if not os.path.isabs(c) else c
        if os.path.exists(joined) and joined.lower().endswith(".pdf"):
            return joined
    # 兜底：扫描 /input 下所有 PDF
    for root, _dirs, files in os.walk("/input"):
        for fn in files:
            if fn.lower().endswith(".pdf"):
                return os.path.join(root, fn)
    return ""


def run_extractor(pdf_path: str, workdir: str) -> dict:
    """调用 extract_pdf.py。"""
    if not pdf_path:
        return {"status": "failed", "status_detail": "未定位到输入 PDF"}
    out_json = os.path.join(workdir, "extract_result.json")
    script = os.path.join(HERE, "extract_pdf.py")
    r = subprocess.run([sys.executable, script, pdf_path, out_json,
                        "--workdir", workdir],
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0 or not os.path.exists(out_json):
        return {"status": "failed",
                "status_detail": f"extract_pdf.py 失败: {r.stderr[-500:]}"}
    with open(out_json, encoding="utf-8") as f:
        return json.load(f)


def build_result(case: dict, task_md: str, extraction: dict) -> dict:
    """组装 result.json。output_contract 字段全部占位，供 Agent 填写。"""
    case_id = case.get("case_id") or case.get("id") or case.get("caseId") or ""
    # output_contract 可能是字段名列表，也可能是 {字段: 说明} 字典
    contract = case.get("output_contract") or case.get("outputs") or {}
    if isinstance(contract, list):
        contract_fields = {k: "" for k in contract if isinstance(k, str)}
    elif isinstance(contract, dict):
        contract_fields = {k: "" for k in contract.keys()}
    else:
        contract_fields = {}

    result = {
        "case_id": case_id,
        # 题面要求的输出字段：占位，Agent 需按题面填写真实答案
        "answer": contract_fields,
        # 结构化解析结果（可复核的结构）
        "structured": {
            "title": extraction.get("title", ""),
            "authors": extraction.get("authors", ""),
            "sections": extraction.get("sections", []),
            "tables": extraction.get("tables", []),
            "formulas": extraction.get("formulas", []),
            "captions": extraction.get("captions", []),
            "references": extraction.get("references", []),
            "footnotes": extraction.get("footnotes", []),
            "document": extraction.get("document", {}),
        },
        # 证据与来源定位
        "evidence": [],
        # 诚实状态：success / partial / failed / refused / unable_to_judge
        "status": extraction.get("status", "partial"),
        "status_detail": extraction.get("status_detail", ""),
        # 不确定项 / 未报告项
        "uncertainty": extraction.get("uncertainty", []),
        "warnings": extraction.get("warnings", []),
        # 变更记录（时间戳）
        "changes": [{
            "time": datetime.now(timezone.utc).isoformat(),
            "action": "extract_pdf 生成结构化草稿",
            "detail": f"段落 {extraction.get('paragraph_count')} 段，"
                      f"表格 {len(extraction.get('tables', []))}，"
                      f"公式 {extraction.get('formula_count')}，"
                      f"参考文献 {extraction.get('reference_count')}",
        }],
    }
    return result


def main():
    os.makedirs(WORK_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    case = load_json(INPUT_CASE)
    task_md = ""
    if os.path.exists(INPUT_TASK):
        with open(INPUT_TASK, encoding="utf-8", errors="replace") as f:
            task_md = f.read()

    if isinstance(case, dict) and case.get("_error"):
        result = {"status": "failed", "status_detail": case["_error"],
                  "case_id": "", "answer": {}, "evidence": [],
                  "uncertainty": [{"item": "case.json", "reason": case["_error"]}],
                  "changes": []}
    else:
        pdf_path = find_material_path(case if isinstance(case, dict) else {})
        extraction = run_extractor(pdf_path, WORK_DIR)
        result = build_result(case if isinstance(case, dict) else {}, task_md,
                              extraction)
        # 材料定位证据
        if pdf_path:
            result["evidence"].append({
                "item": "输入材料",
                "value": pdf_path,
                "source": "case.json / input",
            })

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"wrote {OUTPUT_JSON} (case_id={result.get('case_id')}, "
          f"status={result.get('status')})")


if __name__ == "__main__":
    main()
