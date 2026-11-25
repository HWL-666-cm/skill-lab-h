"""Emit the deliverable: result.json, assertions.trig and validation.json.

One assertion becomes one nanopublication, because an atomic citable claim is
the unit of the format. Nanopublication IRIs are derived from the claim content
so that a rerun on the same input produces byte-identical files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

REL_NS = "https://w3id.org/np/rel/"
AIDA_NS = "http://purl.org/aida/"
NP = "http://www.nanopub.org/nschema#"
NPX = "http://purl.org/nanopub/x/"
HYCL = "http://purl.org/petapico/o/hycl#"
CITO = "http://purl.org/spar/cito/"
DRAFT_NS = "urn:np:draft:"

PREFIXES = [
    ("np", NP),
    ("npx", NPX),
    ("hycl", HYCL),
    ("cito", CITO),
    ("prov", "http://www.w3.org/ns/prov#"),
    ("dct", "http://purl.org/dc/terms/"),
    ("schema", "https://schema.org/"),
    ("rdf", "http://www.w3.org/1999/02/22-rdf-syntax-ns#"),
    ("rdfs", "http://www.w3.org/2000/01/rdf-schema#"),
    ("xsd", "http://www.w3.org/2001/XMLSchema#"),
    ("rel", REL_NS),
]


def ttl_string(value: str) -> str:
    escaped = (value or "").replace("\\", "\\\\").replace('"', '\\"')
    escaped = escaped.replace("\r", " ").replace("\n", "\\n").replace("\t", " ")
    return f'"{escaped}"'


def pct(char: str) -> str:
    """Percent-encode one character as UTF-8 bytes, using the standard library only."""
    return "".join(f"%{b:02X}" for b in char.encode("utf-8"))


def aida_iri(sentence: str) -> str:
    """AIDA sentence IRI: spaces become '+', the full stop is kept."""
    body = (sentence or "").strip()
    body = " ".join(body.split())
    out = []
    for ch in body:
        if ch == " ":
            out.append("+")
        elif ch.isalnum() or ch in ".,;:()'!?–-/&%":
            out.append(ch)
        else:
            out.append(pct(ch))
    return AIDA_NS + "".join(out)


def slug(value: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return s[:40] or "entity"


def claim_digest(claim: dict) -> str:
    key = json.dumps(
        {
            "text": claim.get("text", ""),
            "predicate": claim.get("predicate", ""),
            "subject": (claim.get("subject") or {}).get("label", ""),
            "object": (claim.get("object") or {}).get("label", ""),
            "quote": (claim.get("evidence") or {}).get("quote", ""),
        },
        ensure_ascii=False, sort_keys=True,
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def claim_base(claim: dict) -> str:
    return DRAFT_NS + claim_digest(claim)


def entity_iri(label: str, base: str) -> str:
    return f"{base}/entity/{slug(label)}"


def _verb_form(predicate: str, lexicon: dict) -> str:
    """Return the canonical natural-language verb for a relation, for the AIDA text."""
    rel = (lexicon.get("relations") or {}).get((predicate or "").upper(), {})
    return rel.get("verb") or (predicate or "associated with").lower().replace("_", " ")


def _guess_type(label: str, lexicon: dict) -> str:
    """Guess an entity type from the label using the lexicon's entity_types cues."""
    low = (label or "").lower()
    best, best_n = "ENTITY", 0
    for name, spec in (lexicon.get("entity_types") or {}).items():
        if name == "ENTITY":
            continue
        for cue in spec.get("cues", []):
            if cue.lower() in low and len(cue) > best_n:
                best, best_n = name, len(cue)
        for suf in spec.get("suffixes", []):
            if low.endswith(suf):
                best, best_n = name, len(suf) + 1
    return best


def to_legacy_claim(np: dict, lexicon: dict | None = None) -> dict:
    """Convert the nested nanopub format to emit.py's legacy claim format.

    The v2 Agent writes::

        {"assertion": {"subject": str, "predicate": str, "object": str, ...},
         "evidence": {"quote": str, "location": {"page": int, ...}, ...},
         "pubinfo": {"paper": str, "identifier": str, ...}, ...}

    emit.py's render path expects::

        {"text": str, "subject": {"label", "type"}, "predicate": UPPER,
         "object": {"label", "type"}, "evidence": {"page", ...}, ...}

    Conversions here: subject/object string -> {label, type}; predicate -> upper;
    evidence.location.page -> evidence.page; pubinfo.identifier -> provenance
    source (so each claim keeps its own source link). The TriG rendering below
    is untouched.
    """
    lexicon = lexicon or {}
    a = np.get("assertion", {}) or {}
    ev = np.get("evidence", {}) or {}
    loc = ev.get("location", {}) or {}
    pi = np.get("pubinfo", {}) or {}
    conf = np.get("confidence", {}) or {}

    subj_label = (a.get("subject") or "").strip()
    obj_label = (a.get("object") or "").strip()
    pred = (a.get("predicate") or "ASSOCIATED_WITH").upper()
    condition = (a.get("condition") or "").strip()
    negation = bool(a.get("negation"))

    verb = _verb_form(pred, lexicon)
    parts = [subj_label, verb, obj_label]
    if negation:
        base = verb
        if base.endswith("es"):
            base = base[:-2]
        elif base.endswith("s") and not base.endswith("ss"):
            base = base[:-1]
        parts[1] = "does not " + base
    if condition:
        parts.append(condition)
    text = " ".join(p for p in parts if p)
    if text and not text.endswith((".", "。", "!", "?", "！", "？")):
        text += "."

    scope = [condition] if condition else []
    return {
        "id": np.get("id", ""),
        "text": text,
        "subject": {"label": subj_label, "type": _guess_type(subj_label, lexicon)},
        "predicate": pred,
        "object": {"label": obj_label, "type": _guess_type(obj_label, lexicon)},
        "qualifiers": {"scope": scope, "polarity": None, "population": None},
        "evidence": {
            "quote": ev.get("quote", ""),
            "quote_end": ev.get("quote_end", ""),
            "page": loc.get("page"),
            "sentence_id": loc.get("sentence_id") or "",
        },
        "provenance": {"source": pi.get("paper", ""),
                       "doi": pi.get("identifier", "")},
        "confidence_basis": conf.get("basis", ""),
        "relation_type": "direct" if ev.get("evidence_type") == "direct" else "inferred",
    }


def render_claim(claim: dict, source: dict) -> str:
    base = claim_base(claim)
    aida = aida_iri(claim.get("text", ""))
    subj = claim.get("subject") or {}
    obj = claim.get("object") or {}
    rel = claim.get("predicate") or "ASSOCIATED_WITH"
    ev = claim.get("evidence") or {}
    quote = ev.get("quote") or ""
    quote_end = ev.get("quote_end") or ""
    page = ev.get("page")
    sentence_id = ev.get("sentence_id") or ""
    span = ev.get("char_span") or [None, None]

    lines = []
    lines.append(f"# assertion {claim.get('id', '?')} | page {page} | {sentence_id}")
    lines.append(f"<{base}/Head> {{")
    lines.append(f"  <{base}> a np:Nanopublication ;")
    lines.append(f"    np:hasAssertion <{base}/assertion> ;")
    lines.append(f"    np:hasProvenance <{base}/provenance> ;")
    lines.append(f"    np:hasPublicationInfo <{base}/pubinfo> .")
    lines.append("}")
    lines.append("")
    lines.append(f"<{base}/assertion> {{")
    lines.append(f"  <{aida}> a hycl:AIDA-Sentence ;")
    lines.append(f"    rdfs:label {ttl_string(claim.get('text', ''))} ;")
    lines.append(f"    prov:wasDerivedFrom <{source.get('iri')}> ;")
    if quote:
        lines.append(f"    cito:hasQuotedText {ttl_string(quote)} ;")
    if quote_end:
        lines.append(f"    cito:hasQuotedTextEnd {ttl_string(quote_end)} ;")
    lines.append(f"    cito:quotes <{source.get('iri')}> .")
    lines.append("")
    lines.append(f"  <{base}/statement> a rdf:Statement ;")
    lines.append(f"    rdf:subject <{entity_iri(subj.get('label', ''), base)}> ;")
    lines.append(f"    rdf:predicate <{REL_NS}{rel}> ;")
    lines.append(f"    rdf:object <{entity_iri(obj.get('label', ''), base)}> ;")
    lines.append(f"    rdfs:label {ttl_string(claim.get('text', ''))} .")
    lines.append("")
    lines.append(f"  <{entity_iri(subj.get('label', ''), base)}> "
                 f"rdfs:label {ttl_string(subj.get('label', ''))} ;")
    lines.append(f"    a <{REL_NS}entity/{subj.get('type', 'ENTITY')}> .")
    lines.append(f"  <{entity_iri(obj.get('label', ''), base)}> "
                 f"rdfs:label {ttl_string(obj.get('label', ''))} ;")
    lines.append(f"    a <{REL_NS}entity/{obj.get('type', 'ENTITY')}> .")
    lines.append("")
    lines.append(f"  <{base}/evidence> a <{CITO}Quote> ;")
    lines.append(f"    cito:hasQuotedText {ttl_string(quote)} ;")
    if page is not None:
        lines.append(f"    dct:source {ttl_string(f'page {page}')} ;")
    if sentence_id:
        lines.append(f"    rdfs:comment {ttl_string(f'sentence {sentence_id}')} ;")
    if span[0] is not None and span[1] is not None:
        lines.append(f"    <{REL_NS}charSpan> {ttl_string(f'{span[0]}-{span[1]}')} ;")
    lines.append(f"    prov:wasQuotedFrom <{source.get('iri')}> .")
    lines.append("}")
    lines.append("")
    lines.append(f"<{base}/provenance> {{")
    prov_parts = [f"  <{base}/assertion> prov:wasDerivedFrom <{source.get('iri')}> ;"]
    prov_parts.append(f"    prov:wasGeneratedBy <{base}/activity> .")
    prov_parts.append("")
    prov_parts.append(f"  <{base}/activity> a prov:Activity ;")
    prov_parts.append(f"    rdfs:label {ttl_string('assertion extraction from the quoted passage')} .")
    lines.extend(prov_parts)
    lines.append("}")
    lines.append("")
    lines.append(f"<{base}/pubinfo> {{")
    lines.append(f"  <{base}> dct:source {ttl_string(source.get('name') or '')} ;")
    lines.append(f"    rdfs:label {ttl_string((claim.get('id') or '') + ': ' + (claim.get('text') or '')[:90])} ;")
    lines.append(f"    npx:hasNanopubType <{HYCL}AIDA-Sentence> .")
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def build_trig(claims: list[dict], source: dict) -> str:
    header = [f"@prefix {p}: <{iri}> ." for p, iri in PREFIXES]
    header.append("")
    header.append("# Draft nanopublications. Not signed and not published: the urn:np:draft")
    header.append("# IRIs are content hashes, not trusty URIs. Sign before publishing.")
    header.append("")
    body = "\n".join(render_claim(c, source) for c in claims)
    return "\n".join(header) + "\n" + body


RELATION_TYPE = {"direct": "direct", "inferred": "inferred"}


def build_assertions(draft_claims: list[dict], report: dict) -> list[dict]:
    by_id = {item["id"]: item for item in report.get("items", [])}
    out = []
    for claim in draft_claims:
        cid = claim.get("id", "?")
        item = by_id.get(cid, {})
        checks = item.get("checks", {})
        quote_check = checks.get("quote", {})
        ev = dict(claim.get("evidence") or {})
        if quote_check.get("char_span"):
            ev["char_span"] = quote_check["char_span"]
        if quote_check.get("located_page") is not None:
            ev["page"] = quote_check["located_page"]
        if quote_check.get("sid"):
            ev["sentence_id"] = quote_check["sid"]
        out.append({
            "id": cid,
            "text": claim.get("text", ""),
            "aida": checks.get("aida", {}).get("criteria", {}),
            "subject": claim.get("subject") or {},
            "predicate": claim.get("predicate", ""),
            "predicate_iri": REL_NS + (claim.get("predicate") or ""),
            "object": claim.get("object") or {},
            "qualifiers": claim.get("qualifiers") or {},
            "evidence": ev,
            "provenance": claim.get("provenance") or {},
            "confidence_basis": claim.get("confidence_basis", ""),
            "relation_type": RELATION_TYPE.get(claim.get("relation_type", ""),
                                               claim.get("relation_type") or "direct"),
            "status": {"pass": "verified", "warn": "warning",
                       "fail": "failed"}.get(item.get("verdict"), "unchecked"),
            "issues": [{"code": c["code"], "detail": c.get("detail", ""),
                        "fix": c.get("fix", "")}
                       for c in checks.values() if not c["ok"]],
        })
    return out


def build_result(case_id: str, draft: dict, report: dict, source: dict,
                 parsed: dict, status: str, uncertainty: list[str]) -> dict:
    claims = draft.get("assertions") or []
    return {
        "case_id": case_id,
        "status": status,
        "task": "nanopublication-assertion-extraction",
        "input": {
            "file": source.get("name"),
            "pages": (parsed.get("source") or {}).get("n_pages"),
            "paragraphs": (parsed.get("source") or {}).get("n_paragraphs"),
            "sentences": (parsed.get("source") or {}).get("n_sentences"),
        },
        "assertions": build_assertions(claims, report),
        "sources": [{
            "name": source.get("name"),
            "iri": source.get("iri"),
            "doi": source.get("doi"),
            "title": source.get("title") or (parsed.get("source") or {}).get("title"),
            "year": source.get("year"),
        }],
        "validation": {
            "status": report.get("status"),
            "counts": report.get("counts"),
            "top_failures": report.get("top_failures"),
            "structure": report.get("structure"),
        },
        "uncertainty": uncertainty,
    }


def write_all(out_dir: Path, trig: str, result: dict, report: dict) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "assertions.trig").write_text(trig, encoding="utf-8", newline="\n")
    (out_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n")
    (out_dir / "validation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n")
    return {
        "dir": str(out_dir),
        "files": sorted(p.name for p in out_dir.iterdir()),
        "trig_bytes": len(trig.encode("utf-8")),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Emit result.json and assertions.trig.")
    ap.add_argument("--draft", required=True)
    ap.add_argument("--parsed", required=True)
    ap.add_argument("--validation", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--source-name", default="")
    ap.add_argument("--source-iri", default="")
    ap.add_argument("--case-id", default="")
    args = ap.parse_args(argv)

    draft = json.loads(Path(args.draft).read_text(encoding="utf-8"))
    parsed = json.loads(Path(args.parsed).read_text(encoding="utf-8"))
    report = json.loads(Path(args.validation).read_text(encoding="utf-8"))
    source = {
        "name": args.source_name or (parsed.get("source") or {}).get("path", ""),
        "iri": args.source_iri or "urn:source:unidentified",
        "doi": draft.get("source", {}).get("doi"),
        "title": draft.get("source", {}).get("title"),
        "year": draft.get("source", {}).get("year"),
    }
    claims = draft.get("assertions") or []
    trig = build_trig(claims, source)
    result = build_result(args.case_id or draft.get("case_id", ""), draft, report,
                          source, parsed, report.get("status", "partial"),
                          draft.get("uncertainty") or [])
    print(json.dumps(write_all(Path(args.out), trig, result, report),
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
