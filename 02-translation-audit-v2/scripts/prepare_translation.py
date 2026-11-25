#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
prepare_translation.py — 翻译前准备（阅读03｜文献翻译 Skill）

职责（全部为确定性、可复现、无外部模型调用）：
  1. 从结构化解析结果生成"段落级翻译任务"（段落号 ↔ 原文 ↔ 页码/栏位/章节定位）；
  2. 抽取候选术语表（缩略词 + 首字母大写多词短语 + 高频 n-gram），供 Agent 确认译名；
  3. 对每段做"占位符保护"：把文献引用、数字+单位、URL/DOI、公式块替换成 {{P_n}}，
     确保翻译后这些要素与原文逐一对应（关系准 / 可核验）。

术语表被"真正执行"的关键在 validate_translation.py：翻译后由代码校验并强制回填，
而不是只在提示词里写一句"请使用术语表"。
"""

import json
import re
import sys
from collections import Counter

# ---------------------------------------------------------------------------
# 占位符保护：这些要素翻译时不得改动
# ---------------------------------------------------------------------------
_CITATION_RE = re.compile(r'\[(\d+(?:\s*[,，、\-–—]\s*\d+)*)\]')          # [12], [26, 27], [12-14]
_AUTHYEAR_RE = re.compile(                                                  # (Zhu et al., 2015), (Wang et al., 2018a)
    r'\([A-Z][a-zA-Z\-]+(?:\s+et\s+al\.)?(?:\s*[,，]?\s*(?:and|&)\s*[A-Z][a-zA-Z\-]+)?'
    r'\s*[,，]\s*(?:19|20)\d{2}[a-z]?\)'
)
_URL_RE = re.compile(
    r'(?:https?://|doi:|DOI:|www\.|arXiv:)\S+'
    r'|[\w.+-]+@[\w-]+\.[\w.-]+'                                           # email
)
# 数字 + 单位（单位本身跨语言一致，保护整个"数字+单位"避免错位/误译）
_UNIT_LIST = (
    r'%|‰|°C|°F|K|ms|s|kg|g|mg|m|cm|mm|km|µm|nm|MHz|GHz|Hz|W|kW|mW|'
    r'V|kV|A|mA|Ω|mol|M|L|mL|dB|bps|Mbps|Gbps|B|KB|MB|GB|TB|FLOPS'
)
_NUM_UNIT_RE = re.compile(
    r'(?<![\w])\d+(?:[.,]\d+)*(?:\s*[×xX]\s*10\^?-?\d+)?\s*(?:' + _UNIT_LIST + r')(?![%\w])'
)
_EQUATION_NUM_RE = re.compile(r'(?<![\w])\(\d+\)(?![\w])')                # 公式编号 (1) (2)


def protect_segment(text: str):
    """
    把不可改动的要素替换为 {{P_n}}，返回 (protected_text, protection_map)。
    protection_map: {"{{P_0}}": 原文片段, ...}
    """
    if not text:
        return text, {}
    mapping = {}
    counter = 0

    def repl(m):
        nonlocal counter
        token = "{{P_%d}}" % counter
        counter += 1
        mapping[token] = m.group(0)
        return token

    # 先保护公式编号、引用（数字式 + 作者年份式）、URL、数字+单位（按"整体优先"顺序）
    text = _EQUATION_NUM_RE.sub(repl, text)
    text = _CITATION_RE.sub(repl, text)
    text = _AUTHYEAR_RE.sub(repl, text)
    text = _URL_RE.sub(repl, text)
    text = _NUM_UNIT_RE.sub(repl, text)
    return text, mapping


def _is_formula_paragraph(para: dict) -> bool:
    """借用 extract_document.py 的公式标记（若存在），公式段整体不译。"""
    if para.get("kind") == "formula" or para.get("is_formula"):
        return True
    txt = para.get("text", "")
    if not txt:
        return False
    # 数学字体/高密度特殊字符的启发式兜底
    special = sum(1 for c in txt if not c.isalnum() and not c.isspace())
    if len(txt) < 200 and special >= max(3, len(txt) * 0.15):
        return True
    return False


# ---------------------------------------------------------------------------
# 候选术语抽取（确定性，供 Agent 确认译名）
# ---------------------------------------------------------------------------
_ACRONYM_RE = re.compile(r'\b[A-Z]{2,8}\b')
_CAP_PHRASE_RE = re.compile(r'\b[A-Z][a-zA-Z\-]+(?:\s+[A-Z][a-zA-Z\-]+)+\b')

_STOP = {
    "the", "and", "for", "with", "that", "this", "from", "have", "has",
    "were", "are", "was", "will", "can", "not", "our", "their", "these",
    "those", "into", "over", "under", "than", "then", "where", "which",
    "when", "while", "each", "such", "between", "using", "also", "however",
    "although", "because", "section", "figure", "table", "appendix",
    "introduction", "related", "work", "experiments", "results", "method",
    "methods", "conclusion", "abstract", "references", "we", "they", "it",
}


def extract_term_candidates(paragraphs, max_terms=80):
    """抽取候选术语：缩略词 + 首字母大写多词短语 + 高频双词/三词短语。"""
    full_text = "\n".join(p.get("text", "") for p in paragraphs)
    candidates = Counter()

    # 1) 缩略词
    for m in _ACRONYM_RE.finditer(full_text):
        w = m.group(0)
        if w not in ("I", "A", "B", "II", "III", "IV", "V", "VI", "VII", "VIII"):
            candidates[("acronym", w)] += 1

    # 2) 首字母大写多词短语（疑似专有名词）
    for m in _CAP_PHRASE_RE.finditer(full_text):
        words = m.group(0).split()
        words = [w for w in words if w.lower() not in _STOP]
        if len(words) >= 2 and any(w[0].isupper() for w in words):
            candidates[("phrase", " ".join(words))] += 1

    # 3) 高频双词/三词短语（去停用词，小写）
    tokens = re.findall(r"[a-zA-Z][a-zA-Z\-]{2,}", full_text.lower())
    for n in (2, 3):
        for i in range(len(tokens) - n + 1):
            gram = tokens[i:i + n]
            if any(w in _STOP for w in gram):
                continue
            candidates[("ngram", " ".join(gram))] += 1

    # 只保留出现 ≥3 次的，按频次排序
    result = []
    for (kind, term), cnt in candidates.most_common():
        if cnt < 3:
            continue
        result.append({"term": term, "kind": kind, "count": cnt})
        if len(result) >= max_terms:
            break
    return result


# ---------------------------------------------------------------------------
# 行 → 段落 聚合（段落全：跨页/跨栏不漏段、不重复、不错位）
# ---------------------------------------------------------------------------
def group_lines_to_paragraphs(lines):
    """
    lines: extract_document.py 输出的 body 行（含 page/column/y0/y1/x0/text）。
    把同页同栏、且纵向上连续的"行"聚成段落；换段依据：
      - 行间距明显大于本栏中位行距（空行分隔）；
      - 或行首缩进（x0 显著大于本栏正文左缘）。
    返回 [{text, page, column, y0, y1, first_line_indent, line_count}]。
    """
    if not lines:
        return []
    # 按 (page, column) 分组，组内按 y0 排序
    groups = {}
    for l in lines:
        key = (l.get("page"), l.get("column"))
        groups.setdefault(key, []).append(l)
    paragraphs = []
    for key, ls in groups.items():
        ls.sort(key=lambda x: (x.get("y0", 0), x.get("x0", 0)))
        # 本栏中位行距（连续行 y0 差值）
        gaps = [ls[i + 1]["y0"] - ls[i]["y0"]
                for i in range(len(ls) - 1)
                if 0 < (ls[i + 1]["y0"] - ls[i]["y0"]) < 0.1]
        median_gap = sorted(gaps)[len(gaps) // 2] if gaps else 0.03
        # 本栏正文左缘：x0 的众数（排除首行缩进）
        x0s = [l.get("x0", 0) for l in ls]
        x0_mode = max(set(x0s), key=x0s.count) if x0s else 0.0
        cur = None
        for l in ls:
            x0 = l.get("x0", 0)
            y0 = l.get("y0", 0)
            indented = (x0 - x0_mode) > 0.015
            new_para = False
            if cur is None:
                new_para = True
            else:
                gap = y0 - cur["y1"]
                # 空行（gap 明显大于中位行距）或 首行缩进 → 新段
                if gap > max(median_gap * 1.7, 0.02):
                    new_para = True
                elif indented and cur["line_count"] > 0:
                    new_para = True
            if new_para:
                cur = {"text": l.get("text", ""), "page": key[0],
                       "column": key[1], "y0": y0,
                       "y1": l.get("y1", y0), "line_count": 1,
                       "first_line_indent": indented}
                paragraphs.append(cur)
            else:
                cur["text"] += " " + l.get("text", "")
                cur["y1"] = max(cur["y1"], l.get("y1", y0))
                cur["line_count"] += 1
    # 全局阅读顺序：先页、再栏（左→右）、再 y0
    paragraphs.sort(key=lambda p: (p["page"] or 0, p["column"] or 0, p["y0"]))
    return paragraphs


# ---------------------------------------------------------------------------
# 段落级翻译任务生成
# ---------------------------------------------------------------------------
def build_translation_job(extracted: dict, termbase: list = None, max_paras=None):
    """
    extracted: extract_document.py 的 parse_pdf 输出
    termbase: 已确认的术语表 [{source, target, do_not_translate, forbidden_alternatives}]
    返回 translation_job：segments（每段带 id/页码/栏位/章节/原文/保护后文本/占位符映射）。
    """
    lines = extracted.get("paragraphs", []) or []
    sections = extracted.get("sections", [])
    doc = extracted.get("document", {})

    # 章节定位：用 section 的 page + y0 近似（段落在哪个 section 之下）
    sec_boundaries = sorted(
        [(s.get("page", 0), s.get("y0", 0), s.get("heading", "")) for s in sections])

    def section_of(page, y0):
        cur = ""
        for sp, sy, sh in sec_boundaries:
            if (sp, sy) <= (page, y0):
                cur = sh
        return cur

    # 行 → 段落
    paras = group_lines_to_paragraphs(lines)

    segments = []
    for i, p in enumerate(paras):
        pid = i + 1
        text = p.get("text", "").strip()
        if not text:
            continue
        page = p.get("page")
        y0 = p.get("y0", 0)
        col = p.get("column")
        if _is_formula_paragraph(p):
            segments.append({
                "id": pid, "page": page, "column": col,
                "section": section_of(page, y0),
                "source": text, "protected": text, "protection_map": {},
                "kind": "formula", "do_not_translate": True,
            })
            continue
        protected, pmap = protect_segment(text)
        segments.append({
            "id": pid, "page": page, "column": col,
            "section": section_of(page, y0),
            "source": text, "protected": protected, "protection_map": pmap,
            "kind": "text", "do_not_translate": False,
        })

    if max_paras:
        segments = segments[:max_paras]

    return {
        "document": {
            "title": doc.get("title", ""),
            "page_count": doc.get("page_count"),
            "ocr_used": doc.get("ocr_used", False),
            "warnings": extracted.get("warnings", []),
        },
        "term_candidates": extract_term_candidates(lines),
        "termbase": termbase or [],
        "segment_count": len(segments),
        "segments": segments,
    }


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法: python3 prepare_translation.py <extracted.json> <job.json> [--max-paras N]")
        sys.exit(1)
    src, dst = sys.argv[1], sys.argv[2]
    max_paras = None
    if "--max-paras" in sys.argv:
        max_paras = int(sys.argv[sys.argv.index("--max-paras") + 1])
    extracted = json.load(open(src, encoding="utf-8"))
    job = build_translation_job(extracted, max_paras=max_paras)
    json.dump(job, open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("wrote", dst, "(segments=%d, term_candidates=%d)"
          % (job["segment_count"], len(job["term_candidates"])))
