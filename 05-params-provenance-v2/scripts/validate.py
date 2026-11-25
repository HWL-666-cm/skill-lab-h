#!/usr/bin/env python3
"""Quality gate. Four states, because "not checked" is not "passed".

A gate that can only say pass/warn/fail invites a quiet lie: any check the tool
could not run ends up counted as a pass, and the overall status looks better than
the evidence.  So every check returns one of

    pass         the check ran and the material satisfies it
    warn         it ran and found something a reviewer should see
    fail         it ran and found something that blocks use
    not_checked  it could not run here, and is NOT counted as a pass

The summary status is ``incomplete`` when nothing failed but something was not
checked.  That word is the point: the deliverable is honest about its own reach.
"""

from __future__ import annotations

import re
from typing import Any

PASS, WARN, FAIL, UNCHECKED = "pass", "warn", "fail", "not_checked"
_ORDER = {PASS: 0, UNCHECKED: 1, WARN: 2, FAIL: 3}


def _c(code: str, status: str, detail: str, fix: str = "", **extra) -> dict:
    return {"code": code, "status": status, "detail": detail, "fix": fix, **extra}


def _unit_index(pack: dict) -> dict[tuple[str, str], dict]:
    idx = {}
    for u in pack.get("units", []):
        idx[(u["source"], u["locator"])] = u
    return idx


_LINE_LOC = re.compile(r"^L(\d+)$")


def validate(ledger: dict, alignment: dict, gaps: dict, pack: dict,
             draft_text: str, result_meta: dict | None = None) -> dict[str, Any]:
    checks: list[dict] = []
    uidx = _unit_index(pack)
    entries = ledger.get("entries") or []
    conflicts = ledger.get("conflicts") or []
    fwd = alignment.get("forward") or {}
    bwd = alignment.get("backward") or {}

    # ------------------------------------------------------------- ledger
    checks.append(_c("ledger_has_rows", PASS if entries else FAIL,
                     f"{len(entries)} rows", "no parameter could be read from the material"
                     if not entries else ""))
    if not entries:
        for code in ("row_source_present", "locator_resolves", "quote_verbatim",
                     "value_parseable", "no_dangling_pointer"):
            checks.append(_c(code, UNCHECKED, "no rows to check", "provide readable material"))

    missing_source = [e for e in entries if not (e["values"] and e["values"][0]["path"]
                                                 and e["values"][0]["locator"])]
    checks.append(_c("row_source_present", PASS if not missing_source else FAIL,
                     f"{len(missing_source)} rows without path/locator",
                     "every value needs a position a human can open"))

    unresolved, bad_quote = [], []
    for e in entries:
        for v in e["values"]:
            u = uidx.get((v["path"], v["locator"]))
            if u is None:
                # a locator that is not in the index is either a bad pointer or a
                # locator style this build cannot resolve; both are reported
                unresolved.append(f"{e['name']}@{v['path']}:{v['locator']}")
                continue
            q = (v.get("quote") or "").strip()
            if q and q[:80] not in u["text"]:
                bad_quote.append(f"{e['name']}@{v['path']}:{v['locator']}")
    checks.append(_c("locator_resolves", PASS if not unresolved else FAIL,
                     f"{len(unresolved)} values point nowhere"
                     + (f": {unresolved[:3]}" if unresolved else ""),
                     "a locator that does not resolve cannot be checked by a reviewer"))
    checks.append(_c("quote_verbatim", PASS if not bad_quote else FAIL,
                     f"{len(bad_quote)} quotes are not verbatim"
                     + (f": {bad_quote[:3]}" if bad_quote else ""),
                     "a paraphrase in the quote field cannot prove the value was read"))

    unparsed = [e["name"] for e in entries
                if all(v.get("value") is None for v in e["values"])]
    checks.append(_c("value_parseable", PASS if not unparsed else WARN,
                     f"{len(unparsed)} rows are categorical or unparsed"
                     + (f": {unparsed[:4]}" if unparsed else ""),
                     "a categorical setting is fine; an unparsed number is not",
                     rows=unparsed[:8]))

    dangling = [c["name"] for c in conflicts if len(c.get("values") or []) < 2]
    checks.append(_c("no_dangling_pointer", PASS if not dangling else FAIL,
                     f"{len(dangling)} conflicts declared without distinct values",
                     "a conflict flag with no second value would mislead the author"))

    # ------------------------------------------------------------ the draft
    inv = fwd.get("invented") or []
    checks.append(_c("no_invented_number", PASS if not inv else FAIL,
                     f"{len(inv)} numbers have no material source"
                     + (f" (e.g. {inv[0]['raw']} in paragraph {inv[0]['paragraph']})" if inv else ""),
                     "either cite the file and line, or remove the number",
                     examples=[{"raw": x["raw"], "paragraph": x["paragraph"]} for x in inv[:5]]))

    vo = fwd.get("value_only") or []
    checks.append(_c("no_false_attribution", PASS if not vo else WARN,
                     f"{len(vo)} values match a ledger row whose parameter is not named nearby"
                     + (f" (e.g. {vo[0]['raw']} -> {vo[0]['entry_name']})" if vo else ""),
                     "name the parameter next to the value, or confirm the attribution",
                     examples=[{"raw": x["raw"], "row": x["entry_name"]} for x in vo[:5]]))

    mat_only = fwd.get("in_material") or []
    checks.append(_c("in_material_not_ledger", PASS if not mat_only else WARN,
                     f"{len(mat_only)} numbers exist in the material but not in the ledger"
                     + (f" (e.g. {mat_only[0]['raw']} at {mat_only[0]['where']})" if mat_only else ""),
                     "add them to the ledger so the text value has a parameter name",
                     examples=[{"raw": x["raw"], "where": x["where"]} for x in mat_only[:5]]))

    mm = fwd.get("mismatch") or []
    checks.append(_c("no_value_mismatch", PASS if not mm else WARN,
                     f"{len(mm)} numbers disagree with the ledger value of the parameter named next to them"
                     + (f" (e.g. {mm[0]['entry_name']}: text {mm[0]['raw']} vs ledger "
                        f"{mm[0]['ledger_value']} at {mm[0]['ledger_at']})" if mm else ""),
                     "fix the number, or name the parameter the number actually belongs to",
                     examples=[{"raw": x["raw"], "name": x["entry_name"],
                                "ledger_value": x["ledger_value"]} for x in mm[:5]]))

    rate = fwd.get("trace_rate", 0.0)
    # a number that exists in the ledger but lacks a label nearby is already
    # reported as its own finding; fabrication has its own hard check above, so
    # this density measure does not fail again at 0.65 for the same thing
    checks.append(_c("trace_rate", PASS if rate >= 0.75 else (WARN if rate >= 0.40 else FAIL),
                     f"{rate:.3f} of draft numbers traced to the ledger",
                     "above 0.75 most numbers carry their own source; between 0.40 and 0.75 "
                     "work through the untraced list; below 0.40 the section is mostly "
                     "numbers without a source",
                     value=rate))

    amb = fwd.get("ambiguous") or []
    total_num = max(1, int(alignment.get("text_numbers") or 0))
    a_rate = len(amb) / total_num
    checks.append(_c("ambiguity_rate", PASS if a_rate <= 0.05 else WARN,
                     f"{len(amb)}/{total_num} numbers match more than one parameter",
                     "name the parameter next to the value so the row is unambiguous"))

    undisclosed = []
    for cf in conflicts:
        if (cf.get("severity_hint") or "blocking") != "blocking":
            continue          # a question for the author, not a contradiction to disclose
        shown = sum(1 for v in cf["values"]
                    if v.get("raw") and str(v["raw"]).lower() in (draft_text or "").lower())
        if shown < 2:
            undisclosed.append(cf["name"])
    checks.append(_c("conflict_disclosed", PASS if not undisclosed else FAIL,
                     f"{len(undisclosed)} conflicts are not shown in the draft"
                     + (f": {undisclosed[:3]}" if undisclosed else ""),
                     "show both values, or say which one applies and why",
                     names=undisclosed[:8]))

    boiler = [g for g in (gaps.get("gaps") or []) if g.get("kind") == "boilerplate_limit"]
    checks.append(_c("boilerplate_absent", PASS if not boiler else WARN,
                     f"{len(boiler)} boilerplate limitations",
                     "name the input or condition that makes the method fail",
                     examples=[g["text"] for g in boiler[:3]]))

    # ------------------------------------------------------------- coverage
    cov = alignment.get("coverage") or {}
    reported = [el for el, st in cov.items()
                if st.get("written") or st.get("text_signal") == 1]
    ELEMENTS = ("steps", "setup", "params", "data", "baseline", "limits", "repro")
    missing = [el for el in ELEMENTS if el not in reported]
    checks.append(_c("elements_reported", PASS if not missing else (WARN if len(missing) <= 1 else FAIL),
                     f"{len(reported)}/{len(ELEMENTS)} elements have a signal; missing {missing}",
                     "cover the element or state in the draft that the material lacks it",
                     missing=missing))

    # 复现清单（做得着）：版本/环境/命令/数据获取至少给到一个，否则读者照文复现会踩空
    repro_ok = cov.get("repro", {}).get("text_signal") == 1
    checks.append(_c("repro_checklist", PASS if repro_ok else WARN,
                     "reproducibility signals found" if repro_ok
                     else "no code version / environment / command / data acquisition given",
                     "give the version, environment, commands and data acquisition so the section is redoable"))

    steps_ok = cov.get("steps", {}).get("text_signal") == 1
    checks.append(_c("steps_signal", PASS if steps_ok else WARN,
                     "ordered procedure detected" if steps_ok else "no ordered procedure detected",
                     "write the steps as a sequence with input, action, output"))

    limits_ok = cov.get("limits", {}).get("text_signal") == 1 and not boiler
    checks.append(_c("limits_specific", PASS if limits_ok else WARN,
                     "limitations name a failure scenario" if limits_ok
                     else "limitations are missing or generic",
                     "state the condition under which the method fails"))

    # ------------------------------------------------------------- honesty
    meta = result_meta or {}
    checks.append(_c("uncertainty_present", PASS if meta.get("uncertainty") else FAIL,
                     f"{len(meta.get('uncertainty') or [])} uncertainty notes",
                     "state what could not be checked and why"))
    checks.append(_c("change_log_present", PASS if meta.get("change_log") is not None else FAIL,
                     f"{len(meta.get('change_log') or [])} change records",
                     "record what was written, aligned and left open"))
    st = meta.get("status")
    limits = meta.get("limits") or []
    checks.append(_c("status_consistent",
                     PASS if (st != "partial" or limits) else FAIL,
                     f"status={st}, limits={len(limits)}",
                     "a partial result must list what is missing"))

    unchecked = [c["code"] for c in checks if c["status"] == UNCHECKED]
    checks.append(_c("status_not_overstated",
                     PASS if not (unchecked and st == "complete") else FAIL,
                     f"{len(unchecked)} checks skipped, declared status={st}",
                     "do not declare complete while checks were skipped",
                     unchecked=unchecked))

    # ---------------------------------------------------------- determinism
    id_re = re.compile(r"^(?:e|p|g)[0-9a-f]{10,12}$")
    bad_ids = [e["entry_id"] for e in entries if not id_re.match(str(e["entry_id"]))]
    checks.append(_c("ids_content_hashed", PASS if not bad_ids else WARN,
                     f"{len(bad_ids)} ids are not content hashes",
                     "ids must not depend on run order"))

    stamp = re.search(r"20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9]{2}[:-][0-9]{2}", draft_text or "")
    checks.append(_c("no_timestamp_in_draft", PASS if not stamp else WARN,
                     "draft has no timestamp" if not stamp else "draft contains a timestamp",
                     "a timestamp makes repeated runs differ byte for byte"))

    # ------------------------------------------------------------- summary
    counts = {s: sum(1 for c in checks if c["status"] == s)
              for s in (PASS, WARN, FAIL, UNCHECKED)}
    if counts[FAIL]:
        status = "fail"
    elif counts[UNCHECKED]:
        status = "incomplete"
    elif counts[WARN]:
        status = "warn"
    else:
        status = "pass"
    worst = sorted(checks, key=lambda c: -_ORDER[c["status"]])
    return {
        "status": status,
        "counts": counts,
        "checks": checks,
        "top_failures": [{"code": c["code"], "status": c["status"], "detail": c["detail"]}
                         for c in worst if c["status"] != PASS][:8],
        "note": "not_checked is reported separately and is never counted as pass",
    }


def main() -> int:
    import argparse
    import json
    from pathlib import Path
    ap = argparse.ArgumentParser(description="re-check an existing run directory")
    ap.add_argument("--dir", required=True)
    ap.add_argument("--material", required=True)
    a = ap.parse_args()
    d = Path(a.dir)
    import materials as M
    pack = M.read_material(Path(a.material))
    ledger = json.loads((d / "ledger.json").read_text(encoding="utf-8"))
    align_pack = json.loads((d / "alignment.json").read_text(encoding="utf-8"))
    gaps_pack = json.loads((d / "gaps.json").read_text(encoding="utf-8"))
    draft = (d / "methods.md").read_text(encoding="utf-8") if (d / "methods.md").is_file() else ""
    result = json.loads((d / "result.json").read_text(encoding="utf-8")) if (d / "result.json").is_file() else {}
    rep = validate(ledger, align_pack, gaps_pack, pack, draft, result)
    print(json.dumps({"status": rep["status"], "counts": rep["counts"],
                      "top": rep["top_failures"]}, ensure_ascii=False, indent=2))
    return 0 if rep["status"] in ("pass", "warn") else 1


if __name__ == "__main__":
    raise SystemExit(main())
