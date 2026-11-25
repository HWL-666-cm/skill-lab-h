#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run.py — 评测环境入口（阅读14｜Nanopublication Skill）

评测约定（Harbor Runtime contract）：
  原始输入：/input/case.json 与 /input/task.md
  最终结果：/app/output/result.json（含 case_id 与 output_contract 全部字段）

职责（确定性部分，不生成断言内容本身）：
  1. 读取 case.json/task.md，定位输入材料；
  2. 调用 extract_document.py 提取章节/段落/标题/作者（供证据定位与 pubinfo）；
  3. 加载受控关系词表 predicates.json，提供 nanopub 空模板与质量检查器；
  4. 写 result.json 草稿：case_id + output_contract 占位 + nanopub 上下文 + 状态。

断言拆分（subject/predicate/object）、证据绑定、来源元数据由加载本 Skill 的 Agent
依据 SKILL.md 的拆解规则/受控词表/证据最小充分性规则填写，并用
nanopub_schema.py 做质量检查。本脚本不预制答案。
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


def find_material_path(case):
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
    answer_placeholder = ({k: None for k in output_contract.keys()}
                          if isinstance(output_contract, dict) else {})

    material = find_material_path(case)
    changes, warnings = [], []
    status = "success"
    status_detail = ""

    # 加载受控关系词表
    predicates_path = os.path.join(HERE, "..", "resources", "predicates.json")
    predicates = load_json(predicates_path).get("predicates", []) if os.path.exists(predicates_path) else []

    context = {"sections": [], "title": "", "authors": "", "predicates": predicates,
               "nanopub_template": {}, "paragraphs": []}

    if not material or not os.path.exists(material):
        status = "failed"
        status_detail = "未定位到输入材料（/input 下无 PDF/txt/docx）。"
        warnings.append(status_detail)
    else:
        changes.append({"time": now_iso(), "action": "定位材料", "detail": material})
        ext_json = os.path.join(WORK_DIR, "extracted.json")
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
                # 复用 nanopub_schema 的空模板
                sys.path.insert(0, HERE)
                try:
                    from nanopub_schema import empty_nanopub_template
                    context["nanopub_template"] = empty_nanopub_template()
                except Exception as e:
                    warnings.append("加载 nanopub 模板失败：%s" % e)
                context["sections"] = extracted.get("sections", [])
                context["paragraphs"] = extracted.get("paragraphs", [])
                context["title"] = extracted.get("title", "")
                context["authors"] = extracted.get("authors", "")
                changes.append({"time": now_iso(), "action": "生成 nanopub 上下文",
                                "detail": "sections=%d, predicates=%d"
                                % (len(context["sections"]), len(predicates))})

    result = {
        "case_id": case_id,
        "answer": answer_placeholder,
        "structured": context,
        "evidence": [],
        "status": status,
        "status_detail": status_detail,
        "uncertainty": [],
        "warnings": warnings,
        "changes": changes,
    }
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("wrote", OUTPUT_JSON, "(status=%s, sections=%d, predicates=%d)"
          % (status, len(context["sections"]), len(predicates)))


if __name__ == "__main__":
    main()
