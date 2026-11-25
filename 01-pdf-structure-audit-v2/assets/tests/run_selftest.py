#!/usr/bin/env python3
"""Self-tests for the PDF front-matter extraction fix.

Run:  python assets/tests/run_selftest.py

These lock the regression the demo result used to exhibit: a two-line title was
split into "title = first line, authors = second line", and the affiliation /
arXiv watermark lines were emitted as level-1 sections.  No PDF is needed; the
synthetic Line objects below mirror the front matter of a typical paper.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import extract_pdf as E  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((name, bool(cond), detail))


def line(text: str, font: float, y0: float, page: int = 1) -> E.Line:
    return E.Line(text=text, page=page, x0=0.2, y0=y0, x1=0.8, y1=y0 + 0.02,
                  font_size=font, spans=[])


def main() -> int:
    # 两行标题（换行是常态）+ 作者行 + 机构行 + arXiv 水印 + 摘要
    lines_by_page = {1: [
        line("Decision Transformer: Reinforcement", 17.0, 0.130),
        line("Learning via Sequence Modeling", 17.0, 0.160),
        line("Lili Chen 1 , Kevin Lu 2 , and Aravind Rajeswaran 1", 12.0, 0.196),
        line("1 UC Berkeley 2 Facebook AI Research 3 Google Brain", 10.0, 0.224),
        line("Abstract", 9.0, 0.299),
        line("arXiv:2106.01345v2 [cs.LG] 24 Jun 2021", 20.0, 0.400),
    ]}
    title, authors, skip = E.extract_front_matter(lines_by_page, 9.0)

    # 标题合并且顺序正确（不能再把第二行当作者）
    check("title_merged",
          title == "Decision Transformer: Reinforcement Learning via Sequence Modeling",
          f"title={title!r}")
    # 作者是作者行，不是标题第二行、也不是摘要首句
    check("authors_correct",
          authors.startswith("Lili Chen") and "Kevin Lu" in authors,
          f"authors={authors!r}")
    # 标题/作者/机构/水印都在跳过集里（标题行 font 17 的两行 + 作者行 + 机构行 + 水印）
    check("title_lines_skipped",
          all((l.page, round(l.y0, 2)) in skip
              for l in lines_by_page[1] if l.font_size >= 16.5),
          f"skip={skip}")
    check("affiliation_skipped",
          (1, round(0.224, 2)) in skip, f"skip={skip}")
    check("arxiv_skipped",
          (1, round(0.400, 2)) in skip, f"skip={skip}")

    # 分类器：机构行/水印不该是 heading，真正的章节该是 heading
    check("affiliation_not_section",
          E.classify_line(line("1 UC Berkeley 2 Facebook AI Research 3 Google Brain", 10.0, 0.1), 9.0) != "heading")
    check("arxiv_not_section",
          E.classify_line(line("arXiv:2106.01345v2 [cs.LG] 24 Jun 2021", 20.0, 0.1), 9.0) != "heading")
    check("abstract_is_section",
          E.classify_line(line("Abstract", 9.0, 0.1), 9.0) == "heading")

    bad = [r for r in results if not r[1]]
    for name, ok, detail in results:
        if not ok:
            print(f"FAIL  {name}  {detail}")
    print(f"{len(results) - len(bad)}/{len(results)} passed")
    return len(bad)


if __name__ == "__main__":
    raise SystemExit(main())
