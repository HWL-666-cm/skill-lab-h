#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render.py —— 内部字段 → 目标规范渲染（解析 ≠ 转换，这是转换一侧）。

把 citation_audit 整理后的文献条目渲染成 GB/T 7714—2015 或 APA(第7版) 的
文末列表行。支持的文献类型标识：

  [J] 期刊  [M] 专著  [C] 会议/论文集  [EB/OL] 电子资源

规则（保守实现，不做目标期刊细则里的作者缩写/文种分组等人工项）：
  - 作者 3 人以上：GB/T 用「等」/「et al.」（按文种），APA 用「et al.」；
  - GB/T 期刊格式：作者. 题名[J]. 刊名, 年, 卷(期): 页码.
  - 缺字段不臆造：缺卷期页就省略对应段，并在 rendered 旁给 completeness。

用法：
  python3 render.py --bib references.json --style gbt7714 --out refs.txt
  python3 render.py --bib references.json --style apa --out refs.txt
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from citation_audit import load_bib  # noqa: E402


def _authors(entry) -> list[str]:
    a = entry.get("authors") or entry.get("author") or []
    if isinstance(a, str):
        a = [x.strip() for x in a.replace(";", ",").split(",") if x.strip()]
    return [str(x) for x in a] if isinstance(a, list) else []


def _is_chinese(s: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in (s or ""))


def _gbt_authors(entry, n_max=3) -> str:
    a = _authors(entry)
    if not a:
        return ""
    if len(a) <= n_max:
        return ", ".join(a)
    zh = _is_chinese(entry.get("title") or entry.get("journal") or "")
    tail = "等" if zh else "et al"   # 不加句点，render 统一在作者后补 ". "
    return ", ".join(a[:n_max]) + ", " + tail


def _apa_authors(entry) -> str:
    a = _authors(entry)
    if not a:
        return ""
    def fmt(x):
        parts = x.split()
        if len(parts) == 1:
            return x
        surname = parts[0]
        initials = "".join(p[0].upper() + "." for p in parts[1:] if p)
        return f"{surname}, {initials}"
    if len(a) == 1:
        return fmt(a[0])
    if len(a) <= 20:
        return ", ".join(fmt(x) for x in a[:-1]) + ", & " + fmt(a[-1])
    return ", ".join(fmt(x) for x in a[:19]) + ", ... " + fmt(a[-1])


def _type_code(entry) -> str:
    t = str(entry.get("type") or entry.get("entry_type") or "").upper()
    if t in ("J", "JOURNAL", "ARTICLE", "期刊"):
        return "J"
    if t in ("M", "BOOK", "专著"):
        return "M"
    if t in ("C", "CONFERENCE", "PROCEEDINGS", "会议"):
        return "C"
    if t in ("EB/OL", "ONLINE", "网页", "电子"):
        return "EB/OL"
    # 推断：有 journal 字段 → J；有 publisher 无 journal → M
    if entry.get("journal") or entry.get("container_title") or entry.get("volume"):
        return "J"
    if entry.get("publisher") and not entry.get("journal"):
        return "M"
    return "J"


def _doi(entry) -> str:
    d = str(entry.get("doi") or "").strip()
    if not d:
        return ""
    if d.startswith("http"):
        return d
    return "https://doi.org/" + d


def render_gbt(entry) -> str:
    code = _type_code(entry)
    a = _gbt_authors(entry)
    title = str(entry.get("title") or "").strip()
    year = str(entry.get("year") or entry.get("date") or "").strip()
    journal = str(entry.get("journal") or entry.get("container_title") or "").strip()
    volume = str(entry.get("volume") or "").strip()
    issue = str(entry.get("issue") or entry.get("number") or "").strip()
    pages = str(entry.get("pages") or entry.get("page") or "").strip()

    if code == "J":
        volissue = volume
        if issue:
            volissue = f"{volume}({issue})" if volume else f"({issue})"
        core = journal
        if year:
            core = f"{core}, {year}"
        if volissue:
            core = f"{core}, {volissue}"
        if pages:
            core = f"{core}: {pages}"
        return f"{a}. {title}[J]. {core}." if a else f"{title}[J]. {core}."
    if code == "M":
        publisher = str(entry.get("publisher") or "").strip()
        return f"{a}. {title}[M]. {publisher}, {year}." if (a and publisher and year) else f"{title}[M]."
    if code == "C":
        publisher = str(entry.get("publisher") or entry.get("booktitle") or "").strip()
        return f"{a}. {title}[C]. {publisher}, {year}." if a else f"{title}[C]."
    if code == "EB/OL":
        d = _doi(entry)
        acc = str(entry.get("access_date") or "").strip()
        return f"{a}. {title}[EB/OL]. {d}" + (f" ({acc})" if acc else "") + "."
    return f"{title}[{code}]."


def render_apa(entry) -> str:
    code = _type_code(entry)
    a = _apa_authors(entry)
    title = str(entry.get("title") or "").strip()
    year = str(entry.get("year") or entry.get("date") or "").strip()
    journal = str(entry.get("journal") or entry.get("container_title") or "").strip()
    volume = str(entry.get("volume") or "").strip()
    issue = str(entry.get("issue") or entry.get("number") or "").strip()
    pages = str(entry.get("pages") or entry.get("page") or "").strip()
    d = _doi(entry)

    def yr():
        return f"({year})." if year else ""

    if code == "J":
        it = journal
        if volume:
            it = f"{journal}, {volume}" if journal else volume
        if issue:
            it = f"{it}({issue})"
        if pages:
            it = f"{it}, {pages}"
        head = f"{a} {yr()} {title}." if a else f"{title} {yr()}"
        tail = f" {it}." if it else ""
        if d:
            tail += f" {d}"
        return head + tail
    if code == "M":
        publisher = str(entry.get("publisher") or "").strip()
        return f"{a} {yr()} {title}. {publisher}." if a else f"{title} {yr()} {publisher}."
    return f"{a} {yr()} {title}." if a else f"{title} {yr()}"


def render_entry(entry, style: str) -> dict:
    text = render_gbt(entry) if style == "gbt7714" else render_apa(entry)
    missing = [k for k in ("title", "year") if not str(entry.get(k) or "").strip()]
    return {
        "key": entry.get("key") or entry.get("id"),
        "type": _type_code(entry),
        "style": style,
        "rendered": text,
        "completeness": "complete" if not missing else "missing_" + "+".join(missing),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="参考文献渲染（GB/T 7714—2015 / APA）")
    ap.add_argument("--bib", required=True)
    ap.add_argument("--style", choices=["gbt7714", "apa"], default="gbt7714")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    bib = load_bib(json.loads(Path(args.bib).read_text(encoding="utf-8")))
    rows = [render_entry(e, args.style) for e in bib]
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        for i, r in enumerate(rows, 1):
            f.write(f"[{i}] {r['rendered']}\n")
    summary = {
        "style": args.style, "entries": len(rows),
        "incomplete": [r["key"] for r in rows if r["completeness"] != "complete"],
        "rendered": args.out,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
