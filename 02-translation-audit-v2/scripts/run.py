#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run.py — 评测环境入口（阅读03｜文献翻译 Skill）

评测约定（Harbor Runtime contract）：
  原始输入：/input/case.json  与  /input/task.md
  工作目录：/app/work（中间产物）
  最终结果：/app/output/result.json（含 case_id 与 case.json 中 output_contract 的全部字段）

职责（确定性部分，不产生译文本身）：
  1. 读取 /input/case.json 与 /input/task.md；
  2. 定位输入材料（PDF 等），调用 extract_document.py 结构化解析；
  3. 调用 prepare_translation.py 生成"段落级翻译任务"（含候选术语表 + 占位符保护）；
  4. 生成 /app/output/result.json 草稿：case_id + output_contract 字段占位 +
     双语段落骨架（原文 + 定位 + 保护后文本）+ 候选术语表 + 状态 + 不确定性 + 变更记录。

译文本身由加载本 Skill 的 Agent 依据 SKILL.md 的术语约束与占位符规则逐段完成，
并用 validate_translation.py 核验与强制回填。本脚本不预制答案。
"""

import json
import os
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
        return {"_error": "无法读取 %s: %s" % (path, e)}


def find_material_path(case: dict):
    candidates = []
    for key in ("material", "input", "pdf", "file", "files", "path", "document",
                "source", "resource", "url", "input_path", "material_path"):
        v = case.get(key)
        if isinstance(v, str):
            candidates.append(v)
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, str):
                    candidates.append(item)
    # 材料可能在 /input 目录
    if os.path.isdir("/input"):
        for name in os.listdir("/input"):
            if name.lower().endswith((".pdf", ".txt", ".docx", ".md")):
                candidates.append(os.path.join("/input", name))
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return (candidates[0] if candidates else "")


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main():
    os.makedirs(WORK_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    case = load_json(INPUT_CASE)
    task = ""
    try:
        with open(INPUT_TASK, encoding="utf-8") as f:
            task = f.read()
    except Exception:
        pass

    case_id = case.get("case_id") or case.get("id") or "unknown"
    output_contract = case.get("output_contract") or {}
    if isinstance(output_contract, dict):
        answer_placeholder = {k: None for k in output_contract.keys()}
    else:
        answer_placeholder = {}

    material = find_material_path(case)
    changes = []
    warnings = []
    status = "success"
    status_detail = ""
    structured = {"bilingual_segments": [], "term_candidates": [],
                  "termbase": [], "document": {}}

    if not material or not os.path.exists(material):
        status = "failed"
        status_detail = "未定位到输入材料（/input 下无 PDF/txt/docx）。"
        warnings.append(status_detail)
    else:
        changes.append({"time": now_iso(), "action": "定位材料", "detail": material})
        ext_json = os.path.join(WORK_DIR, "extracted.json")
        job_json = os.path.join(WORK_DIR, "translation_job.json")
        # 1) 结构化解析
        r = subprocess.run(
            [sys.executable, os.path.join(HERE, "extract_document.py"),
             material, ext_json, "--workdir", os.path.join(WORK_DIR, "ext")],
            capture_output=True, text=True)
        if r.returncode != 0 or not os.path.exists(ext_json):
            status = "failed"
            status_detail = "结构化解析失败：%s" % (r.stderr.strip()[:300] or "未知错误")
            warnings.append(status_detail)
        else:
            extracted = load_json(ext_json)
            if extracted.get("status") == "failed":
                status = "failed"
                status_detail = extracted.get("status_detail", "解析失败")
                warnings.append(status_detail)
            else:
                # 2) 生成段落级翻译任务（候选术语表 + 占位符保护）
                r2 = subprocess.run(
                    [sys.executable, os.path.join(HERE, "prepare_translation.py"),
                     ext_json, job_json],
                    capture_output=True, text=True)
                if r2.returncode != 0 or not os.path.exists(job_json):
                    warnings.append("翻译任务生成失败：%s" % r2.stderr.strip()[:300])
                else:
                    job = load_json(job_json)
                    structured["bilingual_segments"] = [
                        {"id": s["id"], "page": s.get("page"),
                         "column": s.get("column"), "section": s.get("section"),
                         "source": s["source"], "protected": s["protected"],
                         "protection_map": s["protection_map"],
                         "kind": s["kind"], "do_not_translate": s["do_not_translate"]}
                        for s in job.get("segments", [])
                    ]
                    structured["term_candidates"] = job.get("term_candidates", [])
                    structured["termbase"] = job.get("termbase", [])
                    structured["document"] = job.get("document", {})
                    changes.append({"time": now_iso(), "action": "生成翻译任务",
                                    "detail": "segments=%d, term_candidates=%d"
                                    % (job.get("segment_count", 0),
                                       len(job.get("term_candidates", [])))})

    result = {
        "case_id": case_id,
        "answer": answer_placeholder,
        "structured": structured,
        "evidence": [],
        "status": status,
        "status_detail": status_detail,
        "uncertainty": [],
        "warnings": warnings,
        "changes": changes,
    }
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("wrote", OUTPUT_JSON, "(status=%s, segments=%d)"
          % (status, len(structured["bilingual_segments"])))


if __name__ == "__main__":
    main()
