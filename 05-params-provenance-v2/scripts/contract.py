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
    "parameters": "ledger", "parameter_ledger": "ledger", "params": "ledger",
    "claims": "claims", "assertions": "claims",
    "evidence": "evidence_index", "facts": "evidence_index",
    "source_map": "evidence_index", "provenance": "evidence_index",
    "draft": "methods_markdown", "manuscript": "methods_markdown",
    "methods": "methods_markdown", "section": "methods_markdown",
    "text": "methods_markdown", "article": "methods_markdown",
    "conflicts": "conflicts", "inconsistencies": "conflicts",
    "gaps": "gaps", "questions": "gaps", "open_questions": "gaps",
    "uncertainty": "uncertainty", "uncertainties": "uncertainty",
    "change_log": "change_log", "changes": "change_log", "revisions": "change_log",
    "coverage": "coverage", "elements": "coverage",
    "validation": "validation", "checks": "validation",
    "sources": "sources", "materials": "sources",
    "status": "status", "case_id": "case_id", "case": "case_id",
    "warnings": "warnings", "notes": "uncertainty",
    "tables": "ledger", "figure_refs": "evidence_index",
}

DERIVED = ("evidence_index", "claims", "sources")


def build_evidence_index(result: dict) -> list[dict]:
    """Every value with its position, flat, for a reviewer who wants one list."""
    out: list[dict] = []
    for e in result.get("ledger", {}).get("entries", []):
        for v in e.get("values", []):
            out.append({
                "kind": "parameter_value",
                "name": e["name"],
                "scope": e.get("scope", ""),
                "value": v.get("raw", ""),
                "source": {"kind": v.get("source_kind", ""), "path": v.get("path", ""),
                           "locator": v.get("locator", ""), "quote": v.get("quote", "")},
                "ledger_status": e.get("status", ""),
            })
    for t in result.get("alignment", {}).get("forward", {}).get("traced", []):
        out.append({
            "kind": "text_number",
            "value": t.get("raw", ""),
            "section": t.get("heading", ""),
            "paragraph": t.get("paragraph"),
            "entry_id": t.get("entry_id"),
            "source": {"path": t.get("evidence", "").rsplit(":", 1)[0],
                       "locator": t.get("evidence", "").rsplit(":", 1)[-1]},
        })
    return out


def build_claims(result: dict) -> list[dict]:
    """One row per statement the draft makes with a number behind it."""
    out: list[dict] = []
    al = result.get("alignment", {})
    for t in al.get("forward", {}).get("traced", []):
        out.append({"claim": f"{t.get('entry_name')} = {t.get('raw')}",
                    "support": "traced", "entry_id": t.get("entry_id"),
                    "where": t.get("evidence", "")})
    for i in al.get("forward", {}).get("invented", []):
        out.append({"claim": f"unsourced value {i.get('raw')}",
                    "support": "none", "where": f"paragraph {i.get('paragraph')}"})
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
            elif target == "claims":
                result[f] = build_claims(result)
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
