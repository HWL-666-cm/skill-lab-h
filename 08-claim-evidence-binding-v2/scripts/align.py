#!/usr/bin/env python3
"""Two-way claim<->evidence alignment.

forward:  each sentence in the draft  -> is there a checkable anchor?
backward: each key work / figure in material -> did the draft use it?

We deliberately do NOT decide whether a paraphrase is semantically faithful;
that needs a human.  What we can decide mechanically is anchoring: a citation
number, a figure/section number, a verbatim quote, or an explicit "author
judgement" marker.  Anything weaker is reported, not silently passed.
"""
from __future__ import annotations

import re
from typing import Any

from claims import _sentences, _text_of, _line_of

CITE_KINDS = {"bibkey", "number", "author_year"}


def _compile_cite_patterns(lex: dict) -> list[tuple[str, re.Pattern, str]]:
    out = []
    for p in lex.get("citation_patterns", []):
        try:
            out.append((p["name"], re.compile(p["regex"], re.I), p.get("kind", "number")))
        except re.error:
            continue
    return out


def _compile_fig_patterns(lex: dict) -> list[tuple[str, re.Pattern, str]]:
    out = []
    for p in lex.get("figure_patterns", []):
        try:
            out.append((p["name"], re.compile(p["regex"], re.I), p.get("kind", "figure")))
        except re.error:
            continue
    return out


def _find_citations(text: str, pats: list[tuple[str, re.Pattern, str]]) -> list[dict]:
    found: list[dict] = []
    for name, rx, kind in pats:
        for m in rx.finditer(text):
            # Optional groups may be None (e.g. "(2020)" with no author).  Fall
            # back to the whole match rather than crashing the whole run.
            val = ""
            if m.lastindex:
                for gi in range(1, m.lastindex + 1):
                    g = m.group(gi)
                    if g and g.strip():
                        val = g.strip()
                        break
            # For author-year citations the whole match carries both author and
            # year, which is what _ref_for_value needs to resolve the entry.
            use = m.group(0).strip() if kind == "author_year" else (val or m.group(0).strip())
            found.append({"pattern": name, "kind": kind,
                          "raw": m.group(0).strip(),
                          "value": use,
                          "span": (m.start(), m.end())})
    # De-duplicate overlapping matches.  "Smith et al. (2020)" is also matched
    # by the bare "(2020)" pattern; counting both would double the citation and
    # the unauthorised bare year would be reported as unverifiable.
    found.sort(key=lambda c: (c["span"][0], -(c["span"][1] - c["span"][0])))
    kept: list[dict] = []
    for c in found:
        s, e = c["span"]
        if any(s < k["span"][1] and k["span"][0] < e for k in kept):
            continue
        kept.append(c)
    for c in kept:
        c.pop("span", None)
    return kept


def _find_figures(text: str, pats: list[tuple[str, re.Pattern, str]]) -> list[dict]:
    found = []
    for name, rx, kind in pats:
        for m in rx.finditer(text):
            found.append({"pattern": name, "kind": kind, "raw": m.group(0).strip(),
                          "number": m.group(1) if m.lastindex else ""})
    return found


def _section_of(pos: int, boundaries: list[tuple[int, str]]) -> str:
    cur = ""
    for at, name in boundaries:
        if at <= pos:
            cur = name
        else:
            break
    return cur


def _draft_sections(draft: str, lex: dict) -> list[tuple[int, str]]:
    """Extract (position, section) boundaries honouring heading hierarchy.

    ``## 相关工作`` 下的 ``### 问题设定`` 等子标题不再把父节切成 0 句：
    三级及以上标题若自己匹配不到节名，就继承最近的顶层节名。
    """
    out: list[tuple[int, str]] = []
    current = ""
    for m in re.finditer(r"^(#{1,6})\s+(.+)$", draft, re.M):
        level = len(m.group(1))
        head = m.group(2).strip()
        sec = ""
        for name, keys in lex.get("section_names", {}).items():
            if any(k.lower() in head.lower() for k in keys):
                sec = name
                break
        if level <= 2:
            if sec:
                current = sec
            out.append((m.start(), sec or head))
        else:
            # 子标题：自己没匹配到节名就继承父节，避免父节被判缺失
            out.append((m.start(), sec or current or head))
    return out


def _classify_section(head: str, lex: dict) -> str:
    for name, keys in lex.get("section_names", {}).items():
        if any(k.lower() in head.lower() for k in keys):
            return name
    return "other"


def _quote_in_material(sentence: str, cands: dict, pack: dict) -> str:
    """Does a distinctive span of this sentence appear verbatim in material?"""
    words = re.findall(r"[\u4e00-\u9fff]{6,}|[A-Za-z]{5,}", sentence)
    if not words:
        return ""
    probe = max(words, key=len)
    if len(probe) < 6:
        return ""
    for u in pack.get("units", []):
        t = _text_of(u)
        if probe.lower() in t.lower():
            return f"{u.get('source','')}:{u.get('locator','')}"
    return ""


def _ref_for_value(value: str, refs_by_key: dict[str, dict]) -> dict | None:
    v = (value or "").strip()
    if not v:
        return None
    if v in refs_by_key:
        return refs_by_key[v]
    # numeric ranges: [1,3] / [2-5]
    for part in re.split(r"[,\s\-–]+", v):
        if part in refs_by_key:
            return refs_by_key[part]
    # author-year: "Smith 2020" / "Smith et al. (2020)"
    m = re.search(r"([A-Z][A-Za-z\-']+).*?((?:19|20)\d{2})", v)
    if m:
        key = f"{m.group(1)}{m.group(2)}"
        if key in refs_by_key:
            return refs_by_key[key]
        for r in refs_by_key.values():
            f = r.get("fields", {})
            if f.get("year") == m.group(2) and m.group(1).lower() in f.get("author", "").lower():
                return r
        # bib key itself may be lowercase: smith2020 vs Smith2020
        k2 = f"{m.group(1).lower()}{m.group(2)}"
        if k2 in refs_by_key:
            return refs_by_key[k2]
        # MIXED HALLUCINATION guard: the author matches a real reference but the
        # year does not.  Bind anyway so _metadata_mismatch can report the exact
        # wrong field, instead of hiding it as a generic "unverifiable".
        for r in refs_by_key.values():
            f = r.get("fields", {})
            author = f.get("author", "")
            if author and m.group(1).lower() in author.lower():
                return r
    return None


def _metadata_mismatch(cite: dict, ref: dict | None, lex: dict) -> list[str]:
    """Compare what is written in the draft against the material entry,
    field by field.  Mixed hallucination (real author + wrong year) is caught
    here, which a shallow author-only check would miss."""
    if ref is None:
        return []
    problems: list[str] = []
    m = re.search(r"((?:19|20)\d{2})", cite.get("raw", ""))
    year = ref.get("fields", {}).get("year", "")
    if m and year and m.group(1) != year:
        problems.append(f"year {m.group(1)} != material {year}")
    return problems


def align(cands: dict, draft: str, lex: dict, pack: dict) -> dict:
    cite_pats = _compile_cite_patterns(lex)
    fig_pats = _compile_fig_patterns(lex)
    boundaries = _draft_sections(draft, lex)
    refs_by_key: dict[str, dict] = {}
    for r in cands.get("references", []):
        refs_by_key[str(r.get("key", ""))] = r
        if r.get("number"):
            refs_by_key[str(r["number"])] = r
        f = r.get("fields", {})
        if f.get("author") and f.get("year"):
            first = f["author"].split()[0]
            refs_by_key.setdefault(f"{first}{f['year']}", r)

    hedge = lex.get("hedge_terms", [])
    overclaim = lex.get("overclaim_terms", [])
    cliche = lex.get("cliche_terms", [])

    forward: list[dict] = []
    for pos, sent in enumerate(_sentences(draft)):
        offset = draft.find(sent, 0 if pos == 0 else max(0, pos))
        sec = _section_of(offset, boundaries) if offset >= 0 else ""
        cites = _find_citations(sent, cite_pats)
        figs = _find_figures(sent, fig_pats)
        quote_ref = _quote_in_material(sent, cands, pack)
        has_judgement = bool(re.search(r"(作者判断|本文判断|我们推测|we argue|we hypothesize|in our view)", sent, re.I))
        over = [w for w in overclaim if w.lower() in sent.lower()]
        hedged = [w for w in hedge if w.lower() in sent.lower()]
        cli = [w for w in cliche if w.lower() in sent.lower()]

        resolved, mism = [], []
        for c in cites:
            r = _ref_for_value(c["value"], refs_by_key)
            if r:
                resolved.append({"cite": c, "ref_key": r.get("key"), "ref": r})
                mism.extend(_metadata_mismatch(c, r, lex))
            else:
                resolved.append({"cite": c, "ref_key": None, "ref": None})

        # status: strongest anchor available
        if resolved and all(x["ref"] is not None for x in resolved) and not mism:
            status = "anchored"
        elif resolved and mism:
            status = "unverified"     # a citation is present but its metadata disagrees
        elif figs or quote_ref:
            status = "loose"          # locatable in material, but no explicit citation
        elif has_judgement:
            status = "loose"          # explicitly marked as author judgement
        elif cites:
            status = "unverified"     # a citation we cannot trace
        else:
            status = "unanchored"

        if over and not hedged and status in ("unanchored", "unverified"):
            status = "overclaimed"

        forward.append({
            "sentence": sent[:500], "section": sec,
            # sec 已经是 _draft_sections 归一化后的节名（或原始标题）。
            # 不要再送 _classify_section 二次匹配：词表里没有 "background" 这个词，
            # 二次匹配会把 background/related_work/contribution 全判成 other。
            "claim_type": sec if sec in lex.get("section_names", {}) else "other",
            "status": status,
            "citations": [{"raw": x["cite"]["raw"], "kind": x["cite"]["kind"],
                           "ref_key": x["ref_key"],
                           "ref_author": (x["ref"] or {}).get("fields", {}).get("author", ""),
                           "ref_year": (x["ref"] or {}).get("fields", {}).get("year", "")}
                          for x in resolved],
            "figures": figs,
            "verbatim_source": quote_ref,
            "metadata_mismatch": mism,
            "overclaim_terms": over, "hedge_terms": hedged, "cliche_terms": cli,
            "explicit_judgement": has_judgement,
        })

    # backward: did the draft mention each key work / figure?
    draft_lower = draft.lower()
    backward: list[dict] = []
    for w in cands.get("key_works", []):
        name = str(w.get("author") or w.get("key") or "")
        year = str(w.get("year") or "")
        hit = bool(name and name.lower()[:12] in draft_lower)
        cited = bool(re.search(r"\\cite[a-zA-Z]*\s*\{[^}]*" + re.escape(str(w.get("key", ""))), draft, re.I)) if w.get("key") else False
        yhit = bool(year and year in draft)
        if hit and (cited or yhit):
            st = "written"
        elif hit or yhit:
            st = "mentioned_without_anchor"
        else:
            st = "not_written"
        backward.append({"kind": "key_work", "key": w.get("key", ""),
                         "author": name, "year": year, "title": w.get("title", ""),
                         "status": st})
    for a in cands.get("figures", []):
        label = a.get("label", "")
        hit = bool(label and label.lower() in draft_lower)
        backward.append({"kind": "figure", "key": a.get("number", ""),
                         "label": label, "source": a.get("source", ""),
                         "status": "written" if hit else "not_written"})

    # roll-up
    by_status: dict[str, int] = {}
    for row in forward:
        by_status[row["status"]] = by_status.get(row["status"], 0) + 1
    by_back: dict[str, int] = {}
    for row in backward:
        by_back[row["status"]] = by_back.get(row["status"], 0) + 1
    anchored = by_status.get("anchored", 0) + by_status.get("loose", 0)
    trace_rate = round(anchored / len(forward), 4) if forward else 0.0

    return {"forward": {"rows": forward, "by_status": by_status,
                        "trace_rate": trace_rate, "total": len(forward)},
            "backward": {"rows": backward, "by_status": by_back, "total": len(backward)},
            "counts": {"metadata_mismatch": sum(len(r["metadata_mismatch"]) for r in forward),
                       "overclaimed": by_status.get("overclaimed", 0),
                       "unanchored": by_status.get("unanchored", 0),
                       "cliche": sum(len(r["cliche_terms"]) for r in forward)}}


if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path
    d = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    print(json.dumps(align(d.get("candidates", {}), Path(sys.argv[2]).read_text(encoding="utf-8"),
                           json.loads(Path(sys.argv[3]).read_text(encoding="utf-8")),
                           d.get("pack", {})), ensure_ascii=False, indent=2)[:2000])
