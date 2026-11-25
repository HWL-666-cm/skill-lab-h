"""Validate a draft assertion set against the paper and the relation lexicon.

Everything here is mechanical: the quote must appear in the document verbatim,
the page must match, the subject must be present in the evidence, the relation
must exist and its type signature must fit. Nothing is repaired silently; every
failure comes with a fix hint the model can act on.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import aida_rules  # noqa: E402
from pdf_text import normalize  # noqa: E402

MIN_QUOTE = 5
MAX_QUOTE = 500
PASTE_RATIO = 0.85


def load_json(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build_sentence_index(parsed: dict) -> list[dict]:
    rows = []
    for para in parsed.get("paragraphs", []):
        for sent in para.get("sentences", []):
            if sent.get("char_start") is None:
                continue
            rows.append({
                "start": sent["char_start"],
                "end": sent["char_end"],
                "page": sent.get("page", para.get("page")),
                "pid": para.get("pidx"),
                "sid": sent.get("id"),
            })
    rows.sort(key=lambda r: r["start"])
    return rows


def locate(parsed: dict, index: list[dict], quote: str) -> dict:
    nq = normalize(quote)
    normal = parsed.get("normal_text", "")
    out = {"found": False, "page": None, "pid": None, "sid": None,
           "char_start": None, "char_end": None}
    if not nq or not normal:
        return out
    pos = normal.find(nq)
    if pos < 0:
        return out
    out.update({"found": True, "char_start": pos, "char_end": pos + len(nq)})
    lo, hi, hit = 0, len(index) - 1, None
    while lo <= hi:
        mid = (lo + hi) // 2
        if index[mid]["start"] <= pos:
            hit = index[mid]
            lo = mid + 1
        else:
            hi = mid - 1
    if hit and pos < hit["end"]:
        out.update({"page": hit["page"], "pid": hit["pid"], "sid": hit["sid"],
                    "sentence_text": normal[hit["start"]:hit["end"]]})
    elif hit:
        out.update({"page": hit["page"], "pid": hit["pid"], "sid": hit["sid"],
                    "sentence_text": normal[hit["start"]:hit["end"]]})
    return out


def text_present(needle: str, haystack: str, min_tokens: int = 1) -> bool:
    """True when a distinctive part of `needle` occurs in `haystack`."""
    n = normalize(needle).lower()
    h = normalize(haystack).lower()
    if not n:
        return False
    if n in h:
        return True
    tokens = [t for t in re.findall(r"[a-z\u4e00-\u9fff]{3,}", n)
              if t not in aida_rules.STOPWORDS]
    if not tokens:
        return False
    hits = sum(1 for t in tokens if t in h)
    need = max(min_tokens, int(round(len(tokens) * 0.6)))
    return hits >= need


def check_signature(rel: str, s_type: str, o_type: str, lexicon: dict) -> dict:
    spec = (lexicon.get("relations") or {}).get(rel)
    if not spec:
        return {"ok": False, "code": "unknown_predicate",
                "detail": f"'{rel}' is not in the controlled relation vocabulary",
                "fix": "Map it to the closest relation in relation-lexicon.json; "
                       "use ASSOCIATED_WITH when no direction is claimed."}
    known = lexicon.get("entity_types", {})
    for t in (s_type, o_type):
        if t and t not in known and t != "*":
            return {"ok": False, "code": "unknown_type",
                    "detail": f"entity type '{t}' is not defined",
                    "fix": f"Use one of: {', '.join(sorted(known))}."}
    st, ot = spec.get("subject_types", []), spec.get("object_types", [])
    if set(st) == {"*"} and set(ot) == {"*"}:
        return {"ok": True}
    unresolved = [t for t in (s_type, o_type) if t in ("", "ENTITY", "*")]
    if unresolved:
        return {"ok": False, "code": "type_unresolved",
                "detail": f"{rel} was not checked against a signature because "
                          f"{unresolved} carry no type",
                "fix": "Label subject.type and object.type from relation-lexicon.json "
                       "so the direction can be verified."}
    fwd = ("*" in st or s_type in st) and ("*" in ot or o_type in ot)
    if fwd:
        return {"ok": True}
    rev = ("*" in ot or s_type in ot) and ("*" in st or o_type in st)
    if rev:
        return {"ok": False, "code": "direction_error",
                "detail": f"{s_type} -> {rel} -> {o_type} matches the reversed signature",
                "fix": f"Swap subject and object, or switch to the inverse relation; "
                       f"the lexicon expects {st} -> {rel} -> {ot}."}
    return {"ok": False, "code": "type_mismatch",
            "detail": f"{s_type} -> {rel} -> {o_type} fits neither direction",
            "fix": f"Expected {st} -> {rel} -> {ot}; retype the entities or "
                   "downgrade to ASSOCIATED_WITH."}


def check_trigger(claim: dict, quote: str, lexicon: dict) -> dict:
    rel = claim.get("predicate", "")
    spec = (lexicon.get("relations") or {}).get(rel) or {}
    cues = spec.get("cues", [])
    scope = claim.get("relation_evidence") or {}
    claimed = (scope.get("trigger") or "").strip()
    q = normalize(quote).lower()
    if claimed:
        if claimed.lower() in q:
            return {"ok": True, "trigger": claimed}
        return {"ok": False, "code": "trigger_not_in_evidence",
                "detail": f"declared trigger '{claimed}' does not occur in the quote",
                "fix": "Quote the clause that contains the trigger verb, or lower the "
                       "relation to ASSOCIATED_WITH and mark it inferred."}
    hits = [c for c in cues if c.lower() in q]
    if hits:
        return {"ok": True, "trigger": hits[0]}
    return {"ok": False, "code": "no_trigger",
            "detail": f"no cue for {rel} found in the quote",
            "fix": "Either quote the sentence carrying the relation verb, or set "
                   "predicate to ASSOCIATED_WITH and confidence_basis to 'co-occurrence only'."}


def check_paste(claim_text: str, parsed: dict) -> dict:
    n = normalize(claim_text)
    if len(n) < 120:
        return {"ok": True}
    for para in parsed.get("paragraphs", []):
        pn = normalize(para.get("text", ""))
        if not pn:
            continue
        if n == pn or (pn.startswith(n) and len(n) / max(len(pn), 1) >= PASTE_RATIO):
            return {"ok": False, "code": "paragraph_pasted",
                    "detail": f"the claim is {len(n)} characters of paragraph "
                              f"P{para.get('pidx'):03d} copied whole",
                    "fix": "Split the paragraph into one claim per proposition."}
    return {"ok": True}


def validate_claim(claim: dict, parsed: dict, index: list[dict], lexicon: dict) -> dict:
    cid = claim.get("id") or "?"
    checks: dict[str, dict] = {}
    text = (claim.get("text") or "").strip()
    evidence = claim.get("evidence") or {}
    quote = (evidence.get("quote") or "").strip()

    aida = aida_rules.check_aida(text) if text else {
        "verdict": "fail", "issue_codes": ["empty"], "criteria": {},
        "scope_must_keep": []}
    checks["aida"] = {
        "ok": aida["verdict"] == "pass",
        "code": "aida_" + aida["verdict"],
        "detail": ",".join(aida["issue_codes"]) or "all four criteria hold",
        "fix": "; ".join(i["fix"] for p in aida.get("criteria", {}).values()
                         for i in p.get("issues", [])[:2]) or "",
        "criteria": {k: v.get("ok") for k, v in aida.get("criteria", {}).items()},
        "scope_must_keep": aida.get("scope_must_keep", []),
    }

    if not quote:
        checks["quote"] = {"ok": False, "code": "missing_evidence",
                           "detail": "no evidence quote",
                           "fix": "Copy the shortest passage that supports the claim."}
    elif not (MIN_QUOTE <= len(quote) <= MAX_QUOTE):
        checks["quote"] = {"ok": False, "code": "quote_length",
                           "detail": f"{len(quote)} characters outside 5-500",
                           "fix": "Trim to the minimal supporting passage."}
    else:
        at = locate(parsed, index, quote)
        if not at["found"]:
            checks["quote"] = {"ok": False, "code": "evidence_drift",
                               "detail": "quote does not occur verbatim in the document",
                               "fix": "Copy the passage character for character from the PDF; "
                                      "do not paraphrase it."}
        else:
            declared = evidence.get("page")
            page_ok = declared in (None, at["page"])
            checks["quote"] = {
                "ok": bool(page_ok),
                "code": "ok" if page_ok else "page_mismatch",
                "detail": f"found on page {at['page']} (declared {declared})",
                "fix": "" if page_ok else f"Set page to {at['page']}.",
                "located_page": at["page"], "pid": at["pid"], "sid": at["sid"],
                "char_span": [at["char_start"], at["char_end"]],
                "sentence_text": at.get("sentence_text"),
            }

    subj = (claim.get("subject") or {}).get("label", "")
    obj = (claim.get("object") or {}).get("label", "")
    if not subj or not obj:
        checks["entities"] = {"ok": False, "code": "entity_missing",
                              "detail": "subject or object label is empty",
                              "fix": "Name both entities explicitly."}
    elif quote and not text_present(subj, quote):
        checks["entities"] = {"ok": False, "code": "subject_not_in_evidence",
                              "detail": f"subject '{subj}' is absent from the quote",
                              "fix": "Quote the passage naming the subject, or correct the subject."}
    elif quote and not text_present(obj, quote):
        checks["entities"] = {"ok": False, "code": "object_not_in_evidence",
                              "detail": f"object '{obj}' is absent from the quote",
                              "fix": "Quote the passage naming the object, or correct the object."}
    else:
        checks["entities"] = {"ok": True, "code": "ok",
                              "detail": "both entities occur in the evidence"}

    rel = claim.get("predicate", "")
    sig = check_signature(rel, (claim.get("subject") or {}).get("type", ""),
                          (claim.get("object") or {}).get("type", ""), lexicon)
    checks["relation"] = sig

    if quote:
        checks["trigger"] = check_trigger(claim, quote, lexicon)
        # Scope is judged against the whole sentence that holds the quote, so a
        # quote trimmed down to the clause cannot hide a dropped condition.
        scope_ref = checks["quote"].get("sentence_text") or quote
        loss = aida_rules.check_scope_loss(text, scope_ref)
        checks["scope"] = {
            "ok": loss["ok"],
            "code": loss["issues"][0]["code"] if loss["issues"] else "ok",
            "detail": "; ".join(i["detail"] for i in loss["issues"]) or "scope and polarity preserved",
            "fix": "; ".join(i["fix"] for i in loss["issues"]),
        }
    checks["paste"] = check_paste(text, parsed)

    if not claim.get("confidence_basis"):
        checks["confidence"] = {"ok": False, "code": "confidence_missing",
                                "detail": "confidence_basis is empty",
                                "fix": "State why this claim is trustworthy: direct quote, "
                                       "inferred from co-occurrence, or weakened by a hedge."}
    else:
        checks["confidence"] = {"ok": True, "code": "ok",
                                "detail": claim["confidence_basis"]}

    hard = {"missing_evidence", "evidence_drift", "paragraph_pasted", "aida_fail",
            "entity_missing", "subject_not_in_evidence", "object_not_in_evidence",
            "unknown_predicate", "direction_error", "quote_length", "empty"}
    codes = [c["code"] for c in checks.values() if not c["ok"]]
    verdict = "fail" if hard & set(codes) else ("warn" if codes else "pass")
    return {
        "id": cid,
        "verdict": verdict,
        "checks": checks,
        "fixes": [{"code": c["code"], "fix": c["fix"]} for c in checks.values()
                  if not c["ok"] and c.get("fix")],
    }


GRAPH_OPEN = re.compile(r"^(\S+)\s*\{\s*$")


def split_graphs(text: str) -> dict[str, str]:
    graphs: dict[str, str] = {}
    cur = None
    buf: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if cur is None:
            m = GRAPH_OPEN.match(s)
            if m:
                cur, buf = m.group(1), []
            continue
        if s == "}":
            graphs[cur] = "\n".join(buf)
            cur = None
        else:
            buf.append(line)
    return graphs


def check_trig(text: str) -> dict:
    graphs = split_graphs(text)
    issues = []
    bases: dict[str, dict] = {}
    for name, body in graphs.items():
        clean = name.strip("<>\"").rstrip("/")
        for suffix in ("Head", "assertion", "provenance", "pubinfo"):
            if clean.endswith("/" + suffix):
                base = clean[: -len(suffix) - 1]
                bases.setdefault(base, {})[suffix] = body
                break
    if not bases:
        issues.append({"code": "no_nanopub", "detail": "no named graph block found",
                       "fix": "Emit Head/assertion/provenance/pubinfo blocks per nanopub."})
    for base, parts in bases.items():
        missing = [s for s in ("Head", "assertion", "provenance", "pubinfo") if s not in parts]
        if missing:
            issues.append({"code": "missing_graph", "detail": f"{base} lacks {missing}",
                           "fix": "A nanopublication needs all four named graphs."})
            continue
        head = parts["Head"]
        for pred in ("hasAssertion", "hasProvenance", "hasPublicationInfo"):
            if pred not in head:
                issues.append({"code": "head_link_missing",
                               "detail": f"{base}/Head does not declare {pred}",
                               "fix": f"Add np:{pred} to the head graph."})
        if not re.search(r"\S", parts["assertion"]) or parts["assertion"].count(".") == 0:
            issues.append({"code": "empty_assertion",
                           "detail": f"{base}/assertion is empty",
                           "fix": "An empty assertion graph parses as TriG but is not a "
                                  "valid nanopublication."})
        if not re.search(r"\S", parts["provenance"]) or parts["provenance"].count(".") == 0:
            issues.append({"code": "empty_provenance",
                           "detail": f"{base}/provenance is empty",
                           "fix": "Cite the source the claim derives from."})
    return {"ok": not issues, "n_nanopubs": len(bases), "issues": issues}


def summarize(items: list[dict]) -> dict:
    tally: dict[str, int] = {}
    for item in items:
        for code in [c["code"] for c in item["checks"].values() if not c["ok"]]:
            tally[code] = tally.get(code, 0) + 1
    ranked = sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))
    return {
        "counts": {
            "pass": sum(1 for i in items if i["verdict"] == "pass"),
            "warn": sum(1 for i in items if i["verdict"] == "warn"),
            "fail": sum(1 for i in items if i["verdict"] == "fail"),
        },
        "top_failures": [{"code": c, "n": n} for c, n in ranked[:8]],
    }


def validate(draft: dict, parsed: dict, lexicon: dict, trig_text: str | None = None) -> dict:
    index = build_sentence_index(parsed)
    claims = draft.get("assertions") or []
    if not claims:
        out = {
            "status": "fail",
            "reason": "draft contains no assertions; nothing was extracted",
            "n_assertions": 0,
            "counts": {"pass": 0, "warn": 0, "fail": 0},
            "top_failures": [],
            "items": [],
        }
        if trig_text is not None:
            out["structure"] = check_trig(trig_text)
        return out
    items = [validate_claim(c, parsed, index, lexicon) for c in claims]
    stats = summarize(items)
    out = {
        "status": "pass" if stats["counts"]["fail"] == 0 else (
            "partial" if stats["counts"]["pass"] else "fail"),
        "n_assertions": len(claims),
        **stats,
        "items": items,
    }
    if trig_text is not None:
        structure = check_trig(trig_text)
        out["structure"] = structure
        if not structure["ok"]:
            out["status"] = "fail"
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Validate draft assertions against a paper.")
    ap.add_argument("--parsed", required=True, help="pdf_text.py output JSON")
    ap.add_argument("--draft", required=True, help="assertion draft JSON")
    ap.add_argument("--lexicon", required=True, help="relation-lexicon.json")
    ap.add_argument("--trig", help="assertions.trig to check structure")
    ap.add_argument("--out", help="write validation JSON here")
    args = ap.parse_args(argv)

    parsed = load_json(args.parsed)
    draft = load_json(args.draft)
    lexicon = load_json(args.lexicon)
    trig_text = Path(args.trig).read_text(encoding="utf-8") if args.trig else None
    report = validate(draft, parsed, lexicon, trig_text)
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(payload, encoding="utf-8")
        print(json.dumps({"status": report["status"], "counts": report["counts"],
                          "top_failures": report["top_failures"]}, ensure_ascii=False))
    else:
        print(payload)
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
