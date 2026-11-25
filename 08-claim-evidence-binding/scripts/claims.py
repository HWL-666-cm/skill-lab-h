#!/usr/bin/env python3
"""Extract checkable anchors from material: citations, figures, limitations,
contributions, key works.  No judgement here -- this says "these strings exist
at these positions", never "this claim is correct".

The case materials may be a LaTeX project (.bib + .tex), a plain manuscript
(Markdown/PDF text), or a mix.  We therefore parse several shapes and keep the
source + locator + verbatim quote for every anchor, so a later gate can bind a
sentence in the draft back to the exact line it leans on.
"""
from __future__ import annotations

import re
from typing import Any

# ---------- small helpers ----------

def _line_of(unit: dict) -> int:
    loc = str(unit.get("locator", ""))
    m = re.search(r"(\d+)", loc)
    return int(m.group(1)) if m else 0


def _text_of(unit: dict) -> str:
    for key in ("text", "line", "value", "raw", "quote"):
        v = unit.get(key)
        if isinstance(v, str) and v.strip():
            return v
    return ""


def _sentences(text: str) -> list[str]:
    """Split on sentence boundaries for English and Chinese.

    Two real failures this guards against (found on the first end-to-end run):
      * headings ("## 研究背景") were being counted as claims;
      * abbreviations like "et al." / "Fig." split a sentence in half, so the
        citation and its verb ended up in different rows.
    """
    # protect abbreviations before splitting
    protected = text
    repl: dict[str, str] = {}
    for i, abbr in enumerate(("et al.", "Fig.", "Tab.", "e.g.", "i.e.", "Eq.", "Sec.", "vs.")):
        token = f"\x00ABBR{i}\x00"
        repl[token] = abbr
        protected = re.sub(re.escape(abbr), token, protected, flags=re.I)
    parts = re.split(r"(?<=[.!?。！？;；])\s+|[\n]+", protected)
    out: list[str] = []
    for p in parts:
        for token, abbr in repl.items():
            p = p.replace(token, abbr)
        s = p.strip()
        if not s or len(s) < 4:
            continue
        # LaTeX comments (and inline % comments) are not prose claims.  A real
        # arXiv introduction contained marginpar comments that were being
        # reported as unanchored sentences.
        if s.startswith("%"):
            continue
        s = re.sub(r"(?<!\\)%.*$", "", s).strip()
        if len(s) < 4:
            continue
        if re.match(r"^#{1,6}\s", s):        # markdown heading is not a claim
            continue
        if re.match(r"^(?:[-*•]|\d+\.)\s*$", s):
            continue
        out.append(s)
    return out


def _any(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text, re.I) for p in patterns)


# ---------- 1. citation entries (bibliography) ----------

BIB_FIELDS = ("title", "author", "year", "journal", "booktitle", "publisher", "volume", "pages")


def _bib_blocks(tex: str) -> list[dict]:
    """Parse @type{key, field={value}, ...} blocks."""
    out: list[dict] = []
    for m in re.finditer(r"@(\w+)\s*\{\s*([^,\s]+)\s*,", tex):
        typ, key = m.group(1), m.group(2)
        i = m.end()
        depth, start = 1, i
        # find balanced block body
        while i < len(tex) and depth:
            c = tex[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            i += 1
        body = tex[start:i - 1] if depth == 0 else tex[start:]
        fields: dict[str, str] = {}
        for fm in re.finditer(r"(\w+)\s*=\s*\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}", body):
            fields[fm.group(1).lower()] = " ".join(fm.group(2).split())
        out.append({"kind": "bib", "key": key, "entry_type": typ,
                    "fields": {k: fields[k] for k in BIB_FIELDS if k in fields},
                    "raw": " ".join(body.split())[:400]})
    return out


def _bibitem_refs(tex: str, source: str = "") -> list[dict]:
    """Parse embedded `\\bibitem{key} Author. Title. Venue, Year.` blocks.

    Found on a real arXiv source (Attention Is All You Need): the references
    are inline in ms.tex via thebibliography, not in a .bib file.  Missing this
    shape means zero references for a very common LaTeX form.
    """
    out: list[dict] = []
    for m in re.finditer(r"\\bibitem(?:\[[^\]]*\])?\s*\{([^}]+)\}\s*(.*?)(?=\\bibitem|\n\s*\\end\{thebibliography\}|\Z)",
                         tex, re.S):
        key, body = m.group(1), m.group(2)
        clean = " ".join(re.sub(r"\\[a-zA-Z]+\s*\{?\}?", " ", body).split())
        year = re.search(r"\b((?:19|20)\d{2})\b", clean)
        author = re.match(r"^([A-Z][A-Za-z\-']+(?:\s+(?:and|&)\s+[A-Z][A-Za-z\-']+|(?:\s+et\s+al\.?)?)?)", clean)
        # title = text up to the year or first 160 chars
        title = clean[:160]
        out.append({"kind": "bibitem", "key": key,
                    "fields": {"author": author.group(1) if author else "",
                               "year": year.group(1) if year else "",
                               "title": title},
                    "raw": clean[:400], "source": source, "locator": ""})
    return out


def _numbered_refs(units: list[dict]) -> list[dict]:
    """Parse [1] Author, Title. Venue, Year. style reference lists."""
    out: list[dict] = []
    for u in units:
        t = _text_of(u).strip()
        m = re.match(r"^\s*\[(\d{1,3})[\].\s]\s*(.+)$", t)
        if not m:
            continue
        num, rest = m.group(1), m.group(2).strip()
        year = re.search(r"\b((?:19|20)\d{2})\b", rest)
        author = re.match(r"^([A-Z][A-Za-z\-']+(?:\s+and\s+[A-Z][A-Za-z\-']+|(?:\s+et\s+al\.?)?)?)", rest)
        out.append({"kind": "numbered_ref", "key": num, "number": num,
                    "fields": {"author": author.group(1) if author else "",
                               "year": year.group(1) if year else ""},
                    "raw": rest[:400], "source": u.get("source", ""),
                    "locator": u.get("locator", "")})
    return out


def _author_year_refs(units: list[dict]) -> list[dict]:
    """Parse `Author, A. (2020). Title. Venue.` reference lines."""
    out: list[dict] = []
    for u in units:
        t = _text_of(u).strip()
        m = re.match(r"^\s*([A-Z][A-Za-z\-']+(?:\s*(?:&|and)\s*[A-Z][A-Za-z\-']+)?(?:\s+et\s+al\.)?)\s*[,]?\s*\(((?:19|20)\d{2})[a-z]?\)[\.,\s]+(.+)$", t)
        if not m:
            continue
        out.append({"kind": "author_year_ref", "key": f"{m.group(1).split()[0]}{m.group(2)}",
                    "fields": {"author": m.group(1), "year": m.group(2),
                               "title": m.group(3)[:200]},
                    "raw": t[:400], "source": u.get("source", ""),
                    "locator": u.get("locator", "")})
    return out


def extract_reference_entries(pack: dict) -> list[dict]:
    """All bibliographic entries we can find, with stable keys."""
    out: list[dict] = []
    for f in pack.get("files", []):
        src = f.get("source", "")
        if not src.lower().endswith((".tex", ".bib", ".md", ".markdown", ".txt", ".rst")):
            continue
        units = [u for u in pack.get("units", []) if u.get("source") == src]
        tex = "\n".join(_text_of(u) for u in units)
        if src.lower().endswith((".tex", ".bib")):
            out.extend(_bib_blocks(tex))
            out.extend(_bibitem_refs(tex, src))
    out.extend(_numbered_refs(pack.get("units", [])))
    out.extend(_author_year_refs(pack.get("units", [])))
    # de-duplicate by (kind, key)
    seen: set[tuple[str, str]] = set()
    uniq: list[dict] = []
    for r in out:
        k = (r["kind"], str(r.get("key", "")))
        if k in seen:
            continue
        seen.add(k)
        uniq.append(r)
    return uniq


# ---------- 2. figure / table anchors ----------

def extract_figure_anchors(pack: dict, patterns: list[dict]) -> list[dict]:
    out: list[dict] = []
    for u in pack.get("units", []):
        text = _text_of(u)
        for p in patterns:
            for m in re.finditer(p["regex"], text, re.I):
                out.append({"kind": p["kind"], "label": m.group(0).strip(),
                            "number": m.group(1) if m.lastindex else "",
                            "source": u.get("source", ""),
                            "locator": u.get("locator", ""),
                            "quote": text[max(0, m.start() - 60):m.end() + 100].strip()[:260]})
    # de-duplicate by (kind, number, source)
    seen, uniq = set(), []
    for a in out:
        k = (a["kind"], a["number"], a["source"])
        if k not in seen:
            seen.add(k)
            uniq.append(a)
    return uniq


# ---------- 3. limitation / gap / contribution statements from materials ----------

def extract_material_claims(pack: dict, lex: dict) -> dict:
    gap_pat = lex.get("gap_signals", [])
    contrib_pat = lex.get("contribution_signals", [])
    gaps: list[dict] = []
    contribs: list[dict] = []

    for u in pack.get("units", []):
        text = _text_of(u)
        if not text:
            continue
        for s in _sentences(text):
            row = {"text": s[:400], "source": u.get("source", ""),
                   "locator": u.get("locator", ""), "source_kind": u.get("source_kind", "")}
            if _any(gap_pat, s):
                gaps.append(dict(row, claim_type="gap"))
            if _any(contrib_pat, s):
                contribs.append(dict(row, claim_type="contribution"))
    return {"gaps": gaps[:200], "contributions": contribs[:200]}


# ---------- 4. key works mentioned in materials ----------

def extract_key_works(refs: list[dict], pack: dict) -> list[dict]:
    """A work is 'key' if it appears in the reference list.  We do not guess
    importance from adjectives; presence in the bibliography is the criterion."""
    out: list[dict] = []
    alltext = "\n".join(_text_of(u) for u in pack.get("units", [])).lower()
    for r in refs:
        f = r.get("fields", {})
        name = f.get("author") or str(r.get("key", ""))
        title = f.get("title") or ""
        cited_in_body = False
        key = str(r.get("key", ""))
        if key and re.search(r"\\cite[a-zA-Z]*\s*\{[^}]*" + re.escape(key), alltext, re.I):
            cited_in_body = True
        if title and title.lower()[:40] in alltext:
            cited_in_body = True
        out.append({"key": key, "author": name, "year": f.get("year", ""),
                    "title": title, "cited_in_body": cited_in_body,
                    "source": r.get("source", ""), "locator": r.get("locator", "")})
    return out


# ---------- 5. structure signals ----------

def structure_signals(pack: dict, lex: dict) -> dict:
    """Which sections / grouping dimensions exist in the MATERIAL (not the draft)."""
    units = pack.get("units", [])
    heads = [_text_of(u).strip() for u in units if _text_of(u).strip().startswith("#")]
    section_hits: dict[str, int] = {}
    for sec, names in lex.get("section_names", {}).items():
        section_hits[sec] = sum(1 for h in heads if _any([re.escape(n) for n in names], h))
    dim_hits: list[str] = []
    for h in heads:
        for d in lex.get("group_dimensions", []):
            if d.lower() in h.lower() and d not in dim_hits:
                dim_hits.append(d)
    return {"headings_sample": heads[:40], "section_hits": section_hits,
            "group_dimensions_in_material": dim_hits}


def extract(pack: dict, lex: dict) -> dict:
    refs = extract_reference_entries(pack)
    figs = extract_figure_anchors(pack, lex.get("figure_patterns", []))
    mclaims = extract_material_claims(pack, lex)
    works = extract_key_works(refs, pack)
    stats = {"references": len(refs), "figures": len(figs),
             "material_gaps": len(mclaims["gaps"]),
             "material_contributions": len(mclaims["contributions"]),
             "key_works": len(works)}
    return {"references": refs, "figures": figs, "material_claims": mclaims,
            "key_works": works, "structure": structure_signals(pack, lex),
            "stats": stats}


if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path
    lex = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import materials as M
    pack = M.read_material(Path(sys.argv[1]))
    print(json.dumps(extract(pack, lex)["stats"], ensure_ascii=False, indent=2))
