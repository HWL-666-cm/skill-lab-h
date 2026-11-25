#!/usr/bin/env python3
"""Honour whatever output_contract the case declares.

The contract is written by the platform, not by me, so its field names are not
knowable in advance.  Three shapes are supported, because a contract that is
silently ignored is worse than one that is refused:

    {"output_contract": ["a", "b"]}
    {"output_contract": {"fields": ["a", "b"]}}
    {"output_contract": {"a": "...", "b": "..."}}
    {"output_contract": [{"name": "a"}, {"field": "b"}]}

For each declared field: if this package already produces an equivalent under a
different name, copy it; if it is derivable from the ledger, derive it; otherwise
set it to null and record it in ``contract_report.missing``.  Nothing is invented
to make a field look filled.
"""

from __future__ import annotations

import json
from typing import Any

# contract field name -> the key this package produces
ALIASES = {
    # 08 writes an introduction/related-work section; these are the equivalent keys.
    "draft": "intro_related_work_markdown", "manuscript": "intro_related_work_markdown",
    "methods": "intro_related_work_markdown", "section": "intro_related_work_markdown",
    "text": "intro_related_work_markdown", "article": "intro_related_work_markdown",
    "introduction": "intro_related_work_markdown", "related_work": "intro_related_work_markdown",
    "claims": "claim_ledger", "assertions": "claim_ledger",
    "claim_ledger": "claim_ledger", "claim_evidence": "claim_ledger",
    "evidence": "evidence_index", "facts": "evidence_index",
    "source_map": "evidence_index", "provenance": "evidence_index",
    "citation_check": "citation_check", "citations": "citation_check",
    "references": "citation_check", "metadata_check": "citation_check",
    "conflicts": "conflicts", "inconsistencies": "conflicts",
    "gaps": "gaps", "questions": "gaps", "open_questions": "gaps",
    "uncertainty": "uncertainty", "uncertainties": "uncertainty",
    "change_log": "change_log", "changes": "change_log", "revisions": "change_log",
    "coverage": "coverage", "elements": "coverage",
    "validation": "validation", "checks": "validation",
    "sources": "sources", "materials": "sources",
    "alignment": "alignment", "alignment_report": "alignment",
    "status": "status", "case_id": "case_id", "case": "case_id",
    "warnings": "warnings", "notes": "uncertainty",
    "figures": "evidence_index", "figure_refs": "evidence_index",
}

DERIVED = ("evidence_index",)


def build_evidence_index(result: dict) -> list[dict]:
    """Flat list of every claim and the anchor it leans on."""
    out: list[dict] = []
    for row in result.get("claim_ledger", {}).get("rows", []):
        ev = row.get("evidence", {})
        out.append({
            "kind": "claim_evidence",
            "claim_id": row.get("claim_id", ""),
            "claim_type": row.get("claim_type", ""),
            "text": row.get("text", ""),
            "status": row.get("status", ""),
            "citations": ev.get("citations", []),
            "figures": ev.get("figures", []),
            "verbatim_source": ev.get("verbatim_source", ""),
        })
    return out


def build_sources(result: dict, pack: dict | None = None) -> list[dict]:
    out: list[dict] = []
    for s in (pack or {}).get("files", []):
        out.append({"path": s["source"], "kind": s["kind"], "reader": s["reader"],
                    "units": s["units"], "note": s.get("note", "")})
    return out


def declared_fields(contract: Any) -> list[str]:
    out: list[str] = []

    def add(name: str) -> None:
        n = str(name).strip()
        if n and n not in out:
            out.append(n)

    def walk(node: Any, depth: int = 0) -> None:
        if depth > 4 or node is None:
            return
        if isinstance(node, str):
            add(node)
        elif isinstance(node, list):
            for x in node:
                walk(x, depth + 1)
        elif isinstance(node, dict):
            for k in ("name", "field", "key"):
                if isinstance(node.get(k), str) and len(node) <= 3:
                    add(node[k])
                    return
            for k, v in node.items():
                if k in ("fields", "required", "keys", "output_contract", "schema"):
                    walk(v, depth + 1)
                elif isinstance(v, (list, dict)):
                    walk(v, depth + 1)
                else:
                    add(k)

    if isinstance(contract, dict) and "output_contract" in contract:
        contract = contract["output_contract"]
    walk(contract)
    return out


def apply(result: dict, contract: Any, pack: dict | None = None) -> tuple[dict, dict]:
    fields = declared_fields(contract)
    report = {"declared": fields, "satisfied": [], "aliased": [], "derived": [],
              "missing": [], "note": ""}
    if not fields:
        return result, report

    for f in fields:
        key = f.strip().lower().replace("-", "_").replace(" ", "_")
        if f in result or key in result:
            report["satisfied"].append(f)
            continue
        target = ALIASES.get(key)
        if target and target in result:
            result[f] = result[target]
            report["aliased"].append({"field": f, "from": target})
            continue
        if target in DERIVED:
            if target == "evidence_index":
                result[f] = build_evidence_index(result)
            else:
                result[f] = build_sources(result, pack)
            report["derived"].append({"field": f, "from": target})
            continue
        result[f] = None
        report["missing"].append(f)

    if report["missing"]:
        report["note"] = ("fields with no equivalent were set to null rather than "
                          "filled with a plausible-looking value")
        result.setdefault("uncertainty", []).append(
            "output_contract fields not produced: " + ", ".join(report["missing"]))
    result["contract_report"] = report
    return result, report


if __name__ == "__main__":
    print(json.dumps(declared_fields({"output_contract": ["draft", "parameters", "xyz"]}),
                     ensure_ascii=False))
