#!/usr/bin/env python3
"""The parameter ledger: one row per (name, scope), every value kept.

Why a ledger and not a list of parameters in the text
-----------------------------------------------------
A parameter written in prose is an assertion.  A ledger row is an assertion plus
two facts that can be checked later: where the value came from, and what else was
said about the same name.  Everything downstream (the two-way alignment, the gap
list, the gate) reads this structure rather than the prose.

Four decisions worth stating
----------------------------
1.  **Same name in different scopes of one file is not a conflict.**  A config
    that writes ``train.batch_size: 32`` next to ``infer.batch_size: 64`` has
    already answered the question by naming the sections; the same holds for two
    rows of one results table (XL/2 vs B/4).  Collapsing those would manufacture
    a conflict that does not exist.
2.  **Different files carrying different values for one name IS the conflict we
    are looking for.**  A config saying ``learning_rate: 1e-4`` and a log saying
    ``lr: 1e-3`` is exactly the failure this tool exists to catch, and it would
    be invisible if scopes were compared literally -- the config's scope is the
    section name ``train`` while the log's scope is the line's position
    ``log/epoch1``.  Those are the same claim in two places, so the comparison
    runs across files and only within a name.
3.  **A conflict keeps every value.**  No averaging, no "latest wins".  The
    author has to pick; the tool's job is to show both with their positions.
4.  **A manuscript-only value is not confirmed.**  A paper saying "lr 1e-4" is
    evidence that the paper says so, not evidence about the code.  It is graded
    ``manuscript_only`` and goes to the confirmation list.
"""

from __future__ import annotations

import hashlib
from typing import Any

import numbers as N

SOURCE_WEIGHT = {
    "author_confirmed": 6, "config": 5, "log": 4, "code": 3,
    "manuscript": 2, "other": 1, "none": 0,
}

# sources that can settle a disagreement: they are the run itself, not a
# description of it.  Two manuscript values disagreeing is a question for the
# author, not a finding, because prose often describes several instances.
HARD = {"config", "log", "code", "author_confirmed"}

# parameters where "10%" and "0.1" are the same claim written differently
RATIO_NAME = ("rate", "ratio", "dropout", "split", "fraction", "p_", "prob", "比例", "率")


def _eid(*parts: str) -> str:
    return "e" + hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:10]


def _is_ratio_name(name: str) -> bool:
    n = name.lower()
    return any(tok in n for tok in RATIO_NAME)


def equivalent(a: dict, b: dict, name: str) -> tuple[bool, str]:
    """Same claim?  ``a`` and ``b`` are flat value rows: {value: float, family: str}."""
    va = {"value": a.get("value"), "family": a.get("family", "none")}
    vb = {"value": b.get("value"), "family": b.get("family", "none")}
    if N.same(va, vb):
        return True, ""
    if not _is_ratio_name(name):
        return False, ""
    # numbers.py already divides a percent by 100, so a percent-written value and a
    # fraction-written value agree in number and differ only in "family"; that is a
    # form difference, not a disagreement about the setting
    pa, pb = va["family"] == "percent", vb["family"] == "percent"
    x, y = va["value"], vb["value"]
    if pa != pb and x is not None and y is not None and abs(x - y) <= 1e-12:
        return True, "same ratio written as percent on one side and as a fraction on the other"
    return False, ""


def build(cands: dict, schema: dict) -> dict[str, Any]:
    groups: dict[tuple[str, str], list[dict]] = {}
    held_back = 0
    for c in cands["candidates"]:
        if c.get("tier") == "other":
            held_back += 1
            continue
        groups.setdefault((c["name"], c["scope"]), []).append(c)

    entries: list[dict] = []
    distinct_of: dict[str, list[dict]] = {}
    percent_notes: list[dict] = []

    for key in sorted(groups):
        items = sorted(groups[key], key=lambda c: (SOURCE_WEIGHT.get(c["source"]["kind"], 0) * -1,
                                                   c["source"]["path"], c["source"]["locator"]))
        name, scope = key
        values = []
        for c in items:
            values.append({
                "raw": c["value"].get("raw", ""),
                "value": c["value"].get("value"),
                "unit": c["value"].get("unit", ""),
                "family": c["value"].get("family", "none"),
                "magnitude_suffix": c["value"].get("magnitude_suffix"),
                "source_kind": c["source"]["kind"],
                "path": c["source"]["path"],
                "locator": c["source"]["locator"],
                "quote": c["source"]["quote"],
                "tier": c["tier"],
                "param_id": c["param_id"],
                "shape": c["shape"],
            })

        base = values[0]
        distinct = [base]
        for v in values[1:]:
            same_as_any, note = False, ""
            for d in distinct:
                ok, nt = equivalent(v, d, name)
                if ok:
                    same_as_any, note = True, nt
                    if nt:
                        percent_notes.append({"name": name, "scope": scope, "note": nt,
                                              "a": d["raw"], "b": v["raw"]})
                    break
            if not same_as_any:
                distinct.append(v)

        kinds = {v["source_kind"] for v in values}
        hard = bool(kinds & HARD)
        if len(distinct) > 1 and hard:
            status = "conflicting"
        elif len(distinct) > 1:
            # one sentence often describes several instances: "8x A100s for XL/2
            # and 4x A100s for B/4".  Prose alone cannot say which belongs to which,
            # so this is a question for the author, not a contradiction.
            status = "prose_multi_value"
        elif hard:
            status = "confirmed"
        elif kinds == {"manuscript"}:
            status = "manuscript_only"
        else:
            status = "weak_source"

        entry = {
            "entry_id": _eid(name, scope),
            "name": name,
            "scope": scope,
            "family": items[0]["family"],
            "element": items[0]["element"] or _element_of(items[0]["family"]),
            "unit": next((v["unit"] for v in values if v["unit"]), ""),
            "status": status,
            "source_kinds": sorted(kinds),
            "best_source_kind": max(kinds, key=lambda k: SOURCE_WEIGHT.get(k, 0)),
            "n_values": len(values),
            "n_distinct": len(distinct),
            "values": values,
        }
        entries.append(entry)
        distinct_of[entry["entry_id"]] = distinct

    conflicts = _cross_file_conflicts(entries, distinct_of, percent_notes)
    conflict_names = {c["name"] for c in conflicts}

    # a name that appears in several scopes is worth showing, not merging
    by_name: dict[str, list[dict]] = {}
    for e in entries:
        by_name.setdefault(e["name"], []).append(e)
    multi_scope = [
        {"name": n, "scopes": [e["scope"] for e in es],
         "values": [v["raw"] for e in es for v in distinct_of[e["entry_id"]]],
         "note": "same parameter in several scopes; not a conflict, and not merged"}
        for n, es in sorted(by_name.items())
        if len({e["scope"] for e in es}) > 1 and n not in conflict_names
    ]

    return {
        "entries": entries,
        "conflicts": conflicts,
        "percent_form_notes": percent_notes,
        "multi_scope": multi_scope,
        "stats": {
            "entries": len(entries),
            "values": len(cands["candidates"]),
            "conflicting": len(conflicts),
            "conflicting_names": sorted(conflict_names),
            "manuscript_only": sum(1 for e in entries if e["status"] == "manuscript_only"),
            "prose_multi_value": sum(1 for e in entries if e["status"] == "prose_multi_value"),
            "weak_source": sum(1 for e in entries if e["status"] == "weak_source"),
            "multi_scope_names": len(multi_scope),
            "held_back_other_tier": held_back,
            "by_element": _count(e["element"] for e in entries),
            "by_family": _count(e["family"] for e in entries),
            "by_best_kind": _count(e["best_source_kind"] for e in entries),
        },
    }


def _agree(a_vals: list[dict], b_vals: list[dict], name: str,
           a_hard: bool, b_hard: bool) -> bool:
    """Does one side's claim appear on the other, given what each side can prove?

    Two hard sources must agree value for value: a config and a log are both the
    run, so a number that appears in one and not the other is a real contradiction.

    A hard source against prose is one-directional.  A README routinely documents
    several runs ("imgsz=640" in the quick-start example, "imgsz=2048" for the
    Cityscapes benchmark), so the prose mentioning an extra instance is not a
    contradiction -- but the value the run actually used has to appear in the
    prose at all.  Requiring set equality here turned a correct README into a
    false blocking conflict in the ultralytics material.
    """
    if a_hard and b_hard:
        return (_covers(a_vals, b_vals, name) and _covers(b_vals, a_vals, name))
    if a_hard:
        return _covers(a_vals, b_vals, name)
    if b_hard:
        return _covers(b_vals, a_vals, name)
    return _covers(a_vals, b_vals, name) and _covers(b_vals, a_vals, name)


def _covers(side: list[dict], other: list[dict], name: str) -> bool:
    """Every value of ``side`` is matched by some value of ``other``."""
    return all(any(equivalent(v, o, name)[0] for o in other) for v in side)


def _cross_file_conflicts(entries: list[dict], distinct_of: dict[str, list[dict]],
                          percent_notes: list[dict]) -> list[dict]:
    """Disagreement about one name that no single file has already disambiguated.

    Entries from the same file are never compared: the author's own layout (two
    sections, two table rows) is what tells those apart, and re-reading it as a
    contradiction would block a correct manuscript.  Everything else is compared,
    because "config says X, log says Y" is the finding, not a scoping detail.
    """
    by_name: dict[str, list[dict]] = {}
    for e in entries:
        by_name.setdefault(e["name"], []).append(e)

    out: list[dict] = []
    for name in sorted(by_name):
        es = by_name[name]
        if len(es) < 2:
            continue
        paths = {e["entry_id"]: {v["path"] for v in e["values"]} for e in es}
        hard = {e["entry_id"]: bool(set(e["source_kinds"]) & HARD) for e in es}
        involved: list[dict] = []
        for i, a in enumerate(es):
            for b in es[i + 1:]:
                if paths[a["entry_id"]] & paths[b["entry_id"]]:
                    continue
                if _agree(distinct_of[a["entry_id"]], distinct_of[b["entry_id"]], name,
                          hard[a["entry_id"]], hard[b["entry_id"]]):
                    continue
                for e in (a, b):
                    if e not in involved:
                        involved.append(e)
        if not involved:
            continue
        kinds: set[str] = set()
        for e in involved:
            kinds |= set(e["source_kinds"])
        if not (kinds & HARD):
            # prose alone cannot say which instance a value belongs to; ask
            # instead of declaring a contradiction
            for e in involved:
                if e["status"] == "manuscript_only":
                    e["status"] = "prose_multi_value"
            continue

        # Two hard sources disagreeing means the run contradicts itself and no
        # draft can be correct: blocking.  A hard source against prose is a
        # question, because a README also documents other runs -- the ultralytics
        # README explains "batch=1" for a latency measurement while the training
        # config says 16, and blocking on that would be a false alarm.
        hard_seen = {k for k in kinds if k in HARD}
        severity = "blocking" if len(hard_seen) >= 2 else "major"

        kept: list[dict] = []
        for e in involved:
            e["status"] = "conflicting"
            for v in distinct_of[e["entry_id"]]:
                row = {"raw": v["raw"], "value": v["value"], "family": v["family"],
                       "path": v["path"], "locator": v["locator"],
                       "source_kind": v["source_kind"]}
                if not any(x["raw"] == row["raw"] and x["path"] == row["path"]
                           and x["locator"] == row["locator"] for x in kept):
                    kept.append(row)
        out.append({
            "entry_id": involved[0]["entry_id"],
            "entry_ids": [e["entry_id"] for e in involved],
            "name": name,
            "scope": involved[0]["scope"],
            "scopes": [e["scope"] for e in involved],
            "kind": "value_disagreement",
            "severity_hint": severity,
            "values": kept,
            "reason": "one parameter name carries different values in different files; "
                      "both are kept and the author must say which one the run used"
                      if severity == "blocking" else
                      "the run's recorded value does not appear in the prose, which may "
                      "describe a different run or be out of date",
        })
    return out


ELEMENT_OF_FAMILY = {
    "optim": "params", "schedule": "params", "model": "params",
    "data": "data", "runtime": "setup", "reproducibility": "setup",
    "eval": "params", "other": "params",
}


def _element_of(family: str) -> str:
    return ELEMENT_OF_FAMILY.get(family, "params")


def _count(items) -> dict[str, int]:
    out: dict[str, int] = {}
    for i in items:
        out[i] = out.get(i, 0) + 1
    return out
