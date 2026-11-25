"""Honour the case's `output_contract` field names inside result.json.

Why this module exists
----------------------
The runtime contract in `task.md` says result.json must carry "all original
output_contract fields and case_id". That contract arrives inside
`/input/case.json` and its exact shape is not published, so guessing a single
concrete layout would be fragile. This module is therefore deliberately
tolerant about the *input* shape and strict about the *output* guarantee:

  * it reads the declared field names from a dict of field descriptions, a list
    of names, a `{"fields": ...}` / `{"required": ...}` wrapper, or a JSON
    string that parses to any of those;
  * it never drops a canonical field, it only adds the declared name pointing at
    the same value (an alias), so the platform can read either spelling;
  * for a declared name it cannot map with confidence it writes the key with a
    null value and reports the gap in `contract_report.missing` and in
    `result.uncertainty`. A visible hole is better than a silent one, and it is
    never filled with invented content.

Scope limit worth knowing: only top-level field names are remapped. If the
contract describes per-assertion names, the assertion objects keep the
canonical keys listed in `references/output-contract.md`.
"""

from __future__ import annotations

import json
import re

# Canonical name -> the names we accept for it. Compared after `norm()`, so
# "case_id", "caseId", "case-id" and "Case ID" all collapse to "caseid".
ALIASES: dict[str, tuple[str, ...]] = {
    "case_id": ("caseid", "id", "case", "casename", "inputid", "taskcaseid",
                "casereference", "caseref"),
    "status": ("status", "runstatus", "resultstatus", "state", "outcome",
               "completion"),
    "task": ("task", "tasktype", "taskname", "taskkind"),
    "input": ("input", "inputs", "inputfiles", "inputfile", "materials",
              "material", "materialfiles"),
    "assertions": ("assertions", "assertion", "claims", "claim", "statements",
                   "statement", "facts", "records", "entries", "items",
                   "results", "knowledge", "knowledgeunits", "nanopublications"),
    "sources": ("sources", "source", "sourcemetadata", "sourcesmetadata",
                "provenance", "references", "citations", "papers", "metadata"),
    "validation": ("validation", "checks", "quality", "verification", "audit",
                   "qa", "selfcheck"),
    "uncertainty": ("uncertainty", "uncertainties", "limitations", "notes",
                    "openquestions", "caveats", "unresolved", "unresolveditems",
                    "boundaries"),
    "contract_report": ("contractreport", "outputcontractreport"),
    # Not a canonical key of its own: only materialised when the case asks for it.
    "evidence_index": ("evidence", "evidences", "evidencefragments",
                       "evidencequotes", "quotations", "passages",
                       "quotepassages", "evidenceindex", "supportingevidence"),
}

def build_evidence_index(result: dict) -> list[dict]:
    """Flatten per-assertion evidence into one top-level list.

    Only called when a case declares an evidence field at the top level. The
    values are copied, not recomputed, so this can never disagree with the
    per-assertion evidence it came from.
    """
    rows = []
    for claim in result.get("assertions") or []:
        ev = claim.get("evidence") or {}
        rows.append({
            "assertion_id": claim.get("id"),
            "quote": ev.get("quote"),
            "page": ev.get("page"),
            "char_span": ev.get("char_span"),
            "sentence_id": ev.get("sentence_id"),
        })
    return rows


# Canonical keys that do not exist in a bare result.json but can be derived
# from it without inventing anything.
DERIVED = {
    "evidence_index": build_evidence_index,
}


def norm_key(name: str) -> str:
    """Lower-case and drop everything that is not a letter or digit."""
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


# Reverse lookup: normalised alias -> canonical key. `setdefault` keeps the
# first writer, and the canonical spelling is written first, so it always wins.
LOOKUP: dict[str, str] = {}
for _canon, _names in ALIASES.items():
    for _n in (_canon,) + _names:
        LOOKUP.setdefault(norm_key(_n), _canon)


def declared_fields(contract) -> list[str]:
    """Return the declared top-level field names, in first-seen order."""
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
            # Unwrap the usual single-key containers before reading names.
            lowered = {norm_key(k): k for k in node}
            for wrapper in ("fields", "required", "properties", "schema",
                            "contract", "outputcontract", "resultjson"):
                if len(node) == 1 and wrapper in lowered:
                    walk(node[lowered[wrapper]], depth + 1)
                    return
            for key in node:
                add(key)

    walk(contract)
    return seen


def apply(result: dict, contract) -> tuple[dict, dict]:
    """Return (result_with_aliases, report). Never mutates the input dict."""
    out = dict(result)
    names = declared_fields(contract)
    report = {
        "declared": names,
        "native": [],      # declared name is already a canonical key
        "aliased": {},     # declared name -> canonical key it was copied from
        "derived": {},     # declared name -> canonical key it was computed from
        "missing": [],     # declared name we could not map
        "source": "case.json:output_contract" if names else "absent",
    }
    if not names:
        return out, report

    for name in names:
        if name in out:
            report["native"].append(name)
            continue
        canon = LOOKUP.get(norm_key(name))
        if canon and canon in out:
            out[name] = out[canon]
            report["aliased"][name] = canon
        elif canon and canon in DERIVED:
            out[name] = DERIVED[canon](out)
            report["derived"][name] = canon
        else:
            out[name] = None
            report["missing"].append(name)

    # Make the gap visible in the human-facing part of the result too.
    if report["missing"]:
        note = ("output_contract declares field(s) " + ", ".join(report["missing"])
                + " that this skill does not produce; they are present as null "
                  "instead of being guessed. See contract_report.missing.")
        out["uncertainty"] = list(out.get("uncertainty") or []) + [note]

    out["contract_report"] = report
    return out, report
