#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_cases.py — 生成自测用的合成 PDF（不依赖任何外部素材、不需要联网）。

为什么要合成而不是只拿真实论文测：真实论文只能证明"这两种版式能跑"，证不了分支是否真的
走到了。评审关心的几类异常输入——加密、无文字层、超长文档、三栏——在公开论文里不好凑齐，
也不该把别人论文放进提交包。合成件可以精确控制"该走到哪个分支"，并能随代码一起分发。
真实论文的对照结果另见 references/benchmark.md（只登记题录与指标，不放原文）。

用法：
    python tests/make_cases.py --out /tmp/pdfcases          # 生成全部
    python tests/make_cases.py --out /tmp/pdfcases --only two_column
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pymupdf

PAGE_W, PAGE_H = 595, 842
FN_REG = pymupdf.Font("helv")
FN_BOLD = pymupdf.Font("hebo")

PARAS = [
    "Visibility forecasting at airports is a hard problem because low-visibility events are "
    "rare, strongly stratified, and driven by interactions between radiative cooling, "
    "turbulence and advection that numerical models resolve only partially.",
    "Statistical post-processing offers a practical alternative. Instead of resolving the "
    "microphysics, it learns a mapping from predictors that are already available from the "
    "numerical model to the probability of the target event, using a long archive of "
    "historical observations as the training signal.",
    "The predictor set matters more than the learning algorithm in most published comparisons. "
    "Ceiling, runway visual range, dew point depression and boundary layer height carry most of "
    "the signal, while radiation terms add skill only during the evening transition when the "
    "boundary layer collapses rapidly.",
    "We therefore fit separate models for each forecast step rather than one model with the "
    "lead time as a feature, because the error structure changes with horizon and a single "
    "model tends to compromise between regimes that behave quite differently.",
    "Calibration is checked with reliability diagrams and the Brier decomposition. A model that "
    "is sharp but poorly calibrated is worse than a well calibrated model with the same area "
    "under the curve, because the operational decision threshold depends on the user.",
    "Missing predictors are imputed from the previous analysis cycle and flagged, so that the "
    "downstream consumer can decide whether a given forecast should be trusted at all.",
]


def para(i: int, n: int = 1) -> str:
    return " ".join(PARAS[(i + k) % len(PARAS)] for k in range(n))


def _write_column(page, rect: pymupdf.Rect, blocks: list[tuple[str, int, bool]]):
    """在 rect 里顺序排 blocks：[(text, fontsize, bold), ...]，每块单独成一个文本对象。

    为什么每块要单独 write_text：真实排版软件（LaTeX、InDesign）每栏都是独立的文本对象，
    所以 PyMuPDF 不会把左右栏同一基线上的字合并成"一行"。如果这里图省事用一个 TextWriter
    写整页，三栏的字会落进同一个文本块，PyMuPDF 按基线把它们拼成一行——那测的是生成器的
    缺陷，不是解析器的能力。
    """
    y = rect.y0
    for text, size, bold in blocks:
        font = FN_BOLD if bold else FN_REG
        used = _textbox_height(text, font, size, rect.width)
        if y + used > rect.y1:
            break
        tw = pymupdf.TextWriter(page.rect)
        tw.fill_textbox(pymupdf.Rect(rect.x0, y, rect.x1, y + used + 4), text,
                        font=font, fontsize=size)
        tw.write_text(page)
        y += used + 6
    return y


def _textbox_height(text: str, font: pymupdf.Font, size: float, width: float) -> float:
    """估算 fill_textbox 需要的高度（按词宽累加，逐行折行）。"""
    words = text.split()
    lines, cur = 1, 0.0
    for w in words:
        wl = font.text_length(w + " ", fontsize=size)
        if cur + wl > width:
            lines += 1
            cur = wl
        else:
            cur += wl
    return lines * size * 1.35


def _put(page, x: float, y: float, text: str, size: float = 11, bold: bool = False) -> None:
    """写一行并立即落成独立文本对象（不与别的块共享内容流）。"""
    tw = pymupdf.TextWriter(page.rect)
    tw.append((x, y), text, font=FN_BOLD if bold else FN_REG, fontsize=size)
    tw.write_text(page)


def _head(page, x: float, y: float, text: str, size: float = 12) -> float:
    _put(page, x, y, text, size, bold=True)
    return y + size * 1.7


def _table(page, x0: float, y0: float, ncol: int = 4, nrow: int = 4, colw: float = 70) -> float:
    """画一个带横线竖线的表（有线策略必须能认出来），返回底边 y。"""
    h = 16
    x1 = x0 + colw * ncol
    for r in range(nrow + 1):
        page.draw_line((x0, y0 + r * h), (x1, y0 + r * h), color=(0, 0, 0), width=0.6)
    for c in range(ncol + 1):
        page.draw_line((x0 + c * colw, y0), (x0 + c * colw, y0 + nrow * h),
                       color=(0, 0, 0), width=0.6)
    header = ["station", "ceiling", "rvr", "score"]
    for c in range(ncol):
        page.insert_text((x0 + c * colw + 3, y0 + 12), header[c % len(header)],
                         fontname="hebo", fontsize=7)
    for r in range(1, nrow):
        for c in range(ncol):
            val = f"{r * 10 + c}" if c else f"58{100 + r}"
            page.insert_text((x0 + c * colw + 3, y0 + r * h + 12), val,
                             fontname="helv", fontsize=7)
    return y0 + nrow * h


def single_column(path: Path, pages: int = 3) -> None:
    doc = pymupdf.open()
    for pno in range(pages):
        page = doc.new_page(width=PAGE_W, height=PAGE_H)
        y = 70
        if pno == 0:
            y = _head(page, 60, y, "Single Column Structure Benchmark", 17) + 4
            _put(page, 60, y, "A. Author, B. Author", 10)
            y += 14
            _put(page, 60, y, "Institute of Synthetic Layouts, Testville", 9)
            y += 16
            _put(page, 60, y, "Abstract.", 9, bold=True)
            y += 12
            y = _write_column(page, pymupdf.Rect(60, y, PAGE_W - 60, y + 80),
                              [(para(0, 2), 9, False)]) + 6
            y = _head(page, 60, y, "1 Introduction", 12)
        else:
            y = _head(page, 60, y, f"{pno + 1} Method", 12)
        for i in range(3):
            y = _write_column(page, pymupdf.Rect(60, y, PAGE_W - 60, PAGE_H - 80),
                              [(para(pno * 3 + i), 9, False)])
        if pno == 1:
            _put(page, 60, y + 8, "Table 1. Synthetic station table with borders.", 8)
            _table(page, 60, y + 14)
    doc.save(path)
    doc.close()


def two_column(path: Path, pages: int = 3) -> None:
    doc = pymupdf.open()
    for pno in range(pages):
        page = doc.new_page(width=PAGE_W, height=PAGE_H)
        top = 60
        if pno == 0:
            top = _head(page, 50, top, "A Two Column Paper About Visibility Nowcasting", 16) + 2
            _put(page, 50, top, "C. Writer, D. Writer", 10)
            top += 18
            top = _write_column(page, pymupdf.Rect(50, top, PAGE_W - 50, top + 70),
                                [("Abstract. " + para(0, 2), 8.5, False)])
            top = _head(page, 50, top + 2, "1 Introduction", 11)
        else:
            top = _head(page, 50, top, f"{pno + 1} Results", 11)
        gutter = 12
        mid = (PAGE_W - 100) // 2 + 50
        left = pymupdf.Rect(50, top, mid - gutter / 2, PAGE_H - 60)
        right = pymupdf.Rect(mid + gutter / 2, top, PAGE_W - 50, PAGE_H - 60)
        _write_column(page, left, [(para(pno * 2 + i), 8.5, False) for i in range(4)])
        _write_column(page, right, [(para(pno * 2 + i + 1), 8.5, False) for i in range(4)])
    doc.save(path)
    doc.close()


def three_column(path: Path, pages: int = 2) -> None:
    doc = pymupdf.open()
    for pno in range(pages):
        page = doc.new_page(width=PAGE_W, height=PAGE_H)
        top = _head(page, 40, 60, f"{pno + 1} Three Column Section", 11)
        w = (PAGE_W - 80 - 24) / 3
        for c in range(3):
            x0 = 40 + c * (w + 12)
            _write_column(page, pymupdf.Rect(x0, top, x0 + w, PAGE_H - 60),
                          [(para(pno * 3 + c + i), 8, False) for i in range(3)])
    doc.save(path)
    doc.close()


def scanned(path: Path, pages: int = 2) -> None:
    """无文字层：先把文字渲染成位图，再整页贴图。文本层为空、图片数 > 0 → 路由 OCR。"""
    src = pymupdf.open()
    for pno in range(pages):
        page = src.new_page(width=PAGE_W, height=PAGE_H)
        _write_column(page, pymupdf.Rect(50, 60, PAGE_W - 50, PAGE_H - 60),
                      [(para(pno + i, 2), 10, False) for i in range(3)])
    out = pymupdf.open()
    for pno in range(pages):
        pix = src[pno].get_pixmap(dpi=120)
        page = out.new_page(width=PAGE_W, height=PAGE_H)
        page.insert_image(page.rect, pixmap=pix)
    out.save(path)
    out.close()
    src.close()


def encrypted(path: Path) -> None:
    doc = pymupdf.open()
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    _write_column(page, pymupdf.Rect(50, 60, PAGE_W - 50, 400), [(para(0, 2), 10, False)])
    doc.save(path, encryption=pymupdf.PDF_ENCRYPT_AES_256,
             user_pw="secret", owner_pw="secret", permissions=0)
    doc.close()


def long_doc(path: Path, pages: int = 60) -> None:
    doc = pymupdf.open()
    for pno in range(pages):
        page = doc.new_page(width=PAGE_W, height=PAGE_H)
        top = 60
        if pno == 0:
            top = _head(page, 50, top, "A Long Document For Runtime Budget Testing", 15)
            top = _head(page, 50, top, "1 Introduction", 11)
        elif pno % 5 == 0:
            top = _head(page, 50, top, f"{(pno // 5) + 2} Discussion", 11)
        mid = (PAGE_W - 100) // 2 + 50
        _write_column(page, pymupdf.Rect(50, top, mid - 6, PAGE_H - 60),
                      [(para(pno + i), 8.5, False) for i in range(3)])
        _write_column(page, pymupdf.Rect(mid + 6, top, PAGE_W - 50, PAGE_H - 60),
                      [(para(pno + i + 1), 8.5, False) for i in range(3)])
    doc.save(path)
    doc.close()


def cjk_single(path: Path) -> None:
    """中文单栏：验证全角空格、全角标点、中文标题不会被当成乱码。"""
    doc = pymupdf.open()
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    y = 70
    page.insert_text((55, y), "北部湾海雾预报的统计降尺度方法", fontname="china-s", fontsize=16)
    y += 30
    page.insert_text((55, y), "张三　李四", fontname="china-s", fontsize=10)
    y += 24
    page.insert_text((55, y), "摘要：本文利用２０１１—２０１７年的观测资料", fontname="china-s", fontsize=9)
    y += 30
    page.insert_text((55, y), "1　引言", fontname="china-s", fontsize=12)
    y += 8
    for i, line in enumerate([
        "海雾是暖湿空气流经冷下垫面时形成的低能见度天气现象，对我",
        "国沿海地区的交通运输和渔业生产影响显著。由于雾滴尺度小、",
        "生消速度快，数值模式对海雾的预报能力长期不足，因此统计后",
        "处理仍是业务中提高预报准确率的主要手段之一。",
    ]):
        page.insert_text((55, y + 18 + i * 15), line, fontname="china-s", fontsize=9)
    doc.save(path)
    doc.close()


BUILDERS = {
    "single_column": single_column,
    "two_column": two_column,
    "three_column": three_column,
    "scanned": scanned,
    "encrypted": encrypted,
    "long_doc": long_doc,
    "cjk_single": cjk_single,
}


def main() -> int:
    ap = argparse.ArgumentParser(description="生成自测用合成 PDF")
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", default=None, help="只生成指定 case（逗号分隔）")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    wanted = args.only.split(",") if args.only else list(BUILDERS)
    made = []
    for name in wanted:
        fn = BUILDERS[name.strip()]
        p = out / f"{name}.pdf"
        fn(p)
        made.append({"case": name, "file": str(p), "bytes": p.stat().st_size})
    print(json.dumps(made, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
