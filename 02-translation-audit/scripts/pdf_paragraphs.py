#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pdf_paragraphs.py — PDF -> 段落级结构化文本（段号 + 物理页码 + 章节 + 跨页续段）

为什么这么做（设计依据，来自对 ASCMO 双栏 PDF 的实测）：
1) 预提取的 .txt 已丢段落边界（双栏每行仅 50–64 字符），靠行宽猜段落会错；
   PDF 的 block 本身就是段落，且带 x0/y0 坐标 —— 用它才有真实物理依据。
2) 双栏论文：左栏 x0≈46、右栏 x0≈307。按 x0 分栏、栏内按 y0 排序，
   才得到正确阅读顺序；直接按整个页面 y0 排会把左右栏交错。
3) 页眉页脚位置固定且混着页码，会污染段落与术语统计。这里不写死 y 阈值，
   改用"跨页重复出现的短行"识别，换版式也能自适应。
4) 跨页断段真实存在：上一页末块是半句、下一页首块不是接续（中间插了表）。
   用"句子未完结 + 下一块不像段首"判断续接，避免漏段/错位。

输出 JSON：{source, page_count, paragraphs:[{pid, page, section, kind, text, continued_from}], issues}
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import pymupdf  # PyMuPDF
except ImportError:  # pragma: no cover
    print(json.dumps({"error": "PyMuPDF (pymupdf) not installed"}), file=sys.stderr)
    raise SystemExit(2)

CAPTION = re.compile(r"^\s*(Table|Figure|Fig\.?)\s*\d", re.I)
NUM_HEADING = re.compile(r"^\s*(\d+(?:\.\d+)*)\s+(\S.{0,70})$")
# 句末标点（英文句号需后跟空白或结尾，避免 PM2.5 / et al. 误判）
SENT_END = re.compile(r"[.!?。！？][\"'”’)\]]?\s*$")

# 首页元数据 / 出版社声明 / 通讯地址：不是正文，不参与翻译与术语统计
META = re.compile(
    r"^(Adv\.|www\.|https?://|doi:|©|Creative Commons|Published by |"
    r"Received:|Revised:|Accepted:|Published:|Correspondence:|"
    r"^\d?[A-Z]?Department of |^\d?Institute of |E-?mail:|"
    r"Open Access|This work is distributed|"
    r"Citation:|Editor:|Review status:|"
    r"OPEN$|scientificreports|"
    r"[A-Z][a-z]+ [A-Z][a-z]+ \d+(?:,\d+)*(?:\*)?(?:,|$))",
    re.I,
)
# 作者行：多个"名 [中间名.] 姓 + 上标数字"，用逗号连接（支持 Sebastian J. Dietz1 这类）
AUTHOR_LINE = re.compile(r"^[A-Z][a-z]+(?: [A-Z]\.)?(?: [A-Z][a-z\-]+)+ \d[\d,*\s]*(?:,|$)")
# 数学/公式特征符：出现即大概率是公式块或其碎片
FORMULA_CHAR = re.compile(r"[∂∑∏∫≤≥≠≈±×÷ˆθαβγδμσΣϵℓ√∞∈∀∃∼−·±]")
# 参考文献章节标题：允许标题与第一条文献同块（如 "References 1. Koschmieder, H. ..."）
REF_HEADING = re.compile(r"^\s*(\d+(?:\.\d+)*\s+)?(References|Bibliography|参考文献)\b", re.I)
# 表格行：短、含常见表头词或无标点，且被 caption 包围
TABLE_HINT = re.compile(r"^(lvp state|variable|unit|description|occurrence|capacity|ceiling|threshold)", re.I)


def squash(text: str) -> str:
    """block 内保留了 PDF 的硬换行，压成单行；保留断词连字符合并。"""
    t = text.replace("\r", "")
    # "pre- diction" -> "prediction"：连字符后跟空格再跟小写字母
    t = re.sub(r"([A-Za-z])-\s+([a-z])", r"\1\2", t)
    # PDF 里常见的不间断空格(NBSP \xa0)、hair space(\u200a)、全角空格(\u3000)，
    # 不归一的话正则会失配（实测作者行因此没被识别成 meta）
    t = re.sub(r"[\u00a0\u2000-\u200b\u202f\u205f\u3000]", " ", t)
    t = re.sub(r"[ \t]*\n[ \t]*", " ", t)
    t = re.sub(r"\s{2,}", " ", t)
    return t.strip()


def _norm_key(t: str) -> str:
    """用于识别跨页重复的页眉页脚：去数字、去空白、转小写。"""
    return re.sub(r"\d+", "#", re.sub(r"\s+", " ", t)).strip().lower()


def detect_running_headers(pages_blocks: list[list[dict]]) -> set[str]:
    """跨页重复出现的短行 = 页眉/页脚（含页码，因为数字已被 # 归一）。"""
    from collections import Counter

    cnt: Counter[str] = Counter()
    for blocks in pages_blocks:
        seen_this_page = set()
        for b in blocks:
            if len(b["text"]) <= 120:
                k = _norm_key(b["text"])
                if k and k not in seen_this_page:
                    seen_this_page.add(k)
                    cnt[k] += 1
    n_pages = max(1, len(pages_blocks))
    # 出现在 ≥ 一半页面上、且短的，判为页眉页脚
    return {k for k, c in cnt.items() if n_pages >= 3 and c >= max(2, int(n_pages * 0.5))}


def extract(pdf_path: Path) -> dict:
    doc = pymupdf.open(str(pdf_path))
    pages_blocks: list[list[dict]] = []
    for pno in range(doc.page_count):
        page = doc[pno]
        blocks = []
        for b in page.get_text("blocks"):
            x0, y0, x1, y1, txt, bno, btype = b
            if btype != 0:
                continue
            t = squash(txt)
            if not t:
                continue
            blocks.append({"x0": round(x0), "y0": round(y0), "w": round(x1 - x0), "h": round(y1 - y0), "text": t})
        pages_blocks.append(blocks)

    running = detect_running_headers(pages_blocks)

    paragraphs: list[dict] = []
    issues: list[dict] = []
    section = ""
    pid = 0
    prev_para_text = ""      # 上一个"正文段"（跳过 meta/formula/fragment/caption）
    prev_para_pid = 0
    body_started = False     # 是否已进入正文（Abstract / 1 Introduction 之后）
    in_refs = False          # 是否已进入参考文献区（其条目不是待译正文）

    for pno, blocks in enumerate(pages_blocks, 1):
        # 先剔页眉页脚
        kept = []
        for b in blocks:
            if _norm_key(b["text"]) in running:
                continue
            kept.append(b)
        if not kept:
            continue

        # 分栏判定
        xs = sorted({b["x0"] for b in kept})
        mid = (min(xs) + max(xs)) / 2
        left = [b for b in kept if b["x0"] < mid]
        right = [b for b in kept if b["x0"] >= mid]
        two_col = len(left) >= 2 and len(right) >= 2 and (max(xs) - min(xs)) > 150

        if two_col:
            order = sorted(left, key=lambda b: b["y0"]) + sorted(right, key=lambda b: b["y0"])
        else:
            order = sorted(kept, key=lambda b: b["y0"])

        for b in order:
            t = b["text"]
            kind = "para"
            m = NUM_HEADING.match(t)
            if CAPTION.match(t):
                kind = "caption"
            elif META.match(t) or AUTHOR_LINE.match(t):
                kind = "meta"
            elif FORMULA_CHAR.search(t) and len(t) < 200:
                kind = "formula"
            elif m and len(t) <= 75:
                kind = "heading"
                section = re.sub(r"\s+", " ", t).strip()
            elif len(t) < 40 and not SENT_END.search(t) and not re.search(r"[a-z]{4,}\s+[a-z]{4,}", t):
                # 极短且无完整短语的块：多为表格行/版式碎片，单独标记，避免污染段落对齐
                kind = "fragment"

            # 参考文献区：一旦进入，后续段落标 reference（不翻译、不参与续段/术语统计）
            if REF_HEADING.match(t):
                in_refs = True
                section = t.strip()[:40]
                # 标题与首条文献同块时，整块按文献处理；否则是纯标题
                kind = "heading" if len(t.strip()) <= 20 else "reference"
            elif in_refs and kind == "para":
                kind = "reference"

            pid += 1
            continued_from = None
            # 续段检测：只对"正文段"做，比较对象是上一个正文段（跳过被页脚/公式/碎片打断的块）。
            # 判据：上一正文段句子未完结，且本段以小写字母开头（真正的段首一般大写）。
            if (
                kind == "para"
                and prev_para_text
                and not SENT_END.search(prev_para_text)
                and t
                and t[0].islower()
            ):
                continued_from = prev_para_pid
                issues.append({
                    "pid": pid,
                    "type": "paragraph_continuation",
                    "detail": f"本段疑似紧接上一正文段（pid {prev_para_pid}）的续接，已标记 continued_from，便于人工确认是否应合并。",
                })

            paragraphs.append({
                "pid": pid,
                "page": pno,
                "section": section,
                "kind": kind,
                "text": t,
                "continued_from": continued_from,
            })
            if kind == "para":
                prev_para_text = t
                prev_para_pid = pid

    # 低文本页提示（可能扫描页）
    for pno, blocks in enumerate(pages_blocks, 1):
        chars = sum(len(b["text"]) for b in blocks)
        if chars < 120:
            issues.append({"page": pno, "type": "low_text_page",
                           "detail": "本页可提取字符很少，可能是图片页/扫描页，需 OCR 或人工核对。"})

    doc.close()
    return {
        "source": str(pdf_path),
        "page_count": len(pages_blocks),
        "extraction": "pymupdf-block",
        "running_headers_removed": len(running),
        "paragraphs": paragraphs,
        "issues": issues,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    data = extract(Path(args.pdf))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    kinds = {}
    for p in data["paragraphs"]:
        kinds[p["kind"]] = kinds.get(p["kind"], 0) + 1
    print(json.dumps({
        "out": args.out,
        "pages": data["page_count"],
        "paragraphs": len(data["paragraphs"]),
        "kinds": kinds,
        "running_headers_removed": data["running_headers_removed"],
        "issues": len(data["issues"]),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
