#!/usr/bin/env python3
"""锚点核验：检查结构化笔记里每条 claim 的 anchor 是否真指向原文。

这是本 Skill 的核心创新点。基础 Agent 常犯的错：
  - 写 "见第 3 页" 但那页根本没有这句话（锚点漂移）；
  - 写 "TS=0.40" 但原文是 0.46（数值错配）；
  - 给笼统出处 "Methods"（粒度不足，无法复核）。
本脚本把每个 claim 的 (page/quote/numbers) 拿回原文逐字比对，输出可机器判定的 verdict。

不认领域知识，只认"锚点指回去能不能找到"——换任何论文都成立。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

# 与 pdf_extract 一致的规范化（全角->半角、去空白）
def norm(s: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s or ""))


NUM_RE = re.compile(r"\d+(?:\.\d+)?%?")


def numbers(s: str):
    # 先 NFKC：原文的 ０.３０ 与笔记的 0.30 必须视为同一个数
    return [n for n in NUM_RE.findall(unicodedata.normalize("NFKC", s or ""))]


def get_page_text(pages: list, page_no: int) -> str:
    for p in pages:
        if p.get("page") == page_no:
            return p.get("text", "")
    return ""


def nearby_text(pages: list, page_no: int, radius: int = 1) -> str:
    """容错：整篇页码定位可能因 PDF 页码偏移，允许 ±radius 页。"""
    out = []
    for p in pages:
        if abs(p.get("page", 0) - page_no) <= radius:
            out.append(p.get("text", ""))
    return "\n".join(out)


def audit_claim(claim: dict, pages: list, sections: list, page_map: dict) -> dict:
    cid = claim.get("id", "?")
    anchor = claim.get("anchor") or {}
    page = anchor.get("page")
    section = anchor.get("section", "")
    quote = anchor.get("quote", "")
    value = claim.get("value", "")
    flags = []

    # 页码解析：page_map 把印刷页码映射到 PDF 页序，必须贯穿所有核验步骤。
    if not isinstance(page, int) or page < 1:
        flags.append("missing_page")
        actual = None
        page_text = ""
    else:
        actual = page_map.get(str(page), page)
        page_text = get_page_text(pages, actual)
        if not page_text:
            page_text = nearby_text(pages, actual)
            if page_text:
                flags.append("page_shifted")
        if not page_text:
            flags.append("page_not_found")

    npage = norm(page_text)

    # 2. 锚点粒度：只有笼统章节、没有页码或 quote
    if not quote and not value:
        flags.append("anchor_too_vague")

    # 3. quote 是否真在（该页或相邻页）原文中。允许 NFKC+去空白后子串匹配。
    target = actual if actual is not None else (page if isinstance(page, int) else 0)
    if quote:
        q = norm(quote)
        if q and q not in npage:
            # 再试相邻页
            if q not in norm(nearby_text(pages, target)):
                flags.append("quote_not_found")

    # 4. 数值核验：claim.value 里的数字必须能在该页找到（±1 页容错）。
    #    无页码时退化为全篇扫描：数字连全篇都找不到，基本就是编造的。
    vn = numbers(value)
    if vn:
        if "missing_page" in flags:
            hay = norm("\n".join(p.get("text", "") for p in pages))
            scope = "numbers_not_in_document"
        else:
            hay = norm(nearby_text(pages, target))
            scope = "numbers_not_on_page"
        missing = [n for n in vn if n not in hay]
        if missing:
            flags.append(scope + ":" + ",".join(missing))

    # 5. section 名称是否出现在该页附近文本（不强求，给 warning）
    warn = []
    if section:
        sec_norm = norm(section)
        if sec_norm and sec_norm not in npage:
            sec_pages = [s["page"] for s in sections if section in s.get("heading", "")]
            if not sec_pages:
                warn.append("section_not_in_toc")
            elif abs(sec_pages[0] - target) > 1:
                warn.append("section_page_mismatch")

    if not flags:
        verdict = "ok"
    elif "page_not_found" in flags or "quote_not_found" in flags or any(
        f.startswith("numbers_not_on_page") or f.startswith("numbers_not_in_document") for f in flags):
        verdict = "mismatch"
    else:
        verdict = "weak"

    return {
        "id": cid,
        "verdict": verdict,
        "flags": flags,
        "warnings": warn,
        "checked": {
            "page": page,
            "quote_len": len(quote or ""),
            "value_numbers": numbers(value),
        },
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--extracted", required=True, help="pdf_extract.py 的输出 JSON")
    ap.add_argument("--notes", required=True, help="结构化笔记 JSON（含 claims 数组）")
    ap.add_argument("--out", required=True, help="核验报告 JSON")
    args = ap.parse_args(argv)

    ex = json.loads(Path(args.extracted).read_text(encoding="utf-8"))
    notes = json.loads(Path(args.notes).read_text(encoding="utf-8"))
    pages = ex.get("pages", [])
    sections = ex.get("sections", [])
    page_map = notes.get("page_map", {}) or {}
    claims = notes.get("claims", [])

    results = [audit_claim(c, pages, sections, page_map) for c in claims]
    counts = {v: sum(1 for r in results if r["verdict"] == v) for v in ("ok", "weak", "mismatch")}
    overall = "ok" if counts["mismatch"] == 0 and counts["weak"] == 0 else (
        "partial" if counts["mismatch"] == 0 else "failed")
    report = {
        "overall": overall,
        "counts": counts,
        "total": len(results),
        "results": results,
        "issue_pages": [i["page"] for i in ex.get("issues", []) if i.get("type") == "garbled_or_formula"],
        "note": "issue_pages 上的 claim 逐字核验不可靠，只允许锚到页，不得写精确 quote。",
    }
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[anchor_audit] {overall} ok={counts['ok']} weak={counts['weak']} "
          f"mismatch={counts['mismatch']} -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
