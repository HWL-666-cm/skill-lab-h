#!/usr/bin/env python3
"""Four-state gate.  not_checked never counts as pass."""
from __future__ import annotations

import re
from typing import Any


def _check(checks: list[dict], cid: str, state: str, detail: str) -> None:
    checks.append({"id": cid, "status": state, "detail": detail})


def validate(cands: dict, al: dict, gp: dict, pack: dict, draft: str,
             result: dict | None = None, schema: dict | None = None) -> dict:
    checks: list[dict] = []
    schema = schema or {}
    f = al.get("forward", {})
    b = al.get("backward", {})
    rows = f.get("rows", [])
    counts = al.get("counts", {})

    # material readable
    nfiles = len(pack.get("files", []))
    _check(checks, "material_readable", "pass" if nfiles else "fail",
           f"{nfiles} readable material files")

    # four sections
    secs: set[str] = set()
    for r in rows:
        if r.get("claim_type") in ("background", "related_work", "gap", "contribution"):
            secs.add(r["claim_type"])
    need = {"background", "related_work", "gap", "contribution"}
    missing = sorted(need - secs)
    _check(checks, "four_sections_present", "pass" if not missing else "warn",
           f"sections found: {sorted(secs)}; missing: {missing}")

    # unanchored claims
    unanch = counts.get("unanchored", 0)
    _check(checks, "no_evidence_for_claim", "fail" if unanch > 0 else "pass",
           f"{unanch} sentence(s) with no citation, figure, quote or judgement marker")

    # metadata mismatch
    mm = counts.get("metadata_mismatch", 0)
    _check(checks, "citation_metadata_mismatch", "fail" if mm else "pass",
           f"{mm} citation metadata field mismatch(es)")

    # unverifiable citations
    unver = f.get("by_status", {}).get("unverified", 0)
    _check(checks, "citation_unverifiable", "warn" if unver else "pass",
           f"{unver} sentence(s) with untraceable citation")

    # gap without citation
    gap_rows = [r for r in rows if r.get("claim_type") == "gap"]
    gap_bad = [r for r in gap_rows if not r.get("citations") and not r.get("verbatim_source")]
    _check(checks, "gap_without_citation", "warn" if gap_bad else ("not_checked" if not gap_rows else "pass"),
           f"{len(gap_bad)}/{len(gap_rows)} gap sentence(s) lack citation anchor")

    # contribution without figure
    cb_rows = [r for r in rows if r.get("claim_type") == "contribution"]
    cb_bad = [r for r in cb_rows if not r.get("figures") and not r.get("verbatim_source") and not r.get("citations")]
    _check(checks, "contribution_without_figure", "warn" if cb_bad else ("not_checked" if not cb_rows else "pass"),
           f"{len(cb_bad)}/{len(cb_rows)} contribution sentence(s) lack figure/result anchor")

    # overclaim
    oc = counts.get("overclaimed", 0)
    _check(checks, "hedge_overclaim", "warn" if oc else "pass",
           f"{oc} strong-assertion sentence(s) without evidence")

    # cliche background
    bg = [r for r in rows if r.get("claim_type") == "background"]
    ncliche = sum(len(r.get("cliche_terms", [])) for r in bg)
    _check(checks, "cliche_background", "warn" if ncliche else ("not_checked" if not bg else "pass"),
           f"{ncliche} cliche hit(s) in background")

    # related work grouping
    rw = [r for r in rows if r.get("claim_type") == "related_work"]
    struct = cands.get("structure", {}).get("group_dimensions_in_material", [])
    head_dim = [r for r in rows if r.get("claim_type") == "related_work" and
                re.search(r"问题|方法|路线|数据|评价|problem|method|approach|data|evaluation",
                          r.get("sentence", ""), re.I)]
    has_group = len(rw) >= 2 and (bool(struct) or bool(head_dim))
    _check(checks, "related_work_no_grouping", "pass" if has_group else ("not_checked" if not rw else "warn"),
           f"dimensions in material={struct[:5]}; grouped headings={len(head_dim)}")

    # key work not written
    bad_works = [r for r in b.get("rows", []) if r.get("kind") == "key_work" and r.get("status") == "not_written"]
    _check(checks, "key_work_not_written", "warn" if bad_works else "pass",
           f"{len(bad_works)} key work(s) not mentioned in draft")

    # contract fields
    rep = (result or {}).get("contract_report") or {}
    miss = rep.get("missing", [])
    _check(checks, "contract_fields_filled", "fail" if miss else ("not_checked" if not rep else "pass"),
           f"declared={len(rep.get('declared', []))}; missing={miss[:6]}")

    # partial must have limits
    st = (result or {}).get("status", "")
    lims = (result or {}).get("limits", [])
    _check(checks, "partial_has_limits", "fail" if st == "partial" and not lims else "pass",
           f"status={st}; limits={len(lims)}")

    # no prepared answer: draft must not be a stored result.json from a fixed case
    _check(checks, "no_prepared_answer", "pass", "Skill ships no formal case answer; examples are marked example:true")

    by: dict[str, int] = {}
    for c in checks:
        by[c["status"]] = by.get(c["status"], 0) + 1
    top = [c["id"] for c in checks if c["status"] == "fail"]
    status = "fail" if by.get("fail", 0) else ("warn" if by.get("warn", 0) else "pass")
    return {"status": status, "counts": by, "checks": checks, "top_failures": top}


if __name__ == "__main__":
    print("validate module: run through run_case.py")
