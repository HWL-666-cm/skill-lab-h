#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run.py — 评测环境入口（阅读14｜Nanopublication Skill，v2）

评测约定（Harbor Runtime contract）：
  原始输入：/input/case.json 与 /input/task.md
  最终结果：/app/output/result.json（含 case_id 与 output_contract 全部字段）

编排：extract →（Agent 填断言）→ emit → validate → contract。

两阶段（由 /app/work/nanopubs.json 是否存在决定）：
  阶段 A（无断言文件）：extract_document.py + pdf_text.py 提取，写骨架 result.json
                       （status=partial，assertions 为空，附章节/受控词表/空模板上下文），
                       提示 Agent 拆断言写入 /app/work/nanopubs.json 后重跑。
  阶段 B（有断言）：读断言 → emit.to_legacy_claim 转四图格式 → emit.build_trig 出
                   assertions.trig → validate.validate 逐条校验 → emit.build_result
                   出 result.json（顶层 assertions[]）→ contract.apply 补 output_contract。

不变量：assertions 为空时绝不写 status=success；TriG 为空时绝不写 success。
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import pdf_text          # noqa: E402  引用定位引擎（validate 依赖其 normalize/句子索引）
import emit              # noqa: E402  四图 TriG 渲染
import validate as validate_mod  # noqa: E402  逐条断言校验
import contract          # noqa: E402  output_contract 顶层字段补齐

INPUT_CASE = "/input/case.json"
INPUT_TASK = "/input/task.md"
WORK = "/app/work"
OUT = "/app/output"
OUT_JSON = "/app/output/result.json"
LEXICON = HERE.parent / "resources" / "predicates.json"
NANOPUBS = os.path.join(WORK, "nanopubs.json")


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {"_error": "无法读取 %s: %s" % (path, e)}


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def find_material(case):
    candidates = []
    for key in ("material", "input", "pdf", "file", "files", "path", "document",
                "source", "resource", "input_path", "material_path"):
        v = case.get(key)
        if isinstance(v, str):
            candidates.append(v)
        elif isinstance(v, list):
            candidates.extend(x for x in v if isinstance(x, str))
    if os.path.isdir("/input"):
        for name in os.listdir("/input"):
            if name.lower().endswith((".pdf", ".txt", ".docx", ".md")):
                candidates.append(os.path.join("/input", name))
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return (candidates[0] if candidates else "")


def load_nanopubs():
    """从 Agent 写的 nanopubs.json 或 result.json 的 answer 里捞断言列表。"""
    if os.path.exists(NANOPUBS):
        data = load_json(NANOPUBS)
        for key in ("nanopubs", "assertions", "claims", "items"):
            v = data.get(key)
            if isinstance(v, list) and v:
                return v
        if isinstance(data, list):
            return data
    if os.path.exists(OUT_JSON):
        r = load_json(OUT_JSON)
        ans = r.get("answer") or {}
        if isinstance(ans, list):
            return ans
        for val in ans.values():
            if isinstance(val, list) and val and isinstance(val[0], dict) \
                    and ("assertion" in val[0] or "subject" in val[0]):
                return val
    return []


def build_source(nanopubs, extracted):
    """从第一条断言的 pubinfo 取来源元数据，作为 emit 的 source IRI。"""
    pi = {}
    for np in nanopubs:
        p = np.get("pubinfo") or {}
        if p.get("paper") or p.get("identifier"):
            pi = p
            break
    ident = pi.get("identifier") or ""
    return {
        "name": pi.get("paper") or extracted.get("title") or os.path.basename("material"),
        "iri": ident or "urn:source:unidentified",
        "doi": ident if ident.startswith(("10.", "doi:")) else "",
        "title": pi.get("paper") or extracted.get("title", ""),
        "year": pi.get("year"),
    }


def write_json(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8", newline="\n")


def main():
    os.makedirs(WORK, exist_ok=True)
    os.makedirs(OUT, exist_ok=True)
    case = load_json(INPUT_CASE)
    case_id = case.get("case_id") or case.get("id") or "unknown"
    output_contract = case.get("output_contract") if isinstance(case, dict) else None
    material = find_material(case)
    warnings, changes = [], []

    # ---- 阶段 A：extract（两条线并行，都不失败才算可用）----
    extracted = {}
    if material and os.path.exists(material):
        ext_json = os.path.join(WORK, "extracted.json")
        r = subprocess.run(
            [sys.executable, str(HERE / "extract_document.py"), material,
             ext_json, "--workdir", os.path.join(WORK, "ext")],
            capture_output=True, text=True)
        if r.returncode == 0 and os.path.exists(ext_json):
            extracted = load_json(ext_json)
            changes.append({"time": now_iso(), "action": "extract_document",
                            "detail": "sections=%d" % len(extracted.get("sections", []))})
        else:
            warnings.append("extract_document.py 失败：%s" % (r.stderr.strip()[:200] or "未知"))

    parsed = {}
    try:
        doc = pdf_text.parse(material)
        parsed = doc.to_dict()
        write_json(os.path.join(WORK, "parsed.json"), parsed)
        changes.append({"time": now_iso(), "action": "pdf_text.parse",
                        "detail": "sentences=%d" % parsed.get("source", {}).get("n_sentences", 0)})
    except Exception as e:
        warnings.append("pdf_text.parse 失败（引用定位将降级）：%s" % e)

    lexicon = load_json(LEXICON)
    relations = sorted((lexicon.get("relations") or {}).keys())

    # 空模板（给 Agent 参考）
    try:
        from nanopub_schema import empty_nanopub_template
        template = empty_nanopub_template()
    except Exception:
        template = {}

    context = {
        "sections": extracted.get("sections", []),
        "title": extracted.get("title", ""),
        "authors": extracted.get("authors", ""),
        "relations": relations,
        "entity_types": sorted((lexicon.get("entity_types") or {}).keys()),
        "nanopub_template": template,
    }

    nanopubs = load_nanopubs()

    if not material or not os.path.exists(material):
        result = {"case_id": case_id, "status": "failed",
                  "task": "nanopublication-assertion-extraction",
                  "input": {"file": material or ""}, "assertions": [], "sources": [],
                  "validation": {"status": "fail", "reason": "no input material found"},
                  "uncertainty": ["未定位到输入材料（/input 下无 PDF/txt/docx）"],
                  "warnings": warnings, "changes": changes, "structured": context}
        result, _ = contract.apply(result, output_contract)
        write_json(OUT_JSON, result)
        print(json.dumps({"status": "failed", "reason": result["uncertainty"][0]},
                         ensure_ascii=False))
        return

    # ---- 阶段 A 出口：无断言 → 骨架，status=partial，绝不 success ----
    if not nanopubs:
        result = {
            "case_id": case_id, "status": "partial",
            "task": "nanopublication-assertion-extraction",
            "input": {"file": os.path.basename(material),
                      "pages": (extracted.get("page_count") or
                                (parsed.get("source") or {}).get("n_pages"))},
            "assertions": [], "sources": [],
            "validation": {"status": "fail", "reason": "no assertions filled yet",
                           "n_assertions": 0,
                           "counts": {"pass": 0, "warn": 0, "fail": 0}},
            "uncertainty": ["断言尚未生成。请按 SKILL.md 拆解断言并写入 /app/work/nanopubs.json，"
                            "然后重跑 run.py 以完成 emit + validate。"],
            "warnings": warnings, "changes": changes, "structured": context,
        }
        result, _ = contract.apply(result, output_contract)
        write_json(OUT_JSON, result)
        print(json.dumps({"status": "partial", "phase": "skeleton",
                          "sections": len(context["sections"]),
                          "relations": len(relations)}, ensure_ascii=False))
        return

    # ---- 阶段 B：emit → validate → contract ----
    legacy_claims = [emit.to_legacy_claim(np, lexicon) for np in nanopubs]
    draft = {"case_id": case_id, "assertions": legacy_claims,
             "uncertainty": [u.get("reason") or u.get("item") or str(u)
                             for np in nanopubs for u in (np.get("uncertainty") or [])]}
    source = build_source(nanopubs, extracted)
    trig = emit.build_trig(legacy_claims, source)

    report = validate_mod.validate(draft, parsed, lexicon, trig)
    result = emit.build_result(case_id, draft, report, source, parsed,
                               report["status"], draft.get("uncertainty") or [])
    result, contract_report = contract.apply(result, output_contract)

    # 保证：TriG 为空绝不 success
    if not trig.strip() or not legacy_claims:
        result["status"] = "partial"
        result["uncertainty"] = list(result.get("uncertainty") or []) + \
            ["no assertions could be emitted to TriG"]

    emit.write_all(Path(OUT), trig, result, report)
    print(json.dumps({"status": result["status"], "n_assertions": len(legacy_claims),
                      "counts": report.get("counts"),
                      "contract_missing": contract_report.get("missing", [])},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
