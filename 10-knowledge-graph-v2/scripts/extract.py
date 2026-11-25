#!/usr/bin/env python3
"""Generate candidate mentions and candidate edges. No final judgement here.

Why split this from the graph assembly: an extractor that both proposes and
accepts its own output cannot be audited. This module only proposes; every
proposal carries the paragraph id, the character span and the sentence it came
from, so the later stages can reject it with a reason.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import materials as M

# --------------------------------------------------------------- rule tables

# direction semantics:
#   fwd  -> subject sits before the trigger, object after
#   rev  -> the trigger introduces the cause ("due to X"), subject after
#   obj_method -> the trigger introduces the instrument ("using X")
#   obj_value -> the trigger introduces a number ("an RMSE of 1.2 km")
RULES: list[dict[str, Any]] = [
    {"rel": "APPLIES_METHOD", "dir": "obj_method",
     "re": r"\b(?:using|used|based on|employ(?:s|ed|ing)?|with the (?:help|aid) of|by means of|driven by)\b"},
    {"rel": "TARGETS", "dir": "fwd",
     "re": r"\b(?:predict(?:s|ed|ing)?|forecast(?:s|ed|ing)?|estimat(?:e|es|ed|ing)|simulat(?:e|es|ed|ing)|detect(?:s|ed|ing)?|reproduc(?:e|es|ed|ing))\b"},
    {"rel": "EVALUATES", "dir": "fwd",
     "re": r"\b(?:evaluat(?:e|es|ed|ing)|validat(?:e|es|ed|ing)|verif(?:y|ies|ied)|assess(?:es|ed|ing)?|compar(?:e|es|ed|ing) (?:with|against))\b"},
    {"rel": "ACHIEVES", "dir": "obj_value",
     "re": r"\b(?:RMSE|MAE|accuracy|precision|recall|F1|bias|correlation coefficient|R2|skill score|hit rate|error)\b"},
    {"rel": "CAUSES", "dir": "fwd",
     "re": r"\b(?:lead(?:s|ing)? to|led to|result(?:s|ing)? in|resulted in|caus(?:e|es|ed|ing)|trigger(?:s|ed|ing)?|induc(?:e|es|ed|ing))\b"},
    {"rel": "CAUSES", "dir": "rev",
     "re": r"\b(?:due to|caused by|as a result of|attributable to|driven by)\b"},
    {"rel": "ASSOCIATED_WITH", "dir": "fwd",
     "re": r"\b(?:correlat(?:e|es|ed|ion)|associat(?:e|es|ed|ion)|related to|co-?vary|consistent with)\b"},
    {"rel": "IMPROVES_ON", "dir": "fwd",
     "re": r"\b(?:outperform(?:s|ed|ing)?|better than|superior to|improv(?:e|es|ed|ing) (?:on|over)|exceed(?:s|ed|ing)?)\b"},
    {"rel": "OCCURS_AT", "dir": "fwd",
     "re": r"\b(?:occur(?:s|red|ring)?|form(?:s|ed|ing)?|appear(?:s|ed|ing)?|observ(?:e|ed|ing) (?:at|in|over)|locat(?:e|ed|ing) (?:at|in))\b"},
    {"rel": "OBSERVED_DURING", "dir": "fwd",
     "re": r"\b(?:during|from \d{4} to \d{4}|in (?:spring|summer|autumn|fall|winter)|between \d{4} and \d{4})\b"},
    {"rel": "MEASURED_BY", "dir": "obj_method",
     "re": r"\b(?:measured (?:by|with|using)|obtained (?:by|from)|derived from|retrieved (?:by|from))\b"},
    {"rel": "PART_OF", "dir": "fwd",
     "re": r"\b(?:part of|belongs to|located in|situated in)\b"},
]

STOP_ACRONYM = {
    "THE", "AND", "FOR", "WITH", "THIS", "THAT", "FROM", "WERE", "WAS", "ARE",
    "HAS", "HAVE", "NOT", "BUT", "ALL", "ANY", "CAN", "MAY", "ITS", "THEIR",
    "THESE", "THOSE", "SUCH", "ALSO", "ONLY", "MORE", "MOST", "THAN", "THEN",
    "WHEN", "WHERE", "WHICH", "WHILE", "INTO", "OVER", "UNDER", "BETWEEN",
    "FIG", "FIGS", "TABLE", "EQ", "SECTION", "NOTE", "PMC", "DOI",
}

CITATION_RE = re.compile(r"\[\d{1,3}(?:[,\-]\d{1,3})*\]")

# "Full Name (ABBREV)" 缩写声明，例如 "critical success index (CSI)"、
# "Weather Research and Forecasting (WRF)"。全称用「括号前的词向后取最短后缀，
# 使实义词首字母按序构成缩写」来确定，避免把 "Sea using the WRF" 里多余的
# "Sea using the" 也吞进全称。
ABBREV_RE = re.compile(r"\(([A-Z][A-Z0-9]{1,9})\)")

_FILLER_WORDS = {"of", "for", "in", "the", "and", "to", "on", "with", "a", "an", "at", "by"}
_LEAD_FILLER_RE = re.compile(r"^(?:the|a|an|of|for|in|and)\s+", re.I)


def _is_subsequence(needle: str, haystack: str) -> bool:
    """needle 是否按序出现在 haystack 中（缩写的首字母校验）。"""
    it = iter(haystack)
    return all(c in it for c in needle)


def _minimal_full_name(text_before: str, abbr: str) -> str | None:
    """从缩写括号向前，找「最短」的实义词后缀，使首字母按序构成缩写。"""
    words = re.findall(r"[A-Za-z][A-Za-z]*", text_before)[-9:]
    for start in range(len(words) - 1, -1, -1):
        suffix = words[start:]
        initials = "".join(w[0].upper() for w in suffix if w.lower() not in _FILLER_WORDS)
        if initials and _is_subsequence(abbr.upper(), initials):
            full = _LEAD_FILLER_RE.sub("", " ".join(suffix)).strip()
            if len(full.split()) >= 2:
                return full
    return None


def detect_abbreviations(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    """扫描各段原文，识别 "全称 (缩写)" 声明，作为同篇别名合并的自动候选。

    只提出候选、不裁决：最终是否合并由 align.py 按 (source_id, type) 是否一致
    决定，并记录 basis=abbreviation_pattern；类型不一致则记为 type_conflict 候选。
    """
    pairs: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    for src in parsed["sources"]:
        sid = src["source_id"]
        for para in src["paragraphs"]:
            text = para["text"]
            for m in ABBREV_RE.finditer(text):
                abbr = m.group(1).strip()
                full = _minimal_full_name(text[:m.start()], abbr)
                if not full:
                    continue
                key = (sid, full.lower(), abbr)
                if key in seen:
                    continue
                seen.add(key)
                pairs.append({
                    "source_id": sid, "paragraph_id": para["paragraph_id"],
                    "full": full, "abbrev": abbr,
                    "quote": text[max(0, m.start() - 30):m.end() + 30].strip(),
                    "basis": "abbreviation_pattern",
                })
    return pairs


def find_mentions(text: str, lexicon: dict[str, Any]) -> list[dict[str, Any]]:
    """Return non-overlapping candidate mentions with offsets."""
    taken: list[tuple[int, int]] = []
    out: list[dict[str, Any]] = []

    def free(a: int, b: int) -> bool:
        return all(b <= x or a >= y for x, y in taken)

    def push(a: int, b: int, hint: str, how: str) -> None:
        if not free(a, b):
            return
        surface = text[a:b].strip()
        if len(surface) < 2:
            return
        taken.append((a, b))
        out.append({"surface": surface, "start": a, "end": b, "type_hint": hint, "found_by": how})

    # 1) lexicon terms, longest first so "sea fog" beats "fog"
    pairs: list[tuple[str, str]] = []
    for hint in ("PHENOMENON", "METHOD", "DATASET", "VARIABLE"):
        for term in lexicon.get(hint, []):
            pairs.append((term, hint))
    for term, hint in sorted(pairs, key=lambda x: -len(x[0])):
        pattern = r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])"
        for m in re.finditer(pattern, text, re.I):
            push(m.start(), m.end(), hint, "lexicon")

    # 2) acronyms and product-like tokens
    for m in re.finditer(r"\b[A-Z][A-Za-z0-9]{1,9}(?:-[A-Z0-9]{1,6})?\b", text):
        tok = m.group(0)
        upper = sum(1 for c in tok if c.isupper())
        has_digit = any(c.isdigit() for c in tok)
        if tok.upper() in STOP_ACRONYM:
            continue
        if upper < 2 and not has_digit:
            continue
        if tok.lower() == tok:
            continue
        push(m.start(), m.end(), "METHOD", "acronym")

    # 2b) method noun phrases: a bare "model" is too generic to be a node, but
    # "numerical model", "WRF model" or "machine learning model" name a method.
    for m in re.finditer(
            r"\b((?:[A-Za-z][\w-]*\s+){0,3}(?:models?|simulations?|schemes?|algorithms?|networks?|parameteri[sz]ations?|experiments?))\b",
            text, re.I):
        phrase = m.group(1)
        head = re.split(r"\s+", phrase)[0].lower()
        lead = {"the", "this", "these", "those", "a", "an", "such", "same", "each", "its",
                "in", "on", "at", "of", "for", "with", "by", "from", "to", "as", "and",
                "or", "that", "which", "their", "our", "its", "two", "three", "both"}
        if len(phrase.split()) < 2 or head in lead:
            continue
        if phrase.lower().strip() in {"numerical model", "weather model"}:
            pass
        push(m.start(), m.end(), "METHOD", "noun_phrase")

    # 3) capitalised place names
    for m in re.finditer(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2}\b", text):
        tok = m.group(0)
        if any(tok.endswith(s) for s in lexicon.get("LOCATION_SUFFIX", [])):
            push(m.start(), m.end(), "LOCATION", "proper")

    # 4) quantities with units
    unit_re = "|".join(re.escape(u) for u in sorted(lexicon.get("UNITS", []), key=len, reverse=True))
    if unit_re:
        for m in re.finditer(r"\b\d+(?:\.\d+)?\s*(?:" + unit_re + r")(?![A-Za-z0-9])", text):
            push(m.start(), m.end(), "VALUE", "quantity")

    # 5) years and ranges
    for m in re.finditer(r"\b(?:19|20)\d{2}\s*(?:[-–]\s*(?:19|20)\d{2})?\b", text):
        push(m.start(), m.end(), "TIME_PERIOD", "year")

    out.sort(key=lambda x: x["start"])
    return out


def strength_of(sentence: str, schema: dict[str, Any]) -> dict[str, Any]:
    """Classify evidence as this paper's own result or a citation of someone else's."""
    low = sentence.lower()
    if CITATION_RE.search(sentence) or re.search(
            r"\b(?:reported by|previous stud|earlier stud|have shown|has shown|was reported|et al\.)", low):
        cls = "cited"
        attribution = "cited_work"
    elif re.search(r"\b(?:may|might|could|we hypothesi[sz]e|is likely|suggest(?:s|ed)?)\b", low):
        cls = "hypothesis"
        attribution = "this_paper"
    elif re.search(r"\b(?:we found|our results|this study|we show|our simulation|the present study)\b", low):
        cls = "own_result"
        attribution = "this_paper"
    elif re.search(r"\b(?:we used|we applied|we conducted|in this study)\b", low):
        cls = "own_method"
        attribution = "this_paper"
    elif re.search(r"\b(?:it is well known|generally|in general|typically|is known to)\b", low):
        cls = "review"
        attribution = "background"
    else:
        cls = "background"
        attribution = "this_paper"
    spec = schema["evidence_strength"][cls]
    return {"class": cls, "weight": spec["weight"], "attribution": attribution}


def _nearest(mentions: list[dict], pos: int, side: str, types: set[str] | None) -> dict | None:
    pool = [m for m in mentions if (types is None or m["type_hint"] in types)]
    if side == "before":
        cand = [m for m in pool if m["end"] <= pos]
        return max(cand, key=lambda m: m["end"]) if cand else None
    cand = [m for m in pool if m["start"] >= pos]
    return min(cand, key=lambda m: m["start"]) if cand else None


SUBJECT_TYPES = {"PHENOMENON", "DATASET", "VARIABLE", "LOCATION", "METHOD", "TIME_PERIOD"}
METHOD_TAKERS = {"PHENOMENON", "DATASET", "VARIABLE", "LOCATION"}


def relation_candidates(sentence: str, offset: int, mentions: list[dict],
                        schema: dict[str, Any]) -> list[dict[str, Any]]:
    """Propose edges from one sentence. Direction comes from token position.

    The nearest mention *of an allowed type* is used, not simply the nearest
    mention: a number or a year sitting between the verb and its object must not
    cancel the edge.
    """
    out: list[dict] = []
    for rule in RULES:
        spec = schema["relation_types"].get(rule["rel"])
        if not spec:
            continue
        dom = set(spec["domain"]) - {"*"}
        rng = set(spec["range"]) - {"*"}
        dom = dom or SUBJECT_TYPES
        any_range = not rng
        for m in re.finditer(rule["re"], sentence, re.I):
            trig_at = m.start()
            if rule["dir"] == "fwd":
                subj = _nearest(mentions, trig_at, "before", dom)
                obj = _nearest(mentions, trig_at, "after", None if any_range else rng)
            elif rule["dir"] == "rev":
                subj = _nearest(mentions, trig_at, "after", dom)
                obj = _nearest(mentions, trig_at, "before", None if any_range else rng)
            elif rule["dir"] == "obj_method":
                subj = _nearest(mentions, trig_at, "before", dom & METHOD_TAKERS)
                obj = _nearest(mentions, trig_at, "after",
                               (rng or {"METHOD"}) & {"METHOD", "DATASET", "VARIABLE"})
            else:  # obj_value
                subj = _nearest(mentions, trig_at, "before", dom & {"METHOD"})
                obj = _nearest(mentions, trig_at, "after", {"VALUE"})
            if not subj or not obj or subj is obj:
                continue
            if not any_range and obj["type_hint"] not in rng:
                continue
            out.append({
                "relation": rule["rel"],
                "trigger": m.group(0),
                "subject_surface": subj["surface"],
                "subject_type": subj["type_hint"],
                "object_surface": obj["surface"],
                "object_type": obj["type_hint"],
                "subject_span": [offset + subj["start"], offset + subj["end"]],
                "object_span": [offset + obj["start"], offset + obj["end"]],
                "quote": sentence.strip(),
                "dir": rule["dir"],
                "strength": strength_of(sentence, schema),
            })
    return out


def prepare(parsed: dict[str, Any], lexicon: dict[str, Any], schema: dict[str, Any],
            limit_per_source: int = 40) -> dict[str, Any]:
    entities: list[dict] = []
    edges: list[dict] = []
    stats = {"paragraphs": 0, "sentences": 0, "mentions": 0, "edges": 0}

    for src in parsed["sources"]:
        sid = src["source_id"]
        emitted = 0
        for para in src["paragraphs"]:
            stats["paragraphs"] += 1
            text = para["text"]
            para_mentions = find_mentions(text, lexicon)
            stats["mentions"] += len(para_mentions)
            for m in para_mentions:
                entities.append({
                    "source_id": sid, "paragraph_id": para["paragraph_id"],
                    "surface": m["surface"], "type_hint": m["type_hint"],
                    "found_by": m["found_by"],
                    "span": [m["start"], m["end"]],
                    "quote": text[max(0, m["start"] - 40):m["end"] + 40].strip(),
                })
            for a, b in M.iter_sentences(text):
                stats["sentences"] += 1
                sent = text[a:b]
                if len(sent) < 30:
                    continue
                local = [m for m in para_mentions if m["start"] >= a and m["end"] <= b]
                if len(local) < 2:
                    continue
                rels = relation_candidates(sent, a, local, schema)
                for r in rels:
                    r.update({"source_id": sid, "paragraph_id": para["paragraph_id"]})
                edges.extend(rels)
                emitted += len(rels)
            if emitted >= limit_per_source:
                break
        stats.setdefault("per_source", {})[sid] = emitted

    # trim duplicate candidates on the same span pair
    seen: set[tuple] = set()
    uniq_edges = []
    for e in edges:
        key = (e["source_id"], e["paragraph_id"], e["relation"],
               e["subject_surface"].lower(), e["object_surface"].lower())
        if key in seen:
            continue
        seen.add(key)
        uniq_edges.append(e)
    stats["edges"] = len(uniq_edges)
    stats["entities"] = len(entities)

    abbreviations = detect_abbreviations(parsed)
    stats["abbreviation_candidates"] = len(abbreviations)

    return {
        "case_id": parsed["case_id"],
        "sources": parsed["sources"],
        "manifest": parsed["manifest"],
        "warnings": parsed["warnings"],
        "lexicon": lexicon,
        "stats": stats,
        "candidates": {"entities": entities, "edges": uniq_edges},
        "abbreviation_candidates": abbreviations,
    }


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="生成实体与关系候选")
    ap.add_argument("--case", required=True)
    ap.add_argument("--lexicon", required=True)
    ap.add_argument("--schema", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    parsed = M.load_case(Path(args.case))
    lexicon = json.loads(Path(args.lexicon).read_text(encoding="utf-8"))
    schema = json.loads(Path(args.schema).read_text(encoding="utf-8"))
    pack = prepare(parsed, lexicon, schema)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: pack["stats"][k] for k in ("paragraphs", "sentences", "mentions", "entities", "edges")},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
