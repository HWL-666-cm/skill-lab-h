"""Run one case end to end.

Two stages keep the deterministic parts deterministic and leave judgement to
the model:

  prepare  parse the PDF and write candidates.json plus parsed.json
  finish   validate a draft against the paper, emit result.json and assertions.trig

`--auto` builds a conservative draft without a model, so the pipeline still
produces something reviewable when no model is available.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import aida_rules  # noqa: E402
import emit  # noqa: E402
import pdf_text  # noqa: E402
import validate as validate_mod  # noqa: E402

CAPTION = re.compile(r"^\s*(fig(ure)?\.?|table|scheme|algorithm)\s*\d", re.I)
NOISE = re.compile(
    r"(https?://|\bdoi\b|@"
    r"|^\s*(references|bibliography)\s*$"
    r"|^\s*(acknowledg|funding|conflict of interest|author contrib|keywords|"
    r"index terms|received|accepted|published|correspondence))",
    re.I,
)
CONCLUSION = re.compile(r"\b(conclu|finding|indicat|demonstrat|suggest|show|reveal|"
                        r"increase|decrease|reduce|improv|associat|correlat|predict|"
                        r"caus|lead to|result in|表明|显示|说明|结果表明|研究发现|"
                        r"显著|提高|降低|相关)", re.I)


def find_pdfs(case: dict, base: Path) -> list[Path]:
    hits: list[Path] = []

    def walk(node):
        if isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
        elif isinstance(node, str) and node.lower().endswith(".pdf"):
            p = Path(node)
            if not p.is_absolute():
                p = (base / node)
            hits.append(p)

    walk(case)
    seen, out = set(), []
    for p in hits:
        if p.name not in seen:
            seen.add(p.name)
            out.append(p)
    return out


def guess_relation(sentence: str, lexicon: dict) -> tuple[str, str]:
    low = sentence.lower()
    best = ("ASSOCIATED_WITH", "")
    for rel, spec in (lexicon.get("relations") or {}).items():
        if rel == "ASSOCIATED_WITH":
            continue
        for cue in spec.get("cues", []):
            if cue.lower() in low:
                return rel, cue
    for cue in (lexicon.get("relations", {}).get("ASSOCIATED_WITH", {}).get("cues") or []):
        if cue.lower() in low:
            return "ASSOCIATED_WITH", cue
    return best


NON_ENTITY = set("""
the a an of in on at to for with by from and or but as is are was were be been
this that these those it its their our we they which who whom whose than then
that such not no only also more most less least very much many few some any all
each both either neither can could may might must should would will shall do does
did done have has had having if when while whereas because since although though
""".split())


def guess_entity(segment: str) -> str:
    """Take the trailing noun-ish chunk of a segment as the entity label."""
    seg = re.sub(r"[\(\)\[\]\"“”]", " ", segment)
    seg = re.split(r"[.,;:!?]", seg)[0]
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z\-]+|[\u4e00-\u9fff]{2,}", seg)]
    chunk: list[str] = []
    for w in reversed(words):
        if w.lower() in NON_ENTITY:
            if chunk:
                break
            continue
        chunk.append(w)
        if len(chunk) >= 5:
            break
    chunk.reverse()
    return " ".join(chunk).strip()


def guess_type(label: str, lexicon: dict) -> str:
    low = label.lower()
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


def collect_candidates(doc, lexicon: dict, limit: int) -> list[dict]:
    rows = []
    for para in doc.paragraphs:
        text = para["text"]
        if CAPTION.match(text) or NOISE.search(text):
            continue
        for sent in para["sentences"]:
            s = sent["text"]
            n = len(s)
            if n < 40 or n > 400:
                continue
            if CAPTION.match(s) or NOISE.search(s):
                continue
            rel, cue = guess_relation(s, lexicon)
            score = 0
            if cue:
                score += 3
            if CONCLUSION.search(s):
                score += 2
            if re.search(r"\d", s):
                score += 1
            if rel != "ASSOCIATED_WITH":
                score += 2
            if score == 0:
                continue
            pre = aida_rules.check_aida(s)
            rows.append({
                "sid": sent["id"],
                "page": sent["page"],
                "pid": para["pidx"],
                "text": s,
                "char_span": [sent["char_start"], sent["char_end"]],
                "relation_hint": rel,
                "trigger_hint": cue,
                "aida_precheck": {
                    "verdict": pre["verdict"],
                    "issue_codes": pre["issue_codes"],
                    "scope_must_keep": pre["scope_must_keep"],
                },
                "score": score,
            })
    rows.sort(key=lambda r: (-r["score"], r["char_span"][0] or 0))
    return rows[:limit]


def auto_draft(cands: list[dict], lexicon: dict, source: dict, case_id: str) -> dict:
    claims = []
    for i, c in enumerate(cands, start=1):
        text = c["text"].strip()
        rel = c["relation_hint"]
        trigger = c["trigger_hint"]
        if trigger:
            idx = text.lower().find(trigger.lower())
            left, right = text[:idx], text[idx + len(trigger):]
        else:
            cut = max(len(text) // 2, 1)
            left, right = text[:cut], text[cut:]
        subj, obj = guess_entity(left), guess_entity(right)
        claims.append({
            "id": f"T{i:02d}",
            "text": text if text.endswith(".") else text + ".",
            "subject": {"label": subj, "type": guess_type(subj, lexicon)},
            "predicate": rel,
            "object": {"label": obj, "type": guess_type(obj, lexicon)},
            "qualifiers": {"scope": c["aida_precheck"].get("scope_must_keep", []),
                           "polarity": None, "population": None},
            "evidence": {"quote": c["text"], "page": c["page"], "sentence_id": c["sid"]},
            "provenance": {"source": source.get("name")},
            "confidence_basis": "rule-based candidate: relation and entities were "
                                "matched by trigger words, not read sentence by sentence",
            "relation_type": "inferred",
        })
    return {"case_id": case_id, "assertions": claims,
            "uncertainty": ["draft produced without a model; treat every claim as a candidate"]}


def prepare(case_path: Path, out_dir: Path, lexicon: dict, limit: int) -> dict:
    case = json.loads(case_path.read_text(encoding="utf-8")) if case_path.exists() else {}
    base = case_path.parent
    pdfs = find_pdfs(case, base)
    if not pdfs:
        return {"status": "blocked", "reason": "no PDF found in case.json",
                "case_id": case.get("case_id") or case.get("id") or ""}
    missing = [str(p) for p in pdfs if not p.exists()]
    if missing:
        return {"status": "blocked", "reason": f"declared PDF missing: {missing}",
                "case_id": case.get("case_id") or ""}
    doc = pdf_text.parse(pdfs[0])
    out_dir.mkdir(parents=True, exist_ok=True)
    parsed = doc.to_dict()
    (out_dir / "parsed.json").write_text(
        json.dumps(parsed, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n")
    cands = collect_candidates(doc, lexicon, limit)
    payload = {
        "case_id": case.get("case_id") or case.get("id") or pdfs[0].stem,
        "source": {**parsed["source"], "path": str(pdfs[0])},
        "output_contract": case.get("output_contract"),
        "candidates": cands,
    }
    (out_dir / "candidates.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n")
    return {
        "status": "prepared",
        "case_id": payload["case_id"],
        "n_candidates": len(cands),
        "pages": parsed["source"]["n_pages"],
        "sentences": parsed["source"]["n_sentences"],
        "files": ["parsed.json", "candidates.json"],
        "dir": str(out_dir),
    }


def finish(draft_path: Path, parsed_path: Path, out_dir: Path, lexicon: dict,
           source_name: str, source_iri: str, case_id: str) -> dict:
    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    parsed = json.loads(parsed_path.read_text(encoding="utf-8"))
    source = {
        "name": source_name or parsed["source"]["path"],
        "iri": source_iri or "urn:source:unidentified",
        "doi": (draft.get("source") or {}).get("doi"),
        "title": (draft.get("source") or {}).get("title"),
        "year": (draft.get("source") or {}).get("year"),
    }
    trig = emit.build_trig(draft.get("assertions") or [], source)
    report = validate_mod.validate(draft, parsed, lexicon, trig)

    # One repair round: give every failed claim the located page and span so the
    # next draft can bind evidence without re-reading the PDF.
    fixed = []
    for claim in draft.get("assertions") or []:
        item = next((i for i in report["items"] if i["id"] == claim.get("id")), None)
        if item and item["verdict"] != "pass":
            q = item["checks"].get("quote", {})
            fixed.append({
                "id": claim.get("id"),
                "verdict": item["verdict"],
                "codes": [c["code"] for c in item["checks"].values() if not c["ok"]],
                "page": q.get("located_page"),
                "char_span": q.get("char_span"),
                "sentence_id": q.get("sid"),
                "fixes": item["fixes"],
            })
    (out_dir / "repair.json").write_text(
        json.dumps({"round": 1, "items": fixed}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n")

    result = emit.build_result(case_id or draft.get("case_id", ""), draft, report,
                               source, parsed, report["status"],
                               draft.get("uncertainty") or [])
    written = emit.write_all(out_dir, trig, result, report)
    return {"status": report["status"], **written,
            "counts": report["counts"],
            "needs_repair": len(fixed)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run one nanopublication assertion case.")
    ap.add_argument("--case", default="/input/case.json")
    ap.add_argument("--lexicon", required=True)
    ap.add_argument("--out", default="/app/output")
    ap.add_argument("--stage", choices=["prepare", "finish", "auto", "all"], default="all")
    ap.add_argument("--draft")
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--source-iri", default="")
    args = ap.parse_args(argv)

    lexicon = json.loads(Path(args.lexicon).read_text(encoding="utf-8"))
    case_path = Path(args.case)
    out_dir = Path(args.out)

    if args.stage in ("prepare",):
        print(json.dumps(prepare(case_path, out_dir, lexicon, args.limit),
                         ensure_ascii=False, indent=2))
        return 0

    if args.stage in ("finish",):
        if not args.draft:
            print(json.dumps({"status": "blocked", "reason": "--draft is required"},
                             ensure_ascii=False))
            return 2
        info = finish(Path(args.draft), out_dir / "parsed.json", out_dir, lexicon,
                      "", args.source_iri, "")
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0 if info["status"] == "pass" else 1

    prep = prepare(case_path, out_dir, lexicon, args.limit)
    if prep["status"] == "blocked":
        print(json.dumps(prep, ensure_ascii=False, indent=2))
        return 3

    if args.stage == "auto":
        parsed = json.loads((out_dir / "parsed.json").read_text(encoding="utf-8"))
        cands = json.loads((out_dir / "candidates.json").read_text(encoding="utf-8"))
        source = {"name": Path(parsed["source"]["path"]).name,
                  "iri": args.source_iri or "urn:source:unidentified"}
        draft = auto_draft(cands["candidates"], lexicon, source, cands["case_id"])
        draft_path = out_dir / "draft.auto.json"
        draft_path.write_text(json.dumps(draft, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8", newline="\n")
        info = finish(draft_path, out_dir / "parsed.json", out_dir, lexicon,
                      source["name"], source["iri"], cands["case_id"])
        print(json.dumps({"prepared": prep, "finished": info}, ensure_ascii=False, indent=2))
        return 0 if info["status"] == "pass" else 1

    print(json.dumps({"prepared": prep,
                      "next": "write a draft from candidates.json, then run --stage finish --draft PATH"},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
