#!/usr/bin/env python3
"""PDF -> 带页码文本 + 章节骨架 + 异常标记。

设计依据（来自对真实论文 PDF 的探测，见 _validation/probe_*.py）：
1. 中文黑体(FZHTK/GBK)与英文 Bold 是章节标题的强信号；
2. 英文编号标题(如 '1 Introduction')常常不加粗，需要编号兜底；
3. 图题('图 3 2023...')、期刊栏头('OPEN')、关键词行会被误抓，需要后处理过滤；
4. 中文 PDF 有公式/符号乱码(控制字符)，必须标记而不是当正文。

不依赖平台预提取层，直接读 PDF 原生文本。无 pymupdf 时明确报错，交给平台 pdf-text-tool。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

try:
    import pymupdf
except ImportError:
    try:
        import fitz as pymupdf  # type: ignore
    except ImportError:
        pymupdf = None

# ---------- 标题识别 ----------
CN_HEAD_FONT = re.compile(r"FZHTK|Hei|Black|SimHei|Heiti|黑体|方正小标", re.I)
EN_BOLD_FONT = re.compile(r"bold|black|semibold", re.I)
PURE_NUM = re.compile(r"^\s*(\d+(?:\.\d+)*)\s*$")
NUM_HEAD = re.compile(r"^\s*(\d+(?:\.\d+)*)[\s\u3000]+(.{1,60})$")
CN_WORD = re.compile(r"^[\u4e00-\u9fa5]{2,14}$")
EN_WORD = re.compile(r"^[A-Za-z][A-Za-z \-&/']{2,55}$")
# 编号后跟"数字+单位/年份"不是标题，如 "2 h."、"3 2023"（图题）
NOT_A_TITLE_TAIL = re.compile(
    r"^(\d|19\d{2}|20\d{2})([ \u3000]*(h|d|m|s|km|%|°|\.|year|years|d\.|\d))", re.I
)

# 明确不是标题的行（页眉页脚/元数据标签/图题）
HEADING_BLACKLIST = re.compile(
    r"^(OPEN|关键词|中图分类号|文献标志码|文章编号|收稿日期|修回日期|基金项目|"
    r"第一作者|通信作者|摘\s*要|Abstract|https?://|www\.|doi|Vol\.|doi:|"
    r"第\s*\d+\s*卷|第\s*\d+\s*期|Journal|海洋气象学报|Scientific Reports)",
    re.I,
)
FIGURE_CAPTION = re.compile(r"^(图|表|Fig\.?|Table)\s*\d", re.I)

# ---------- 异常文本 ----------
CTRL_OR_PUA = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ue000-\uf8ff]")


def normalize_for_match(text: str) -> str:
    """比对用规范化：全角->半角、去所有空白、NFKC。只用于核验，不改原文。"""
    s = unicodedata.normalize("NFKC", text or "")
    return re.sub(r"\s+", "", s)


def line_text(line: dict) -> str:
    return "".join(sp.get("text", "") for sp in line.get("spans", [])).strip()


def line_style(line: dict):
    spans = line.get("spans", [])
    size = max((sp.get("size", 0) for sp in spans), default=0)
    bold = any(EN_BOLD_FONT.search(sp.get("font", "")) or CN_HEAD_FONT.search(sp.get("font", ""))
               for sp in spans)
    return size, bold


def tail_is_title_word(tail: str) -> bool:
    """编号后的尾段是否像标题词。全角先转半角，再排除数字/年份/单位/地名式数字串。"""
    tail = unicodedata.normalize("NFKC", tail).strip()
    if not tail or len(tail) > 55:
        return False
    if re.match(r"^\d", tail):           # 数字开头（年份/编号/小数）一律不是标题
        return False
    if re.search(r"\d", tail) and not re.search(r"[\u4e00-\u9fa5]", tail):
        # 含数字但无中文：站号+地名 "58027 Xuzhou" 之类
        return False
    if CN_WORD.fullmatch(tail) or EN_WORD.fullmatch(tail):
        return True
    # 允许 "Discussion and conclusion" 这类英文短语，但必须无数字
    return bool(re.fullmatch(r"[A-Za-z][A-Za-z \-&/()'’]{3,54}", tail))


def is_heading_text(t: str, size: float, bold: bool) -> bool:
    """判断一行文本（可能已合并编号+标题）是否为章节标题。"""
    if not t or len(t) > 70 or HEADING_BLACKLIST.match(t) or FIGURE_CAPTION.match(t):
        return False
    if CTRL_OR_PUA.search(t):
        return False
    short_cn = bool(CN_WORD.fullmatch(t))
    short_en = bool(EN_WORD.fullmatch(t))
    m = NUM_HEAD.match(unicodedata.normalize("NFKC", t))
    if m and size >= 8.5 and tail_is_title_word(m.group(2)):
        return True
    if bold and size >= 10.5 and (short_cn or short_en):
        return True
    return False


def clean_heading(t: str) -> str:
    t = re.sub(r"\s+", " ", t).strip()
    m = NUM_HEAD.match(t)
    if m:
        return f"{m.group(1)} {m.group(2).strip()}"
    return t


def extract(pdf_path: Path) -> dict:
    if pymupdf is None:
        raise RuntimeError(
            "pymupdf/fitz 不可用。请改用平台 pdf-text-tool 提取带页码文本，"
            "或 pip install pymupdf 后重试。不得凭文件名/标签补造内容。"
        )
    doc = pymupdf.open(str(pdf_path))
    pages, sections, issues = [], [], []
    seen_heads = set()
    for idx in range(doc.page_count):
        page = doc[idx]
        raw = page.get_text("text")
        if CTRL_OR_PUA.search(raw):
            issues.append({
                "page": idx + 1,
                "type": "garbled_or_formula",
                "detail": "本页含不可解析控制字符/私用区符号（多为公式或嵌入字体），逐字核验不可靠，锚点只到页。",
            })
        # 印刷页码：从页首/页尾的孤立数字或期刊页眉抽取（尽力而为）
        printed = None
        m = re.search(r"(?m)^\s*(\d{1,4})\s*$", raw)
        if m:
            printed = m.group(1)
        pages.append({
            "page": idx + 1,
            "printed_page": printed,
            "chars": len(raw),
            "suspicious": bool(CTRL_OR_PUA.search(raw)),
            "text": raw,
        })
        # 章节标题：先把每个 block 的 lines 拍平，再处理"编号行 + 标题行"跨行的情况。
        # Dietz 2019 的 "1\nIntroduction" 就是编号与标题分两行，只扫 span 会漏。
        d = page.get_text("dict")
        flat_lines = []
        for b in d.get("blocks", []):
            for ln in b.get("lines", []):
                t = line_text(ln)
                if t:
                    flat_lines.append((t, *line_style(ln)))
        li = 0
        while li < len(flat_lines):
            t, size, bold = flat_lines[li]
            num = PURE_NUM.match(t)
            merged = None
            if num:
                # 纯编号行：尝试和紧随其后的短行合并
                if li + 1 < len(flat_lines):
                    nt, ns, nb = flat_lines[li + 1]
                    if len(nt) <= 60 and not HEADING_BLACKLIST.match(nt) and not FIGURE_CAPTION.match(nt):
                        cand = f"{num.group(1)} {nt}"
                        if is_heading_text(cand, max(size, ns), bold or nb):
                            merged = (cand, max(size, ns))
                            li += 1  # 跳过被合并的标题行
            else:
                if is_heading_text(t, size, bold):
                    merged = (t, size)
            if merged:
                h = clean_heading(merged[0])
                if h and h not in seen_heads:
                    seen_heads.add(h)
                    sections.append({
                        "heading": h,
                        "page": idx + 1,
                        "size": round(merged[1], 1),
                        "font": "",
                    })
            li += 1
    doc.close()
    # 后处理 1：去掉标题里混入的印刷页码（如 "105 Reference models"）
    for s in sections:
        s["heading"] = re.sub(r"^\d{2,4}\s+", "", s["heading"]).strip()
    # 后处理 2：给每个标题算层级（编号段数，无编号按 0；同页首个无编号标题视为 1）
    for s in sections:
        m = re.match(r"^(\d+(?:\.\d+)*)\s", s["heading"])
        s["level"] = len(m.group(1).split(".")) if m else 0
        s["number"] = m.group(1) if m else None
    # 后处理 3：去掉明显是正文残句的标题（过长、含句号结尾的非编号行）
    sections = [s for s in sections if not (s["level"] == 0 and s["heading"].endswith("."))]
    # 图像占比高的页：正文很少说明可能是图片页/扫描页
    for p in pages:
        if p["chars"] < 120:
            issues.append({
                "page": p["page"],
                "type": "low_text_page",
                "detail": "本页可提取字符很少，可能是图片页/扫描页，需要看页面图像或走 OCR。",
            })
    return {
        "source": str(pdf_path),
        "page_count": len(pages),
        "extraction": "pymupdf-native-text-layer",
        "pages": pages,
        "sections": sections,
        "issues": issues,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True, help="输入 PDF 路径")
    ap.add_argument("--out", required=True, help="输出 JSON 路径")
    args = ap.parse_args(argv)
    data = extract(Path(args.pdf))
    Path(args.out).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[pdf_extract] pages={data['page_count']} sections={len(data['sections'])} "
          f"issues={len(data['issues'])} -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
