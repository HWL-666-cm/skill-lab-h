#!/usr/bin/env python3
"""Self-test for the knowledge-graph skill. No network, no model, no fixtures on disk.

Run: python assets/tests/run_selftest.py
Exit 0 only when every check passes.
"""

from __future__ import annotations

import json
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import align  # noqa: E402
import contract  # noqa: E402
import emit  # noqa: E402
import extract  # noqa: E402
import materials as M  # noqa: E402
import query as Q  # noqa: E402
import validate as V  # noqa: E402

SCHEMA = json.loads((ROOT / "assets" / "schema.json").read_text(encoding="utf-8"))
PASSED, FAILED = 0, 0


def check(name: str, cond: bool, msg: str = "") -> None:
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"PASS {name}")
    else:
        FAILED += 1
        print(f"FAIL {name} {msg}")


def parsed_two_papers() -> dict:
    """Minimal in-memory case: two papers, one paragraph each, sharing a term."""
    def src(sid, text, pid="p001"):
        return {"source_id": sid, "doi": f"10.0000/{sid}", "title": sid, "authors": [],
                "year": "2024", "license": "CC-BY-4.0", "sha256": "x", "path": "",
                "paragraphs": [{"paragraph_id": pid, "section": "Results", "kind": "body",
                                "text": text, "id_source": "publisher"}]}
    return {"case_id": "t", "input_dir": "mem",
            "sources": [src("S1", "WRF was used for the sea fog simulation, and the RMSE was 1.2 km."),
                        src("S2", "Rain increased, and sea fog formed due to cold water upwelling.")],
            "manifest": [{"source_id": "S1"}, {"source_id": "S2"}], "warnings": [], "case_raw": {}}


def draft_basic() -> dict:
    p = parsed_two_papers()
    s1 = p["sources"][0]["paragraphs"][0]["text"]
    s2 = p["sources"][1]["paragraphs"][0]["text"]
    return {
        "entities": [
            {"key": "a", "surface": "sea fog", "type": "PHENOMENON", "source_id": "S1",
             "paragraph_id": "p001", "quote": s1},
            {"key": "b", "surface": "WRF", "type": "METHOD", "source_id": "S1",
             "paragraph_id": "p001", "quote": s1},
            {"key": "c", "surface": "RMSE", "type": "VARIABLE", "source_id": "S1",
             "paragraph_id": "p001", "quote": s1},
            {"key": "d", "surface": "1.2 km", "type": "VALUE", "source_id": "S1",
             "paragraph_id": "p001", "quote": s1},
            {"key": "e", "surface": "sea fog", "type": "PHENOMENON", "source_id": "S2",
             "paragraph_id": "p001", "quote": s2},
            {"key": "f", "surface": "cold water upwelling", "type": "PHENOMENON", "source_id": "S2",
             "paragraph_id": "p001", "quote": s2},
        ],
        "edges": [
            {"subject": "a", "predicate": "APPLIES_METHOD", "object": "b", "source_id": "S1",
             "paragraph_id": "p001", "quote": s1,
             "strength": {"class": "own_method", "weight": 0.8, "attribution": "this_paper"}},
            {"subject": "b", "predicate": "ACHIEVES", "object": "d", "source_id": "S1",
             "paragraph_id": "p001", "quote": s1, "conditions": ["variable=RMSE"],
             "strength": {"class": "own_result", "weight": 0.9, "attribution": "this_paper"}},
            {"subject": "f", "predicate": "CAUSES", "object": "e", "source_id": "S2",
             "paragraph_id": "p001", "quote": s2,
             "strength": {"class": "own_result", "weight": 0.9, "attribution": "this_paper"}},
        ],
    }


# --------------------------------------------------------------- material/quote

def test_quote_matching() -> None:
    text = "WRF was used for the sea fog simulation."
    r = V.match_quote("WRF was used for the sea fog simulation", text)
    check("quote.exact", r["ok"] and r["contiguous"])
    r = V.match_quote("WRF was used … sea fog simulation", text)
    check("quote.ellipsis_fragments", r["ok"] and r["fragments"] == 2)
    r = V.match_quote("WRF simulated fog", text)
    check("quote.drift_detected", not r["ok"])
    text2 = "The \ufb01xed value was 5.5U\u2212 at \u201csea\u201d."
    r = V.match_quote('The fixed value was 5.5U- at "sea".', text2)
    check("quote.typography_normalised", r["ok"], str(r))


def test_jats_ids() -> None:
    xml = """<article><front><article-meta>
      <title-group><article-title>T</article-title></title-group>
      <article-id pub-id-type="doi">10.1/x</article-id>
      <permissions><license><license_ref>https://creativecommons.org/licenses/by/4.0/</license_ref></license></permissions>
      <pub-date><year>2024</year></pub-date>
      </article-meta></front>
      <body><sec><title>Intro</title><p>%s</p><p id="keep-me">%s</p></sec></body></article>""" % (
        "A" * 60, "B" * 60)
    src = M.parse_jats.__wrapped__(Path("x.xml")) if hasattr(M.parse_jats, "__wrapped__") else None
    # parse from a temp file to exercise the real path
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "a.xml"
        p.write_text(xml, encoding="utf-8")
        src = M.parse_jats(p, "S9")
    ids = [x["paragraph_id"] for x in src["paragraphs"]]
    check("jats.publisher_id_kept", "keep-me" in ids, str(ids))
    check("jats.generated_id_labelled",
          any(x["id_source"] == "generated" for x in src["paragraphs"]))
    check("jats.license_read", "creativecommons" in src["license"])


# ------------------------------------------------------------------- identity

def test_identity() -> None:
    g = align.build_graph(draft_basic(), parsed_two_papers(), SCHEMA)
    labels = [(n["label"], n["identity_scope"], len(n["source_ids"])) for n in g["nodes"]]
    check("identity.same_term_split_across_papers",
          sum(1 for l, s, k in labels if l == "sea fog") == 2, str(labels))
    check("identity.split_recorded", len(g["candidate_alignments"]) == 1,
          json.dumps(g["candidate_alignments"], ensure_ascii=False)[:160])
    check("identity.no_product_merge_without_product",
          g["stats"]["product_nodes"] == 0, str(g["stats"]))

    d = draft_basic()
    d["entities"].append({"key": "g", "surface": "WRF", "type": "METHOD", "source_id": "S2",
                          "paragraph_id": "p001",
                          "quote": parsed_two_papers()["sources"][1]["paragraphs"][0]["text"]})
    g2 = align.build_graph(d, parsed_two_papers(), SCHEMA)
    wrf = [n for n in g2["nodes"] if n["label"] == "WRF"][0]
    check("identity.product_merge_for_acronym",
          wrf["identity_scope"] == "product" and len(wrf["source_ids"]) == 2, str(wrf))
    check("identity.product_merge_recorded", any(m["node_id"] == wrf["id"] for m in g2["merges"]))

    d3 = draft_basic()
    d3["entities"].append({"key": "h", "surface": "Incheon", "type": "LOCATION",
                           "source_id": "S1", "paragraph_id": "p001",
                           "quote": parsed_two_papers()["sources"][0]["paragraphs"][0]["text"],
                           "aliases": ["sea fog"]})
    g3 = align.build_graph(d3, parsed_two_papers(), SCHEMA)
    check("identity.no_alias_merge_across_types",
          any(t["decision"] == "kept_separate" for t in g3["type_conflicts"])
          or sum(1 for n in g3["nodes"] if n["label"] in {"Incheon", "sea fog"}) >= 2)


def test_alias_union() -> None:
    p = parsed_two_papers()
    txt = p["sources"][0]["paragraphs"][0]["text"]
    d = {"entities": [
        {"key": "a", "surface": "sea fog", "type": "PHENOMENON", "source_id": "S1",
         "paragraph_id": "p001", "quote": txt},
        {"key": "b", "surface": "fog", "type": "PHENOMENON", "source_id": "S1",
         "paragraph_id": "p001", "quote": txt, "aliases": ["sea fog"]},
    ], "edges": []}
    g = align.build_graph(d, p, SCHEMA)
    fog_nodes = [n for n in g["nodes"] if n["type"] == "PHENOMENON"]
    check("identity.alias_union_same_paper", len(fog_nodes) == 1, str(len(fog_nodes)))
    check("identity.alias_merge_has_basis",
          any(m["basis"] == "declared_alias_in_same_paper" for m in g["merges"]))


# ------------------------------------------------------------------- conflicts

def test_conditions_and_conflicts() -> None:
    p = parsed_two_papers()
    txt = p["sources"][0]["paragraphs"][0]["text"]
    base = [{"key": "m", "surface": "WRF", "type": "METHOD", "source_id": "S1",
             "paragraph_id": "p001", "quote": txt},
            {"key": "v1", "surface": "1.2 km", "type": "VALUE", "source_id": "S1",
             "paragraph_id": "p001", "quote": txt},
            {"key": "v2", "surface": "RMSE", "type": "VALUE", "source_id": "S1",
             "paragraph_id": "p001", "quote": txt}]
    same = {"entities": base, "edges": [
        {"subject": "m", "predicate": "ACHIEVES", "object": "v1", "source_id": "S1",
         "paragraph_id": "p001", "quote": txt, "conditions": ["site=A"]},
        {"subject": "m", "predicate": "ACHIEVES", "object": "v2", "source_id": "S1",
         "paragraph_id": "p001", "quote": txt, "conditions": ["site=A"]}]}
    g = align.build_graph(same, p, SCHEMA)
    check("conflict.same_conditions_detected", len(g["conflicts"]) == 1,
          json.dumps(g["conflicts"], ensure_ascii=False)[:120])

    diff = json.loads(json.dumps(same))
    diff["edges"][1]["conditions"] = ["site=B"]
    g2 = align.build_graph(diff, p, SCHEMA)
    check("conflict.different_conditions_not_conflict", len(g2["conflicts"]) == 0)


# ---------------------------------------------------------- direction & strength

def test_direction() -> None:
    p = parsed_two_papers()
    s2 = p["sources"][1]["paragraphs"][0]["text"]
    d = {"entities": [
        {"key": "e", "surface": "sea fog", "type": "PHENOMENON", "source_id": "S2",
         "paragraph_id": "p001", "quote": s2},
        {"key": "f", "surface": "cold water upwelling", "type": "PHENOMENON", "source_id": "S2",
         "paragraph_id": "p001", "quote": s2}], "edges": [
        {"subject": "f", "predicate": "CAUSES", "object": "e", "source_id": "S2",
         "paragraph_id": "p001", "quote": s2,
         "strength": {"class": "own_result", "weight": 0.9, "attribution": "this_paper"}}]}
    g = align.build_graph(d, p, SCHEMA)
    r = V.validate(g, p, SCHEMA)
    check("direction.passive_cause_accepted", r["counts"]["fail"] == 0, str(r["top_failures"]))

    bad = json.loads(json.dumps(d))
    bad["edges"][0]["subject"], bad["edges"][0]["object"] = "e", "f"
    g2 = align.build_graph(bad, p, SCHEMA)
    r2 = V.validate(g2, p, SCHEMA)
    codes = [i["checks"]["direction"]["code"] for i in r2["items"]
             if i["kind"] == "edge" and not i["checks"]["direction"]["ok"]]
    check("direction.passive_cause_reversed_flagged", "direction_error" in codes, str(codes))


def _parsed_with(text: str) -> dict:
    src = {"source_id": "S1", "doi": "10.1/x", "title": "t", "authors": [], "year": "2024",
           "license": "CC-BY-4.0", "sha256": "x", "path": "",
           "paragraphs": [{"paragraph_id": "p001", "section": "Results", "kind": "body",
                           "text": text, "id_source": "publisher"}]}
    return {"case_id": "t", "input_dir": "mem", "sources": [src],
            "manifest": [{"source_id": "S1"}], "warnings": [], "case_raw": {}}


def test_strength() -> None:
    def run(text, cls):
        p = _parsed_with(text)
        d = {"entities": [
            {"key": "m", "surface": "WRF", "type": "METHOD", "source_id": "S1",
             "paragraph_id": "p001", "quote": text},
            {"key": "d", "surface": "1.2 km", "type": "VALUE", "source_id": "S1",
             "paragraph_id": "p001", "quote": text}],
            "edges": [{"subject": "m", "predicate": "ACHIEVES", "object": "d", "source_id": "S1",
                       "paragraph_id": "p001", "quote": text,
                       "strength": {"class": cls, "weight": 0.9, "attribution": "this_paper"}}]}
        g = align.build_graph(d, p, SCHEMA)
        return V.validate(g, p, SCHEMA)

    r = run("Previous studies reported that WRF achieves 1.2 km [3].", "own_result")
    bad = [i["checks"]["strength"]["code"] for i in r["items"]
           if i["kind"] == "edge" and "strength" in i["checks"]
           and not i["checks"]["strength"]["ok"]]
    check("strength.cited_marked_own_flagged", "strength_overclaim" in bad, str(bad))
    r2 = run("In this study WRF achieves 1.2 km [3].", "own_result")
    edge_checks = [i["checks"] for i in r2["items"] if i["kind"] == "edge"]
    check("strength.own_voice_overrides_marker",
          bool(edge_checks) and all(c.get("strength", {}).get("ok") for c in edge_checks))


def test_page_rule() -> None:
    p = parsed_two_papers()
    txt = p["sources"][0]["paragraphs"][0]["text"]
    d = {"entities": [{"key": "m", "surface": "WRF", "type": "METHOD", "source_id": "S1",
                       "paragraph_id": "p001", "quote": txt, "page": 7}],
         "edges": [{"subject": "m", "predicate": "ACHIEVES", "object": "m", "source_id": "S1",
                    "paragraph_id": "p001", "quote": txt}]}
    g = align.build_graph(d, p, SCHEMA)
    r = V.validate(g, p, SCHEMA)
    codes = [c["code"] for i in r["items"] for c in i["checks"].values() if not c["ok"]]
    check("page.invented_page_rejected", "invented_page" in codes, str(codes))


# --------------------------------------------------------------------- queries

def test_queries() -> None:
    g = align.build_graph(draft_basic(), parsed_two_papers(), SCHEMA)
    res = Q.run_queries(g, [
        {"id": "q1", "type": "path", "a": "WRF", "b": "sea fog", "question": "p"},
        {"id": "q2", "type": "negative", "question": "What was the fog frequency in 2040?"},
        {"id": "q3", "type": "conflicts", "question": "c"},
    ])
    by_id = {x["id"]: x for x in res["queries"]}
    check("query.path_answered", by_id["q1"]["status"] == "answered" and by_id["q1"]["edge_ids"],
          by_id["q1"]["answer"])
    check("query.negative_is_insufficient", by_id["q2"]["status"] == "insufficient_evidence")
    check("query.conflict_list_ok", by_id["q3"]["status"] == "answered")

    multi = Q.entity_profile(g, Q._index(g), "sea fog")
    check("query.multi_node_profile", len(multi["node_ids"]) == 2, str(multi["node_ids"]))


# -------------------------------------------------------------------- contract

def test_contract() -> None:
    base = {"case_id": "c", "status": "partial", "nodes": [], "edges": [],
            "uncertainty": [], "sources": []}
    out, rep = contract.apply(base, ["case_id", "claims", "evidence", "nonsense_field"])
    check("contract.alias_copied", rep["aliased"].get("claims") == "edges", str(rep))
    check("contract.derived_evidence", rep["derived"].get("evidence") == "evidence_index")
    check("contract.missing_is_null",
          out["nonsense_field"] is None and "nonsense_field" in rep["missing"])
    check("contract.missing_visible_in_uncertainty",
          any("nonsense_field" in u for u in out["uncertainty"]))
    check("contract.input_not_mutated", "claims" not in base)


# ------------------------------------------------------------------ determinism

def test_determinism() -> None:
    p = parsed_two_papers()
    d = draft_basic()
    g1 = align.build_graph(json.loads(json.dumps(d)), p, SCHEMA)
    g2 = align.build_graph(json.loads(json.dumps(d)), p, SCHEMA)
    r1 = V.validate(g1, p, SCHEMA, Q.run_queries(g1), d)
    r2 = V.validate(g2, p, SCHEMA, Q.run_queries(g2), d)
    q1 = Q.run_queries(g1)
    q2 = Q.run_queries(g2)
    res1 = emit.build_result("t", p, g1, q1, r1, "partial")
    res2 = emit.build_result("t", p, g2, q2, r2, "partial")
    a = json.dumps(res1, ensure_ascii=False, sort_keys=True)
    b = json.dumps(res2, ensure_ascii=False, sort_keys=True)
    check("determinism.result_identical", a == b)
    check("determinism.node_ids_stable",
          [n["id"] for n in g1["nodes"]] == [n["id"] for n in g2["nodes"]])


def test_empty_draft() -> None:
    g = align.build_graph({"entities": [], "edges": []}, parsed_two_papers(), SCHEMA)
    r = V.validate(g, parsed_two_papers(), SCHEMA, Q.run_queries(g), {})
    res = emit.build_result("t", parsed_two_papers(), g, Q.run_queries(g), r, "partial")
    check("edge_case.empty_draft_no_crash",
          res["status"] == "partial" and res["graph"]["stats"]["nodes"] == 0)


# ------------------------------------------------------- v2: abbreviation + incremental

def test_abbreviation_detection() -> None:
    src = {"source_id": "S1", "doi": "10.1/x", "title": "t", "authors": [], "year": "2024",
           "license": "CC-BY-4.0", "sha256": "x", "path": "",
           "paragraphs": [{"paragraph_id": "p001", "section": "Methods", "kind": "body",
                           "text": "The critical success index (CSI) was computed from the contingency table.",
                           "id_source": "publisher"}]}
    p = {"case_id": "t", "input_dir": "mem", "sources": [src],
         "manifest": [{"source_id": "S1"}], "warnings": [], "case_raw": {}}
    ab = extract.detect_abbreviations(p)
    check("abbrev.detected_pair", len(ab) == 1 and ab[0]["full"] == "critical success index"
          and ab[0]["abbrev"] == "CSI", json.dumps(ab, ensure_ascii=False)[:160])
    p["abbreviation_candidates"] = ab

    txt = src["paragraphs"][0]["text"]
    d = {"entities": [
        {"key": "a", "surface": "critical success index", "type": "VARIABLE",
         "source_id": "S1", "paragraph_id": "p001", "quote": txt},
        {"key": "b", "surface": "CSI", "type": "VARIABLE",
         "source_id": "S1", "paragraph_id": "p001", "quote": txt},
    ], "edges": []}
    g = align.build_graph(d, p, SCHEMA)
    var_nodes = [n for n in g["nodes"] if n["type"] == "VARIABLE"]
    check("abbrev.merged_without_model_declaration", len(var_nodes) == 1, str(var_nodes))
    check("abbrev.merge_basis_recorded",
          any(m.get("basis") == "abbreviation_pattern" for m in g["merges"]),
          json.dumps(g["merges"], ensure_ascii=False)[:200])


def test_incremental_node_stability() -> None:
    def src(sid, text):
        return {"source_id": sid, "doi": f"10.0/{sid}", "title": sid, "authors": [],
                "year": "2024", "license": "CC-BY-4.0", "sha256": "x", "path": "",
                "paragraphs": [{"paragraph_id": "p001", "section": "R", "kind": "body",
                                "text": text, "id_source": "publisher"}]}
    t1 = "WRF was used for the sea fog simulation in Incheon."
    t2 = "A different sea fog event was studied in Incheon with WRF v4."
    d1 = {"entities": [
        {"key": "a", "surface": "WRF", "type": "METHOD", "source_id": "S1",
         "paragraph_id": "p001", "quote": t1},
        {"key": "b", "surface": "sea fog", "type": "PHENOMENON", "source_id": "S1",
         "paragraph_id": "p001", "quote": t1}], "edges": []}
    p1 = {"case_id": "t", "input_dir": "mem", "sources": [src("S1", t1)],
          "manifest": [{"source_id": "S1"}], "warnings": [], "case_raw": {}}
    g1 = align.build_graph(d1, p1, SCHEMA)
    s1_ids = {n["id"]: n["label"] for n in g1["nodes"]}

    d2 = json.loads(json.dumps(d1))
    d2["entities"] += [
        {"key": "c", "surface": "sea fog", "type": "PHENOMENON", "source_id": "S2",
         "paragraph_id": "p001", "quote": t2},
        {"key": "d", "surface": "WRF", "type": "METHOD", "source_id": "S2",
         "paragraph_id": "p001", "quote": t2}]
    p2 = {"case_id": "t", "input_dir": "mem",
          "sources": [src("S1", t1), src("S2", t2)],
          "manifest": [{"source_id": "S1"}, {"source_id": "S2"}], "warnings": [], "case_raw": {}}
    g2 = align.build_graph(d2, p2, SCHEMA)
    ids2 = {n["id"]: n["label"] for n in g2["nodes"]}
    # instance 节点（sea fog，含 source 的内容哈希）在加入 S2 后原样保留；
    # 跨篇同名产品 "WRF" 从 instance 提升为 product 节点，编号变化必须记录为合并。
    sea_fog_s1 = next(i for i, lbl in s1_ids.items() if lbl == "sea fog")
    check("incremental.instance_node_id_preserved", ids2.get(sea_fog_s1) == "sea fog",
          str((sea_fog_s1, ids2)))
    check("incremental.product_promotion_recorded",
          any(m.get("label") == "WRF" and m.get("identity_scope") == "product" for m in g2["merges"]),
          json.dumps(g2["merges"], ensure_ascii=False)[:200])
    # 跨篇同名 "sea fog" 不合并（两个 instance），"WRF" 合并为一个 product
    sea_fog_nodes = [n for n in g2["nodes"] if n["label"] == "sea fog"]
    wrf_nodes = [n for n in g2["nodes"] if n["label"] == "WRF"]
    check("incremental.sea_fog_split_wrf_product",
          len(sea_fog_nodes) == 2 and all(n["identity_scope"] == "instance" for n in sea_fog_nodes)
          and len(wrf_nodes) == 1 and wrf_nodes[0]["identity_scope"] == "product",
          json.dumps([(n["label"], n["identity_scope"]) for n in sea_fog_nodes + wrf_nodes]))


def test_gain_comparison() -> None:
    """同输入下，朴素字符串相等建图 vs 本 Skill 策略建图的对照，量化 Skill 的增益。"""
    def naive_graph(d, p):
        # 朴素做法：同一 surface（忽略大小写）合并为一个节点，不记依据、不记 scope、不记证据强度
        nodes, by_label = [], {}
        for e in d["entities"]:
            k = e["surface"].strip().lower()
            if k not in by_label:
                by_label[k] = f"n{len(nodes)}"
                nodes.append({"id": by_label[k], "label": e["surface"],
                              "source_ids": [e["source_id"]]})
            else:
                node = next(n for n in nodes if n["id"] == by_label[k])
                node["source_ids"].append(e["source_id"])
        return {"nodes": nodes, "candidate_alignments": [], "merges": [],
                "type_conflicts": [], "scope_notes": 0}
    p = parsed_two_papers()
    d = draft_basic()
    naive = naive_graph(d, p)
    skill = align.build_graph(d, p, SCHEMA)
    naive_seafog = sum(1 for n in naive["nodes"] if n["label"].lower() == "sea fog")
    skill_seafog = sum(1 for n in skill["nodes"] if n["label"].lower() == "sea fog")
    # 朴素把跨篇同名 "sea fog" 合并成 1 个节点（错并）；Skill 拆成 2 个并记 not_merged
    check("gain.naive_wrongly_merges_sea_fog", naive_seafog == 1 and skill_seafog == 2)
    check("gain.skill_records_why_not_merged", len(skill["candidate_alignments"]) == 1)
    # 朴素无依据记录、无证据强度、无 scope；Skill 每条边都带证据与强度
    check("gain.skill_adds_evidence_binding",
          all(e.get("evidence") for e in skill["edges"]) and
          all(e.get("strength") for e in skill["edges"]))
    check("gain.skill_scope_and_basis_recorded",
          len(skill["merges"]) + len(skill["candidate_alignments"]) > len(naive["merges"]))


def main() -> int:
    for fn in (test_quote_matching, test_jats_ids, test_identity, test_alias_union,
               test_conditions_and_conflicts, test_direction, test_strength, test_page_rule,
               test_queries, test_contract, test_determinism, test_empty_draft,
               test_abbreviation_detection, test_incremental_node_stability,
               test_gain_comparison):
        fn()
    total = PASSED + FAILED
    print(f"\n{total} checks: {PASSED} passed, {FAILED} failed")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
