#!/usr/bin/env python3
"""Honour whatever output_contract the case declares at runtime.

The platform writes the contract, so its field names are not knowable in
advance.  Three shapes are supported (list / {"fields": ...} / mapping); a
contract silently ignored is worse than one that is refused.

For each declared field: if this package already produces an equivalent under
a different name, copy it; if it is derivable from the build pack, derive it;
otherwise set it to null and record it in contract_report.missing.  Nothing is
invented to make a field look filled.
"""
from __future__ import annotations

import json
from typing import Any

# contract field name -> the key this package produces
ALIASES = {
    "case_id": "case_id", "case": "case_id", "input_id": "case_id",
    "status": "status", "state": "status", "run_status": "status",
    "sources": "sources", "materials": "sources", "inputs": "sources",
    "source_map": "sources", "input_files": "sources",
    "uncertainty": "uncertainty", "uncertainties": "uncertainty",
    "limits": "uncertainty", "caveats": "uncertainty", "questions": "uncertainty",
    "changes": "changes", "change_log": "changes", "fixes": "changes",
    "repairs": "changes", "revisions": "changes", "diff": "changes",
    "error_ledger": "error_ledger", "diagnostics": "error_ledger",
    "errors": "error_ledger", "issues": "error_ledger", "findings": "error_ledger",
    "build_manifest": "build_manifest", "manifest": "build_manifest",
    "environment": "build_manifest", "dependencies": "build_manifest",
    "versions": "build_manifest", "reproduce": "reproduce",
    "reproducibility": "reproduce", "reproduction": "reproduce",
    "artifacts": "artifacts", "source_files": "artifacts",
    "tex_source": "artifacts", "latex_source": "artifacts",
    "manuscript": "artifacts", "source": "artifacts", "latex": "artifacts",
    "result": "artifacts", "output": "artifacts", "main_result": "artifacts",
    "validation": "validation", "checks": "validation", "gate": "validation",
    "warnings": "warnings", "notes": "uncertainty",
    "profile": "project_profile", "project_profile": "project_profile",
    "engine": "build_manifest", "compiler": "build_manifest",
}

DERIVED = ("sources", "artifacts")


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


def build_sources(result: dict, pack: dict | None = None) -> list[dict]:
    out: list[dict] = []
    for s in (pack or {}).get("files", []):
        out.append({"path": s.get("path", ""), "kind": s.get("kind", ""),
                    "role": s.get("role", ""), "note": s.get("note", "")})
    return out


def build_artifacts(result: dict) -> list[dict]:
    out: list[dict] = []
    for a in result.get("artifacts", []) or []:
        out.append(a)
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
            if target == "sources":
                result[f] = build_sources(result, pack)
            else:
                result[f] = build_artifacts(result)
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
    print(json.dumps(declared_fields({"output_contract": ["case_id", "errors", "xyz"]}),
                     ensure_ascii=False))
