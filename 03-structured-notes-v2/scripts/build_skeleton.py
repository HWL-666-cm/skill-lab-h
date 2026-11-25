#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_skeleton.py — 结构化笔记骨架生成（阅读10｜文献总结与结构化笔记）

职责（确定性，无模型调用）：
  1. 把 extract_document.py 的解析结果转成"笔记骨架"：
     - section_tree：论文自身章节树（层级 path，如 3 → 3.1 → 3.1.1），供"对得上"；
     - paper_card：统一字段模板（研究问题/数据/方法/方法前提/发现/关键数值/局限/未报告）；
     - paragraphs/figures_tables/references：带 page/column/section 定位，供"找得回"锚点。
  2. 输出可检索的 JSON，供 Agent 按 SKILL.md 填充内容，供"用得上"。

本脚本不生成笔记内容本身（那是 Agent 的事），只生成"结构 + 锚点 + 空字段"。
"""

import json
import re
import sys


def build_section_tree(sections):
    """把扁平 sections 列表（含 level）重建成层级树。返回带 children 的树 + 路径。"""
    tree = []
    stack = []  # (level, node)
    for s in sections:
        level = s.get("level", 1)
        node = {
            "heading": s.get("heading", ""),
            "level": level,
            "page": s.get("page"),
            "children": [],
        }
        # 回退栈到父级
        while stack and stack[-1][0] >= level:
            stack.pop()
        if stack:
            parent = stack[-1][1]
            node["parent"] = parent["heading"]
            parent["children"].append(node)
        else:
            tree.append(node)
        stack.append((level, node))
    return tree


def assign_section_path(sections):
    """给每个 section 计算路径：编号章节用自身编号（如 2.1→'2.1'），无编号用标题。"""
    result = []
    for s in sections:
        text = (s.get("heading", "") or "").strip()
        m = re.match(r'^(\d+(?:\.\d+)*)', text)
        if m:
            path = m.group(1)
        else:
            path = text[:30]
        s2 = dict(s)
        s2["path"] = path
        result.append(s2)
    return result


def section_of(page, y0, sec_bounds):
    """返回 (page, y0) 之前的最近章节 path。"""
    cur = ""
    for sp, sy, path in sec_bounds:
        if (sp, sy) <= (page, y0):
            cur = path
    return cur


def _filter_sections(sections, title):
    """去掉非正文章节噪声：标题、arXiv 横幅、URL/脚注式标题。"""
    keep = []
    title_norm = re.sub(r"\s+", " ", title or "").strip().lower()
    for s in sections:
        h = (s.get("heading", "") or "").strip()
        if not h:
            continue
        hn = re.sub(r"\s+", " ", h).strip().lower()
        if hn == title_norm or title_norm.startswith(hn[:40]):
            continue  # 文档标题
        if re.match(r"^(arxiv:|cs\.|math\.|hep-|quant-)", h, re.I):
            continue  # arXiv 横幅
        if s.get("y0", 0) > 0.85:
            continue  # 页面底部 = 脚注区（非章节标题）
        if re.search(r"https?://|github\.com|\.edu/|\.org/", h):
            continue  # URL/脚注
        if re.match(r"^[a-z]", h) and not re.match(r"^\d", h):
            continue  # 小写开头 = 正文行（非标题）
        # 表格数据行：非空白字符中数字/小数点占比 >70%
        nonws = [c for c in h if not c.isspace()]
        if nonws and sum(c.isdigit() or c in ".·,−-–" for c in nonws) / len(nonws) > 0.7:
            continue
        if len(h) > 60:
            continue  # 过长 = 脚注/正文，非章节标题
        if re.search(r"[.!?。]$", h) and len(h) > 30:
            continue  # 句末标点且较长 = 脚注句子
        keep.append(s)
    return keep


def build_note_skeleton(extracted):
    """extracted: extract_document.py 的 parse_pdf 输出。"""
    doc = extracted.get("document", {})
    sections = extracted.get("sections", [])
    paragraphs = extracted.get("paragraphs", [])
    title = extracted.get("title", "")
    authors = extracted.get("authors", "")
    sections = _filter_sections(sections, title)

    sec_paths = assign_section_path(sections)
    sec_bounds = sorted([(s.get("page", 0), s.get("y0", 0), s.get("path", ""))
                         for s in sec_paths])

    # 段落 → 章节路径 + 锚点
    para_nodes = []
    for i, p in enumerate(paragraphs):
        page = p.get("page")
        y0 = p.get("y0", 0)
        text = (p.get("text") or "").strip()
        if not text:
            continue
        para_nodes.append({
            "id": i + 1,
            "page": page,
            "column": p.get("column"),
            "section": section_of(page, y0, sec_bounds),
            "text": text,
        })

    # 图表/表格锚点
    figures_tables = []
    for c in extracted.get("captions", []):
        figures_tables.append({"kind": "caption", "text": c.get("text", ""),
                               "page": c.get("page")})
    for t in extracted.get("tables", []):
        # table 可能是 dict（有 rows）或简化结构
        if isinstance(t, dict):
            figures_tables.append({"kind": "table",
                                   "text": (t.get("caption") or t.get("text") or "")[:200],
                                   "page": t.get("page")})
    for f in extracted.get("formulas", [])[:100]:
        figures_tables.append({"kind": "formula", "text": f.get("text", "")[:120],
                               "page": f.get("page")})

    # 论文卡片空模板（Agent 填写）
    paper_card = {
        "title": title,
        "authors": authors,
        "year": "",
        "source": doc.get("file", ""),
        "research_question": "",
        "objectives": [],
        "data": "",
        "method": "",
        "method_conditions": [],      # 让结论成立的前提条件（关键，避免"留不住"）
        "main_findings": [],           # [{claim, anchor, evidence_marker}]
        "key_numbers": [],             # [{value, unit, baseline, condition, anchor}]
        "limitations": [],
        "unreported": [],              # 原文未报告的信息（不补造）
    }

    return {
        "document": {
            "title": title,
            "authors": authors,
            "page_count": doc.get("page_count"),
            "ocr_used": doc.get("ocr_used", False),
            "warnings": extracted.get("warnings", []),
        },
        "section_tree": build_section_tree(sec_paths),
        "section_list": sec_paths,
        "paper_card": paper_card,
        "paragraphs": para_nodes,
        "figures_tables": figures_tables,
        "references": extracted.get("references", []),
        "footnotes": extracted.get("footnotes", []),
    }


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法: python3 build_skeleton.py <extracted.json> <skeleton.json>")
        sys.exit(1)
    extracted = json.load(open(sys.argv[1], encoding="utf-8"))
    skeleton = build_note_skeleton(extracted)
    json.dump(skeleton, open(sys.argv[2], "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print("wrote", sys.argv[2],
          "(sections=%d, paragraphs=%d, figures_tables=%d)"
          % (len(skeleton["section_list"]), len(skeleton["paragraphs"]),
             len(skeleton["figures_tables"])))
