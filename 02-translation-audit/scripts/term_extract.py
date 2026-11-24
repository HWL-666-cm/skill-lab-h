#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""term_extract.py — 从段落级原文抽取术语候选，生成"待定译名"的术语表骨架

为什么只抽候选、不定译名：
    术语译名涉及领域约定（如 low-visibility procedure 在民航语境是"低能见度程序"），
    脚本不该假装懂领域。这里只做统计信号 + 定位，把"定译名"留给 Agent/人，
    再用 translation_audit.py 强制这个译名在全篇被执行。

抽取三类候选：
    1) 缩写定义：`full term (ABBR)` —— 最强的术语锚点，但有被 PDF 硬换行切断的
       （实测 `numerical weather prediction` 被切成 `weather prediction`），
       所以先合并断行、再要求全称是"紧邻括号的连续名词短语"，遇虚词即截断。
    2) 高频名词短语：2–4 词，净化页眉/引用噪声后统计（`et al` 这类要排除）。
    3) 缩写单独出现：正文里裸用的大写缩写（lvp/NWP），也要能反向查到定义。

输入：pdf_paragraphs.py 的输出 JSON
输出：术语表骨架 JSON（target 为空，locked=false），每个候选带 occurrences（pid/page/section）
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

# 定语/虚词：全称遇到它们就从这里截断，避免把 "are from the atmospheric high" 当成全称
STOP = {"the", "a", "an", "of", "and", "or", "for", "from", "in", "on", "at", "to",
        "by", "with", "as", "is", "are", "was", "were", "this", "that", "these", "those",
        "we", "our", "its", "it", "their", "which", "such", "used", "based"}
# 引用噪声 / 常见非术语
NOISE_PHRASE = {"et al", "e g", "i e", "fig", "table", "eq", "see", "cf", "vs"}

# 缩写定义：大写（NWP）与小写（lvp/rvr/cei）都要支持。
# 学术论文里小写缩写很常见（这篇的 lvp 出现几十次），只认大写会漏掉核心术语。
ABBR_DEF = re.compile(r"\(([A-Za-z]{2,6})\)")
# 括号内不是缩写的常见词
NOT_ABBR = {"eg", "ie", "see", "cf", "etc", "vs", "ed", "eds", "fig", "figs", "tab",
            "al", "pp", "vol", "no", "eq", "eqs", "sec", "sect", "ca", "approx"}
# 抓括号前的一段文字，作为全称候选
PRECEDING = re.compile(r"([A-Za-z][A-Za-z\-]*(?:\s+[A-Za-z][A-Za-z\-]*){0,6})\s*$")


def norm(s: str) -> str:
    return unicodedata.normalize("NFKC", s or "")


def refine_full_form(preceding: str) -> str:
    """把括号前文字裁成真正的名词短语：从右往左取词，遇到虚词/短词就停。"""
    words = preceding.strip().split()
    out = []
    for w in reversed(words):
        lw = w.lower().strip(",")
        if lw in STOP or len(w) <= 1:
            break
        out.append(w)
    full = " ".join(reversed(out))
    return full.strip()


def iter_sentences(text: str):
    """按句切，供缩写定义在同一句内定位。"""
    parts = re.split(r"(?<=[.!?])\s+", text)
    for p in parts:
        if p.strip():
            yield p.strip()


def extract_candidates(paras: list[dict]):
    # 只统计正文段（跳过 meta/formula/fragment/caption/reference）
    body = [p for p in paras if p["kind"] == "para"]

    concepts: dict[str, dict] = {}

    def add(source: str, abbr: str | None, pid: int, page: int, section: str, how: str):
        key = norm(source).strip().lower()
        if not key:
            return
        c = concepts.get(key)
        if not c:
            c = concepts[key] = {
                "concept_id": f"C{len(concepts)+1:02d}",
                "source": source.strip(),
                "abbr": abbr or "",
                "target": "",
                "aliases_allowed": [],
                "forbidden": [],
                "evidence": how,
                "occurrences": [],
            }
        if abbr and not c["abbr"]:
            c["abbr"] = abbr
        if not any(o["pid"] == pid for o in c["occurrences"]):
            c["occurrences"].append({"pid": pid, "page": page, "section": section})

    abbr_count = 0
    # 先统计括号内 2–6 字母词在全文的出现频次：真正的缩写会在正文反复出现，
    # 括号里偶然出现的普通词（如 (see)）频次低，可借此过滤。
    bracket_freq: Counter[str] = Counter()
    for p in body:
        for m in ABBR_DEF.finditer(norm(p["text"])):
            bracket_freq[m.group(1).lower()] += 1

    for p in body:
        text = norm(p["text"])
        # 1) 缩写定义
        for m in ABBR_DEF.finditer(text):
            abbr_raw = m.group(1)
            abbr_l = abbr_raw.lower()
            if abbr_l in NOT_ABBR or abbr_l in {"utc", "usa", "doi", "pdf", "url", "ii", "iii", "iv"}:
                continue
            # 小写缩写要求全文出现 ≥2 次，避免把孤立的括号词当定义
            if abbr_raw.islower() and bracket_freq[abbr_l] < 2:
                continue
            before = text[:m.start()]
            pm = PRECEDING.search(before)
            if not pm:
                continue
            full = refine_full_form(pm.group(1))
            if len(full.split()) < 2:
                continue
            add(full, abbr_raw, p["pid"], p["page"], p["section"], "abbreviation-definition")
            abbr_count += 1

    # 2) 高频名词短语（只在正文段内，且跨段出现 ≥3 次）
    phrase_counter: Counter[str] = Counter()
    phrase_pos: dict[str, list[dict]] = defaultdict(list)
    for p in body:
        text = norm(p["text"])
        for m in re.finditer(r"\b([a-z][a-z\-]+(?:\s+[a-z][a-z\-]+){1,3})\b", text):
            ph = m.group(1)
            if ph in NOISE_PHRASE or any(w in STOP for w in ph.split()):
                continue
            if len(ph) < 8:
                continue
            phrase_counter[ph] += 1
            if len(phrase_pos[ph]) < 6:
                phrase_pos[ph].append({"pid": p["pid"], "page": p["page"], "section": p["section"]})

    for ph, n in phrase_counter.most_common(40):
        if n < 3:
            continue
        # 已被缩写定义覆盖的，跳过（避免重复概念）
        if any(norm(c["source"]).lower() == ph for c in concepts.values()):
            continue
        key = ph
        if key in concepts:
            continue
        concepts[key] = {
            "concept_id": f"C{len(concepts)+1:02d}",
            "source": ph,
            "abbr": "",
            "target": "",
            "aliases_allowed": [],
            "forbidden": [],
            "evidence": f"high-frequency-phrase({n})",
            "occurrences": phrase_pos[ph],
        }

    return list(concepts.values()), abbr_count


def merge_inflections(concepts: list[dict]) -> list[dict]:
    """把同一概念的词形变体合并（lead time / lead times、OLR 大小写差异）。

    为什么必须做：术语表里同一概念出现两条，审计时会把合法的单复数当成"两种译名"，
    产生误报；也会让 Agent 重复定译名。合并时保留更长的源形式，其余记为 aliases_allowed。
    """
    def canon(s: str) -> str:
        t = norm(s).lower().strip()
        t = re.sub(r"[^a-z0-9\- ]", "", t)
        words = []
        for w in t.split():
            if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
                w = w[:-1]
            words.append(w)
        return " ".join(words)

    groups: dict[str, list[dict]] = defaultdict(list)
    for c in concepts:
        groups[canon(c["source"])].append(c)

    merged: list[dict] = []
    for _, group in groups.items():
        if len(group) == 1:
            merged.append(group[0])
            continue
        group.sort(key=lambda c: (-len(c["source"]), -len(c["occurrences"])))
        base = group[0]
        occ = list(base["occurrences"])
        for other in group[1:]:
            if other["source"] != base["source"] and other["source"] not in base["aliases_allowed"]:
                base["aliases_allowed"].append(other["source"])
            for o in other["occurrences"]:
                if not any(x["pid"] == o["pid"] for x in occ):
                    occ.append(o)
            if other["abbr"] and not base["abbr"]:
                base["abbr"] = other["abbr"]
        base["occurrences"] = occ
        merged.append(base)

    # 同缩写合并：同一缩写（如 lvp）在多处定义成"修饰语不同、核心词相同"的全称，
    # 本质是同一概念（capacity-reducing low-visibility procedure / low-visibility procedure）。
    # 判据：两组 abbr 相同，且一个 source 以另一个 source 的词序列结尾。
    def merge_same_abbr(items: list[dict]) -> list[dict]:
        out: list[dict] = []
        for c in items:
            placed = False
            if c.get("abbr"):
                for base in out:
                    if not base.get("abbr") or base["abbr"].lower() != c["abbr"].lower():
                        continue
                    a, b = base["source"].lower(), c["source"].lower()
                    # 后缀包含关系（词级）
                    if a.endswith(b) or b.endswith(a):
                        longer, shorter = (base, c) if len(base["source"]) >= len(c["source"]) else (c, base)
                        if shorter["source"] not in longer["aliases_allowed"]:
                            longer["aliases_allowed"].append(shorter["source"])
                        for o in c["occurrences"]:
                            if not any(x["pid"] == o["pid"] for x in longer["occurrences"]):
                                longer["occurrences"].append(o)
                        # 用短的替换掉 out 里原来的 base
                        if longer is c:
                            out[out.index(base)] = c
                        placed = True
                        break
            if not placed:
                out.append(c)
        return out

    merged = merge_same_abbr(merged)

    # 重新编号，按出现次数降序
    merged.sort(key=lambda c: (-len(c["occurrences"]), c["source"].lower()))
    for i, c in enumerate(merged, 1):
        c["concept_id"] = f"C{i:02d}"
    return merged


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--paras", required=True, help="pdf_paragraphs.py 输出 JSON")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    data = json.loads(Path(args.paras).read_text(encoding="utf-8"))
    paras = data["paragraphs"]
    concepts, abbr_count = extract_candidates(paras)
    raw_count = len(concepts)
    concepts = merge_inflections(concepts)

    body_paras = [p for p in paras if p["kind"] == "para"]
    glossary = {
        "source": data.get("source", ""),
        "schema_version": "1.0",
        "stats": {
            "body_paragraphs": len(body_paras),
            "candidates_raw": raw_count,
            "candidates_merged": len(concepts),
            "abbreviation_definitions": abbr_count,
        },
        "note": "target 为空表示待定译名；Agent 填完后把 locked 置 true，并用 translation_audit.py 校验全篇执行。",
        "concepts": concepts,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(glossary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({
        "out": args.out,
        "body_paragraphs": len(body_paras),
        "candidates": len(concepts),
        "with_abbr": sum(1 for c in concepts if c["abbr"]),
        "sample": [{"source": c["source"][:40], "abbr": c["abbr"], "occ": len(c["occurrences"]),
                    "how": c["evidence"]} for c in concepts[:8]],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
