#!/usr/bin/env python3
"""Load the case materials into one paragraph index.

Two input shapes are supported on purpose, because the platform bundle and a
local corpus do not arrive in the same form:

1. JSON material files (corpus-manifest.json / material.json /
   primary-material.json / secondary-material.json). Field names vary between
   revisions, so every reader below accepts a small set of synonyms instead of
   one hard-coded spelling.
2. JATS XML files. When a bundle ships the publisher XML rather than a
   pre-segmented index, paragraphs are read straight from <body>/<abstract>/
   <caption>.

Rule that matters for this task: the position of a piece of evidence is the
organizer's JATS paragraph id. If a paragraph carries no id, we generate a
stable one and label it `generated` -- we never present a generated id as if it
came from the publisher, and we never invent a PDF page number.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable

# ---------------------------------------------------------------- normalising

_SPACE = {
    "\u00a0": " ", "\u2007": " ", "\u202f": " ", "\u2009": " ",
    "\u200a": " ", "\u200b": "", "\ufeff": "",
}
_QUOTE = {
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"',
    "\u2032": "'", "\u2033": '"',
}
_DASH = {
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-",
    "\u2014": "-", "\u2212": "-", "\u2015": "-",
}
_LIGATURE = {
    "\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi",
    "\ufb04": "ffl", "\ufb05": "st", "\ufb06": "st",
}


def norm_text(text: str) -> str:
    """Fold typographic variants so a quote copied from the text always matches."""
    out = []
    for ch in text:
        if ch in _LIGATURE:
            out.append(_LIGATURE[ch])
        elif ch in _SPACE:
            out.append(_SPACE[ch])
        elif ch in _QUOTE:
            out.append(_QUOTE[ch])
        elif ch in _DASH:
            out.append(_DASH[ch])
        else:
            out.append(ch)
    s = unicodedata.normalize("NFKC", "".join(out))
    s = re.sub(r"\s+", " ", s).strip()
    return s


def norm_key(text: str) -> str:
    """Key used for blocking: lowercase alphanumerics only."""
    return re.sub(r"[^a-z0-9]", "", norm_text(text).lower())


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------- JATS

def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _text_of(node: ET.Element) -> str:
    return norm_text("".join(node.itertext()))


def _child(node: ET.Element, name: str) -> ET.Element | None:
    """First direct child with this local name (namespace-agnostic)."""
    for c in node:
        if _localname(c.tag) == name:
            return c
    return None


def _caption_id(node: ET.Element, prefix: str, n: int) -> str:
    raw = node.get("id")
    return raw if raw else f"{prefix}{n}"


def parse_jats(path: Path, source_id: str | None = None) -> dict[str, Any]:
    """Read one JATS article into a source record with paragraph-level ids."""
    raw = path.read_bytes()
    root = ET.fromstring(raw)

    def first(xpath: str) -> ET.Element | None:
        for el in root.iter():
            if _localname(el.tag) == xpath:
                return el
        return None

    sid = source_id or path.stem
    title_el = first("article-title")
    doi_el = None
    for el in root.iter():
        if _localname(el.tag) == "article-id" and el.get("pub-id-type") == "doi":
            doi_el = el
            break
    license_el = first("license")
    license_url = ""
    if license_el is not None:
        ref = ""
        for el in license_el.iter():
            if _localname(el.tag) == "license_ref" and (el.text or "").strip():
                ref = el.text.strip()
                break
        license_url = (ref
                       or license_el.get("{http://www.w3.org/1999/xlink}href")
                       or license_el.get("license-type") or "").strip()
    year = ""
    for el in root.iter():
        if _localname(el.tag) == "pub-date":
            y = _child(el, "year")
            if y is not None and y.text:
                year = y.text.strip()
                break
    authors: list[str] = []
    for el in root.iter():
        if _localname(el.tag) == "contrib" and el.get("contrib-type") in (None, "author"):
            sn = gn = None
            for c in el.iter():
                name = _localname(c.tag)
                if name == "surname" and sn is None:
                    sn = c
                elif name == "given-names" and gn is None:
                    gn = c
            if sn is not None and sn.text:
                authors.append(" ".join(x for x in [gn.text if gn is not None else "", sn.text] if x).strip())

    paragraphs: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    def add(kind: str, section: str, text: str, pid: str | None) -> None:
        text = norm_text(text)
        if len(text) < 40:          # titles, table cells, stray fragments
            return
        base = pid or f"p{len(paragraphs) + 1:03d}"
        candidate, k = base, 1
        while candidate in seen_ids:
            k += 1
            candidate = f"{base}-{k}"
        seen_ids.add(candidate)
        paragraphs.append({
            "paragraph_id": candidate,
            "section": section,
            "kind": kind,
            "text": text,
            "id_source": "publisher" if pid else "generated",
        })

    body = None
    for el in root.iter():
        if _localname(el.tag) == "body":
            body = el
            break

    def walk_sec(sec: ET.Element, trail: list[str]) -> None:
        title = ""
        for child in sec:
            if _localname(child.tag) == "title":
                title = _text_of(child)
                break
        path_names = trail + ([title] if title else [])
        for child in sec:
            name = _localname(child.tag)
            if name == "sec":
                walk_sec(child, path_names)
            elif name == "p":
                add("body", " > ".join(path_names), _text_of(child), child.get("id"))

    if body is not None:
        for child in body:
            name = _localname(child.tag)
            if name == "sec":
                walk_sec(child, [])
            elif name == "p":
                add("body", "", _text_of(child), child.get("id"))

    abstract = None
    for el in root.iter():
        if _localname(el.tag) == "abstract":
            abstract = el
            break
    if abstract is not None:
        for p in abstract.iter():
            if _localname(p.tag) == "p":
                add("abstract", "Abstract", _text_of(p), p.get("id"))

    fig_n = tab_n = 0
    for el in root.iter():
        name = _localname(el.tag)
        if name == "fig":
            fig_n += 1
            cap = next((c for c in el.iter() if _localname(c.tag) == "caption"), None)
            if cap is not None:
                add("caption", "Figure caption", _text_of(cap), _caption_id(el, "f", fig_n))
        elif name == "table-wrap":
            tab_n += 1
            cap = next((c for c in el.iter() if _localname(c.tag) == "caption"), None)
            if cap is not None:
                add("caption", "Table caption", _text_of(cap), _caption_id(el, "t", tab_n))

    return {
        "source_id": sid,
        "doi": (doi_el.text or "").strip() if doi_el is not None else "",
        "title": _text_of(title_el) if title_el is not None else "",
        "authors": authors,
        "year": year,
        "license": license_url,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "path": path.name,
        "paragraphs": paragraphs,
    }


# --------------------------------------------------------------------- JSON

_TEXT_KEYS = ("text", "content", "body", "value", "paragraph", "sentence_text")
_ID_KEYS = ("paragraph_id", "para_id", "pid", "id", "paragraphId", "uid")
_SEC_KEYS = ("section", "section_title", "heading", "sec", "sectionTitle")


def _pick(d: dict, keys: Iterable[str], default=None):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return default


def normalise_paragraphs(items: list[dict], fallback_section: str = "") -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for raw in items:
        if not isinstance(raw, dict):
            continue
        text = norm_text(str(_pick(raw, _TEXT_KEYS, "") or ""))
        if len(text) < 40:
            continue
        pid_raw = _pick(raw, _ID_KEYS)
        pid = str(pid_raw).strip() if pid_raw else f"p{len(out) + 1:03d}"
        base, k = pid, 1
        while pid in seen:
            k += 1
            pid = f"{base}-{k}"
        seen.add(pid)
        out.append({
            "paragraph_id": pid,
            "section": str(_pick(raw, _SEC_KEYS, fallback_section) or ""),
            "kind": str(raw.get("kind") or raw.get("type") or "body"),
            "text": text,
            # an id that the material itself marks as generated stays marked
            "id_source": str(raw.get("id_source") or ("publisher" if pid_raw else "generated")),
        })
    return out


def _source_from_json(obj: Any, fallback_id: str) -> dict[str, Any]:
    """Accept {source_id, paragraphs:[...]} or {meta, paragraphs} or a bare list."""
    if isinstance(obj, list):
        obj = {"source_id": fallback_id, "paragraphs": obj}
    if not isinstance(obj, dict):
        return {"source_id": fallback_id, "paragraphs": []}
    meta = obj.get("meta") or obj.get("metadata") or {}
    paras = None
    for key in ("paragraphs", "paras", "blocks", "content", "sections", "items"):
        if isinstance(obj.get(key), list):
            paras = obj[key]
            break
    if paras is None and isinstance(meta.get("paragraphs"), list):
        paras = meta["paragraphs"]
    sid = str(_pick(obj, ("source_id", "sourceId", "id", "paper_id", "doi"), fallback_id) or fallback_id)
    return {
        "source_id": sid,
        "doi": str(_pick(obj, ("doi", "DOI"), "") or ""),
        "title": str(_pick(obj, ("title", "paper_title"), "") or ""),
        "authors": obj.get("authors") or [],
        "year": str(_pick(obj, ("year", "pubYear", "pub_year"), "") or ""),
        "license": str(_pick(obj, ("license", "licence", "rights"), "") or ""),
        "sha256": str(_pick(obj, ("sha256", "hash", "checksum"), "") or ""),
        "path": "",
        "paragraphs": normalise_paragraphs(paras or []),
    }


# -------------------------------------------------------------- case loading

CASE_KEYS = ("sources", "papers", "documents", "items", "corpus", "materials")


def _sources_of(obj: Any, fallback: str) -> list[dict]:
    if isinstance(obj, list):
        return [s for s in (_source_from_json(x, f"{fallback}-{i + 1}") for i, x in enumerate(obj)) if s["paragraphs"]]
    if isinstance(obj, dict):
        for key in CASE_KEYS:
            if isinstance(obj.get(key), list):
                return [s for s in (_source_from_json(x, f"{fallback}-{i + 1}") for i, x in enumerate(obj[key])) if s["paragraphs"]]
        if any(k in obj for k in ("paragraphs", "paras", "blocks")):
            s = _source_from_json(obj, fallback)
            return [s] if s["paragraphs"] else []
    return []


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_case(case_path: Path) -> dict[str, Any]:
    """Return {case_id, sources, manifest, warnings, input_dir}."""
    case_path = Path(case_path)
    warnings: list[str] = []
    case: dict[str, Any] = {}
    if case_path.is_file():
        case = _read_json(case_path) or {}
        base = case_path.parent
    else:
        base = case_path
        for name in ("case.json", "input.json"):
            if (base / name).is_file():
                case = _read_json(base / name) or {}
                break

    case_id = str(case.get("case_id") or case.get("caseId") or base.name)
    sources: list[dict] = []

    # 1) explicit lists inside case.json
    sources.extend(_sources_of(case, case_id))

    # 2) named material files next to case.json
    if not sources:
        for name in ("primary-material.json", "secondary-material.json"):
            p = base / name
            if p.is_file():
                sources.extend(_sources_of(_read_json(p), p.stem.replace("-material", "")))
        agg = base / "material.json"
        if agg.is_file():
            loaded = _sources_of(_read_json(agg), "material")
            if loaded:
                sources = loaded          # the aggregate supersedes split files
            else:
                warnings.append("material.json present but no paragraph list recognised")

    # 3) JATS XML fallback
    if not sources:
        xmls = sorted(base.glob("*.xml")) + sorted((base / "raw").glob("*.xml")) if (base / "raw").is_dir() else sorted(base.glob("*.xml"))
        for x in xmls:
            try:
                sources.append(parse_jats(x))
            except Exception as exc:      # malformed XML is reported, not fatal
                warnings.append(f"cannot parse {x.name}: {exc}")

    manifest: list[dict] = []
    mf = base / "corpus-manifest.json"
    if mf.is_file():
        data = _read_json(mf) or {}
        if isinstance(data, dict):
            for key in CASE_KEYS:
                if isinstance(data.get(key), list):
                    manifest = data[key]
                    break
        elif isinstance(data, list):
            manifest = data
    if not manifest:
        manifest = [{k: s.get(k) for k in ("source_id", "doi", "title", "authors", "year", "license", "sha256")} for s in sources]
        warnings.append("corpus-manifest.json absent; manifest rebuilt from material files")

    # de-duplicate sources by id, keep the richer one
    merged: dict[str, dict] = {}
    for s in sources:
        sid = s["source_id"]
        if sid not in merged or len(s["paragraphs"]) > len(merged[sid]["paragraphs"]):
            merged[sid] = s
    sources = list(merged.values())

    # manifest metadata wins for bibliographic fields, material files for text
    meta_by_id = {}
    for m in manifest:
        if isinstance(m, dict) and m.get("source_id"):
            meta_by_id[str(m["source_id"])] = m
    for s in sources:
        meta = meta_by_id.get(s["source_id"], {})
        for key in ("doi", "title", "year", "license", "sha256"):
            if not s.get(key) and meta.get(key):
                s[key] = meta[key]
        if not s.get("authors") and meta.get("authors"):
            s["authors"] = meta["authors"]

    # a generated paragraph id must be announced, never passed off as publisher
    for s in sources:
        n_gen = sum(1 for p in s["paragraphs"] if p["id_source"] == "generated")
        if n_gen:
            warnings.append(
                f"{s['source_id']}: {n_gen}/{len(s['paragraphs'])} paragraph ids generated "
                "(publisher XML had no id attribute); no PDF page number is claimed"
            )

    return {
        "case_id": case_id,
        "sources": sources,
        "manifest": manifest,
        "warnings": warnings,
        "input_dir": str(base),
        "case_raw": case,
    }


def paragraph_index(parsed: dict) -> dict[tuple[str, str], dict]:
    idx = {}
    for s in parsed["sources"]:
        for p in s["paragraphs"]:
            idx[(s["source_id"], p["paragraph_id"])] = {**p, "source_id": s["source_id"]}
    return idx


def iter_sentences(text: str) -> list[tuple[int, int]]:
    """Split on sentence-final punctuation, keeping offsets into `text`."""
    out: list[tuple[int, int]] = []
    start, i, n = 0, 0, len(text)
    abbrev = {"e.g.", "i.e.", "et al.", "fig.", "figs.", "eq.", "no.", "vs.", "approx.",
              "cf.", "resp.", "ca.", "dr.", "prof.", "st.", "u.s.", "al."}
    while i < n:
        ch = text[i]
        if ch in ".!?":
            j = i + 1
            while j < n and text[j] in "\"')]":
                j += 1
            if j >= n or text[j] == " ":
                tail = text[max(start, i - 6):i + 1].lower()
                if ch == "." and any(tail.endswith(a) for a in abbrev):
                    i += 1
                    continue
                if ch == "." and i > 0 and text[i - 1].isdigit() and j < n and text[j:j + 2].strip().isdigit():
                    i += 1
                    continue
                seg = text[start:j]
                if seg.strip():
                    out.append((start, j))
                start = j
                i = j
                continue
        i += 1
    if start < n and text[start:].strip():
        out.append((start, n))
    return out


def main() -> int:
    """CLI: print what the loader saw, so a human can confirm the input shape."""
    import argparse
    ap = argparse.ArgumentParser(description="查看材料结构（只读）")
    ap.add_argument("--case", required=True, help="case.json 或材料目录")
    ap.add_argument("--sample", type=int, default=2, help="每篇打印几段样例")
    args = ap.parse_args()
    parsed = load_case(Path(args.case))
    print(json.dumps({"case_id": parsed["case_id"], "input_dir": parsed["input_dir"],
                      "sources": [{"source_id": s["source_id"], "doi": s.get("doi"),
                                   "year": s.get("year"), "license": s.get("license"),
                                   "paragraphs": len(s["paragraphs"]),
                                   "generated_ids": sum(1 for p in s["paragraphs"]
                                                        if p["id_source"] == "generated"),
                                   "kinds": sorted({p["kind"] for p in s["paragraphs"]})}
                                  for s in parsed["sources"]],
                      "warnings": parsed["warnings"]},
                     ensure_ascii=False, indent=2))
    for s in parsed["sources"]:
        for p in s["paragraphs"][:args.sample]:
            print(f"\n[{s['source_id']} {p['paragraph_id']}] ({p['kind']}, {p['section'][:40]})")
            print("  " + p["text"][:240])
    return 0 if parsed["sources"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
