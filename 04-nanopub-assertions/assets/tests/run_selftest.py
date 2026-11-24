"""Self-test for the assertion skill. Standard library only, no PDF required.

Builds its own fixtures in a temporary directory, so a fresh checkout can run it
without any input files.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import aida_rules  # noqa: E402
import emit  # noqa: E402
import validate as v  # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(name)
    else:
        FAILED.append(f"{name}: {detail}")


def codes_of(text: str, quote: str = "") -> set[str]:
    out = aida_rules.check_aida(text)
    if quote:
        out["scope_loss"] = aida_rules.check_scope_loss(text, quote)
        return set(out["issue_codes"]) | {i["code"] for i in out["scope_loss"]["issues"]}
    return set(out["issue_codes"])


def test_aida() -> None:
    check("aida.pass", not codes_of("Vitamin D deficiency causes rickets in children."),
          str(codes_of("Vitamin D deficiency causes rickets in children.")))
    check("aida.first_person", "first_person" in codes_of("We present an algorithm."))
    check("aida.pronoun", "leading_pronoun" in codes_of("This approach works."))
    check("aida.question", "question" in codes_of("Does the method reduce cost?"))
    check("aida.coordinated",
          "coordinated_verb" in codes_of(
              "The algorithm guarantees the cost bound and proves the uncertainty bound."))
    check("aida.no_full_stop", "no_full_stop" in codes_of("The method works"))


def test_scope() -> None:
    quote = "Given a fixed U, the estimation performance is robust to the change in bearing noise."
    check("scope.kept",
          "scope_dropped" not in codes_of(
              "Given a fixed uncertainty threshold, the estimation performance is robust "
              "to changes in bearing noise.", quote))
    check("scope.dropped",
          "scope_dropped" in codes_of(
              "The estimation performance is robust to changes in bearing noise.", quote))
    check("polarity.dropped",
          "polarity_dropped" in codes_of(
              "Vitamin D causes rickets.", "Vitamin D deficiency causes rickets."))
    check("number.mismatch",
          "number_mismatch" in codes_of(
              "The cost factor is 30.", "The cost factor is 28.9."))


def make_parsed() -> dict:
    text = (
        "Vitamin D deficiency causes rickets in children. "
        "The cost factor stays within 28.9 of the optimum. "
        "Given a fixed U, the estimation performance is robust to bearing noise."
    )
    sentences = []
    cursor = 0
    for i, frag in enumerate([
        "Vitamin D deficiency causes rickets in children.",
        "The cost factor stays within 28.9 of the optimum.",
        "Given a fixed U, the estimation performance is robust to bearing noise.",
    ], start=1):
        sentences.append({"id": f"P001S{i:02d}", "text": frag, "page": 1,
                          "char_start": cursor, "char_end": cursor + len(frag)})
        cursor += len(frag) + 1
    return {
        "source": {"path": "fixture.pdf", "engine": "fixture", "n_pages": 1,
                   "n_paragraphs": 1, "n_sentences": 3, "title": ""},
        "paragraphs": [{"pidx": 1, "page": 1, "text": text, "bbox": [0, 0, 0, 0],
                        "sentences": sentences}],
        "normal_text": text,
    }


def make_lexicon() -> dict:
    return {
        "version": "test",
        "entity_types": {k: {"cues": []} for k in
                         ["DISEASE", "DRUG", "CHEMICAL", "MEASURE", "METHOD",
                          "CONDITION", "PROCESS", "ENTITY"]},
        "relations": {
            "CAUSES": {"subject_types": ["CHEMICAL", "CONDITION"],
                       "object_types": ["DISEASE"], "cues": ["causes"]},
            "TREATS": {"subject_types": ["DRUG"], "object_types": ["DISEASE"],
                       "cues": ["treats"]},
            "ASSOCIATED_WITH": {"subject_types": ["*"], "object_types": ["*"],
                                "cues": ["associated with"]},
            "ENABLES": {"subject_types": ["METHOD"], "object_types": ["MEASURE"],
                        "cues": ["guarantees"]},
        },
    }


def claim(**kw) -> dict:
    base = {
        "id": "A01",
        "text": "Vitamin D deficiency causes rickets.",
        "subject": {"label": "Vitamin D deficiency", "type": "CHEMICAL"},
        "predicate": "CAUSES",
        "object": {"label": "rickets", "type": "DISEASE"},
        "qualifiers": {"scope": [], "polarity": "loss", "population": None},
        "evidence": {"quote": "Vitamin D deficiency causes rickets in children.", "page": 1},
        "provenance": {"source": "fixture"},
        "confidence_basis": "direct quote",
        "relation_type": "direct",
        "relation_evidence": {"trigger": "causes"},
    }
    base.update(kw)
    return base


def test_signature() -> None:
    lex = make_lexicon()
    ok = v.check_signature("TREATS", "DRUG", "DISEASE", lex)
    check("sig.ok", ok["ok"], str(ok))
    bad = v.check_signature("TREATS", "DISEASE", "DRUG", lex)
    check("sig.direction", bad.get("code") == "direction_error", str(bad))
    unknown = v.check_signature("INVENTED", "DRUG", "DISEASE", lex)
    check("sig.unknown", unknown.get("code") == "unknown_predicate", str(unknown))
    untyped = v.check_signature("TREATS", "ENTITY", "DISEASE", lex)
    check("sig.untyped", untyped.get("code") == "type_unresolved", str(untyped))
    anyrel = v.check_signature("ASSOCIATED_WITH", "ENTITY", "ENTITY", lex)
    check("sig.any", anyrel["ok"], str(anyrel))


def test_validate() -> None:
    parsed, lex = make_parsed(), make_lexicon()
    good = {"case_id": "t", "assertions": [claim()]}
    rep = v.validate(good, parsed, lex)
    check("validate.good", rep["status"] == "pass",
          json.dumps(rep["items"][0]["checks"], ensure_ascii=False)[:200])

    drifted = {"case_id": "t", "assertions": [claim(
        evidence={"quote": "Vitamin D deficiency is linked with rickets in children", "page": 1})]}
    rep = v.validate(drifted, parsed, lex)
    codes = [c["code"] for c in rep["items"][0]["checks"].values() if not c["ok"]]
    check("validate.drift", "evidence_drift" in codes, str(codes))

    pasted = {"case_id": "t", "assertions": [claim(
        text=parsed["paragraphs"][0]["text"])]}
    rep = v.validate(pasted, parsed, lex)
    codes = [c["code"] for c in rep["items"][0]["checks"].values() if not c["ok"]]
    check("validate.pasted", "paragraph_pasted" in codes or "aida_fail" in codes, str(codes))

    wrong_page = {"case_id": "t", "assertions": [claim(
        evidence={"quote": "Vitamin D deficiency causes rickets in children.", "page": 9})]}
    rep = v.validate(wrong_page, parsed, lex)
    codes = [c["code"] for c in rep["items"][0]["checks"].values() if not c["ok"]]
    check("validate.page", "page_mismatch" in codes, str(codes))


def test_structure() -> None:
    source = {"name": "fixture.pdf", "iri": "urn:source:fixture"}
    trig = emit.build_trig([claim()], source)
    rep = v.check_trig(trig)
    check("trig.ok", rep["ok"] and rep["n_nanopubs"] == 1, str(rep["issues"]))

    empty = """@prefix np: <http://www.nanopub.org/nschema#> .
@prefix prov: <http://www.w3.org/ns/prov#> .

<urn:np:draft:x/Head> {
  <urn:np:draft:x> a np:Nanopublication ;
    np:hasAssertion <urn:np:draft:x/assertion> ;
    np:hasProvenance <urn:np:draft:x/provenance> ;
    np:hasPublicationInfo <urn:np:draft:x/pubinfo> .
}

<urn:np:draft:x/assertion> {
}

<urn:np:draft:x/provenance> {
  <urn:np:draft:x/assertion> prov:wasDerivedFrom <urn:source:fixture> .
}

<urn:np:draft:x/pubinfo> {
  <urn:np:draft:x> a np:Nanopublication .
}
"""
    rep = v.check_trig(empty)
    check("trig.emptied",
          any(i["code"] == "empty_assertion" for i in rep["issues"]),
          str(rep["issues"]))

    half = trig.split("<urn:np:draft:")[0] + "<urn:np:draft:" + trig.split("<urn:np:draft:")[1].split("/Head>")[0] + "/Head> {\n}\n"
    rep = v.check_trig(half)
    check("trig.missing", not rep["ok"], str(rep["issues"])[:120])

    aida = emit.aida_iri("Malaria is transmitted by mosquitoes.")
    check("aida.iri", aida == "http://purl.org/aida/Malaria+is+transmitted+by+mosquitoes.",
          aida)


def test_determinism() -> None:
    source = {"name": "fixture.pdf", "iri": "urn:source:fixture"}
    a = emit.build_trig([claim()], source)
    b = emit.build_trig([claim()], source)
    check("determinism.trig", a == b, "two runs produced different bytes")
    with tempfile.TemporaryDirectory() as tmp:
        p1, p2 = Path(tmp) / "a.json", Path(tmp) / "b.json"
        from collections import Counter
        c1 = Counter(claim()["text"])
        p1.write_text(json.dumps(claim(), sort_keys=True), encoding="utf-8")
        p2.write_text(json.dumps(claim(), sort_keys=True), encoding="utf-8")
        check("determinism.json", p1.read_bytes() == p2.read_bytes(), str(c1)[:20])


def main() -> int:
    for fn in (test_aida, test_scope, test_signature, test_validate,
               test_structure, test_determinism):
        fn()
    total = len(PASSED) + len(FAILED)
    for name in PASSED:
        print(f"PASS  {name}")
    for item in FAILED:
        print(f"FAIL  {item}")
    print(f"\n{len(PASSED)}/{total} passed")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    raise SystemExit(main())
