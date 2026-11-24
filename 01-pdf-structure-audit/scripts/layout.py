#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""layout.py — 版面分区与阅读顺序：把"坐标上的字"排成"人读的顺序"。

为什么这么做：
1) 直接 page.get_text() 是按 PDF 内部写画顺序返回的，双栏论文会左右栏交错。PyMuPDF 官方
   FAQ 也承认 sort=True 对多栏"有帮助但不完美"，建议自己按 block 的 bbox 找栏边界。
2) 所以这里先判"这一页是几栏"，再按栏切。判据不用"页面宽度取中点"——因为摘要、跨栏表格、
   通栏标题会跨过中点，取中点会把它们劈成两半。改用"左栏行的右边缘是否越过右栏的左边缘"
   这一条充分条件：只要 80% 的左栏行都在右栏左边缘之前结束，就说明中间存在真正的栏缝。
3) 通栏元素（标题、摘要、跨栏表）不能当栏内内容排，它是**分区边界**：先把页面按它切成
   若干带，再在每个带内分栏。这样"标题 → 左栏 → 右栏 → 通栏表 → 左栏…"的顺序才正确。
4) 段落不靠"行宽"猜：先用 PDF 自己的 block（block 近似段落），block 内再按行间距与首行缩进
   切分。跨页/跨栏断段只在"上段句未完结 + 下段小写开头"时才算续段，避免把两段拼成一句。
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
from pathlib import Path

import pdfcore
from pdfcore import PdfDoc, bbox_width, norm_text

SENT_END = re.compile(r"[.!?。！？：:][\"'”’)\]）】]?\s*$")
BULLET = re.compile(r"^\s*([（(]?\d+[.、)）]|[•·▪◦\-–—*]|[a-zA-Z][.)])\s+")
# 首行缩进：段首行比栏左边缘再往右缩进 4pt 以上
INDENT_MIN = 4.0
GAP_FACTOR = 1.55


def _content_box(lines: list[dict]) -> tuple[float, float, float, float]:
    if not lines:
        return (0.0, 0.0, 0.0, 0.0)
    return (
        min(l["bbox"][0] for l in lines),
        min(l["bbox"][1] for l in lines),
        max(l["bbox"][2] for l in lines),
        max(l["bbox"][3] for l in lines),
    )


def detect_columns(lines: list[dict], content) -> dict:
    """判栏。返回 {"mode": "1col"/"2col"/"3col", "splits": [x...], "gutter": [...]}。

    只用"窄行"当样本：通栏的标题、摘要、跨栏表会跨过栏缝，如果把它们算进聚类，就会得出
    "左栏的行越过了右栏左边缘"从而误判成单栏（Dietz 第 1 页就是这样：摘要通栏，
    下面的正文其实是两栏，整页判成 1 栏后正文被逐行左右交错读出）。
    """
    if len(lines) < 6:
        return {"mode": "1col", "splits": [], "gutter": []}
    cw = max(1.0, content[2] - content[0])
    # 只用"像正文的行"当样本：表格单元格短（"lvp"、"(m)"），它们的右边缘落在栏缝里，
    # 会把栏缝估算带偏（Dietz 第 4 页因此把栏缝算到 x=245，比真实的 297 差了 50pt）。
    narrow = [l for l in lines if bbox_width(l["bbox"]) < 0.62 * cw and len(l["text"]) >= 25]
    if len(narrow) < 8:
        return {"mode": "1col", "splits": [], "gutter": []}

    x0s = sorted(l["bbox"][0] for l in narrow)
    # 聚类 x0
    clusters: list[list[float]] = []
    for x in x0s:
        if clusters and x - clusters[-1][-1] <= 18.0:
            clusters[-1].append(x)
        else:
            clusters.append([x])
    min_count = max(3, int(len(narrow) * 0.12))
    starts = [c[0] for c in clusters if len(c) >= min_count]
    # 合并过近的起点（同一栏的左边缘常有 1-2pt 抖动）
    merged: list[float] = []
    for s in starts:
        if merged and s - merged[-1] < 0.28 * cw:
            continue
        merged.append(s)
    if len(merged) < 2:
        return {"mode": "1col", "splits": [], "gutter": []}

    # 逐对验证：左栏（含之前所有更左的栏）的行右边缘是否越过右栏左边缘
    splits, gutters = [], []
    for i in range(len(merged) - 1):
        right_start = merged[i + 1]
        left_lines = [l for l in narrow if l["bbox"][0] < right_start - 2]
        if len(left_lines) < 4:
            return {"mode": "1col", "splits": [], "gutter": []}
        crossing = [l for l in left_lines if l["bbox"][2] > right_start + 3]
        # 容忍到 45%：通栏表格/摘要会让"左栏行越过栏缝"的计数虚高（Dietz 第 4 页有整幅
        # 通栏表，硬卡 20% 会把整页判成单栏，正文随即被逐行左右交错读出）。单栏页的
        # 正文行几乎全部跨过"伪栏缝"，比例通常在 70% 以上，仍然会被判回单栏。
        if len(crossing) / len(left_lines) > 0.45:
            return {"mode": "1col", "splits": [], "gutter": []}
        # 栏缝宽度只用**紧邻左栏**的行算，不能用"所有更左的行"：三栏页算第二道栏缝时，
        # 若把第一栏的行也算进中位数，中位数会被第一栏较短的右边缘拉低，栏缝落到第二栏
        # 中间（合成用例 three_column 实测：真栏缝应是 379→392，被算成 317.8→392.9），
        # 于是第二栏的行被当成"通栏行"各自成带，三栏文字交错读成一团。
        adjacent = [l for l in narrow if merged[i] - 2 <= l["bbox"][0] < right_start - 2]
        edge_src = adjacent if len(adjacent) >= 4 else left_lines
        left_edges = sorted(l["bbox"][2] for l in edge_src)
        left_med = left_edges[len(left_edges) // 2]
        if right_start - left_med < 6.0:
            return {"mode": "1col", "splits": [], "gutter": []}
        splits.append((left_med + right_start) / 2)
        gutters.append((round(left_med, 1), round(right_start, 1)))

    if len(splits) >= 2:
        mode = "3col"
    else:
        mode = "2col"
    return {"mode": mode, "splits": splits, "gutter": gutters}


def _col_of(x0: float, splits: list[float]) -> int:
    c = 0
    for s in splits:
        if x0 > s:
            c += 1
    return c


def order_page(model: dict, cols: dict) -> list[dict]:
    """给每行编阅读顺序：带(zone, 通栏段) → 栏 → 纵坐标。

    通栏行（跨过栏缝的行，如标题/摘要/跨栏表）单独成带，上下内容分属不同带。
    这样"标题在左栏之上、摘要通栏、正文两栏"的顺序才对。
    """
    lines = model["lines"]
    splits = cols["splits"]
    ordered: list[dict] = []
    if not splits:
        seq = sorted(lines, key=lambda l: (round(l["bbox"][1], 1), l["bbox"][0]))
        for i, l in enumerate(seq):
            ordered.append({"line": l["id"], "zone": 0, "col": 0, "order": i})
        return ordered

    def crosses(l):
        return any(l["bbox"][0] < s < l["bbox"][2] - 2 for s in splits)

    # 按纵向扫描，遇到通栏行就把它前后切成不同带
    seq = sorted(lines, key=lambda l: (round(l["bbox"][1], 1), l["bbox"][0]))
    bands: list[dict] = []
    cur = {"spanning": None, "lines": []}
    for l in seq:
        if crosses(l):
            if cur["lines"]:
                bands.append(cur)
            bands.append({"spanning": l["id"], "lines": [l]})
            cur = {"spanning": None, "lines": []}
        else:
            cur["lines"].append(l)
    if cur["lines"]:
        bands.append(cur)

    order = 0
    for zi, band in enumerate(bands):
        if band["spanning"]:
            ordered.append({"line": band["spanning"], "zone": zi, "col": 0, "order": order})
            order += 1
            continue
        by_col: dict[int, list[dict]] = {}
        for l in band["lines"]:
            by_col.setdefault(_col_of(l["bbox"][0], splits), []).append(l)
        for c in sorted(by_col):
            for l in sorted(by_col[c], key=lambda x: (round(x["bbox"][1], 1), x["bbox"][0])):
                ordered.append({"line": l["id"], "zone": zi, "col": c, "order": order})
                order += 1
    return ordered


def _median_gap(lines: list[dict]) -> float:
    gaps = []
    for a, b in zip(lines, lines[1:]):
        g = b["bbox"][1] - a["bbox"][3]
        if g >= 0:
            gaps.append(g)
    return statistics.median(gaps) if gaps else 0.0


def build_paragraphs(model: dict, order: list[dict]) -> list[dict]:
    """把有序行合成段落：block 相同 + 间距正常 + 无缩进断点 → 同一段。"""
    by_id = {l["id"]: l for l in model["lines"]}
    paras: list[dict] = []
    cur: dict | None = None
    prev: dict | None = None

    for item in order:
        l = by_id[item["line"]]
        gap = None
        if prev is not None and prev["zone"] == item["zone"] and prev["col"] == item["col"]:
            gap = l["bbox"][1] - prev["bbox"][3]
        med_gap = prev["_med_gap"] if prev else 0.0
        line_h = l["bbox"][3] - l["bbox"][1]

        new_para = False
        if cur is None:
            new_para = True
        else:
            if l["block"] != cur["block"] and cur["col"] == item["col"] and cur["zone"] == item["zone"]:
                new_para = True
            if prev is not None and gap is not None:
                if gap > max(med_gap * GAP_FACTOR, line_h * 0.55):
                    new_para = True
            if prev is not None and prev["size"] != l["size"]:
                new_para = True
            if prev is not None and prev["col"] != item["col"]:
                new_para = True
            if prev is not None and BULLET.match(l["text"]) and SENT_END.search(prev["text"] or ""):
                new_para = True

        if new_para:
            cur = {
                "id": f"p{model['no']}para{len(paras)}",
                "page": model["no"],
                "zone": item["zone"], "col": item["col"],
                "block": l["block"],
                "bbox": list(l["bbox"]),
                "lines": [l["id"]],
                "text": l["text"],
                "text_raw": l["text_raw"],
                "size": l["size"], "bold": l["bold"], "math": l["math"],
                "order": item["order"],
                "_med_gap": 0.0,
            }
            paras.append(cur)
        else:
            cur["lines"].append(l["id"])
            cur["text"] = pdfcore.dehyphenate(cur["text"], l["text"])
            cur["text_raw"] = cur["text_raw"] + "\n" + l["text_raw"]
            cur["bbox"][2] = max(cur["bbox"][2], l["bbox"][2])
            cur["bbox"][3] = max(cur["bbox"][3], l["bbox"][3])
            cur["bold"] = cur["bold"] or l["bold"]
            cur["math"] = cur["math"] or l["math"]
        cur["_med_gap"] = med_gap or (l["bbox"][3] - l["bbox"][1]) * 0.35
        prev = dict(l)
        prev["zone"] = item["zone"]
        prev["col"] = item["col"]
        prev["_med_gap"] = cur["_med_gap"]

    # 清理内部字段并补宽度
    for p in paras:
        p.pop("_med_gap", None)
        p["width"] = round(p["bbox"][2] - p["bbox"][0], 1)
        p["height"] = round(p["bbox"][3] - p["bbox"][1], 1)
    return paras


def analyze(pdf_path: str | Path, keep_models: bool = False) -> dict:
    pdf = PdfDoc(pdf_path)
    if not pdf.opened:
        return {
            "source": str(pdf_path), "page_count": pdf.doc.page_count,
            "status": "blocked", "reason": "PDF 需要密码，空密码也无法打开",
            "pages": [], "issues": [{"type": "encrypted", "detail": "等待人工提供密码"}],
        }
    triage = pdfcore.triage_document(pdf)
    pages, models = [], []
    for pno in range(pdf.doc.page_count):
        model = pdf.page_lines(pno)
        if keep_models:
            models.append(model)
        if triage["pages"][pno]["route"] == "ocr":
            # 路由到 OCR 的页不做几何排版：没有文字层时任何坐标推断都是编造。
            pages.append({
                "no": model["no"], "width": model["width"], "height": model["height"],
                "rotation": model["rotation"], "layout": {"mode": "unknown", "splits": []},
                "paras": [], "route": "ocr",
            })
            continue
        lines = model["lines"]
        content = _content_box(lines)
        cols = detect_columns(lines, content)
        order = order_page(model, cols)
        paras = build_paragraphs(model, order)
        pages.append({
            "no": model["no"], "width": model["width"], "height": model["height"],
            "rotation": model["rotation"],
            "layout": {"mode": cols["mode"], "splits": [round(s, 1) for s in cols["splits"]],
                       "gutter": cols["gutter"], "content": [round(v, 1) for v in content]},
            "paras": paras, "route": triage["pages"][pno]["route"],
            "line_count": len(lines),
        })
    pdf.close()

    # 续段判断不在这里做：此时还不知道哪些段是表头/题注/公式（它们不含句末标点，
    # 会把续段判据全部误触发，Dietz 第 4 页一次就误报 100+ 条）。等 structure.py 定完角色，
    # 只在"正文→正文"之间判续段。
    return {
        "source": str(pdf_path),
        "page_count": triage["page_count"],
        "status": "ok",
        "triage": triage,
        "pages": pages,
        "issues": [],
        "models": models if keep_models else None,
    }


def reading_order_metrics(doc: dict) -> dict:
    """量化"排得对"：统计"回跳"次数。

    为什么不用"横向跳转"：正常换栏时 x 会从右栏跳回左栏，那是**正确**行为，用横向跳转
    计数会把对的也算成错的。真正错误只有一种：已经读到右栏（或更右），却又回到左栏且
    纵向位置更靠上——这是串栏交错的指纹。所以判据取"x 大幅减小 且 y 也上移"。
    """
    back_jumps = total = 0
    for pg in doc["pages"]:
        for a, b in zip(pg["paras"], pg["paras"][1:]):
            total += 1
            dx = b["bbox"][0] - a["bbox"][0]
            dy = b["bbox"][1] - a["bbox"][1]
            if dx < -150 and dy < -20:
                back_jumps += 1
    return {"adjacent_pairs": total, "backward_jumps": back_jumps,
            "backward_ratio": round(back_jumps / total, 4) if total else 0.0}


def main() -> int:
    ap = argparse.ArgumentParser(description="版面分区 + 阅读顺序 + 段落")
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--metrics", action="store_true", help="同时输出串栏跳转指标")
    args = ap.parse_args()
    doc = analyze(args.pdf)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    summary = {
        "out": args.out, "pages": doc["page_count"], "status": doc["status"],
        "layout_modes": {},
        "paras": sum(len(p["paras"]) for p in doc["pages"]),
        "issues": len(doc["issues"]),
    }
    for pg in doc["pages"]:
        m = pg["layout"]["mode"]
        summary["layout_modes"][m] = summary["layout_modes"].get(m, 0) + 1
    if args.metrics:
        summary["order_metrics"] = reading_order_metrics(doc)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
