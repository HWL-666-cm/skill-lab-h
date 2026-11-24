#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pdfcore.py — 01 题共享底座：打开 PDF、字符归一化、页级 line/block 模型、页面分诊。

为什么要有这一层（设计依据）：
1) PDF 只记录"在 x,y 画哪个字形"，没有段落/表格/栏的语义。所以下游每一个结构判断
   都必须建立在"带坐标的 line/span"上，而不是先前的纯文本。这里统一产出带 bbox 的
   line 模型，后面分栏、章节、表格、公式都从它派生，避免各脚本各写一套坐标口径。
2) 逐字一致是评分硬指标，但"逐字"和"可比较"是两件事：原文里的 NBSP、软连字符、
   连字 fi 必须先归一化才能做比对，否则比对结果全是假不一致。因此每个文本单元同时
   保留 text_raw（原样，供引用与逐字核对）与 text（归一化，供匹配与统计）。
3) 乱码不能留给下游报错。ToUnicode 缺失/错误时文本层无解，必须在分诊阶段就判出来，
   否则会拿一堆 CID 数字当"正文"继续往下走。
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import pymupdf  # PyMuPDF >= 1.23

# ---------------------------------------------------------------- 归一化

# 这些字符看起来像空格但不是 ASCII 空格：不归一，正则与逐字比对都会失配。
SPACE_LIKE = {
    "\u00a0": " ",  # NBSP
    "\u2000": " ",  # en quad
    "\u2001": " ",
    "\u2002": " ",
    "\u2003": " ",
    "\u2004": " ",
    "\u2005": " ",
    "\u2006": " ",
    "\u2007": " ",
    "\u2008": " ",
    "\u2009": " ",  # thin space
    "\u200a": " ",  # hair space
    "\u202f": " ",  # narrow NBSP
    "\u205f": " ",  # medium math space
    "\u3000": " ",  # 全角空格
    "\u200b": "",   # 零宽空格（直接删，留着会把一个词切成两个）
    "\u00ad": "",   # 软连字符（是排版提示，不是字符）
    "\ufeff": "",   # BOM
}

_LIGATURES = {"\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi", "\ufb04": "ffl"}

CID_ARTIFACT = re.compile(r"\(cid:\d+\)")
REPLACEMENT = re.compile("[\ufffd\ue000-\uf8ff]")


def norm_text(text: str) -> str:
    """归一化：供匹配/统计用。保留大小写与全角数字（全角数字在数值核验时另行 NFKC）。"""
    if not text:
        return ""
    for k, v in SPACE_LIKE.items():
        text = text.replace(k, v)
    for k, v in _LIGATURES.items():
        text = text.replace(k, v)
    text = text.replace("\r", "")
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def nfkc(text: str) -> str:
    """全角→半角、上标字符→普通字符。用于数值比对与术语比对，不用于逐字展示。"""
    return unicodedata.normalize("NFKC", norm_text(text))


def dehyphenate(left: str, right: str) -> str:
    """拼接两行时处理行尾断词：'compre-' + 'hensive' -> 'comprehensive'。

    只在连字符后接小写字母时合并；'state-of-' + 'the-art' 这种保留连字符。
    """
    left = left.rstrip()
    if left.endswith("-") and right[:1].islower():
        return left[:-1] + right.lstrip()
    return left + " " + right.lstrip() if left else right.lstrip()


def garbled_ratio(text: str) -> float:
    """乱码占比：替换符 + 私用区 + (cid:N) 伪字符。"""
    if not text:
        return 0.0
    bad = len(REPLACEMENT.findall(text)) + len(CID_ARTIFACT.findall(text)) * 6
    return bad / max(1, len(text))


def has_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text))


# ---------------------------------------------------------------- 字体/公式判据

MATH_FONT = re.compile(r"(CMMI|CMSY|CMEX|CMR\d|MSBM|MTMI|MTSY|MTSYN|Symbol|STIX|Euclid|Math)", re.I)
MATH_GLYPH = re.compile(r"[α-ωΑ-Ωϑϕϵ∑∏∫∂∇√∞≈≠≤≥±∓×÷∈∉⊂⊃⊆⊇∪∩→←↔⇒⇔′″ˆ˜‾⋅∙·∙⟨⟩⌈⌉⌊⌋]")
FORMULA_NUMBER = re.compile(r"^[(（]\s*(\d+[a-z]?|\d+\.\d+|[A-Z]\d*)\s*[)）]\s*$")


def is_math_span(span: dict) -> bool:
    return bool(MATH_FONT.search(span.get("font", ""))) or bool(MATH_GLYPH.search(span.get("text", "")))


# ---------------------------------------------------------------- 页级模型


def _round(x: float) -> float:
    return round(float(x), 1)


def bbox_tuple(b) -> list[float]:
    return [_round(v) for v in (b[0], b[1], b[2], b[3])]


def bbox_width(b) -> float:
    return float(b[2]) - float(b[0])


def bbox_height(b) -> float:
    return float(b[3]) - float(b[1])


def bbox_area(b) -> float:
    return max(0.0, bbox_width(b)) * max(0.0, bbox_height(b))


def bbox_intersect(a, b) -> float:
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)


def bbox_iou(a, b) -> float:
    inter = bbox_intersect(a, b)
    if inter <= 0:
        return 0.0
    return inter / (bbox_area(a) + bbox_area(b) - inter)


class PdfDoc:
    """包装 pymupdf.Document，负责密码、字体 ToUnicode 缓存、页级 line 模型。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.doc = pymupdf.open(str(self.path))
        self._tounicode_cache: dict[int, bool] = {}
        self.password_required = bool(self.doc.needs_pass)
        self.opened = True
        if self.password_required:
            # 只尝试空密码：很多"加密"PDF 只设了权限位而没有用户密码。
            self.opened = bool(self.doc.authenticate(""))

    # -- 字体 ---------------------------------------------------------
    def font_has_tounicode(self, xref: int) -> bool:
        if xref in self._tounicode_cache:
            return self._tounicode_cache[xref]
        ok = True
        try:
            kind, value = self.doc.xref_get_key(xref, "ToUnicode")
            ok = kind != "null" and bool(value)
        except Exception:
            ok = False
        self._tounicode_cache[xref] = ok
        return ok

    def page_fonts_missing_tounicode(self, page) -> tuple[int, int]:
        missing = total = 0
        try:
            fonts = page.get_fonts(full=True)
        except Exception:
            return 0, 0
        seen = set()
        for f in fonts:
            xref = f[0]
            if xref in seen:  # 同一字体在一页里可能多次出现
                continue
            seen.add(xref)
            total += 1
            if not self.font_has_tounicode(xref):
                missing += 1
        return missing, total

    # -- 页级 line 模型 ------------------------------------------------
    def page_lines(self, pno: int) -> dict:
        """返回 {width,height,rotation,lines:[...],blocks:[...],raw_text}。

        line 里保留 spans（上下标判定要用 span 的 origin/flags），
        block 里保留 bbox 与 line 下标，便于段落切分。
        """
        page = self.doc[pno]
        rect = page.rect
        data = page.get_text("dict")
        blocks, lines = [], []
        for bi, blk in enumerate(data.get("blocks", [])):
            if blk.get("type") != 0:
                blocks.append({
                    "id": f"p{pno + 1}b{bi}", "bbox": bbox_tuple(blk.get("bbox", (0, 0, 0, 0))),
                    "type": "image", "line_ids": [],
                })
                continue
            blines = []
            for ln in blk.get("lines", []):
                spans = []
                for sp in ln.get("spans", []):
                    t = sp.get("text", "")
                    if not t:
                        continue
                    spans.append({
                        "text": t,
                        "font": sp.get("font", ""),
                        "size": round(float(sp.get("size", 0)), 1),
                        "flags": int(sp.get("flags", 0)),
                        "bbox": bbox_tuple(sp.get("bbox", (0, 0, 0, 0))),
                        "origin_y": round(float(sp.get("origin", (0, 0))[1]), 1),
                        "math": is_math_span(sp),
                    })
                if not spans:
                    continue
                # 把"同一基线上拼了多栏文字"的伪行切开。
                # 为什么需要：PyMuPDF 按基线把同一 block 里的 span 合成一行，如果 PDF 把
                # 相邻栏的文字放进同一个文本块（某些生成器、或者一行真的要横跨两栏时），
                # 左栏行尾会和右栏行首直接拼成一句——三栏合成件实测读出来是
                # "The predictor set matters more than the learning algorithm … Ceiling,
                #  runway visual range, predictors that are already available from the …"。
                # 判据用"相对字号的间隙"：正文词间距是 0.2–0.4 倍字号，栏缝通常在 1 倍字号以上。
                groups: list[list[dict]] = [[spans[0]]]
                for prev, cur in zip(spans, spans[1:]):
                    gap = cur["bbox"][0] - prev["bbox"][2]
                    size = max(cur["size"], prev["size"], 1.0)
                    if gap > max(6.0, 1.0 * size) and len(groups[-1]) >= 1:
                        groups.append([cur])
                    else:
                        groups[-1].append(cur)
                for g in groups:
                    raw = "".join(s["text"] for s in g)
                    text = norm_text(raw)
                    if not text:
                        continue
                    weights = [max(1, len(s["text"])) for s in g]
                    size = round(sum(s["size"] * w for s, w in zip(g, weights)) / sum(weights), 1)
                    lid = len(lines)
                    lines.append({
                        "id": f"p{pno + 1}l{lid}",
                        "block": f"p{pno + 1}b{bi}",
                        "bbox": [round(min(s["bbox"][0] for s in g), 1),
                                 round(min(s["bbox"][1] for s in g), 1),
                                 round(max(s["bbox"][2] for s in g), 1),
                                 round(max(s["bbox"][3] for s in g), 1)],
                        "text_raw": raw,
                        "text": text,
                        "size": size,
                        "bold": any(s["flags"] & 16 for s in g),
                        "italic": any(s["flags"] & 2 for s in g),
                        "math": any(s["math"] for s in g),
                        "spans": g,
                    })
                    blines.append(lid)
            if blines:
                blocks.append({
                    "id": f"p{pno + 1}b{bi}", "type": "text",
                    "bbox": bbox_tuple(blk.get("bbox", (0, 0, 0, 0))),
                    "line_ids": blines,
                })
        try:
            raw_text = page.get_text("text")
        except Exception:
            raw_text = "\n".join(l["text_raw"] for l in lines)
        return {
            "no": pno + 1,
            "width": _round(rect.width), "height": _round(rect.height),
            "rotation": int(page.rotation or 0),
            "lines": lines, "blocks": blocks,
            "raw_text": raw_text,
            "image_count": len(page.get_images(full=True)),
            "drawing_count": len(page.get_drawings()) if hasattr(page, "get_drawings") else 0,
        }

    def close(self):
        try:
            self.doc.close()
        except Exception:
            pass


# ---------------------------------------------------------------- 分诊

TEXT_OK_MIN_CHARS = 120
GARBLED_LIMIT = 0.03


def triage_page(pdf: PdfDoc, pno: int, model: dict | None = None) -> dict:
    """单页分诊：决定这页走文本提取、OCR，还是只能如实标为不可读。

    判据的组合方式与理由：
    - 有字但乱码率高 → ToUnicode 坏了，文本层不可信，必须 OCR；
    - 几乎没字但有整页图 → 扫描页，OCR；
    - 几乎没字但矢量图元很多 → 文字被转曲（轮廓），文本层彻底没有，OCR；
    - 都没命中但字数偏少 → 仍按文本走，但记一条 low_text 警告（可能是图页/公式页）。
    """
    m = model or pdf.page_lines(pno)
    text = m["raw_text"]
    chars = len(text.strip())
    gr = garbled_ratio(text)
    missing, total = pdf.page_fonts_missing_tounicode(pdf.doc[pno])
    flags, reasons = [], []

    if chars == 0 and m["image_count"] > 0:
        route = "ocr"
        reasons.append("no_text_layer_with_images")
    elif chars < 60 and m["drawing_count"] > 80 and m["image_count"] == 0:
        route = "ocr"
        flags.append("text_as_outlines")
        reasons.append("very_little_text_but_many_drawings")
    elif gr > GARBLED_LIMIT:
        route = "ocr"
        flags.append("garbled_text_layer")
        reasons.append(f"garbled_ratio={gr:.3f}")
    elif chars >= TEXT_OK_MIN_CHARS:
        route = "text"
    else:
        route = "text"
        flags.append("low_text")
        reasons.append(f"few_chars={chars}")

    if missing and total and missing / total > 0.5 and route == "text":
        # 字体缺 ToUnicode 但抽取结果正常：不升级为 OCR，只留证据（很多 Type1 标准编码无需该表）。
        flags.append("fonts_without_tounicode")

    return {
        "page": pno + 1,
        "route": route,
        "chars": chars,
        "garbled_ratio": round(gr, 4),
        "images": m["image_count"],
        "drawings": m["drawing_count"],
        "fonts_total": total,
        "fonts_missing_tounicode": missing,
        "rotation": m["rotation"],
        "flags": flags,
        "reasons": reasons,
    }


def triage_document(pdf: PdfDoc) -> dict:
    pages = []
    for pno in range(pdf.doc.page_count):
        model = pdf.page_lines(pno)
        t = triage_page(pdf, pno, model)
        pages.append(t)
    counts = {}
    for p in pages:
        counts[p["route"]] = counts.get(p["route"], 0) + 1
    return {
        "pages": pages,
        "page_count": pdf.doc.page_count,
        "route_counts": counts,
        "password_required": pdf.password_required,
        "opened": pdf.opened,
        "needs_ocr_pages": [p["page"] for p in pages if p["route"] == "ocr"],
        "low_text_pages": [p["page"] for p in pages if "low_text" in p["flags"]],
    }
