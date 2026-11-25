#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""claim_recall.py —— 论断句规则召回（「挂得对」的规则侧，占七成，模型只确认）。

不靠模型语感判断"哪句需要引用"，先用规则把候选论断句捞出来：
  1. 含具体数字/百分比/样本量（12%、n=40、14 个站、0.87、p<0.05）；
  2. 含强断言词（显著/表明/证明/优于/发现/揭示/证实/提高/降低 + demonstrate/show/
     indicate/reveal/outperform/significantly）；
  3. 无主断言（研究表明/据报道/已有研究/据文献 + it has been shown/studies show）；
并排除明显不需要引用的句子：图题表题行、章节标题、方法自述（我们采用/本文提出）。

对每个候选句，记录它是否已带引用（句内或紧邻）。输出 JSON 供模型做 top-3 确认，
模型只判「该句是否需要来源 + 引用位置是否恰当」，且结果落字段。

用法：
  python3 claim_recall.py --input manuscript.md --out claims.json
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

# 强断言词（中英）
ASSERT = re.compile(
    r"显著|表明|证明|优于|发现|揭示|证实|提高|降低|下降|上升|减少|增加|"
    r"demonstrate|show|indicat|prove|reveal|outperform|significantly|"
    r"confirm|establish|correlate|associat", re.I)
# 无主断言
NO_SUBJECT = re.compile(
    r"研究表明|据报道|已有研究|据文献|研究表明|前人|此前研究|"
    r"it has been (shown|demonstrated|reported)|studies (have|show)|"
    r"prior work|previous (studies|research)|has been (shown|reported)", re.I)
# 数字/百分比/样本量
NUM = re.compile(
    r"\d+(?:\.\d+)?\s*(?:%|％|个|例|次|人|年|km|mg|μg|mm|mol|℃|°C|倍|p\s*[<>=]|"
    r"n\s*=\s*\d+)|\bn\s*=\s*\d+|\bp\s*[<>=]", re.I)
# 引用标记（正文内）
CITE = re.compile(r"\[\d[\d,\-\s]*\]|\\cite\{[^}]*\}|\([A-Z][A-Za-z]+,?\s*\d{4}\)|\([A-Za-z]+\s*et\s*al\.?,?\s*\d{4}\)")
# 排除：图题/表题/标题/方法自述
EXCLUDE = re.compile(
    r"^\s*(图|表|fig\.?|table)\s*\d|^#{1,6}\s|"
    r"我们采用|我们使用|本文提出|本文采用|本研究采用|"
    r"we (propose|use|employ|present|introduce|design|implement)|"
    r"this (paper|study) (proposes|uses|presents|introduces)", re.I)


def split_sentences(text: str) -> list[dict]:
    """按句边界切分，带起止位置。中文句号/分号/换行 + 英文句点后跟空白。"""
    sents = []
    start = 0
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        boundary = ch in "。！？；;\n" or (
            ch == "." and (i + 1 >= n or text[i + 1].isspace()))
        if boundary:
            s = text[start:i + 1].strip()
            if s:
                sents.append({"text": s, "start": start, "end": i + 1,
                              "line": text[:start].count("\n") + 1})
            start = i + 1
        i += 1
    if start < n and text[start:].strip():
        sents.append({"text": text[start:].strip(), "start": start, "end": n,
                      "line": text[:start].count("\n") + 1})
    return sents


def recall(text: str) -> list[dict]:
    sents = split_sentences(text)
    out = []
    for s in sents:
        t = s["text"]
        if EXCLUDE.search(t):
            continue
        reasons = []
        if NUM.search(t):
            reasons.append("has_number")
        if ASSERT.search(t):
            reasons.append("strong_assertion")
        if NO_SUBJECT.search(t):
            reasons.append("no_subject_assertion")
        if not reasons:
            continue
        cited = bool(CITE.search(t))
        out.append({
            "sentence": t[:240],
            "line": s["line"],
            "reasons": reasons,
            "already_cited": cited,
            "needs_review": not cited,
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="论断句规则召回")
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    text = Path(args.input).read_text(encoding="utf-8")
    claims = recall(text)
    report = {
        "mode": "rule_recall",
        "candidate_claims": claims,
        "counts": {
            "candidates": len(claims),
            "uncited": sum(1 for c in claims if c["needs_review"]),
            "cited": sum(1 for c in claims if not c["needs_review"]),
        },
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8", newline="\n")
    print(json.dumps(report["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
