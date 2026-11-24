#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""structure.py — 章节树、页眉页脚、题注、脚注、参考文献区，以及"哪些段算正文"。

为什么这么做：
1) 页眉页脚不能靠写死 y 阈值：不同期刊版心不同。改用"同一段文字在多页的页顶/页底重复出现"
   ——重复才是页眉的本质特征，位置只是它的表现。页码单独处理，因为数字每页都不同，
   要先归一化成 # 再比。
2) 章节层级不能只看"字大就是标题"：正文里的强调、图注、表头也会变大。所以用三条证据
   叠：编号（1 / 1.2 / 1.2.3）+ 字号高于正文 + 短。有编号时编号深度直接给层级；没编号
   （不少期刊/预印本不编号）才退回按字号排名定层级，并在结果里注明依据。
3) 角色必须先定、再判续段：表格单元格、题注、公式都不以句号结尾，先判续段会大面积误报
   （Dietz 第 4 页实测一次误报 100+ 条）。所以本脚本产出角色，续段只在本脚本里对
   "正文→正文"判。
4) 认不出的东西要如实标。摘要没有 "Abstract" 字样时，只能"推断"第一段是摘要，
   必须写 method=inferred 并进 uncertainty，不能当成确定事实。
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
from pathlib import Path

import pdfcore

NUM_HEADING = re.compile(
    # 编号后必须跟"字母/汉字/引号开头"的标题文字。只允许 \S 会把 "0 ,θ∗" 这种公式碎片认成标题
    # （Dietz 实测一批公式因此进了目录）。
    r"^\s*(\d{1,2}(?:\.\d{1,2}){0,3})\.?\s+([A-Za-z\u4e00-\u9fff(“\"'].{0,90})$"
)
CAPTION = re.compile(r"^\s*(Table|TABLE|Figure|FIGURE|Fig\.?|FIG\.?|表|图)\s*([0-9]+[a-zA-Z]?|[IVX]+)\b[.:：]?\s*(.*)$")
PAGE_NUM = re.compile(r"^\s*(?:page\s*)?[-–—]?\s*(\d{1,4}|[ivxlc]{1,6})\s*[-–—]?\s*$", re.I)
REF_ENTRY = re.compile(r"^\s*(\[\d{1,3}\]|\(\d{1,3}\)|\d{1,3}\.)\s+\S")
DOI = re.compile(r"\b(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)")
YEAR = re.compile(r"\b(19|20)\d{2}\b")

KNOWN_SECTIONS = {
    "abstract": "abstract", "摘要": "abstract",
    "keywords": "keywords", "key words": "keywords", "关键词": "keywords",
    "introduction": "introduction", "引言": "introduction", "前言": "introduction",
    "related work": "related_work", "background": "background", "背景": "background",
    "data": "data", "data and methods": "methods", "methods": "methods",
    "method": "methods", "methodology": "methods", "材料与方法": "methods", "方法": "methods",
    "results": "results", "result": "results", "结果": "results",
    "discussion": "discussion", "讨论": "discussion",
    "conclusion": "conclusion", "conclusions": "conclusion", "结论": "conclusion",
    "acknowledgements": "acknowledgements", "acknowledgments": "acknowledgements",
    "致谢": "acknowledgements",
    "references": "references", "bibliography": "references", "参考文献": "references",
    "appendix": "appendix", "附录": "appendix",
}
ABSTRACT_WORD = re.compile(r"^\s*(Abstract|ABSTRACT|摘要)\s*[.:：]?\s*", re.I)
KEYWORDS_WORD = re.compile(r"^\s*(Key\s*words?|KEYWORDS|关键词)\b[:：]?\s*", re.I)
EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")
AFFIL = re.compile(r"\b(University|Institute|Laborator|Department|College|Academy|Center|Centre|"
                   r"大学|学院|研究所|实验室|中心)\b", re.I)
SENT_END = re.compile(r"[.!?。！？][\"'”’)\]）】]?\s*$")


def _top_bottom_zones(page: dict, frac: float = 0.10) -> tuple[float, float]:
    h = page["height"]
    return h * frac, h * (1 - frac)


def _is_mathy(p: dict) -> bool:
    t = p.get("text") or ""
    if not t:
        return False
    glyphs = len(pdfcore.MATH_GLYPH.findall(t))
    return glyphs >= 2 and glyphs / max(1, len(t)) > 0.03


def mark_title_block(doc: dict) -> None:
    """先把首页标题整块认出并合并。

    为什么单独做：期刊标题常折成 2–3 行，PyMuPDF 会给成多个 block/para。不先合并，
    "字号最大的那段"只会命中标题的第二行（Dietz 实测拿到的是 "horizons using tree-based
    boosting models"），后续作者、摘要的定位全部跟着错位。
    """
    pages = doc["pages"]
    if not pages:
        return
    p1 = pages[0]["paras"]
    body = doc.get("body_font_size") or 10.0
    top, bottom = _top_bottom_zones(pages[0])
    # 不用"页面顶部 10%"这个几何带筛候选：有些期刊版式很紧，标题就压在 y≈50（单栏合成件
    # 实测 y=51.8，而顶带边界是 84.2），一筛就把真标题当页眉剔掉，随后把 "1 Introduction"
    # 当成标题。页眉在上一遍 detect_running 里已经打上 role=header，这里按角色排除即可。
    cands = [p for p in p1
             if p.get("role") != "header" and p["bbox"][1] < bottom and len(p["text"]) >= 8]
    if not cands:
        return
    biggest = max(p["size"] for p in cands)
    if biggest < body * 1.15:
        return
    seq = [p for p in cands if abs(p["size"] - biggest) <= 0.6]
    # 只取首页顶部连续的那几段（标题几乎总在最上面），避免把后面同字号的强调句并进来
    seq.sort(key=lambda p: p["bbox"][1])
    block = [seq[0]]
    for p in seq[1:]:
        prev = block[-1]
        gap = p["bbox"][1] - prev["bbox"][3]
        if gap <= max(6.0, (prev["bbox"][3] - prev["bbox"][1]) * 1.2):
            block.append(p)
        else:
            break
    text = block[0]["text"]
    for p in block[1:]:
        text = pdfcore.dehyphenate(text, p["text"])
    block[0]["text"] = text
    block[0]["role"] = "title"
    block[0]["merged_ids"] = [p["id"] for p in block]
    block[0]["bbox"] = [min(p["bbox"][0] for p in block), min(p["bbox"][1] for p in block),
                        max(p["bbox"][2] for p in block), max(p["bbox"][3] for p in block)]
    for p in block[1:]:
        p["role"] = "title_continuation"
        p["merged_into"] = block[0]["id"]


FRONT_META = re.compile(
    r"(Received\s*:|Revised\s*:|Accepted\s*:|Published\s*:|Correspondence|E-?mail|doi\.org|"
    r"https?://|Vol\.|ISSN|©|\bpp\.\s*\d)", re.I)


def mark_front_region(doc: dict) -> None:
    """首页"标题之后、摘要之前"那一段属于前言区：作者、单位、通信方式、投稿日期。

    为什么必须单独标：作者行常常是加粗 + 短 + 不含句号，正好符合"标题"的全部排特征，
    不先划出前言区，Dietz 的作者行和 Correspondence 行都会被当成章节标题进目录。
    """
    pages = doc["pages"]
    if not pages:
        return
    p1 = pages[0]
    paras = p1["paras"]
    limit = None
    for p in paras:
        if p.get("role") in ("title", "title_continuation"):
            continue
        t = p.get("text") or ""
        if p.get("role") == "abstract" or ABSTRACT_WORD.match(t):
            limit = p["bbox"][1]
            break
        if NUM_HEADING.match(t) and len(t) <= 90:
            limit = p["bbox"][1]
            break
    if limit is None:
        limit = p1["height"] * 0.45
    for p in paras:
        if p.get("role"):
            continue
        if p["bbox"][1] >= limit:
            continue
        t = p["text"]
        # 作者行的两条通行版式：加粗；或常规体但"像姓名列表"。
        # 为什么不能只认加粗：不少期刊作者行就是常规体（合成件 two_column 的
        # "C. Writer, D. Writer" 因此整行落进正文，authors 报缺失）。
        # 为什么"像姓名列表"要额外卡位置：Scientific Reports 的摘要区是窄栏排版，
        # 摘要续行同样含逗号、同样不以句号结尾（Chen 2024 实测会被误判成 authors）。
        # 作者行一定紧贴标题下方，所以加一条"位于页面上 30%"。
        names_like = (not SENT_END.search(t)) and len(t.split()) <= 14 \
            and p["bbox"][1] < p1["height"] * 0.30
        if AFFIL.search(t):
            p["role"] = "affiliation"
        elif FRONT_META.search(t) or EMAIL.search(t):
            p["role"] = "meta"
        elif (p["bold"] or names_like) and ("," in t or " and " in t) and len(t) <= 300:
            p["role"] = "authors"
        # 没命中明确模式就**不标**：不少期刊（Scientific Reports 等）的摘要没有 "Abstract"
        # 标签，若在这里一律标 meta，摘要就永远找不到（Chen 2024 实测整段摘要被标成 meta/authors）。


def column_lefts(pages: list[dict]) -> dict:
    """每一页每一栏的正文左边缘，用于判断标题是否与栏左对齐。

    算法步骤、编号列表往往整体缩进几 pt（Dietz 的 "3. Fit the gradient vector…" 就在
    307.3+7.4 处），仅凭编号会把它们当章节；"与栏左边缘对齐"这一条能把它们排除掉。
    """
    lefts: dict = {}
    for pg in pages:
        for p in pg["paras"]:
            if len(p["text"]) < 40:
                continue
            key = (pg["no"], p["col"])
            lefts[key] = min(lefts.get(key, 9e9), round(p["bbox"][0], 1))
    return lefts


def detect_running(page: dict, key_counts: dict, n_pages: int, body: float = 10.0) -> None:
    """给页眉/页脚/页码打标：多页重复（数字归一）或独立页码行。

    为什么要排除"像标题的行"：判据是"跨页同位置、数字归一后文本相同"，而连续两页的章节
    标题恰好满足它——"2 Method" 与 "3 Method" 归一后都是 "# method"（合成用例
    single_column 实测：两页的 12pt 章节标题被判成页眉，直接从目录里消失）。
    页眉是版式元素（字号不大于正文、常大写），标题是内容元素（字号大于正文或加粗），
    两者在字号/粗细上可区分。
    """
    top, bottom = _top_bottom_zones(page)
    for p in page["paras"]:
        y0, y1 = p["bbox"][1], p["bbox"][3]
        in_zone = y1 <= top + 6 or y0 >= bottom - 6
        if not in_zone:
            continue
        if PAGE_NUM.match(p["text"]) and len(p["text"]) <= 12:
            p["role"] = "page_number"
            continue
        # 只排除"字号明显大于正文"的行。不能连"加粗但同字号"一起放行：期刊页眉里的
        # 刊名标（Scientific Reports 每页顶部那个加粗的 "OPEN"）就是加粗同字号，
        # 放行后它每页都混进正文（Chen 2024 实测多出 11 段）。
        if p["size"] >= body * 1.05:
            continue
        key = re.sub(r"\d+", "#", re.sub(r"\s+", " ", p["text"])).strip().lower()
        if key and key_counts.get(key, 0) >= max(2, int(n_pages * 0.4)) and n_pages >= 3:
            p["role"] = "header" if y1 <= top + 6 else "footer"
            # 页眉常与页码同段（"Author et al.: Title 105"）：把页码单独抠出来，
            # 否则"页码"这一项在完整性清单里会被判缺失。
            trailing = re.search(r"(\d{1,4})\s*$", p["text"])
            if trailing and len(p["text"]) <= 160:
                p["page_label"] = trailing.group(1)


def body_font_size(pages: list[dict]) -> float:
    sizes, weights = [], []
    for pg in pages:
        top, bottom = _top_bottom_zones(pg)
        for p in pg["paras"]:
            if p.get("role"):
                continue
            if p["bbox"][3] <= top or p["bbox"][1] >= bottom:
                continue
            if len(p["text"]) < 40:
                continue
            sizes.append(p["size"])
            weights.append(len(p["text"]))
    if not sizes:
        return 10.0
    pairs = sorted(zip(sizes, weights))
    total = sum(weights)
    acc = 0
    for s, w in pairs:
        acc += w
        if acc >= total / 2:
            return s
    return sizes[0]


def assign_roles(doc: dict) -> dict:
    """给每个段落定角色。返回 body 字号等上下文信息。"""
    pages = doc["pages"]
    n_pages = len(pages)

    # 正文字号要先算：页眉判据要用它排除"字号明显大于正文"的章节标题。
    # body_font_size 自己会排除页眉页脚区域，所以此时算出来的值不会被打标影响。
    font = body_font_size(pages)
    doc["body_font_size"] = font

    # 第一遍：页眉页脚页码
    key_counts: dict[str, int] = {}
    for pg in pages:
        top, bottom = _top_bottom_zones(pg)
        seen = set()
        for p in pg["paras"]:
            if p["bbox"][3] <= top + 6 or p["bbox"][1] >= bottom - 6:
                k = re.sub(r"\d+", "#", re.sub(r"\s+", " ", p["text"])).strip().lower()
                if k and k not in seen:
                    seen.add(k)
                    key_counts[k] = key_counts.get(k, 0) + 1
    for pg in pages:
        detect_running(pg, key_counts, n_pages, font)

    # 标题整块先认出来：它决定了后面作者/摘要的定位起点，也避免标题行被当成章节
    mark_title_block(doc)
    # 前言区（作者/单位/通信/投稿日期）先划出来，否则它们会被当章节
    mark_front_region(doc)
    lefts = column_lefts(pages)

    # 第二遍：标题/题注/公式/参考文献/正文
    in_refs = False
    heading_cands = []
    for pg in pages:
        top, bottom = _top_bottom_zones(pg)
        for p in pg["paras"]:
            if p.get("role"):
                continue
            text = p["text"]
            t = text.strip()
            if not t:
                p["role"] = "empty"
                continue

            m = CAPTION.match(t)
            # 题注判据：① 编号后必须紧跟分隔符（. : ： |）或行尾，否则是"Figure 3 shows…"
            # 这种正文引用；② 长图注可以到 800 字（Dietz 的 Figure 2 注 528 字，卡 400 会漏）。
            after = t[m.end(2):] if m else ""
            sep_ok = bool(m) and (bool(re.match(r"^\s*[.:：|、]", after)) or len(after.strip()) < 3)
            if m and sep_ok and len(t) < 800:
                kind = "table" if m.group(1).lower().startswith(("table", "表")) else "figure"
                p["role"] = "caption"
                p["caption_of"] = kind
                p["caption_number"] = m.group(2)
                p["caption_text"] = m.group(3).strip()
                continue

            # "Abstract." 常常**单独成段**（Dietz、大量 Elsevier/Wiley 版式），长度 9 个字符；
            # 卡 len>20 会把标签漏掉，摘要随后被当作"无标签"再推断一次，同一段文字既进摘要
            # 又留在正文里（合成用例 single_column 实测重复）。所以短标签也算命中。
            if ABSTRACT_WORD.match(t) and (len(t) > 20 or len(t) <= 16):
                p["role"] = "abstract"
                continue
            if KEYWORDS_WORD.match(t):
                p["role"] = "keywords"
                continue

            key = re.sub(r"^\d+(\.\d+)*\.?\s*", "", t).strip().lower().rstrip(":：")
            known = KNOWN_SECTIONS.get(key)
            if known == "references":
                p["role"] = "heading"
                p["heading_level"] = 1
                p["section_key"] = "references"
                in_refs = True
                continue
            if known and len(t) <= 60:
                p["role"] = "heading"
                p["heading_level"] = 1
                p["section_key"] = known
                in_refs = False if known != "references" else in_refs
                continue

            if in_refs:
                if REF_ENTRY.match(t) or DOI.search(t):
                    p["role"] = "reference"
                    p["ref_number"] = re.sub(r"[^\d]", "", t.split()[0]) if t.split() else None
                    continue

            nm = NUM_HEADING.match(t)
            big = p["size"] >= font * 1.02
            short = len(t) <= 95
            dotted = bool(nm and nm.group(1).count(".") > 0)
            left = lefts.get((pg["no"], p["col"]))
            aligned = left is None or (p["bbox"][0] - left) <= 8.0
            starts_ok = bool(re.match(r"^[A-Z\u4e00-\u9fff0-9(（]", t))
            # 编号只是"可能是标题"，还要有排版证据（字号更大/加粗/带点号编号），并且
            # 与栏左边缘对齐、不以小写或等号开头——这三条把算法步骤、行内公式排除掉。
            if (nm and short and not SENT_END.search(t) and not _is_mathy(p) and aligned
                    and starts_ok and "=" not in t and ". " not in nm.group(2)
                    and (big or p["bold"] or dotted)):
                p["role"] = "heading"
                p["heading_level"] = min(4, nm.group(1).count(".") + 1)
                p["heading_number"] = nm.group(1)
                p["heading_title"] = nm.group(2).strip()
                heading_cands.append(p)
                continue

            bold_short = short and not SENT_END.search(t) and (p["bold"] or p["size"] >= font * 1.08)
            # ". " 用来挡"行内小标题"：如 "Author contributions. The concept…" 是粗体引导句，
            # 不是章节（Dietz 实测这类会整批进目录）
            if (bold_short and len(t.split()) <= 10 and not _is_mathy(p) and aligned
                    and starts_ok and "=" not in t and ". " not in t):
                p["role"] = "heading"
                p["heading_level"] = None  # 待按字号排名补
                heading_cands.append(p)
                continue

            math_chars = len(pdfcore.MATH_GLYPH.findall(t))
            if p["math"] and math_chars >= 2 and len(t) <= 220:
                p["role"] = "formula"
                continue

            if p["bbox"][1] >= bottom - 6 and p["size"] < font * 0.95:
                p["role"] = "footnote"
                continue

            p["role"] = "body"

    # 纯编号标题（"4.1" 单独一行或单独一列）：编号与标题文字会被 PDF 拆成两个段，
    # 这里把它们并回一个标题。三种排版都要认：
    #   a) 编号在左、标题文字在同一行的右侧（Dietz "4.1" + "Nowcasts (+1 to +18 h)"）
    #   b) 编号一行、标题文字紧贴下一行
    #   c) 编号在右（少数期刊右对齐编号）
    # 不能靠字号判：Dietz 的 4.1 比正文还小、不加粗，只靠排版特征会漏，
    # 漏掉后 4.1.1 就挂到 4 下面，目录层级直接错。
    flat_pages = [(pg, p) for pg in pages for p in pg["paras"]]

    def _pure_number(t: str) -> bool:
        return bool(re.fullmatch(r"\d{1,2}(?:\.\d{1,2}){0,3}\.?", (t or "").strip()))

    def _titleish(t: str) -> bool:
        return len(t.strip()) <= 60 and not SENT_END.search(t.strip()) and not _pure_number(t)

    for i, (pg, p) in enumerate(flat_pages):
        t = (p.get("text") or "").strip()
        if p.get("role") not in ("body", "fragment") or not _pure_number(t):
            continue
        left0 = lefts.get((pg["no"], p["col"]))
        if left0 is not None and p["bbox"][0] - left0 > 8:
            continue  # 不在栏左：正文里的上标数字，不是章节号
        num = t.rstrip(".")
        cands = []
        if i > 0:
            prev = flat_pages[i - 1][1]
            if (prev["page"] == p["page"] and prev.get("role") == "body" and _titleish(prev["text"])
                    and abs(prev["bbox"][1] - p["bbox"][1]) <= 5
                    and -2 <= prev["bbox"][0] - p["bbox"][2] <= 18):
                cands.append(("prev", prev))
        if i + 1 < len(flat_pages):
            nxt = flat_pages[i + 1][1]
            if nxt["page"] == p["page"] and _titleish(nxt["text"]):
                same_line = (abs(nxt["bbox"][1] - p["bbox"][1]) <= 5
                             and -2 <= nxt["bbox"][0] - p["bbox"][2] <= 18)
                next_line = 0 <= nxt["bbox"][1] - p["bbox"][3] <= 22
                # 下一行是编号列表项 → 这是列表编号，不是章节号
                if (same_line or next_line) and not re.match(r"^\d{1,2}\.\s", nxt["text"].strip()):
                    cands.append(("next", nxt))
        if not cands:
            continue
        where, other = cands[0]
        host = other if where == "prev" else p
        host["role"] = "heading"
        host["heading_number"] = num
        host["heading_level"] = min(4, num.count(".") + 1)
        if where == "prev":
            host["text"] = f"{num} {other['text'].strip()}"
            host["heading_title"] = other["text"].strip()
            p["role"] = "heading_continuation"
            p["merged_into"] = other["id"]
        else:
            host["text"] = f"{num} {other['text'].strip()}"
            host["heading_title"] = other["text"].strip()
            other["role"] = "heading_continuation"
            other["merged_into"] = p["id"]
        heading_cands.append(host)

    # 第三遍：没编号的标题按字号排名补层级
    sizes = sorted({round(p["size"], 1) for p in heading_cands if p["heading_level"] is None}, reverse=True)
    for p in heading_cands:
        if p["heading_level"] is None:
            rank = sizes.index(round(p["size"], 1)) + 1 if sizes else 2
            p["heading_level"] = min(3, max(1, rank))

    # 章节树
    sections = []
    stack: list[dict] = []
    order = 0
    for pg in pages:
        for p in pg["paras"]:
            if p.get("role") == "heading":
                order += 1
                node = {
                    "id": f"sec{order}", "title": p["text"].strip(),
                    "level": int(p.get("heading_level") or 2),
                    "page": pg["no"], "para": p["id"], "children": [],
                    "number": p.get("heading_number"),
                }
                while stack and stack[-1]["level"] >= node["level"]:
                    stack.pop()
                if stack:
                    stack[-1]["children"].append(node)
                else:
                    sections.append(node)
                stack.append(node)
                p["section_id"] = node["id"]

    # 给正文段挂所属章节
    cur = "front"
    for pg in pages:
        for p in pg["paras"]:
            if p.get("role") == "heading":
                cur = p.get("section_id", cur)
            p["section"] = cur
    doc["sections"] = sections
    return doc


def front_matter(doc: dict) -> dict:
    """首页前言区：标题、作者、单位、摘要、关键词。缺失就写 None + 原因，不编。"""
    pages = doc["pages"]
    out = {"title": None, "authors": None, "affiliations": [], "abstract": None,
           "keywords": None, "method": {}, "uncertainty": []}
    if not pages:
        out["uncertainty"].append("文档没有可解析页面")
        return out
    p1 = pages[0]["paras"]
    body = doc["body_font_size"]
    cands = [p for p in p1 if p.get("role") not in ("header", "footer", "page_number")]
    if not cands:
        out["uncertainty"].append("首页没有可用段落")
        return out

    # 标题：mark_title_block 已经合并好的整块；没有则记不确定，不退回"取最大字号"去猜
    title_p = next((p for p in cands if p.get("role") == "title"), None)
    if title_p:
        out["title"] = title_p["text"]
        out["title_para"] = title_p["id"]
        out["method"]["title"] = "merged_title_block_by_font_size"
    else:
        out["uncertainty"].append("首页未找到明显大于正文的标题块（可能标题是图片或字号与正文相同）")

    # 作者/单位：由 mark_front_region 定好的角色直接取，跨页顺序取第一处
    auth_p = next((p for p in cands if p.get("role") == "authors"), None)
    if auth_p:
        out["authors"] = auth_p["text"]
        out["authors_para"] = auth_p["id"]
        out["method"]["authors"] = "front_region_bold_comma_line"
    else:
        out["uncertainty"].append("未识别到作者行（可能作者只有一人，或与单位同段）")
    out["affiliations"] = [p["text"] for p in cands if p.get("role") == "affiliation"]

    # 摘要：优先显式 Abstract / 摘要
    abs_paras = [p for pg in pages[:2] for p in pg["paras"] if p.get("role") == "abstract"]
    if abs_paras:
        parts = [ABSTRACT_WORD.sub("", abs_paras[0]["text"]).strip()]
        # 摘要常跨段：后续正文段且未进入第一节前，继续并入。
        # 并入的段必须**改掉角色**，否则它会同时出现在摘要和正文里（同一段字被交付两次）。
        # 但也不能无限并：没有章节标题时要靠字数上限收住，不然整页正文都会被当成摘要。
        joined = sum(len(x) for x in parts)
        extra = 0
        started = False
        stopped = False
        for pg in pages[:2]:
            if stopped:
                break
            for p in pg["paras"]:
                if p is abs_paras[0]:
                    started = True
                    continue
                if not started:
                    continue
                if p.get("role") in ("heading", "keywords", "caption", "header", "footer",
                                     "title", "title_continuation"):
                    stopped = True
                    break
                if p.get("role") == "body" and extra < 3 and joined < 2000:
                    parts.append(p["text"])
                    joined += len(p["text"])
                    extra += 1
                    p["role"] = "abstract"
                    p["abstract_of"] = abs_paras[0]["id"]
        out["abstract"] = " ".join(x for x in parts if x)
        out["method"]["abstract"] = "explicit_label"
        out["abstract_para"] = abs_paras[0]["id"]
    else:
        # 无 Abstract 字样：只能推断"首页第一段较长、位于标题/作者之后、在第一个章节标题之前"的正文
        lead = None
        seen_title = False
        for p in cands:
            if p.get("id") == out.get("title_para"):
                seen_title = True
                continue
            if not seen_title:
                continue
            if p.get("role") == "heading":
                break
            if p.get("role") in (None, "body") and len(p["text"]) >= 200 and not p.get("role") == "heading":
                lead = p
                break
        if lead:
            lead["role"] = "abstract"
            out["abstract"] = lead["text"]
            out["abstract_para"] = lead["id"]
            out["method"]["abstract"] = "inferred_leading_block"
            out["uncertainty"].append(
                "原文没有 Abstract/摘要 标签，摘要按“标题后第一个长正文段”推断，需人工确认"
            )
        else:
            out["uncertainty"].append("未找到摘要段（既无标签也无合适的长首段）")

    kw = [p for pg in pages[:3] for p in pg["paras"] if p.get("role") == "keywords"]
    if kw:
        out["keywords"] = KEYWORDS_WORD.sub("", kw[0]["text"]).strip()
        out["method"]["keywords"] = "explicit_label"
    return out


def finalize_body(doc: dict) -> dict:
    """正文流：只保留 body 段，按阅读顺序，判续段并给出合并文本。

    续段判据（三条同时满足）：
      1) 上一段不以句末标点结尾（说明这句没写完）；
      2) 本段以小写字母开头（真正的段首一般大写；中文没有大小写，改用"上一段无句末标点"）；
      3) 两段同章节（跨章节不可能是一句话）。
    满足则标 continued_from，并把文本接到上一段的 text_joined 末尾（用 dehyphenate 处理断词），
    但**仍保留两条独立记录**，因为页码与 bbox 必须各自可核。
    """
    body = []
    for pg in doc["pages"]:
        for p in pg["paras"]:
            if p.get("role") != "body":
                continue
            t = (p.get("text") or "").strip()
            # 单字符/纯数字/纯符号的碎片（如正文里的上标 "2"）不是段落，标 fragment 保留证据
            if len(t) < 3 or re.fullmatch(r"[\d\W_]+", t):
                p["role"] = "fragment"
                continue
            body.append(p)
    issues = []
    for i, p in enumerate(body):
        p["text_joined"] = p["text"]
        if i == 0:
            continue
        prev = body[i - 1]
        if p.get("section") != prev.get("section"):
            continue
        if SENT_END.search(prev["text"] or "") or not p["text"]:
            continue
        starts_lower = p["text"][0].islower() or pdfcore.has_cjk(p["text"][0])
        if not starts_lower:
            continue
        p["continued_from"] = prev["id"]
        prev["text_joined"] = pdfcore.dehyphenate(prev["text_joined"], p["text"])
        issues.append({
            "type": "paragraph_continuation", "page": p["page"], "para": p["id"],
            "detail": f"疑似紧接 {prev['id']}（{prev['page']} 页）；已标 continued_from 并在上一段 text_joined 接续，两条记录各自保留页码",
        })
    doc["body_paragraphs"] = body
    doc["issues"] = doc.get("issues", []) + issues
    return doc


def collect(doc: dict) -> dict:
    """汇总表格题注、图注、参考文献、脚注，便于完整性打勾。"""
    captions, figures, references, footnotes, formulas_like = [], [], [], [], []
    for pg in doc["pages"]:
        for p in pg["paras"]:
            r = p.get("role")
            if r == "caption":
                item = {"page": pg["no"], "para": p["id"], "kind": p.get("caption_of"),
                        "number": p.get("caption_number"), "text": p["text"],
                        "bbox": p["bbox"]}
                captions.append(item)
                if item["kind"] == "figure":
                    figures.append(item)
            elif r == "reference":
                references.append({"page": pg["no"], "para": p["id"], "text": p["text"],
                                   "bbox": p["bbox"],
                                   "doi": (DOI.search(p["text"]).group(1) if DOI.search(p["text"]) else None),
                                   "year": (YEAR.search(p["text"]).group(0) if YEAR.search(p["text"]) else None)})
            elif r == "footnote":
                footnotes.append({"page": pg["no"], "para": p["id"], "text": p["text"]})
            elif r == "formula":
                formulas_like.append({"page": pg["no"], "para": p["id"], "text": p["text"]})
    doc["captions"] = captions
    doc["figures"] = figures
    doc["references"] = references
    doc["footnotes"] = footnotes
    doc["formula_candidates"] = formulas_like
    return doc


def analyze(layout_doc: dict) -> dict:
    doc = assign_roles(layout_doc)
    doc["front_matter"] = front_matter(doc)
    doc = finalize_body(doc)
    doc = collect(doc)
    counts = {}
    for pg in doc["pages"]:
        for p in pg["paras"]:
            counts[p.get("role", "?")] = counts.get(p.get("role", "?"), 0) + 1
    doc["role_counts"] = counts
    return doc


def main() -> int:
    ap = argparse.ArgumentParser(description="章节结构 / 页眉页脚 / 题注 / 参考文献")
    ap.add_argument("--layout", required=True, help="layout.py 输出的 json")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    doc = json.loads(Path(args.layout).read_text(encoding="utf-8"))
    doc = analyze(doc)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({
        "out": args.out,
        "body_font_size": doc["body_font_size"],
        "sections_top": [s["title"][:40] for s in doc["sections"]],
        "role_counts": doc["role_counts"],
        "body_paragraphs": len(doc["body_paragraphs"]),
        "references": len(doc["references"]),
        "captions": len(doc["captions"]),
        "front_matter": {k: (v[:60] + "…" if isinstance(v, str) and len(v) > 60 else v)
                         for k, v in doc["front_matter"].items() if k in ("title", "authors", "method")},
    }, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
