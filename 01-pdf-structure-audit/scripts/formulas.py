#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""formulas.py — 公式识别：编号配对、上下标还原、原文串与归一化串双版本、区域截图。

为什么这么做：
1) 公式在 PDF 里不是"对象"，就是一堆摆好位置的字符。LaTeX 生成的公式经常被拆成
   多个 span（甚至多个 block），直接 get_text 会得到乱序串；上下标更麻烦——它们是
   独立 span 且字号更小、纵向偏移，按行读会变成 "x2" 这种看不出是上标的写法。
   所以这里回到 span 级：用字号 + 基线偏移判上下标，还原成 x^{2} / x_{i} 形式。
2) 公式编号（(1)、(2a)）是"能核回原文"的关键锚点：把编号与公式块绑在一起，
   读者才能按编号回查。判据是"右缘单独一段括号数字"，不靠正则扫全文。
3) 不做 LaTeX 转换：符号保真 + 编号对照 + 区域截图三件就够核验；硬转 LaTeX 反而
   会引入编造（符号猜错、结构猜错），违反"读不出就标注、不靠猜补齐"。
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pdfcore
import pymupdf

NUM_ONLY = re.compile(r"^[(（]\s*(\d+[a-z]?|\d+\.\d+|[A-Z]\d{0,2})\s*[)）]$")
EQ_HINT = re.compile(r"\b(Eq\.?|Equation)\s*[(（]?\s*(\d+[a-z]?)", re.I)
# 判定"这行是不是正文散文"的停用词表。公式里几乎不会连续出现这些词；
# 只要一行里有 3 个以上，它就是在叙述而不是在排版公式（Dietz 实测能滤掉
# "4. Update the predictor function … with 0 < ν ≤ 1 as the shrinkage…" 这类算法步骤）。
STOPWORDS = {
    "the", "and", "of", "to", "with", "for", "is", "are", "in", "on", "by", "as",
    "that", "this", "we", "it", "from", "at", "an", "be", "or", "which", "than",
    "these", "those", "was", "were", "has", "have", "can", "not", "but", "its",
}


def _tokens(text: str) -> list[str]:
    return re.findall(r"[A-Za-z]{2,}", text)


def _prose_score(text: str) -> tuple[int, bool]:
    """返回 (停用词个数, 是否以小写单词开头)。"""
    toks = _tokens(text)
    stops = sum(1 for t in toks if t.lower() in STOPWORDS)
    starts_lower_word = bool(toks) and re.match(r"^[a-z]{3,}", text.strip() or "") is not None
    return stops, starts_lower_word


def _script_kind(span: dict, line_baseline: float, line_size: float) -> str:
    """判上下标：字号明显更小 + 基线偏移明显。PyMuPDF 的 superscript 位不可全信
    （不少 PDF 生成器不设置该 flag），所以以几何为主、flag 为辅。"""
    small = span["size"] < line_size * 0.92
    dy = span["origin_y"] - line_baseline
    if span["flags"] & 1 and small:
        return "sup"
    if not small:
        return ""
    if dy < -line_size * 0.18:
        return "sup"
    if dy > line_size * 0.20:
        return "sub"
    return ""


def elegant(lines: list[dict]) -> dict:
    """把公式的若干行拼成"带上下标标记"的字符串。

    输出两版：
      raw   —— 原样拼接（逐字核对用）
      scripted —— 上下标还原为 ^{} / _{}（继续处理用）
    """
    spans = []
    for ln in lines:
        line_size = max((s["size"] for s in ln["spans"]), default=ln["size"])
        baseline = max((s["origin_y"] for s in ln["spans"]), default=ln["bbox"][3])
        for s in sorted(ln["spans"], key=lambda x: x["bbox"][0]):
            kind = _script_kind(s, baseline, line_size)
            spans.append({
                "text": s["text"], "kind": kind,
                "font": s["font"], "bbox": s["bbox"], "size": s["size"],
                "math": s["math"],
            })
    # 合并相邻同类 span，避免 x^{2}^{3} 这种碎片
    merged: list[dict] = []
    for s in spans:
        if merged and merged[-1]["kind"] == s["kind"] and s["kind"]:
            merged[-1]["text"] += s["text"]
        else:
            merged.append(dict(s))
    raw = "".join(s["text"] for s in merged)
    scripted_parts = []
    for s in merged:
        t = s["text"]
        if s["kind"] == "sup":
            scripted_parts.append("^{" + t.strip() + "}")
        elif s["kind"] == "sub":
            scripted_parts.append("_{" + t.strip() + "}")
        else:
            scripted_parts.append(t)
    scripted = "".join(scripted_parts)
    scripted = re.sub(r"\s+", " ", scripted).strip()
    fonts = sorted({s["font"] for s in merged if s["math"]})
    return {"raw": raw.strip(), "scripted": scripted,
            "has_superscript": any(s["kind"] == "sup" for s in merged),
            "has_subscript": any(s["kind"] == "sub" for s in merged),
            "math_fonts": fonts[:4]}


def number_of(line: dict, col_right: float) -> str | None:
    """右缘的独立括号数字 = 公式编号。判据同时要求位置（靠右）与形态（只有编号）。"""
    if not line["spans"]:
        return None
    last = max(line["spans"], key=lambda s: s["bbox"][2])
    m = NUM_ONLY.match(pdfcore.norm_text(last["text"]))
    if not m:
        return None
    if last["bbox"][2] < col_right - 55:
        return None
    return m.group(1)


def _pack(page_no: int, number: str | None, lines: list[dict], text: dict) -> dict:
    x0 = min(l["bbox"][0] for l in lines)
    y0 = min(l["bbox"][1] for l in lines)
    x1 = max(l["bbox"][2] for l in lines)
    y1 = max(l["bbox"][3] for l in lines)
    return {
        "id": None,
        "page": page_no,
        "number": number,
        "bbox": [round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1)],
        "text_raw": text["raw"],
        "text_scripted": text["scripted"],
        "has_superscript": text["has_superscript"],
        "has_subscript": text["has_subscript"],
        "math_fonts": text["math_fonts"],
        "line_count": len(lines),
        "status": "ok" if number else "unnumbered",
    }


def extract(doc: dict, pdf) -> dict:
    formulas = []
    by_page: dict[int, list[dict]] = {}
    for pg in doc["pages"]:
        if pg["route"] != "text":
            continue
        by_page[pg["no"]] = pdf.page_lines(pg["no"] - 1)["lines"]

    for pg in doc["pages"]:
        lines = by_page.get(pg["no"])
        if not lines:
            continue
        # 表格区域内的"符号"是表头/单位，不是公式（"(Jm−2)"、"(◦C)" 实测会被当成公式）
        table_boxes = [t["bbox"] for t in doc.get("tables", []) if t["page"] == pg["no"]]
        if table_boxes:
            def in_table(ln):
                cx = (ln["bbox"][0] + ln["bbox"][2]) / 2
                cy = (ln["bbox"][1] + ln["bbox"][3]) / 2
                return any(b[0] - 2 <= cx <= b[2] + 2 and b[1] - 2 <= cy <= b[3] + 2 for b in table_boxes)
            lines = [ln for ln in lines if not in_table(ln)]
        content = pg["layout"].get("content") or [0, 0, pg["width"], pg["height"]]
        splits = pg["layout"].get("splits") or []
        col_right = {0: (splits[0] if splits else content[2])}
        for i, s in enumerate(splits or [content[2]]):
            col_right[i] = s
        for i in range(1, len(splits) + 1):
            col_right[i] = content[2]
        if not splits:
            col_right = {0: content[2]}

        def col_of(x0):
            c = 0
            for s in splits:
                if x0 > s:
                    c += 1
            return c

        # 候选行：数学密度高、且不像散文
        cand = []
        for ln in lines:
            if not ln["spans"]:
                continue
            text = ln["text"]
            n_chars = max(1, len(text))
            math_chars = sum(len(pdfcore.MATH_GLYPH.findall(s["text"])) for s in ln["spans"])
            math_font_chars = sum(len(s["text"]) for s in ln["spans"]
                                  if pdfcore.MATH_FONT.search(s["font"]))
            stops, starts_lower = _prose_score(text)
            # 编号列表项（"4. Update the predictor function …"）公式符号多但其实是步骤说明，
            # 用"以阿拉伯数字+点+大写字母开头"这条把它挡掉
            list_item = bool(re.match(r"^\d{1,2}\.\s+[A-Z\u4e00-\u9fff]", text.strip()))
            density = (math_chars + 0.5 * math_font_chars) / n_chars
            num = number_of(ln, col_right.get(col_of(ln["bbox"][0]), content[2]))
            if num:
                cand.append({"line": ln, "num": num, "density": 1.0})
            elif (not starts_lower and not list_item and stops <= 2
                  and (density >= 0.12 or math_font_chars / n_chars >= 0.4)):
                cand.append({"line": ln, "num": None, "density": density})
        if not cand:
            continue

        used = set()
        # ---- 策略一：以"右缘编号"为锚点，按列 + 纵向邻接吃进公式碎片 ----
        # 为什么只按"同列 + 纵向相邻"而不再要求横向重叠：编号贴在栏的右边缘，公式本体在左，
        # 两者横向根本不重叠。实测 Dietz 第 5 页式 (3)，锚点 x536–548、本体 x307–512，
        # 要求横向重叠会把整条公式漏掉，只剩一个 "(3)"。
        anchors = [c for c in cand if c["num"]]
        used_lines: set = set()
        for a in anchors:
            if id(a) in used:
                continue
            ab = a["line"]["bbox"]
            col = col_of(ab[0])
            band = [a]
            used.add(id(a))
            # 同列、纵向 ±32pt 内、非散文、非另一个编号的文本行都算这条公式的碎片
            for ln in lines:
                if ln is a["line"]:
                    continue
                lb = ln["bbox"]
                if col_of(lb[0]) != col:
                    continue
                if lb[3] < ab[1] - 32 or lb[1] > ab[3] + 32:
                    continue
                if any(pdfcore.norm_text(ln["text"]) == pdfcore.norm_text(x["line"]["text"]) for x in anchors):
                    continue
                t = ln["text"]
                if len(t) > 70:
                    continue
                stops, starts_lower = _prose_score(t)
                if stops >= 3 or starts_lower:
                    continue
                mchars = sum(len(pdfcore.MATH_GLYPH.findall(x["text"])) for x in ln["spans"])
                mf = sum(len(x["text"]) for x in ln["spans"] if pdfcore.MATH_FONT.search(x["font"]))
                dens = (mchars + 0.5 * mf) / max(1, len(t))
                # 只吃"确实是公式碎片"的行：数学密度够，或极短的符号碎片（"3"、"X"、"s=0"）。
                # 否则会把 "the proportional odds model is defined as" 这类正文拉进公式。
                short_frag = len(t.strip()) <= 8 and not any(w in STOPWORDS for w in _tokens(t))
                if dens < 0.12 and not short_frag:
                    continue
                band.append({"line": ln, "num": None, "density": dens})
            cl_lines = sorted([x["line"] for x in band],
                              key=lambda l: (round(l["bbox"][1], 0), l["bbox"][0]))
            text = elegant(cl_lines)
            # 只抓到编号本身 → 说明公式本体没抓到，宁可标"未结构化"也不编
            body = pdfcore.norm_text(text["raw"]).replace(a["num"], "").strip(" ().,，。")
            formulas.append(_pack(pg["no"], a["num"], cl_lines, text))
            if len(body) < 3:
                formulas[-1]["status"] = "number_only"
            for x in band:
                x["line"]["formula_id"] = formulas[-1]["id"]
                used_lines.add(id(x["line"]))

        # ---- 策略二：没有编号的公式，只在高密度、无散文、且碎片彼此紧邻时保留 ----
        rest = [c for c in cand if not c["num"] and id(c["line"]) not in used_lines]
        rest.sort(key=lambda c: (col_of(c["line"]["bbox"][0]), c["line"]["bbox"][1]))
        groups: list[list[dict]] = []
        for c in rest:
            b = c["line"]["bbox"]
            placed = False
            for g in groups:
                mb = g[-1]["line"]["bbox"]
                vgap = b[1] - mb[3]
                ov = min(b[2], mb[2]) - max(b[0], mb[0])
                narrow = min(b[2] - b[0], mb[2] - mb[0]) or 1
                if -2 <= vgap <= 8 and ov > 0 and ov / narrow >= 0.3:
                    g.append(c)
                    placed = True
                    break
            if not placed:
                groups.append([c])
        for g in groups:
            if sum(x["density"] for x in g) / len(g) < 0.25:
                continue
            cl_lines = [x["line"] for x in g]
            text = elegant(cl_lines)
            if len(text["raw"]) < 8:
                continue
            stops, _ = _prose_score(text["raw"])
            if stops >= 2:
                continue
            formulas.append(_pack(pg["no"], None, cl_lines, text))
            for x in g:
                x["line"]["formula_id"] = formulas[-1]["id"]

    formulas.sort(key=lambda f: (f["page"], f["bbox"][1], f["bbox"][0]))
    for i, f in enumerate(formulas, 1):
        f["id"] = f"f{i}"
    doc["formulas"] = formulas
    return doc


def mark_formula_paras(doc: dict) -> dict:
    """把落在公式区域里的正文段改标 formula：它们是公式碎片，不是正文。
    不做这一步，Dietz 第 5 页会出现 "RPS RPSS = 1 −" 这种半截公式被当成正文段。"""
    for pg in doc["pages"]:
        boxes = [f["bbox"] for f in doc.get("formulas", []) if f["page"] == pg["no"]]
        if not boxes:
            continue
        for p in pg["paras"]:
            if p.get("role") != "body":
                continue
            b = p["bbox"]
            for bx in boxes:
                inside = (b[0] >= bx[0] - 3 and b[2] <= bx[2] + 3
                          and b[1] >= bx[1] - 3 and b[3] <= bx[3] + 3)
                if inside or pdfcore.bbox_iou(b, bx) > 0.45:
                    p["role"] = "formula"
                    break
    return doc


def render(pdf, formulas: list[dict], outdir: Path, dpi: int = 200) -> int:
    """公式区域截图：给"符号是否保真"留一张可目检的图，不依赖任何外部渲染工具。"""
    outdir.mkdir(parents=True, exist_ok=True)
    n = 0
    for f in formulas:
        page = pdf.doc[f["page"] - 1]
        pad = 3
        rect = pymupdf.Rect(f["bbox"][0] - pad, f["bbox"][1] - pad,
                            f["bbox"][2] + pad, f["bbox"][3] + pad)
        rect = rect & page.rect
        if rect.is_empty:
            continue
        pix = page.get_pixmap(dpi=dpi, clip=rect)
        pix.save(str(outdir / f"{f['id']}.png"))
        f["image"] = f"formulas/{f['id']}.png"
        n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description="公式识别与编号配对")
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--struct", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--render-dir", default=None, help="导出公式区域 PNG 的目录")
    args = ap.parse_args()
    pdf = pdfcore.PdfDoc(args.pdf)
    doc = json.loads(Path(args.struct).read_text(encoding="utf-8"))
    doc = extract(doc, pdf)
    if args.render_dir:
        render(pdf, doc["formulas"], Path(args.render_dir))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({
        "out": args.out,
        "formulas": len(doc["formulas"]),
        "numbered": sum(1 for f in doc["formulas"] if f["number"]),
        "with_sub_or_sup": sum(1 for f in doc["formulas"] if f["has_superscript"] or f["has_subscript"]),
        "sample": [{"id": f["id"], "page": f["page"], "number": f["number"],
                    "scripted": f["text_scripted"][:70]} for f in doc["formulas"][:5]],
    }, ensure_ascii=False, indent=1))
    pdf.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
