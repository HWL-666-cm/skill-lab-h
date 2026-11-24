"""Honour the case's `output_contract` field names inside result.json.

The runtime contract says result.json must carry "all original output_contract
fields and case_id". The contract's exact shape is not published, so this module
is tolerant about the input shape and strict about the output guarantee:

  * declared names are read from a list, a dict of field descriptions, a
    `{"fields": ...}` / `{"required": ...}` wrapper, or a JSON string of either;
  * a declared name is filled by aliasing an existing canonical field, by
    deriving it from the graph, or left as null and reported as missing;
  * nothing is invented. A visible hole beats a silent one.

Only top-level names are remapped; nested node/edge objects keep the canonical
keys documented in `references/output-contract.md`.
"""

from __future__ import annotations

import json
import re

ALIASES: dict[str, tuple[str, ...]] = {
    "case_id": ("caseid", "id", "case", "casename", "inputid", "taskcaseid", "caseref"),
    "status": ("status", "runstatus", "resultstatus", "state", "outcome", "completion"),
    "task": ("task", "tasktype", "taskname", "taskkind"),
    "input": ("input", "inputs", "inputfiles", "inputfile", "materials", "material",
              "materialfiles", "corpus"),
    "graph": ("graph", "kg", "knowledgegraph", "graphdata"),
    "nodes": ("nodes", "entities", "entitylist", "vertices", "concepts"),
    "edges": ("edges", "relations", "triples", "relationships", "links", "assertions",
              "claims", "statements", "facts"),
    "merges": ("merges", "merged", "mergeenrecords", "mergerecords", "alignment"),
    "conflicts": ("conflicts", "conflict", "contradictions", "disagreements"),
    "queries": ("queries", "query", "queryresults", "answers", "qa"),
    "validation": ("validation", "checks", "quality", "verification", "audit", "qa",
                   "selfcheck"),
    "uncertainty": ("uncertainty", "uncertainties", "limitations", "notes",
                    "openquestions", "caveats", "unresolved", "boundaries"),
    "sources": ("sources", "source", "sourcemetadata", "provenance", "references",
                "citations", "papers", "metadata"),
    "change_log": ("changelog", "changes", "updates", "revisionlog", "auditlog"),
    "contract_report": ("contractreport", "outputcontractreport"),
    "evidence_index": ("evidence", "evidences", "evidencequotes", "quotations",
                       "passages", "evidenceindex", "supportingevidence"),
}


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


LOOKUP: dict[str, str] = {}
for _canon, _names in ALIASES.items():
    for _n in (_canon,) + _names:
        LOOKUP.setdefault(_norm(_n), _canon)


def build_evidence_index(result: dict) -> list[dict]:
    """Flatten node/edge evidence into one list of quotable fragments."""
    rows: list[dict] = []
    for kind, items in (("node", result.get("nodes") or []), ("edge", result.get("edges") or [])):
        for item in items:
            for ev in item.get("evidence") or []:
                rows.append({
                    "element_id": item.get("id"),
                    "element_kind": kind,
                    "source_id": ev.get("source_id"),
                    "paragraph_id": ev.get("paragraph_id"),
                    "quote": ev.get("quote"),
                })
    return rows


def build_claims(result: dict) -> list[dict]:
    """Present edges as subject-predicate-object claims, without adding any."""
    rows = []
    for e in result.get("edges") or []:
        rows.append({
            "id": e.get("id"),
            "subject": e.get("subject_label"),
            "predicate": e.get("predicate"),
            "object": e.get("object_label"),
            "evidence": e.get("evidence"),
            "strength": e.get("strength"),
        })
    return rows


DERIVED = {
    "evidence_index": build_evidence_index,
    "edges": build_claims,
}


def declared_fields(contract) -> list[str]:
    seen: list[str] = []

    def add(name: str) -> None:
        name = str(name).strip()
        if name and name not in seen:
            seen.append(name)

    def walk(node, depth: int = 0) -> None:
        if depth > 3 or node is None:
            return
        if isinstance(node, str):
            text = node.strip()
            if text[:1] in "[{":
                try:
                    walk(json.loads(text), depth + 1)
                except Exception:
                    add(text)
            else:
                add(text)
        elif isinstance(node, list):
            for item in node:
                walk(item, depth + 1)
        elif isinstance(node, dict):
            lowered = {_norm(k): k for k in node}
            for wrapper in ("fields", "required", "properties", "schema", "contract",
                            "outputcontract", "resultjson"):
                if len(node) == 1 and wrapper in lowered:
                    walk(node[lowered[wrapper]], depth + 1)
                    return
            for key in node:
                add(key)

    walk(contract)
    return seen


def apply(result: dict, contract) -> tuple[dict, dict]:
    """Return (result_with_aliases, report). Does not mutate the input."""
    out = dict(result)
    names = declared_fields(contract)
    report = {
        "declared": names,
        "native": [],
        "aliased": {},
        "derived": {},
        "missing": [],
        "source": "case.json:output_contract" if names else "absent",
    }
    if not names:
        return out, report

    for name in names:
        if name in out:
            report["native"].append(name)
            continue
        canon = LOOKUP.get(_norm(name))
        if canon and canon in out:
            out[name] = out[canon]
            report["aliased"][name] = canon
        elif canon and canon in DERIVED:
            out[name] = DERIVED[canon](out)
            report["derived"][name] = canon
        else:
            out[name] = None
            report["missing"].append(name)

    if report["missing"]:
        note = ("output_contract 声明了本 Skill 不产出的字段："
                + ", ".join(report["missing"])
                + "；这些字段以 null 交付而不是猜内容，见 contract_report.missing。")
        out["uncertainty"] = list(out.get("uncertainty") or []) + [note]

    out["contract_report"] = report
    return out, report
