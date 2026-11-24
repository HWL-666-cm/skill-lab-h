#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tables.py — 表格区域定位 + 单元格网格重建 + 跨页续表合并。

为什么不用"整页 pdfplumber/find_tables 一把梭"（Dietz 2019 实测）：
1) 这篇论文的表只有横线、没有竖线。`find_tables(strategy="lines")` 全篇只找到 1 个 2×2 小表，
   真正的 Table 1/Table 2 一个都没认出来——有线策略依赖闭合边框，缺竖线就失效。
2) 换 `strategy="text"` 也不行：整页跑会给出 77×10 的假表，因为它把正文段落也当成单元格；
   即使裁到表格区域，还是把 8 列切成 9 列、14 行切成 24 行（空行 + 词被劈开）。
3) 所以这里改成"三步走"：
   a. 用题注定位表格区域（题注是文本，能精确找到；表格本体在题注紧邻处）；
   b. 在区域内用词坐标重建网格：行按 y 聚类，列按"投影空白"切（列间必有空白，因为没有竖线
      反而更干净），每个词按左上角归入唯一单元格——这样切不会把词劈开；
   c. 用一组一致性规则决定"敢不敢认这张表"（行列数、非空率、单元格字数、高度占比），
      不达标就如实标为“检测到表格区域但未结构化”，绝不编造列。
4) 跨页续表：仅当"同列数 + 表头文字高度相似 + 位于下一页顶部"才合并，并保留页码区间。
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
from pathlib import Path

import pdfcore
import pymupdf

CAPTION_KIND = re.compile(r"^\s*(Table|TABLE|表)\s*([0-9]+[a-zA-Z]?|[IVX]+)", re.I)
CONTINUED = re.compile(r"\(?\s*(continued|cont\.|续)\s*\)?", re.I)
MAX_HEIGHT_RATIO = 0.75
MIN_NONEMPTY = 0.35
MAX_CELL_CHARS = 60
COL_GAP_MIN = 7.0


def _words(page, rect) -> list[dict]:
    out = []
    try:
        raw = page.get_text("words", clip=rect)
    except Exception:
        return out
    for w in raw:
        x0, y0, x1, y1, txt = w[0], w[1], w[2], w[3], w[4]
        if not txt.strip():
            continue
        out.append({"x0": x0, "y0": y0, "x1": x1, "y1": y1, "text": txt,
                    "yc": (y0 + y1) / 2, "xc": (x0 + x1) / 2})
    return out


def _order_words(ws: list[dict]) -> list[dict]:
    """按"视觉行"排序：先按纵向重叠聚成行，行内再按 x 排。

    为什么不能直接按 y 排：上标（如 (m w.e.)* 里的 *、x² 里的 2）纵向位置比同行文字高，
    按 y 排会把上标提到行首——实测把 "(m w.e.)∗" 排成了 "w.e.)∗ (m"，逐字比对直接判错。
    """
    if not ws:
        return []
    ws = sorted(ws, key=lambda w: (w["y0"], w["x0"]))
    lines: list[dict] = []
    for w in ws:
        placed = False
        for ln in lines:
            top = max(ln["y0"], w["y0"])
            bot = min(ln["y1"], w["y1"])
            overlap = bot - top
            smaller = max(1e-6, min(ln["y1"] - ln["y0"], w["y1"] - w["y0"]))
            if overlap / smaller > 0.4:
                ln["words"].append(w)
                ln["y0"] = min(ln["y0"], w["y0"])
                ln["y1"] = max(ln["y1"], w["y1"])
                placed = True
                break
        if not placed:
            lines.append({"y0": w["y0"], "y1": w["y1"], "words": [w]})
    out = []
    for ln in sorted(lines, key=lambda l: l["y0"]):
        out.extend(sorted(ln["words"], key=lambda w: w["x0"]))
    return out


def _cluster_rows(words: list[dict]) -> list[dict]:
    """按 y 中心聚成行。阈值取中位行高，"上标/下标"不会自成一行的同时，紧密排布的行也不会被合并。"""
    if not words:
        return []
    heights = sorted(w["y1"] - w["y0"] for w in words)
    h = heights[len(heights) // 2] or 8.0
    tol = max(3.0, h * 0.62)
    words = sorted(words, key=lambda w: (w["yc"], w["x0"]))
    rows: list[list[dict]] = []
    for w in words:
        if rows and abs(w["yc"] - statistics.mean([x["yc"] for x in rows[-1]])) <= tol:
            rows[-1].append(w)
        else:
            rows.append([w])
    return [{
        "words": r,
        "y0": min(w["y0"] for w in r), "y1": max(w["y1"] for w in r),
        "yc": statistics.mean([w["yc"] for w in r]),
    } for r in rows]


def _column_bands(words: list[dict], x0: float, x1: float) -> list[tuple[float, float]]:
    """用投影空白切列：把词覆盖的 x 区间涂到 1pt 网格上，连续空白 >= COL_GAP_MIN 就是列缝。"""
    if not words:
        return []
    lo = int(min(x0, min(w["x0"] for w in words)))
    hi = int(max(x1, max(w["x1"] for w in words))) + 1
    cover = [0] * (hi - lo + 2)
    for w in words:
        a, b = int(w["x0"]) - lo, int(w["x1"]) - lo
        for i in range(max(0, a), min(len(cover) - 1, b) + 1):
            cover[i] += 1
    # 空白段（含"只有 1 个词经过"的弱覆盖，避免某个宽词把列缝堵死）
    gaps, run = [], None
    for i, c in enumerate(cover):
        if c <= 1:
            run = i if run is None else run
        else:
            if run is not None and i - run >= COL_GAP_MIN:
                gaps.append((lo + run, lo + i))
            run = None
    if run is not None and len(cover) - run >= COL_GAP_MIN:
        gaps.append((lo + run, lo + len(cover) - 1))
    # 首尾空白不算列缝（那是页边距）
    left_edge = min(w["x0"] for w in words)
    right_edge = max(w["x1"] for w in words)
    inner = [g for g in gaps if g[0] > left_edge + 3 and g[1] < right_edge - 3]
    bounds = [left_edge]
    for a, b in inner:
        bounds.extend([(a + b) / 2, (a + b) / 2])
    bounds.append(right_edge)
    bands = [(bounds[i], bounds[i + 1]) for i in range(0, len(bounds) - 1, 2)]
    return [(round(a, 1), round(b, 1)) for a, b in bands if b - a > 2]


def _prose_col(matrix: list[list[str]], ci: int) -> bool:
    """该列的文字像不像正文句子。表格单元格短（最多几个词），正文句子长且带句末标点。"""
    txt = [r[ci].strip() for r in matrix if ci < len(r) and r[ci].strip()]
    if not txt:
        return False
    avg_words = sum(len(t.split()) for t in txt) / len(txt)
    avg_chars = sum(len(t) for t in txt) / len(txt)
    ends_sentence = sum(1 for t in txt if t.endswith((".", "。", ":")) and len(t) > 40)
    return avg_words >= 4 or avg_chars >= 45 or ends_sentence >= max(1, len(txt) // 2)


def _prune_edge_cols(matrix: list[list[str]], min_fill: float = 0.5) -> list[int]:
    """裁掉"低填充率 + 像正文"的边缘列，返回保留下来的列下标。

    为什么必须裁：题注定位的表格区域在双栏页里可能被放宽到整页宽度（跨栏大表要用整页宽度
    才抓得全），于是隔壁栏的正文也被切成了"列"。Dietz 第 3 页 Table 1 实测多出第 7 列，
    内容是右栏正文 "error remain unchanged with forecast horizon…"，还连带多出两行。
    为什么只裁边缘列、并且要求填充率低：真正的列即使首行留空（跨列合并的表头）也会在正文
    行里反复出现，填充率不会低；而误抓的正文列只在少数几行有内容（因为正文行高与表格行高
    不同，只有恰好对齐的几行才落进去），填充率极低。只裁边缘是为了不动中间的真列。
    """
    keep = list(range(len(matrix[0]) if matrix else 0))
    rows = len(matrix)

    def fill(ci: int) -> float:
        return sum(1 for r in matrix if r[ci].strip()) / rows if rows else 0.0

    changed = True
    while changed and len(keep) > 2:
        changed = False
        for edge in (keep[-1], keep[0]):
            if len(keep) <= 2:
                break
            if fill(edge) <= min_fill and _prose_col(matrix, edge):
                keep.remove(edge)
                changed = True
                break
    return keep


def _merge_wrapped_rows(matrix: list[list[str]], rows: list[dict],
                        cell_words: dict) -> list[int]:
    """把"单元格内换行"产生的伪行并回上一行，返回保留的行下标。

    为什么要这条：窄列里的长内容会折成两行，两行字框在纵向上是**重叠**的（Chen 第 9 页
    表第 4 列："99348, 99876, …, 99345," 折行后 "99349" 单独占一行）。聚类时它们的中心
    相差 5.7pt，刚好超过 0.62 倍行高的容差，于是被切成两行，输出成一条"只有一格有字"的
    空行。
    为什么判据用"字框重叠"而不是"行距小"：正常数据行之间总有 2pt 上下的空白，而折行的
    两行字框 gap 是负的（-1.9pt）。用 gap < 1pt 就能把两者分开，且不会误并正常稀疏行
    （真表中一格为空只是没字，不会和上一行重叠）。
    """
    drop = set()
    for i in range(1, len(matrix)):
        ne = [ci for ci, c in enumerate(matrix[i]) if c.strip()]
        if len(ne) != 1 or (i - 1) in drop:
            continue
        gap = rows[i]["y0"] - rows[i - 1]["y1"]
        if gap >= 1.0:
            continue
        ci = ne[0]
        matrix[i - 1][ci] = (matrix[i - 1][ci] + " " + matrix[i][ci]).strip()
        cell_words.setdefault((i - 1, ci), []).extend(cell_words.pop((i, ci), []))
        drop.add(i)
    return [i for i in range(len(matrix)) if i not in drop]


def reconstruct_grid(page, rect) -> dict | None:
    """在给定区域内按词坐标重建网格。返回 None 表示区域内没有像表的词分布。"""
    words = _words(page, rect)
    if len(words) < 8:
        return None
    rows = _cluster_rows(words)
    if len(rows) < 2:
        return None
    bands = _column_bands(words, rect.x0, rect.x1)
    if len(bands) < 2:
        return None

    def col_of(x: float) -> int:
        for i, (a, b) in enumerate(bands):
            if a - 1 <= x <= b + 1:
                return i
        return 0 if x < bands[0][0] else len(bands) - 1

    matrix = [["" for _ in bands] for _ in rows]
    cell_words: dict[tuple[int, int], list[dict]] = {}
    for ri, r in enumerate(rows):
        for w in _order_words(r["words"]):
            ci = col_of(w["x0"])
            cell_words.setdefault((ri, ci), []).append(w)
            if matrix[ri][ci]:
                matrix[ri][ci] += " " + w["text"]
            else:
                matrix[ri][ci] = w["text"]

    # 裁掉误抓的正文列，然后丢掉整行为空的行（右栏正文行与表格行高不同，
    # 裁列后这些行的单元格必然全空；留着会输出一排空行，看起来像表结构缺损）
    keep = _prune_edge_cols(matrix)
    if len(keep) < 2:
        return None
    matrix = [[r[i] for i in keep] for r in matrix]
    bands = [bands[i] for i in keep]
    remap_col = {old: new for new, old in enumerate(keep)}
    cell_words = {(ri, remap_col[ci]): ws for (ri, ci), ws in cell_words.items()
                  if ci in remap_col}
    keep_rows = _merge_wrapped_rows(matrix, rows, cell_words)
    keep_rows = [ri for ri in keep_rows if any(c.strip() for c in matrix[ri])]
    if len(keep_rows) < 2:
        return None
    remap_row = {old: new for new, old in enumerate(keep_rows)}
    matrix = [matrix[ri] for ri in keep_rows]
    cell_words = {(remap_row[ri], ci): ws for (ri, ci), ws in cell_words.items()
                  if ri in remap_row}
    rows = [rows[ri] for ri in keep_rows]

    # 单元格 bbox + colspan（词右边界越过的列数）
    cells = {}
    for (ri, ci), ws in cell_words.items():
        x0 = min(w["x0"] for w in ws)
        x1 = max(w["x1"] for w in ws)
        span = 1
        for j in range(ci + 1, len(bands)):
            if x1 > bands[j][0] + 2:
                span += 1
        cells[f"{ri},{ci}"] = {
            "row": ri, "col": ci, "colspan": span,
            "bbox": [round(x0, 1), round(min(w["y0"] for w in ws), 1),
                     round(x1, 1), round(max(w["y1"] for w in ws), 1)],
            "text": matrix[ri][ci],
        }
    return {
        "method": "word_grid",
        "bands": bands,
        "rows": len(rows),
        "cols": len(bands),
        "row_bboxes": [[round(r["y0"], 1), round(r["y1"], 1)] for r in rows],
        "matrix": matrix,
        "cells": cells,
    }


def find_bordered(page, rect) -> dict | None:
    """有线表格优先用 PyMuPDF 的网格检测（有竖线时它比投影更准）。"""
    try:
        tabs = page.find_tables(clip=rect, strategy="lines")
    except Exception:
        return None
    if not tabs.tables:
        return None
    tb = max(tabs.tables, key=lambda t: t.row_count * t.col_count)
    try:
        matrix = tb.extract()
        cells = tb.cells
    except Exception:
        return None
    if not matrix:
        return None
    return {
        "method": "find_tables_lines",
        "bands": [(round(c[0], 1), round(c[2], 1)) for c in cells[:tb.col_count]] if cells else [],
        "rows": tb.row_count, "cols": tb.col_count,
        "row_bboxes": [[round(r.bbox[1], 1), round(r.bbox[3], 1)] for r in tb.rows],
        "matrix": [[(c or "") for c in row] for row in matrix],
        "cells": {},
    }


def looks_like_header(matrix: list[list[str]]) -> bool:
    """首行是不是表头：首行没有数字、次行有数字 → 是。
    无题注的兜底表常把数据行放在首行（Chen 的台站表首行就是 "58131 | Suqian | …"），
    直接当表头输出会把第一条数据写成列名。"""
    if len(matrix) < 2:
        return False
    first = [c.strip() for c in matrix[0] if c and c.strip()]
    second = [c.strip() for c in matrix[1] if c and c.strip()]
    if len(first) < 2:
        return False
    num = re.compile(r"[-−]?\d+([.,]\d+)?")

    def has_digits(cells):
        return any(num.fullmatch(c) or re.search(r"\d", c) for c in cells)

    return (not has_digits(first)) and has_digits(second)


def validate(table: dict, region_height: float, page_height: float) -> tuple[bool, list[str]]:
    """敢不敢认。所有阈值都是为了"宁可少认一张，也不编造一张"。"""
    reasons = []
    if table["rows"] < 2 or table["cols"] < 2:
        reasons.append("rows_or_cols_too_few")
    total = table["rows"] * table["cols"]
    nonempty = sum(1 for r in table["matrix"] for c in r if c and c.strip())
    if total and nonempty / total < MIN_NONEMPTY:
        reasons.append(f"too_many_empty_cells={nonempty}/{total}")
    texts = [c.strip() for r in table["matrix"] for c in r if c and c.strip()]
    if texts:
        avg = sum(len(t) for t in texts) / len(texts)
        if avg > MAX_CELL_CHARS:
            reasons.append(f"cells_look_like_prose(avg_chars={avg:.0f})")
        sentence_like = sum(1 for t in texts if len(t.split()) > 18)
        if sentence_like > len(texts) * 0.3:
            reasons.append("cells_contain_sentences")
        # 多栏正文是"每行被切成几段"，每段都是一个长句碎片（6~9 个词、首字母小写、
        # 结尾没有句号）。真表格的单元格是短标签或数值，长词数的格子只占少数
        # （Dietz 的 Table 2 有一列 Description，6~7 个词的格子也只占 7%）。
        # 没有这条，三栏页会把整页正文当成一张 20×3 的表（合成用例 three_column 实测）。
        long_cells = sum(1 for t in texts if len(t.split()) >= 6)
        if long_cells / len(texts) > 0.45:
            reasons.append(f"cells_are_prose_fragments({long_cells}/{len(texts)} cells >=6 words)")
    if page_height and region_height / page_height > MAX_HEIGHT_RATIO:
        reasons.append("region_covers_most_of_page")
    return (not reasons), reasons


def _hlines(page, y_from: float, y_to: float, x_min: float, x_max: float) -> list[float]:
    """区域内 ≥50pt 长的横线 y 坐标。期刊表格几乎都有顶线/表头线/底线，用它们定上下界
    比"猜下一个正文段"稳（Dietz 的表体第一行就是表头，按'下一段'会把表头当正文排掉）。"""
    ys = []
    try:
        drawings = page.get_drawings()
    except Exception:
        return ys
    for d in drawings:
        for item in d.get("items", []):
            if item[0] != "l":
                continue
            p1, p2 = item[1], item[2]
            if abs(p1.y - p2.y) > 1.2:
                continue
            length = abs(p2.x - p1.x)
            if length < 50 or length < (x_max - x_min) * 0.35:
                continue
            y = (p1.y + p2.y) / 2
            if y_from <= y <= y_to and min(p1.x, p2.x) <= x_max and max(p1.x, p2.x) >= x_min:
                ys.append(round(y, 1))
    return sorted(set(ys))


def _rule_spans(page, rect) -> list[tuple[float, float, float]]:
    """落在 rect 里、长度 >=40pt 的横线，(y, x_left, x_right)。"""
    spans = []
    try:
        drawings = page.get_drawings()
    except Exception:
        return spans
    for d in drawings:
        for item in d.get("items", []):
            if item[0] != "l":
                continue
            p1, p2 = item[1], item[2]
            if abs(p1.y - p2.y) > 1.2:
                continue
            xa, xb = sorted((p1.x, p2.x))
            if xb - xa < 40:
                continue
            y = (p1.y + p2.y) / 2
            if rect.y0 - 1 <= y <= rect.y1 + 1 and xb >= rect.x0 and xa <= rect.x1:
                spans.append((y, xa, xb))
    return spans


def tighten_region(page, rect) -> "pymupdf.Rect":
    """用表格自己的横线收紧区域的左右边界。

    为什么需要：双栏页里"跨栏大表"要用整页宽度才抓得全，所以候选区域会放宽到整页；但放宽
    之后，隔壁栏的正文也被切成了列（Dietz 第 3 页 Table 1 因此多出第 7 列，内容是右栏正文
    "error remain unchanged with forecast horizon…"，还多出两行空行）。
    为什么按横线收紧而不是事后按文字裁列：横线是表格自己画的，它的起止点就是表格的物理边界，
    这是最硬的证据；而"哪一列是正文"只能靠启发式猜，Dietz 这张表误抓的那列在 6 行里有 4 行
    都有字（正文行正好和表格行对齐），填充率 0.67，任何"低填充率才裁"的规则都判不出来。
    只在横线明显比请求区域窄（<88%）时收紧，避免把本来就对齐的区域挪歪。
    """
    spans = _rule_spans(page, rect)
    if len(spans) < 2:
        return rect
    xa = min(s[1] for s in spans)
    xb = max(s[2] for s in spans)
    if xb - xa < 40 or xb - xa >= (rect.x1 - rect.x0) * 0.88:
        return rect
    return pymupdf.Rect(max(rect.x0, xa - 2), rect.y0, min(rect.x1, xb + 2), rect.y1)


def _col_bounds(page_dict: dict, cap: dict) -> tuple[float, float]:
    """题注所在栏的左右边界。双栏页里表格通常只占一栏，用整页宽度定区域会把另一栏正文吞进来
    （Dietz 第 3 页 Table 1 就因此把右栏三段正文当成了表格列）。"""
    content = page_dict["layout"].get("content") or [0, 0, page_dict["width"], page_dict["height"]]
    splits = page_dict["layout"].get("splits") or []
    x0 = cap["bbox"][0]
    if not splits:
        return content[0], content[2]
    idx = 0
    for s in splits:
        if x0 > s:
            idx += 1
    lo = content[0] if idx == 0 else splits[idx - 1] + 2
    hi = content[2] if idx >= len(splits) else splits[idx] - 2
    return lo, hi


def table_region(page_dict: dict, cap: dict, page=None, full_width: bool = False) -> list[float] | None:
    """题注定位表格区域。

    优先用横线（顶线→底线）定界；没有横线时，退到"题注下方 → 本栏下一个长正文段之前"。
    为什么不用"题注下方第一段"：表体的第一行往往就是表头，会被当成正文把区域压成 0 高
    （Dietz 第 4 页实测：区域高度只剩 10pt，一张表都没测出来）。
    """
    if full_width:
        xs = [p["bbox"][0] for p in page_dict["paras"]] + [p["bbox"][2] for p in page_dict["paras"]]
        x0, x1 = min(xs) - 2, max(xs) + 2
    else:
        x0, x1 = _col_bounds(page_dict, cap)
    y0 = cap["bbox"][3] + 2
    limit = min(page_dict["height"] * 0.92, y0 + page_dict["height"] * 0.6)

    if page is not None:
        lines = _hlines(page, y0 - 1, limit, x0, x1)
        if len(lines) >= 2:
            r = pymupdf.Rect(x0, max(y0 - 2, lines[0] - 1.5), x1, min(limit, lines[-1] + 1.5))
            r = tighten_region(page, r)
            return [r.x0, r.y0, r.x1, r.y1]

    after = [p for p in page_dict["paras"]
             if p["bbox"][1] > cap["bbox"][3] + 1 and p.get("role") not in
             ("header", "footer", "page_number", "caption")
             and p["bbox"][0] >= x0 - 4 and p["bbox"][2] <= x1 + 4]
    long_body = [p for p in after if p.get("role") == "body" and len(p["text"]) >= 120]
    if long_body:
        y1 = min(min(p["bbox"][1] for p in long_body) - 2, limit)
    else:
        y1 = limit
    if y1 - y0 < 20:
        return None
    return [x0, y0, x1, y1]


def scan_aligned_tables(page, pg: dict, taken: list[list[float]]) -> list[dict]:
    """无题注/题注离表很远的兜底：找"连续多行、每行 >=3 个对齐单元格"的区域。

    为什么要这条：Chen 2024 的 Table 2 题注在页面最下方、表体在别处，靠"题注邻接"找不到；
    而真正的表格有一个硬特征——连续若干行的单元格左边缘反复落在同一组 x 上。
    为什么要求 >=3 列：正文（尤其双栏）每行也能被切成 2 段（左栏/右栏），只要 2 列就会
    把整页正文误判成表格；3 列以上正文极罕见。
    """
    words = _words(page, pymupdf.Rect(0, 0, pg["width"], pg["height"]))
    if len(words) < 30:
        return []
    rows = _cluster_rows(words)
    if len(rows) < 3:
        return []
    # 每行按 x 间隙切成单元格
    row_cells = []
    for r in rows:
        ws = _order_words(r["words"])
        cells, cur = [], [ws[0]]
        for a, b in zip(ws, ws[1:]):
            if b["x0"] - a["x1"] >= 8:
                cells.append(cur)
                cur = [b]
            else:
                cur.append(b)
        cells.append(cur)
        row_cells.append({
            "y0": r["y0"], "y1": r["y1"],
            "cells": [(round(c[0]["x0"], 1), round(c[-1]["x1"], 1),
                       " ".join(w["text"] for w in c)) for c in cells],
        })

    def signature(row):
        return [round(x / 6) * 6 for x, _, _ in row["cells"]]

    runs, cur = [], []
    for row in row_cells:
        if len(row["cells"]) >= 3:
            if cur and len(row["cells"]) == len(cur[-1]["cells"]) and signature(row) == signature(cur[-1]):
                cur.append(row)
                continue
            if len(cur) >= 3:
                runs.append(cur)
            cur = [row]
        else:
            if len(cur) >= 3:
                runs.append(cur)
            cur = []
    if len(cur) >= 3:
        runs.append(cur)

    out = []
    page_area = pg["width"] * pg["height"]
    for run in runs:
        # 右边界必须取"最右词的右缘"，不能取"最后一列的起始 x"。
        # 取起始 x 会把最后一列切成一半：Chen 第 9 页表第 4 列（99343, 99342 …）实测被切成
        # 只剩首字符 "9"，而且相邻两行的残字还被并进同一单元格变成 "9 9"。
        region = [min(c["cells"][0][0] for c in run) - 2, round(run[0]["y0"], 1),
                  max(max(x1 for _, x1, _ in c["cells"]) for c in run) + 2, round(run[-1]["y1"], 1)]
        # 宽度过窄或覆盖过大（整页正文）都不认
        if region[2] - region[0] < 80 or (region[3] - region[1]) * (region[2] - region[0]) > page_area * 0.5:
            continue
        if any(pdfcore.bbox_iou(region, b) > 0.3 for b in taken):
            continue
        cand = reconstruct_grid(page, pymupdf.Rect(*region))
        if not cand:
            continue
        ok, why = validate(cand, region[3] - region[1], pg["height"])
        if not ok:
            continue
        out.append({"table": cand, "region": [round(v, 1) for v in region],
                    "caption": None, "caption_number": None, "caption_para": None,
                    "page": pg["no"]})
    return out


def parse(pdf, doc: dict) -> dict:
    """逐页找表，标注单元格段落，合并跨页续表。"""
    tables = []
    for pg in doc["pages"]:
        if pg["route"] != "text":
            continue
        page = pdf.doc[pg["no"] - 1]
        caps = [p for p in pg["paras"] if p.get("role") == "caption" and p.get("caption_of") == "table"]
        for cap in caps:
            # 窄区域（题注所在栏）与整页宽度各试一次，取"通过校验且非空单元格更多"的那个。
            # 为什么这样选：跨栏大表（Dietz 的 Table 2 左右两块）在窄区域里只抓到一半，
            # 单元格数明显更少；而"把隔壁栏正文当表格"的假表会因为单元格像句子而校验失败。
            trials = []
            # 候选区域不止"题注下方"：
            #  a) 题注下方（表题在上，最常见）；
            #  b) 题注在页面下部时，表格常常排在**下一页顶部**（Chen 2024 的 Table 2 就是这样，
            #     只在同页找会一张表都测不到）；
            #  c) 题注上方（少数期刊把表题放在表下方）。
            plans = [("below", pg, page, False), ("below", pg, page, True)]
            if cap["bbox"][1] > pg["height"] * 0.6:
                plans.append(("above", pg, page, False))
            if cap["bbox"][1] > pg["height"] * 0.75 and pg["no"] < len(doc["pages"]):
                plans.append(("next_page", doc["pages"][pg["no"]], pdf.doc[pg["no"]], False))
            for where, pg_i, page_i, full_width in plans:
                if where == "above":
                    xs = [p["bbox"][0] for p in pg_i["paras"]] + [p["bbox"][2] for p in pg_i["paras"]]
                    body_above = [p for p in pg_i["paras"] if p["bbox"][3] < cap["bbox"][1] - 2
                                  and p.get("role") in ("body", "heading", "caption")]
                    y1 = cap["bbox"][1] - 2
                    y0 = max((p["bbox"][3] for p in body_above), default=pg_i["height"] * 0.1) + 2
                    if y1 - y0 < 20:
                        continue
                    cand_region = [min(xs) - 2, round(y0, 1), max(xs) + 2, round(y1, 1)]
                elif where == "next_page":
                    xs = [p["bbox"][0] for p in pg_i["paras"]] + [p["bbox"][2] for p in pg_i["paras"]]
                    y0 = min((p["bbox"][1] for p in pg_i["paras"]), default=0) + 1
                    body = [p for p in pg_i["paras"] if p.get("role") == "body" and len(p["text"]) >= 120]
                    y1 = min((p["bbox"][1] for p in body), default=pg_i["height"] * 0.45) - 2
                    if y1 - y0 < 20:
                        continue
                    cand_region = [min(xs) - 2, round(y0, 1), max(xs) + 2, round(y1, 1)]
                else:
                    cand_region = table_region(pg_i, cap, page_i, full_width=full_width)
                if not cand_region:
                    continue
                rect = tighten_region(page_i, pymupdf.Rect(*cand_region))
                cand_region = [round(rect.x0, 1), round(rect.y0, 1), round(rect.x1, 1), round(rect.y1, 1)]
                cand = find_bordered(page_i, rect) or reconstruct_grid(page_i, rect)
                if not cand:
                    continue
                ok_c, why = validate(cand, rect.height, pg_i["height"])
                nonempty = sum(1 for r in cand["matrix"] for c in r if c and c.strip())
                trials.append({"ok": ok_c, "why": why, "table": cand, "region": cand_region,
                               "nonempty": nonempty, "page": pg_i["no"]})
            if not trials:
                continue
            valid = [t for t in trials if t["ok"]]
            best = max(valid, key=lambda t: t["nonempty"]) if valid else trials[0]
            table, region, reasons = best["table"], best["region"], ([] if best["ok"] else best["why"])
            hit_page = best.get("page", pg["no"])
            if not table:
                continue
            ok = not reasons
            table.update({
                "id": f"t{len(tables) + 1}",
                "page": hit_page,
                "caption": cap["text"],
                "caption_number": cap.get("caption_number"),
                "caption_para": cap["id"],
                "region": [round(v, 1) for v in region],
                "bbox": [round(v, 1) for v in (table.get("cells") and
                                               [min(c["bbox"][0] for c in table["cells"].values()),
                                                min(c["bbox"][1] for c in table["cells"].values()),
                                                max(c["bbox"][2] for c in table["cells"].values()),
                                                max(c["bbox"][3] for c in table["cells"].values())]
                                               or region)],
                "status": "structured" if ok else "detected_unstructured",
                "reject_reasons": reasons,
                "pages": [hit_page],
                "header_rows": 1 if looks_like_header(table["matrix"]) else 0,
                "header_rows": 1,
            })
            tables.append(table)
            cap["table_id"] = table["id"]
            if ok:
                # 标记落在表格区域内的段落：它们不是正文，不能进 body 流
                for p in pg["paras"]:
                    if pdfcore.bbox_iou(p["bbox"], table["bbox"]) > 0.55 or \
                            (p["bbox"][1] >= table["bbox"][1] - 2 and p["bbox"][3] <= table["bbox"][3] + 2
                             and p["bbox"][0] >= table["bbox"][0] - 4 and p["bbox"][2] <= table["bbox"][2] + 4):
                        if p.get("role") not in ("caption", "header", "footer", "page_number"):
                            p["role"] = "table_cell"
                            p["table_id"] = table["id"]

    # 兜底：没有题注（或题注离得很远）但确实是"多行多列对齐"的区域
    for pg in doc["pages"]:
        if pg["route"] != "text":
            continue
        page = pdf.doc[pg["no"] - 1]
        taken = [t["bbox"] for t in tables if t["page"] == pg["no"]]
        for raw in scan_aligned_tables(page, pg, taken):
            hit = dict(raw["table"])          # 把重建结果摊平到顶层，保持与其它表同一结构
            hit.update({k: v for k, v in raw.items() if k != "table"})
            hit["id"] = f"t{len(tables) + 1}"
            hit["method"] = hit.get("method", "word_grid")
            hit["status"] = "structured"
            hit["reject_reasons"] = []
            hit["pages"] = [pg["no"]]
            hit["header_rows"] = 1 if looks_like_header(hit["matrix"]) else 0
            hit["bbox"] = [round(min(c["bbox"][0] for c in hit["cells"].values()), 1),
                           round(min(c["bbox"][1] for c in hit["cells"].values()), 1),
                           round(max(c["bbox"][2] for c in hit["cells"].values()), 1),
                           round(max(c["bbox"][3] for c in hit["cells"].values()), 1)] \
                if hit.get("cells") else hit["region"]
            tables.append(hit)
            for p in pg["paras"]:
                b = p["bbox"]
                if (b[0] >= hit["bbox"][0] - 3 and b[2] <= hit["bbox"][2] + 3
                        and b[1] >= hit["bbox"][1] - 3 and b[3] <= hit["bbox"][3] + 3):
                    if p.get("role") not in ("caption", "header", "footer", "page_number"):
                        p["role"] = "table_cell"
                        p["table_id"] = hit["id"]

    # 跨页续表合并
    merged = []
    for t in tables:
        prev = merged[-1] if merged else None
        if (prev and t["status"] == "structured" and prev["status"] == "structured"
                and prev["pages"][-1] == t["page"] - 1
                and t["region"][1] < doc["pages"][t["page"] - 1]["height"] * 0.3
                and t["cols"] == prev["cols"]
                and _header_similar(prev, t)):
            prev["matrix"].extend(t["matrix"])
            prev["rows"] = len(prev["matrix"])
            prev["pages"].append(t["page"])
            prev["continued"] = True
            prev["bbox"][3] = t["bbox"][3]
            for p in doc["pages"][t["page"] - 1]["paras"]:
                if p.get("table_id") == t["id"]:
                    p["table_id"] = prev["id"]
            continue
        merged.append(t)
    for i, t in enumerate(merged, 1):
        t["id"] = f"t{i}"
    doc["tables"] = merged
    return doc


def _header_similar(a: dict, b: dict) -> bool:
    ha = [c for c in (a["matrix"][0] if a["matrix"] else []) if c]
    hb = [c for c in (b["matrix"][0] if b["matrix"] else []) if c]
    if not ha or not hb:
        return True
    sa = pdfcore.norm_text(" ".join(ha)).lower()
    sb = pdfcore.norm_text(" ".join(hb)).lower()
    if CONTINUED.search((a.get("caption") or "") + (b.get("caption") or "")):
        return True
    return sa == sb or sa in sb or sb in sa


def to_markdown(table: dict) -> str:
    lines = []
    caption = table.get("caption") or (
        f"表 {table['caption_number']}" if table.get("caption_number") else "表格（题注未识别）")
    pages = table.get("pages") or [table["page"]]
    suffix = f"（第 {pages[0]}–{pages[-1]} 页）" if len(pages) > 1 else f"（第 {pages[0]} 页）"
    lines.append(f"**{caption}**{suffix}\n")
    header_rows = int(table.get("header_rows", 1))
    cols = table["cols"]
    if header_rows >= 1 and table["matrix"]:
        header = table["matrix"][0]
        body = table["matrix"][1:]
    else:
        header = [""] * cols          # 无表头：留空表头，避免把首条数据当列名
        body = table["matrix"]
    lines.append("| " + " | ".join((c or " ") for c in header) + " |")
    lines.append("|" + "|".join(["---"] * max(1, len(header))) + "|")
    for row in body:
        cells = []
        for c in row:
            cells.append((c or "").replace("|", "\\|").replace("\n", " "))
        lines.append("| " + " | ".join(cells) + " |")
    if table.get("reject_reasons"):
        lines.append(f"\n> 未通过结构校验：{', '.join(table['reject_reasons'])}；"
                     f"原始区域已记录，可按页码人工复核。")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="表格区域定位与单元格网格重建")
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--struct", required=True, help="structure.py 输出的 json")
    ap.add_argument("--out", required=True)
    ap.add_argument("--markdown-dir", default=None)
    args = ap.parse_args()
    pdf = pdfcore.PdfDoc(args.pdf)
    doc = json.loads(Path(args.struct).read_text(encoding="utf-8"))
    doc = parse(pdf, doc)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.markdown_dir:
        md = Path(args.markdown_dir)
        md.mkdir(parents=True, exist_ok=True)
        for t in doc["tables"]:
            (md / f"{t['id']}.md").write_text(to_markdown(t), encoding="utf-8")
    print(json.dumps({
        "out": args.out,
        "tables": [{"id": t["id"], "page": t["page"], "rows": t["rows"], "cols": t["cols"],
                    "method": t["method"], "status": t["status"],
                    "reasons": t["reject_reasons"], "pages": t["pages"]}
                   for t in doc["tables"]],
        "table_cell_paras": sum(1 for pg in doc["pages"] for p in pg["paras"] if p.get("role") == "table_cell"),
    }, ensure_ascii=False, indent=1))
    pdf.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
