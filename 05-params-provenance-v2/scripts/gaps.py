#!/usr/bin/env python3
"""Gap list and follow-up questions.

The task asks for limitations that point at a concrete failure scenario rather
than boilerplate.  So every gap here carries three things:

* ``what``  -- the missing or inconsistent item, named.
* ``why``   -- what specifically goes wrong for a reader who tries to reproduce.
* ``ask``   -- the question a competent outsider would actually ask, phrased so
               the author can answer it in one line.

``why`` is not a template about data quality.  It names the failure: "the reader
cannot tell whether the gap between your run and theirs is the learning rate or
the batch size" beats "limited by experimental conditions".
"""

from __future__ import annotations

import hashlib
from typing import Any

# what goes wrong, per parameter family, when the value is absent
WHY_BY_FAMILY = {
    "optim": "an outsider cannot reproduce the optimisation path, so a difference "
             "between their run and yours cannot be attributed to your method",
    "schedule": "the training budget is undefined, so 'trained to convergence' becomes "
                "a claim the reader cannot test",
    "model": "the model size is undefined, so reported compute and accuracy cannot be "
             "compared with another implementation",
    "data": "the data regime is undefined, so a reader cannot tell whether your result "
            "comes from the method or from a larger or cleaner dataset",
    "runtime": "the environment is undefined, so a run that works for you may fail or "
               "silently change precision elsewhere",
    "reproducibility": "run-to-run variance cannot be separated from the effect you report",
    "eval": "the measurement is undefined, so the reported number cannot be recomputed",
    "other": "a reader cannot check this value against anything",
}

ASK_BY_FAMILY = {
    "optim": "which value did you actually use, and is it per device or global?",
    "schedule": "how long did training run, and was that fixed or early-stopped?",
    "model": "which configuration produced the reported result?",
    "data": "which dataset version and split produced the reported result?",
    "runtime": "which hardware and software versions produced the reported result?",
    "reproducibility": "how many runs, and with which seeds?",
    "eval": "on which split and with which metric implementation?",
    "other": "please confirm the value and where it comes from",
}

SEVERITY = {"invented_number": "blocking", "conflicting": "blocking",
            "unparsed_material": "blocking", "not_written": "major",
            "manuscript_only": "major", "value_mismatch": "major",
            "ambiguous_value": "minor",
            "weak_source": "minor", "missing_element": "major",
            "repro_missing": "major", "boilerplate_limit": "major"}

BOILERPLATE = (
    "limited by data quality", "due to limited time", "further work is needed",
    "受限于数据质量", "由于时间有限", "有待进一步研究", "存在一定局限",
)


def _gid(*parts: str) -> str:
    return "g" + hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:10]


def _gap(kind: str, what: str, where: str, why: str, ask: str, **extra) -> dict:
    severity = extra.pop("severity", None) or SEVERITY.get(kind, "minor")
    return {"gap_id": _gid(kind, what, where), "kind": kind,
            "severity": severity,
            "what": what, "where": where, "why": why, "ask": ask, **extra}


def build(ledger: dict, alignment: dict, pack: dict | None = None,
          draft_text: str = "") -> dict[str, Any]:
    gaps: list[dict] = []

    for inv in alignment["forward"].get("invented") or []:
        gaps.append(_gap(
            "invented_number",
            f"draft states {inv['raw']!r} but no material value matches it",
            f"paragraph {inv['paragraph']} ({inv['heading'] or 'no heading'})",
            "a number that exists nowhere in the material is either a transcription "
            "error or an invented value; either way a reader who checks will not find it, "
            "and the section loses its evidence base at exactly the point it looks most precise",
            f"where does {inv['raw']} come from? If it is a real setting, which file or log line holds it?",
            raw=inv["raw"], context=inv.get("context", "")[:160],
            nearest=inv.get("nearest") or [],
        ))

    for im in alignment["forward"].get("in_material") or []:
        gaps.append(_gap(
            "weak_source",
            f"draft states {im['raw']!r}; the material contains it at {im['where']} but no ledger row names it",
            f"paragraph {im['paragraph']}",
            "a value that appears in the material without a parameter name cannot be "
            "checked against a configuration later, and the reader cannot tell which "
            "setting it belongs to",
            f"which parameter is {im['raw']} the value of?",
            raw=im["raw"], material_position=im["where"],
        ))

    for vo in alignment["forward"].get("value_only") or []:
        gaps.append(_gap(
            "ambiguous_value",
            f"draft states {vo['raw']!r}; the nearest ledger value is {vo['entry_name']} at {vo['evidence']}, "
            "but that parameter is not named in the paragraph",
            f"paragraph {vo['paragraph']}",
            "a value attributed to the wrong parameter is worse than a missing value: it "
            "looks sourced while pointing at a different setting",
            f"is {vo['raw']} the value of {vo['entry_name']}, or of something else?",
            raw=vo["raw"], guessed=vo["entry_name"], evidence=vo["evidence"],
        ))

    for amb in alignment["forward"].get("ambiguous") or []:
        gaps.append(_gap(
            "ambiguous_value",
            f"value {amb['raw']!r} matches {len(amb['candidates'])} ledger rows",
            f"paragraph {amb['paragraph']}",
            "if one number can belong to two parameters, the text does not say which "
            "setting it is, and the ledger cannot confirm either reading",
            f"is {amb['raw']} the value of "
            + " or of ".join(c["name"] for c in amb["candidates"][:3]) + "?",
            candidates=amb["candidates"],
        ))

    for mm in alignment["forward"].get("mismatch") or []:
        also = mm.get("also_matches") or []
        gaps.append(_gap(
            "value_mismatch",
            f"draft says {mm['raw']!r} next to {mm['entry_name']}, but the ledger gives "
            f"{mm['entry_name']} = {mm['ledger_value']}",
            f"paragraph {mm['paragraph']} ({mm['heading'] or 'no heading'}); "
            f"ledger at {mm['ledger_at']}",
            "the sentence names a parameter and gives it a different number than the record "
            "holds, so one of the two is wrong; a reader who checks will distrust the section "
            "at exactly the point where it looks most precise",
            f"is it {mm['raw']} or {mm['ledger_value']}?"
            + (f" ({mm['raw']} is the value of {' / '.join(also)})" if also else ""),
            raw=mm["raw"], name=mm["entry_name"], ledger_value=mm["ledger_value"],
            ledger_at=mm["ledger_at"], also_matches=also,
        ))

    nw_by_name: dict[str, list[dict]] = {}
    for nw in alignment.get("backward", {}).get("not_written") or []:
        nw_by_name.setdefault(nw["name"], []).append(nw)
    hard_names = {n for n, rows in nw_by_name.items()
                  if any(r["source_kind"] in ("config", "log", "code") for r in rows)}
    for name, rows in sorted(nw_by_name.items()):
        fam = next((e["family"] for e in (ledger.get("entries") or []) if e["name"] == name), "other")
        scopes = sorted({r["scope"] for r in rows})
        vals = sorted({str(r["ledger_value"]) for r in rows})
        # a model-size table legitimately omits per-variant rows from the prose;
        # a training setting does not get that excuse
        major = fam in ("optim", "schedule", "reproducibility", "runtime", "data")
        gaps.append(_gap(
            "not_written",
            (f"{name} has {len(rows)} sourced value(s) in {len(scopes)} scope(s) "
             f"({', '.join(vals[:4])}) but the draft gives none")
            if len(rows) > 1 else
            f"{name} = {rows[0]['ledger_value']} has a source but is absent from the draft",
            f"{rows[0]['path']}:{rows[0]['locator']}"
            + (f" and {len(rows) - 1} more" if len(rows) > 1 else ""),
            WHY_BY_FAMILY.get(fam, WHY_BY_FAMILY["other"]),
            ASK_BY_FAMILY.get(fam, ASK_BY_FAMILY["other"]),
            entry_ids=[r["entry_id"] for r in rows], name=name, scope=scopes,
            value=vals[:6], source_kind=rows[0]["source_kind"],
            severity="major" if major else "minor",
        ))

    for mw in alignment.get("backward", {}).get("mentioned_without_value") or []:
        gaps.append(_gap(
            "not_written",
            f"{mw['name']} is mentioned but no value is given",
            "draft body",
            "naming a setting without its value reads as disclosure but gives the "
            "reader nothing to reproduce with",
            ASK_BY_FAMILY.get("other"),
            entry_id=mw["entry_id"], name=mw["name"], scope=mw["scope"],
            value=mw["ledger_value"], shape="mentioned_no_value",
        ))

    for c in ledger.get("conflicts") or []:
        gaps.append(_gap(
            "conflicting",
            f"{c['name']} carries {len(c['values'])} different values in scope {c['scope']!r}",
            ", ".join(f"{v['path']}:{v['locator']}" for v in c["values"]),
            "two values for one parameter mean at most one of them is what produced "
            "the reported result; averaging or picking silently would hide which",
            f"which value is correct for {c['name']}: "
            + " or ".join(str(v["raw"]) for v in c["values"]) + "?",
            values=c["values"],
            severity=c.get("severity_hint") or "blocking",
        ))

    for e in ledger.get("entries") or []:
        if e["status"] == "prose_multi_value":
            gaps.append(_gap(
                "manuscript_only",
                f"{e['name']} carries {e['n_distinct']} different values in prose "
                f"({', '.join(v['raw'] for v in e['values'][:4])})",
                f"{e['values'][0]['path']}:{e['values'][0]['locator']}",
                "one sentence describes several instances; without saying which value "
                "belongs to which model or dataset, a reader reproducing one of them "
                "cannot tell which number applies",
                "which value applies to the configuration you report?",
                entry_id=e["entry_id"], name=e["name"],
                values=[v["raw"] for v in e["values"][:4]],
            ))

    hard_by_name = {e["name"] for e in (ledger.get("entries") or [])
                    if e["status"] in ("confirmed", "conflicting")}
    mo_by_name: dict[str, list[dict]] = {}
    for e in ledger.get("entries") or []:
        if e["status"] == "manuscript_only" and e["name"] not in hard_by_name:
            mo_by_name.setdefault(e["name"], []).append(e)
    for name, rows in sorted(mo_by_name.items()):
        vals = sorted({v["raw"] for e in rows for v in e["values"]})
        gaps.append(_gap(
            "manuscript_only",
            f"{name} = {', '.join(vals[:4])} is only stated in prose, with no config, log or code behind it",
            f"{rows[0]['values'][0]['path']}:{rows[0]['values'][0]['locator']}",
            "a value that only the manuscript asserts cannot be checked against what was "
            "actually executed; if the prose and the run diverged, this is where the "
            "reproduction will fail",
            ASK_BY_FAMILY.get(rows[0]["family"], ASK_BY_FAMILY["other"]),
            entry_ids=[e["entry_id"] for e in rows], name=name, value=vals[:4],
        ))

    for e in ledger.get("entries") or []:
        if e["best_source_kind"] in ("other", "none"):
            gaps.append(_gap(
                "weak_source",
                f"{e['name']} = {e['values'][0]['raw']} comes from {e['best_source_kind']} material",
                f"{e['values'][0]['path']}:{e['values'][0]['locator']}",
                "material that is neither a configuration, a log nor code cannot settle "
                "a disagreement later",
                "can this value be confirmed against a config, log or the code?",
                entry_id=e["entry_id"], name=e["name"],
            ))

    if pack:
        for u in pack.get("unreadable", []):
            gaps.append(_gap(
                "unparsed_material",
                f"{u['source']} could not be read",
                u["source"],
                "a material file that cannot be read is not evidence; values it holds "
                "are missing from the ledger and will look invented in the draft",
                f"please provide {u['source']} in a readable form, or state its key values",
                reason=u["reason"],
            ))

    for el, st in sorted((alignment.get("coverage") or {}).items()):
        if el in ("baseline", "limits", "steps"):
            if st.get("text_signal") == 0 and not st.get("written"):
                gaps.append(_gap(
                    "missing_element",
                    f"the draft shows no {el} content",
                    f"element {el}",
                    {
                        "steps": "without an ordered procedure the reader has to reverse-engineer "
                                 "the pipeline from the parameters alone",
                        "baseline": "without a named baseline and matched budget, any comparison "
                                    "reads as an assertion rather than a result",
                        "limits": "without a stated failure scenario the reader cannot tell which "
                                  "regime the conclusion does not cover",
                    }[el],
                    {
                        "steps": "which sequence of operations produced the reported result?",
                        "baseline": "which baseline, at which version and budget, is this compared against?",
                        "limits": "in which setting does this method stop working, and how would a reader notice?",
                    }[el],
                    element=el,
                ))

    # 复现清单缺项：逐项写成 major 缺口，回改回路才有具体目标
    repro_st = (alignment.get("coverage") or {}).get("repro") or {}
    for item in repro_st.get("missing") or []:
        gaps.append(_gap(
            "repro_missing",
            f"reproducibility item '{item}' is not given",
            "draft body",
            f"without {item} the reader cannot redo the run",
            f"which {item} produced the reported result? state the concrete {item}",
            item=item,
        ))

    for line in _boilerplate_limits(draft_text):
        gaps.append(_gap(
            "boilerplate_limit",
            f"limitation reads as boilerplate: {line!r}",
            "draft body",
            "a limitation that names no failure scenario cannot be used by a reader to "
            "decide whether their case is covered",
            "which concrete input or condition makes this method fail, and what would the "
            "reader observe?",
            text=line,
        ))

    order = {"blocking": 0, "major": 1, "minor": 2}
    gaps.sort(key=lambda g: (order.get(g["severity"], 3), g["kind"], g["what"]))
    counts: dict[str, int] = {}
    for g in gaps:
        counts[g["kind"]] = counts.get(g["kind"], 0) + 1
    return {
        "gaps": gaps,
        "counts": counts,
        "by_severity": {s: sum(1 for g in gaps if g["severity"] == s) for s in order},
        "blocking": [g["gap_id"] for g in gaps if g["severity"] == "blocking"],
    }


def _boilerplate_limits(text: str) -> list[str]:
    out = []
    low = (text or "").lower()
    for phrase in BOILERPLATE:
        if phrase in low:
            i = low.find(phrase)
            out.append(text[max(0, i - 20): i + len(phrase) + 10].strip())
    return out


def to_markdown(gaps: dict, case_id: str) -> str:
    lines = [f"# 材料缺口与追问清单 —— {case_id}", ""]
    lines.append(f"共 {len(gaps['gaps'])} 条："
                 + "、".join(f"{k} {v}" for k, v in sorted(gaps["counts"].items()))
                 + f"（阻断级 {gaps['by_severity']['blocking']} 条）")
    lines.append("")
    lines.append("> 每条缺口都写出「缺了会怎样」和「需要作者回答的问题」。"
                 "阻断级条目会让产出的稿件不能直接使用，必须先确认。")
    lines.append("")
    for sev, label in (("blocking", "阻断"), ("major", "重要"), ("minor", "次要")):
        group = [g for g in gaps["gaps"] if g["severity"] == sev]
        if not group:
            continue
        lines.append(f"## {label}（{len(group)}）")
        lines.append("")
        lines.append("| # | 类型 | 是什么 | 位置 | 缺了会怎样 | 要问作者 |")
        lines.append("|---|---|---|---|---|---|")
        for i, g in enumerate(group, 1):
            lines.append(f"| {i} | `{g['kind']}` | {_esc(g['what'])} | {_esc(g['where'])} | "
                         f"{_esc(g['why'])} | {_esc(g['ask'])} |")
        lines.append("")
    return "\n".join(lines) + "\n"


def _esc(s: str) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")
