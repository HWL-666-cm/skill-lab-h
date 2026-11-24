#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Citation audit: manuscript <-> bibliography consistency, numbering and dedup.

Offline-only. Standard library. No network, no domain knowledge required.
All comparisons use NFKC normalization so full-width Chinese digits/punctuation
and ligatures do not produce false mismatches.
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import defaultdict

VERSION = "1.0"

# ---------------- normalization ----------------

LIGATURES = {
    "\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi",
    "\ufb04": "ffl", "\ufb05": "st", "\ufb06": "st",
    "\u2013": "-", "\u2014": "-", "\u2212": "-", "\uff0d": "-",
    "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
}


def norm(s) -> str:
    """NFKC + ligature/punctuation fold + lowercase + whitespace collapse."""
    if s is None:
        return ""
    if isinstance(s, (int, float)):
        s = str(s)
    s = unicodedata.normalize("NFKC", s)
    s = "".join(LIGATURES.get(ch, ch) for ch in s)
    s = s.lower()
    s = re.sub(r"\s+", " ", s).strip()
    return s


def norm_title(s) -> str:
    """Aggressive title key: letters/digits only, for duplicate detection."""
    s = norm(s)
    s = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", s)
    return s


def norm_doi(s) -> str:
    """Strip common DOI prefixes and trailing punctuation."""
    s = norm(s)
    s = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", s)
    s = s.strip().rstrip(".,;)")
    return s


def first_author_surname(entry: dict) -> str:
    """Best-effort surname from authors list/string (Latin or Chinese)."""
    authors = entry.get("authors") or entry.get("author") or []
    if isinstance(authors, str):
        authors = [a.strip() for a in re.split(r";|,| and ", authors) if a.strip()]
    if not authors:
        return ""
    a = norm(authors[0])
    # "Dietz, Sebastian J." -> "dietz"; "Sebastian J. Dietz" -> last token
    if "," in a:
        return a.split(",")[0].strip()
    cn = re.findall(r"[\u4e00-\u9fff]{2,4}", a)
    if cn:
        return cn[0]
    tokens = re.findall(r"[a-z]+", a)
    return tokens[-1] if tokens else ""


def entry_year(entry: dict) -> str:
    y = entry.get("year", "")
    m = re.search(r"(19|20)\d{2}", str(y))
    return m.group(0) if m else ""


# ---------------- input parsing ----------------

NUM_CITE = re.compile(r"\[(\d+(?:\s*[,，]\s*\d+)*(?:\s*[-–]\s*\d+)?)\]")
KEY_CITE = re.compile(r"\\cite\{([^}]+)\}|\[@([^\]]+)\]")
CAPTION = re.compile(r"(图|表|fig\.?|table)\s*\d", re.I)
REF_HEADING = re.compile(
    r"(?m)^[\s\u3000]*(?:#{1,4}[\s\u3000]*)?(参考文献|引用文献|References|REFERENCES|Bibliography|BIBLIOGRAPHY)[\s\u3000]*$"
)
REF_LINE = re.compile(r"(?m)^[\s\u3000]*\[(\d+)\][\s\u3000]*(?=\S)")


def split_reference_section(text: str) -> tuple[str, str]:
    """Split manuscript into body and trailing bibliography section.

    Without this, the [n] at the start of a reference-list line would be
    counted as an in-text citation and produce a false first-appearance
    error. The section is still audited separately for list/number sync.
    """
    m = REF_HEADING.search(text)
    if not m:
        return text, ""
    return text[:m.start()], text[m.start():]


def expand_nums(raw: str) -> list[int]:
    raw = norm(raw).replace("，", ",")
    out: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        m = re.fullmatch(r"(\d+)\s*-\s*(\d+)", part)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if 0 < a <= b <= 10000:
                out.extend(range(a, b + 1))
        elif part.isdigit() and 0 < int(part) <= 10000:
            out.append(int(part))
    return out


def parse_citations(text: str) -> tuple[str, list[dict]]:
    """Return (style, citations). Style = numeric | key | none.

    A manuscript with both styles is reported as 'mixed' but parsed with both.
    """
    items: list[dict] = []
    for m in NUM_CITE.finditer(text):
        nums = expand_nums(m.group(1))
        if not nums:
            continue
        items.append({
            "raw": m.group(0), "style": "numeric", "tokens": nums,
            "pos": m.start(), "line": text[:m.start()].count("\n") + 1,
        })
    for m in KEY_CITE.finditer(text):
        raw_key = m.group(1) or m.group(2) or ""
        keys = [k.strip() for k in raw_key.split(",") if k.strip()]
        if not keys:
            continue
        items.append({
            "raw": m.group(0), "style": "key", "tokens": keys,
            "pos": m.start(), "line": text[:m.start()].count("\n") + 1,
        })
    items.sort(key=lambda x: x["pos"])
    styles = {i["style"] for i in items}
    style = "mixed" if len(styles) > 1 else (next(iter(styles)) if styles else "none")
    return style, items


def line_at(text: str, pos: int) -> str:
    a = text.rfind("\n", 0, pos) + 1
    b = text.find("\n", pos)
    return text[a:b if b >= 0 else len(text)]


def sentence_at(text: str, pos: int) -> str:
    """Sentence window around a citation.

    An English full stop is a boundary only when followed by whitespace or
    end-of-text; otherwise "PM2.5" would be split into a fake short sentence
    and trigger a false weak_placement warning.
    """
    hard = set("。！？；;\n")
    a = 0
    i = pos - 1
    while i >= 0:
        ch = text[i]
        if ch in hard or (ch == "." and (i + 1 >= len(text) or text[i + 1].isspace())):
            a = i + 1
            break
        i -= 1
    b = len(text)
    i = pos
    while i < len(text):
        ch = text[i]
        if ch in hard or (ch == "." and (i + 1 >= len(text) or text[i + 1].isspace())):
            b = i + 1
            break
        i += 1
    return text[a:b]


def load_bib(data) -> list[dict]:
    """Accept list, {key: entry} map, or {bibliography: [...]}/{"entries": [...]}."""
    if isinstance(data, dict):
        for k in ("bibliography", "entries", "references", "items"):
            if isinstance(data.get(k), list):
                data = data[k]
                break
        else:
            out = []
            for key, val in data.items():
                if isinstance(val, dict):
                    e = dict(val)
                    e.setdefault("key", key)
                    out.append(e)
            return out
    if isinstance(data, list):
        return [dict(e) for e in data if isinstance(e, dict)]
    return []


# ---------------- audits ----------------

def audit_entries(bib: list[dict]) -> list[dict]:
    """Field/source checks. Returns issue dicts (no key = global)."""
    issues: list[dict] = []
    for idx, e in enumerate(bib):
        key = str(e.get("key") or e.get("id") or f"entry{idx + 1}")
        missing = [f for f in ("title", "year") if not norm(e.get(f))]
        authors = e.get("authors") or e.get("author")
        if not authors:
            missing.append("authors")
        if missing:
            issues.append({
                "type": "missing_required_field", "severity": "error", "key": key,
                "field": ",".join(missing),
                "detail": "文献条目缺少必需字段：" + "、".join(missing),
                "evidence": {"present": {f: str(e.get(f, ""))[:60] for f in ("authors", "title", "year")}},
                "suggestion": "回到原始文献库快照补齐；确实没有的字段标为 unavailable，不要臆造。",
            })

        doi_raw = str(e.get("doi") or "")
        doi = norm_doi(doi_raw)
        if doi and re.match(r"^10\.\d{4,9}/\S+", doi) and "doi.org/" not in norm(doi_raw) and not norm(doi_raw).startswith("doi:"):
            issues.append({
                "type": "doi_missing_prefix", "severity": "warning", "key": key,
                "detail": "DOI 写了裸标识符，缺 https://doi.org/ 前缀。",
                "evidence": {"doi": doi_raw[:80]},
                "suggestion": "改为 https://doi.org/<DOI>（GB/T 7714-2015 的常见扣分点）。",
            })

        typ = norm(e.get("type") or e.get("type_label") or "")
        url = norm(e.get("url") or "")
        title_n = norm(e.get("title") or "")
        is_preprint = (
            "preprint" in typ or "arxiv" in url or "arxiv" in title_n
            or bool(e.get("is_preprint"))
        )
        marked_journal = "[j]" in typ or "article-journal" in typ or "journal" in typ
        if is_preprint and marked_journal:
            issues.append({
                "type": "preprint_mislabeled", "severity": "error", "key": key,
                "detail": "预印本被标成期刊论文 [J]，与来源性质不符。",
                "evidence": {"type": str(e.get("type") or e.get("type_label") or "")[:40],
                             "url": str(e.get("url") or "")[:80]},
                "suggestion": "改标 [Preprint] 或 [EB/OL]，并保留平台/版本/DOI；若已正式发表则改用期刊版条目。",
            })

        is_online = "[ol]" in typ or "[eb/ol]" in typ or "online" in typ or bool(url)
        if is_online and not norm(e.get("access_date") or e.get("accessed") or ""):
            issues.append({
                "type": "missing_access_date", "severity": "warning", "key": key,
                "detail": "电子资源缺 [引用日期]，且未标注该字段为不可用。",
                "evidence": {"url": str(e.get("url") or "")[:80]},
                "suggestion": "补 [引用日期]（实际访问当天）；若确实无法确认，写 unavailable 并列入人工确认项。",
            })
    return issues


def find_duplicates(bib: list[dict]) -> tuple[list[dict], list[dict]]:
    """Return (issue dicts, duplicate decisions).

    Rule: identical normalized DOI = strong evidence; title+surname+year = weak
    evidence (warning only). Conflicting strong evidence keeps both entries and
    asks for human review -- this is how we avoid merging different papers by
    the same author.
    """
    issues: list[dict] = []
    decisions: list[dict] = []
    by_doi: dict[str, list[int]] = defaultdict(list)
    for i, e in enumerate(bib):
        d = norm_doi(e.get("doi") or "")
        if d and re.match(r"^10\.\d{4,9}/\S+", d):
            by_doi[d].append(i)

    strong_pairs: set[tuple[int, int]] = set()
    for doi, idxs in by_doi.items():
        if len(idxs) < 2:
            continue
        for a_pos, i in enumerate(idxs):
            for j in idxs[a_pos + 1:]:
                ki = str(bib[i].get("key") or i)
                kj = str(bib[j].get("key") or j)
                ti, tj = norm_title(bib[i].get("title")), norm_title(bib[j].get("title"))
                si, sj = first_author_surname(bib[i]), first_author_surname(bib[j])
                yi, yj = entry_year(bib[i]), entry_year(bib[j])
                conflicting = bool(ti and tj and ti != tj) or bool(si and sj and si != sj) or bool(yi and yj and yi != yj)
                if conflicting:
                    decision = {
                        "keys": [ki, kj], "basis": "same_doi_but_conflicting_metadata",
                        "decision": "keep_both_needs_review", "doi": doi,
                        "reason": "DOI 相同但题名/作者/年份冲突，可能是不同版本或 DOI 录错；不自动合并。",
                        "evidence": {"titles": [bib[i].get("title"), bib[j].get("title")],
                                     "years": [yi, yj]},
                    }
                    issues.append({
                        "type": "duplicate_conflict", "severity": "error",
                        "keys": [ki, kj],
                        "detail": "同 DOI 但元数据冲突，合并会造成错配，已保留两条待人工确认。",
                        "evidence": decision["evidence"],
                        "suggestion": "核对出版社页面或 DOI 解析结果，确认是版本差异还是字段录错。",
                    })
                else:
                    preferred = i if sum(bool(norm(bib[i].get(f))) for f in ("volume", "pages", "url", "access_date")) >= \
                        sum(bool(norm(bib[j].get(f))) for f in ("volume", "pages", "url", "access_date")) else j
                    other = j if preferred == i else i
                    merged_fields = {
                        f: str(bib[preferred].get(f) or bib[other].get(f) or "")
                        for f in ("title", "authors", "year", "venue", "volume", "issue", "pages", "doi", "url", "type")
                    }
                    decision = {
                        "keys": [ki, kj], "basis": "same_doi",
                        "decision": "merge", "keep": str(bib[preferred].get("key") or preferred),
                        "drop": str(bib[other].get("key") or other), "doi": doi,
                        "merged_fields": merged_fields,
                        "reason": "规范化 DOI 一致且题名/作者/年份无冲突；字段按更完整的一条保留。",
                    }
                    strong_pairs.add(tuple(sorted((i, j))))
                    issues.append({
                        "type": "duplicate_same_doi", "severity": "warning",
                        "keys": [ki, kj],
                        "detail": "两条文献 DOI 相同，判为同一条；建议合并并保留合并依据。",
                        "evidence": {"doi": doi, "keep": decision["keep"], "drop": decision["drop"]},
                        "suggestion": "合并为一条，正文两处引用统一指向保留键；在 change_log 记录判据。",
                    })
        decisions.append({"doi": doi, "keys": [str(bib[i].get("key") or i) for i in idxs]})

    # weak evidence: same title + surname + year, different/no DOI
    for i in range(len(bib)):
        for j in range(i + 1, len(bib)):
            if tuple(sorted((i, j))) in strong_pairs:
                continue
            ti, tj = norm_title(bib[i].get("title")), norm_title(bib[j].get("title"))
            si, sj = first_author_surname(bib[i]), first_author_surname(bib[j])
            yi, yj = entry_year(bib[i]), entry_year(bib[j])
            if ti and ti == tj and si and si == sj and yi and yi == yj:
                ki, kj = str(bib[i].get("key") or i), str(bib[j].get("key") or j)
                issues.append({
                    "type": "duplicate_suspected", "severity": "warning",
                    "keys": [ki, kj],
                    "detail": "题名+第一作者+年份一致但 DOI 不同/缺失，疑似同一文献，需人工确认后再合并。",
                    "evidence": {"title": bib[i].get("title"), "surname": si, "year": yi,
                                 "dois": [bib[i].get("doi"), bib[j].get("doi")]},
                    "suggestion": "核对版本（预印本/正式版、期刊/会议）；确认同一条后再合并，禁止自动合并。",
                })
                decisions.append({"keys": [ki, kj], "basis": "title_surname_year",
                                  "decision": "needs_review", "reason": "弱证据，仅提示不自动合并。"})
    return issues, decisions


def audit_consistency(text: str, citations: list[dict], bib: list[dict]) -> tuple[list[dict], dict]:
    """Dangling / unused / numbering continuity / first-appearance order / placement."""
    issues: list[dict] = []
    keys = [str(e.get("key") or e.get("id") or f"entry{i + 1}") for i, e in enumerate(bib)]
    orders = [e.get("order") for e in bib]
    key_set = set(keys)
    style = "numeric" if citations and all(c["style"] == "numeric" for c in citations) else "key"

    seen_order: list = []
    for c in citations:
        for tok in c["tokens"]:
            if tok not in seen_order:
                seen_order.append(tok)

    if style == "numeric":
        valid_nums = set()
        for i, e in enumerate(bib):
            o = e.get("order", i + 1)
            try:
                valid_nums.add(int(o))
            except (TypeError, ValueError):
                pass
        for n in seen_order:
            if n not in valid_nums:
                issues.append({
                    "type": "dangling_citation", "severity": "error", "token": str(n),
                    "detail": f"正文引用 [{n}] 在文献库中找不到对应编号。",
                    "evidence": {"line": c_line(citations, n), "available_orders": sorted(valid_nums)[:20]},
                    "suggestion": "补上该条文献或修正编号；禁止保留指向不存在条目的引用。",
                })
        for i, e in enumerate(bib):
            o = e.get("order", i + 1)
            try:
                on = int(o)
            except (TypeError, ValueError):
                issues.append({
                    "type": "invalid_order", "severity": "error", "key": keys[i],
                    "detail": f"文献条目 order={o!r} 不是整数，无法核验编号。",
                    "evidence": {"key": keys[i]},
                    "suggestion": "改成连续整数，或删除 order 让脚本按列表顺序推断。",
                })
                continue
            if on not in seen_order:
                issues.append({
                    "type": "unused_entry", "severity": "warning", "key": keys[i],
                    "detail": f"文献条目 [{on}] 在正文中没有被引用。",
                    "evidence": {"key": keys[i], "title": str(e.get("title") or "")[:80]},
                    "suggestion": "删除未用条目，或在正文补上真正需要它的论断句。",
                })
        # duplicate orders
        by_order: dict[int, list[str]] = defaultdict(list)
        for i, e in enumerate(bib):
            try:
                by_order[int(e.get("order", i + 1))].append(keys[i])
            except (TypeError, ValueError):
                pass
        for on, ks in by_order.items():
            if len(ks) > 1:
                issues.append({
                    "type": "duplicate_order", "severity": "error", "keys": ks,
                    "detail": f"编号 [{on}] 被 {len(ks)} 条文献占用，正文无法唯一定位。",
                    "evidence": {"order": on, "keys": ks},
                    "suggestion": "给每条文献分配唯一编号后重排。",
                })
        # gaps
        nums = sorted({int(c) for c in seen_order if isinstance(c, int) and int(c) in valid_nums})
        gaps = [n for n in range(1, max(nums) + 1) if n not in nums] if nums else []
        if gaps:
            issues.append({
                "type": "numbering_gap", "severity": "error",
                "detail": "正文编号不连续，缺号：" + ",".join(str(n) for n in gaps),
                "evidence": {"seen": nums, "missing": gaps},
                "suggestion": "按正文首次出现顺序重排，输出 old→new 映射后同步文末列表。",
            })
        # first appearance vs list order. Dangling tokens are excluded: they
        # have no bibliography entry, so they must not appear in a renumbering
        # plan nor make an otherwise monotone sequence look out of order.
        first_nums = [n for n in seen_order if isinstance(n, int) and n in valid_nums]
        monotone = first_nums == sorted(first_nums)
        if not monotone:
            issues.append({
                "type": "first_appearance_order", "severity": "error",
                "detail": "正文编号首次出现顺序不是 1,2,3…，顺序编码制要求按首次引用编号。",
                "evidence": {"first_seen": first_nums[:20], "list_order": sorted(first_nums)[:20]},
                "suggestion": "按首次出现顺序重排；用 numbering.proposed 的映射同步正文与文末。",
            })
        proposed = {str(old): new for new, old in enumerate(first_nums, 1)}
        numbering = {
            "style": style, "first_seen": first_nums, "continuous": monotone and not gaps,
            "current_orders": sorted(valid_nums), "proposed": proposed,
        }
    else:  # key-based or none
        for c in citations:
            for tok in c["tokens"]:
                if str(tok) not in key_set:
                    issues.append({
                        "type": "dangling_citation", "severity": "error", "token": str(tok),
                        "detail": f"\\cite{{{tok}}} 在文献库中找不到对应 key。",
                        "evidence": {"line": c["line"], "available_keys": sorted(key_set)[:20]},
                        "suggestion": "补条目或改正 key；不要留下未定义的引用键。",
                    })
        used = set()
        for c in citations:
            used.update(str(t) for t in c["tokens"])
        for k in keys:
            if k not in used:
                issues.append({
                    "type": "unused_entry", "severity": "warning", "key": k,
                    "detail": f"文献条目 {k} 在正文中没有被引用。",
                    "evidence": {"key": k},
                    "suggestion": "删除未用条目或在正文补上需要它的论断句。",
                })
        ordered_keys = [str(t) for t in seen_order if str(t) in key_set]
        numbering = {
            "style": style, "first_seen": ordered_keys,
            "continuous": True, "proposed": {k: i + 1 for i, k in enumerate(ordered_keys)},
        }

    # placement: caption lines and weak end-of-paragraph placement (warnings only)
    for c in citations:
        ln = line_at(text, c["pos"])
        if CAPTION.search(ln):
            issues.append({
                "type": "citation_in_caption", "severity": "warning",
                "detail": "引用出现在图题/表题行，来源应支撑论断而非图表说明。",
                "evidence": {"line": c["line"], "raw": c["raw"], "line_text": ln[:100]},
                "suggestion": "把引用移到正文论断句；图表如需来源，单独写「数据来源」。",
            })
            continue
        sent = sentence_at(text, c["pos"])
        after = text[c["pos"] + len(c["raw"]): c["pos"] + len(c["raw"]) + 3]
        short = len(norm(sent)) < 18
        if short and (after.startswith(("。", ".", "；", ";", "\n")) or c["pos"] + len(c["raw"]) >= len(text)):
            issues.append({
                "type": "weak_placement", "severity": "warning",
                "detail": "引用落在很短的句子末尾，可能没有明确指向需要来源的论断。",
                "evidence": {"line": c["line"], "raw": c["raw"], "sentence": sent[:80]},
                "suggestion": "把引用紧贴到具体论断之后；一句多引用逗号分隔，多句一引需逐句判断。",
            })
    return issues, numbering


def c_line(citations: list[dict], token) -> int:
    for c in citations:
        if token in c["tokens"]:
            return c["line"]
    return 0


# ---------------- report ----------------

def audit_reference_section(ref_text: str, bib: list[dict]) -> list[dict]:
    """Check that the printed reference list matches the bibliography snapshot."""
    if not ref_text:
        return []
    issues: list[dict] = []
    listed = [int(n) for n in REF_LINE.findall(ref_text)]
    if not listed:
        return []
    expected = []
    for i, e in enumerate(bib):
        try:
            expected.append(int(e.get("order", i + 1)))
        except (TypeError, ValueError):
            pass
    gaps = [n for n in range(1, max(listed) + 1) if n not in listed]
    if gaps:
        issues.append({
            "type": "reference_list_gap", "severity": "error",
            "detail": "文末参考文献列表编号不连续，缺号：" + ",".join(str(n) for n in gaps),
            "evidence": {"listed": listed, "missing": gaps},
            "suggestion": "按正文首次引用顺序重排列表，并与 numbering.proposed 映射同步。",
        })
    if expected and set(listed) != set(expected):
        issues.append({
            "type": "reference_list_mismatch", "severity": "error",
            "detail": "文末列表编号集合与文献库快照不一致（多列、漏列或编号错位）。",
            "evidence": {"listed": listed, "in_bib": sorted(expected),
                         "only_in_list": sorted(set(listed) - set(expected)),
                         "only_in_bib": sorted(set(expected) - set(listed))},
            "suggestion": "以文献库快照为准重建列表，逐条核对后写入 change_log。",
        })
    if listed != sorted(listed):
        issues.append({
            "type": "reference_list_order", "severity": "warning",
            "detail": "文末列表编号未按升序排列。",
            "evidence": {"listed": listed},
            "suggestion": "改成升序；顺序编码制下列表顺序应与正文首次引用顺序一致。",
        })
    return issues


def build_report(manuscript: str, bib_data, manuscript_name: str = "", bib_name: str = "") -> dict:
    bib = load_bib(bib_data)
    body, ref_section = split_reference_section(manuscript)
    style, citations = parse_citations(body)
    issues: list[dict] = []

    issues.extend(audit_entries(bib))
    dup_issues, dup_decisions = find_duplicates(bib)
    issues.extend(dup_issues)
    cons_issues, numbering = audit_consistency(body, citations, bib)
    issues.extend(cons_issues)
    issues.extend(audit_reference_section(ref_section, bib))

    # Missing material must be reported explicitly, never silently pass.
    if not norm(body):
        issues.append({
            "type": "empty_manuscript", "severity": "error",
            "detail": "稿件正文为空，无法执行引用一致性核验。",
            "evidence": {"manuscript": manuscript_name},
            "suggestion": "提供实际稿件后重跑；不要把空输入当作通过。",
        })
    elif not citations and bib:
        issues.append({
            "type": "no_citations_found", "severity": "warning",
            "detail": "稿件中未检出任何 [n] 或 \\cite{key} 引用标记，无法核验引用位置。",
            "evidence": {"entries_in_bib": len(bib)},
            "suggestion": "确认该稿件是否确实无需来源支撑；若需要，按目标格式补插引用。",
        })

    # stable ids + change log
    for i, iss in enumerate(issues, 1):
        iss["id"] = f"I{i:03d}"
    changes = []
    for i, iss in enumerate(issues, 1):
        if iss.get("suggestion"):
            changes.append({
                "id": f"C{i:03d}", "issue_id": iss["id"], "action": iss["suggestion"],
                "reason": iss["detail"],
                "evidence": {k: v for k, v in iss.get("evidence", {}).items()},
            })

    sev = {"error": 0, "warning": 0}
    for iss in issues:
        sev[iss["severity"]] = sev.get(iss["severity"], 0) + 1
    verdict = "needs_revision" if sev.get("error", 0) else ("review_warnings" if sev.get("warning", 0) else "ok")

    return {
        "version": VERSION,
        "inputs": {"manuscript": manuscript_name, "bibliography": bib_name, "citation_style": style,
                   "has_reference_section": bool(ref_section)},
        "counts": {
            "citations_in_text": sum(len(c["tokens"]) for c in citations),
            "citation_marks": len(citations),
            "entries_in_bib": len(bib),
            "issues": len(issues), "errors": sev.get("error", 0), "warnings": sev.get("warning", 0),
        },
        "issues": issues,
        "numbering": numbering,
        "duplicate_decisions": dup_decisions,
        "change_log": changes,
        "verdict": verdict,
        "notes": [
            "所有匹配均做 NFKC 与连字/标点折叠，中文全角与英文 ligature 不影响判定。",
            "severity=warning 的项不阻断结果，但必须在人工确认项里列出。",
            "弱证据去重仅提示，不自动合并；同 DOI 但元数据冲突时保留两条。",
        ],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manuscript", required=True, help="稿件 .md/.txt（含 [n] 或 \\cite{key}）")
    ap.add_argument("--bib", required=True, help="文献库 .json（list / {key:entry} / {entries:[...]}）")
    ap.add_argument("--out", required=True, help="输出报告 .json")
    args = ap.parse_args()

    with open(args.manuscript, encoding="utf-8") as f:
        text = f.read()
    with open(args.bib, encoding="utf-8") as f:
        bib_data = json.load(f)
    report = build_report(text, bib_data, args.manuscript, args.bib)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    c = report["counts"]
    print(f"[citation_audit] {report['verdict']} | citations={c['citations_in_text']} "
          f"entries={c['entries_in_bib']} errors={c['errors']} warnings={c['warnings']}")
    print(f"  report -> {args.out}")


if __name__ == "__main__":
    main()
