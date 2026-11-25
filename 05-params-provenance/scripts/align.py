#!/usr/bin/env python3
"""Two-way alignment between the ledger and the draft.

Forward  (accuracy): every number in the draft must be found in the ledger.
         A number with no ledger value is either a transcription of something the
         material does not contain, or a number the author invented to keep the
         sentence flowing.  Both must be shown, not smoothed over.
Backward (completeness): every ledger row should appear in the draft.  A row that
         never appears is a gap the reader will hit when trying to reproduce.

The two directions share one mechanism and answer two different scoring points,
which is why this is a single module instead of two.

What is deliberately ignored, with a stated reason
-------------------------------------------------
Not every number in a methods section is a parameter.  Years, section numbers,
figure references, citation keys, relative improvements and reported metrics are
all numbers.  Flagging them would bury the real findings, so they are classified
and listed as ``ignored`` with the reason -- visible, but not counted as errors.
"""

from __future__ import annotations

import re
from typing import Any

import numbers as N

IGNORE_YEAR = re.compile(r"^(?:19|20)\d{2}$")
IGNORE_REF = re.compile(r"\[\d+(?:[,–-]\d+)*\]")
IGNORE_STRUCT = re.compile(
    r"\b(?:table|figure|fig\.?|section|sec\.?|eq\.?|equation|algorithm|chapter|"
    r"附录|图|表|第)\s*$", re.I)
RELATIVE = re.compile(
    r"(gain|improv|increase|decrease|reduc|speedup|higher|lower|better|worse|"
    r"提升|降低|提高|减少|改善|下降|相对)", re.I)

# "fails when the batch is smaller than 8" defines the validity domain of the
# method.  The 8 is a real claim, but it is not the value of a setting, so it can
# neither be traced to a config nor accused of being invented.
BOUND_WORDS = re.compile(
    r"\b(?:smaller|larger|greater|fewer|less|more|below|above|under|over|"
    r"at\s+least|at\s+most|up\s+to|no\s+more\s+than|no\s+less\s+than)\b"
    r"\s*(?:than\s*)?$", re.I)
BOUND_SIGN = re.compile(r"(?:<\s*=|>\s*=|[<>≤≥])\s*$")
BOUND_CJK = re.compile(r"(不超过|不少于|大于|小于|低于|高于|多于|至少|至多|以上|以下)\s*$")

# an ordered procedure is a sequence, so one sequence word is not enough: a
# sentence can open with "First" and still not describe any steps.
_SEQ_MARKERS = (
    ("numbered", re.compile(r"^\s*(?:\d+[.)]|[-*])\s+\S", re.M)),
    ("step_label", re.compile(r"\b(?:step|stage|phase)\s*\d", re.I)),
    ("first", re.compile(r"\b(first|firstly|initially|to\s+begin)\b|首先|第一步", re.I)),
    ("then", re.compile(r"\b(then|next|second|secondly|after\s+that|subsequently)\b|然后|接着|其次", re.I)),
    ("finally", re.compile(r"\b(finally|last|lastly|in\s+the\s+end)\b|最后", re.I)),
)


def split_paragraphs(text: str) -> list[dict]:
    """Markdown-ish draft into paragraphs, remembering the heading each sits under."""
    out: list[dict] = []
    heading = ""
    buf: list[str] = []

    def flush() -> None:
        body = "\n".join(buf).strip()
        if body:
            out.append({"index": len(out) + 1, "heading": heading, "text": body})
        buf.clear()

    for line in text.splitlines():
        if re.match(r"^\s{0,3}#{1,6}\s", line):
            flush()
            heading = re.sub(r"^\s{0,3}#{1,6}\s*", "", line).strip()
            continue
        if not line.strip():
            flush()
            continue
        buf.append(line)
    flush()
    return out


def alias_index(lexicon: dict) -> dict[str, list[str]]:
    idx: dict[str, list[str]] = {}
    for e in lexicon.get("params", []):
        idx[e["canonical"]] = [e["canonical"]] + [a for a in (e.get("aliases") or [])]
    return idx


# A100, P4d, V100, TPUv4: a device name carries digits but is not a quantity
_MODELLIKE = re.compile(r"\b[A-Za-z]+\d+[A-Za-z]*\b|\b\d+[A-Za-z]{2,}\b")


def _name_positions(text: str, names: list[str]) -> list[tuple[int, str]]:
    """Where each alias occurs. ``diffusion_steps`` also matches "diffusion steps",
    because a paper writes the spaces while the config writes the underscores."""
    low = text.lower()
    hits: list[tuple[int, str]] = []
    expanded: list[str] = []
    for n in names:
        nl = n.lower()
        if not nl:
            continue
        expanded.append(n)
        if "_" in nl:
            expanded.extend([nl.replace("_", " "), nl.replace("_", "-")])
    for n in expanded:
        nl = n.lower()
        if re.search(r"[\u4e00-\u9fff]", nl):
            start = 0
            while True:
                i = low.find(nl, start)
                if i < 0:
                    break
                hits.append((i, n))
                start = i + len(nl)
            continue
        for m in re.finditer(r"(?<![\w-])" + re.escape(nl) + r"(?![\w-])", low):
            hits.append((m.start(), n))
    return sorted(hits)


def material_value_index(pack: dict | None) -> dict[str, list[dict]]:
    """Every number that appears anywhere in the material, keyed by canonical value.

    This is a weaker form of provenance than a ledger row: it says "this number
    exists somewhere in the material", not "this number is the value of this
    parameter".  It matters because a comment such as ``betas=(0.9, 0.999)`` puts
    0.999 in the material without making it a parameter candidate.  Calling that
    "invented" would be a false accusation.
    """
    idx: dict[str, list[dict]] = {}
    if not pack:
        return idx
    for u in pack.get("units", []):
        for n in N.find_numbers(u["text"]):
            idx.setdefault(N.key_of(n), []).append(
                {"source": u["source"], "locator": u["locator"], "raw": n.get("raw", "")})
    return idx


def align(ledger: dict, draft_text: str, lexicon: dict, cands: dict | None = None,
          pack: dict | None = None) -> dict[str, Any]:
    idx = alias_index(lexicon)
    paras = split_paragraphs(draft_text)
    entries = ledger["entries"]
    mat_idx = material_value_index(pack)
    by_name: dict[str, list[dict]] = {}
    for e in entries:
        by_name.setdefault(e["name"], []).append(e)

    # name -> entry ids present in each paragraph
    para_names: dict[int, dict[str, list[int]]] = {}
    for p in paras:
        found: dict[str, list[int]] = {}
        for name, es in by_name.items():
            if _name_positions(p["text"], idx.get(name, [name])):
                found[name] = [e["entry_id"] for e in es]
        para_names[p["index"]] = found

    traced: list[dict] = []
    value_only: list[dict] = []
    in_material: list[dict] = []
    invented: list[dict] = []
    ambiguous: list[dict] = []
    ignored: list[dict] = []
    mismatch: list[dict] = []

    for p in paras:
        present = para_names.get(p["index"], {})
        for num in N.find_numbers(p["text"]):
            raw = num.get("raw", "")
            ctx = num.get("context", "")
            if _is_ignorable(num, ctx, present):
                ignored.append({**_num_row(num, p), "reason": _ignore_reason(num, ctx, present)})
                continue
            hits = _value_hits(num, entries, present)
            pool = [h for h in hits if h["name"] in present]
            if not hits:
                # A value in no ledger row and no material file is unsourced,
                # even when a parameter name sits next to it.  Guessing that
                # "0.001" is a typo of "0.01" would be a fabricated diagnosis.
                # Record the named parameter and what the ledger really says as
                # a hint, but keep the finding honest: the value has no source.
                mk = N.key_of(num)
                if mk in mat_idx:
                    where = mat_idx[mk][0]
                    in_material.append({**_num_row(num, p),
                                        "where": f"{where['source']}:{where['locator']}",
                                        "note": "the value appears in the material but no ledger row "
                                                "carries it as a parameter value"})
                else:
                    anchor, adist = _closest_name(num, p["text"], set(present), idx,
                                                  max_after=15)
                    hint = {}
                    if anchor and adist <= 30 and by_name.get(anchor):
                        hint = {
                            "named_parameter": anchor,
                            "ledger_value": by_name[anchor][0]["values"][0]["raw"],
                            "ledger_at": by_name[anchor][0]["values"][0]["path"] + ":"
                                         + by_name[anchor][0]["values"][0]["locator"],
                            "note": "the sentence names this parameter, but its value is "
                                    "not in any material; the ledger value is supplied "
                                    "as a hint, not as a provenance for the written number",
                        }
                    invented.append({**_num_row(num, p),
                                     "nearest": _nearest_names(num, entries, present),
                                     **hint})
                continue

            # the parameter this paragraph names closest to the number: the anchor
            # that lets a wrong value be reported as a wrong value instead of as
            # "matches several parameters"
            anchor, adist = _closest_name(num, p["text"], set(present), idx, max_after=15)

            if pool:
                near, dist = _closest_name(num, p["text"], {h["name"] for h in pool}, idx)
                if near and dist <= 90:
                    h = next(h for h in pool if h["name"] == near)
                    traced.append({**_num_row(num, p), "entry_id": h["entry_id"],
                                   "entry_name": h["name"],
                                   "distance": dist,
                                   "evidence": h["value"]["path"] + ":" + h["value"]["locator"]})
                elif anchor and adist <= 30:
                    mismatch.append(_mismatch_row(num, p, anchor, adist, by_name[anchor], hits))
                else:
                    ambiguous.append({**_num_row(num, p),
                                      "candidates": [{"entry_id": h["entry_id"], "name": h["name"],
                                                      "path": h["value"]["path"],
                                                      "locator": h["value"]["locator"]} for h in pool],
                                      "reason": "the paragraph mentions several of these "
                                                "parameters and none is close enough to the value"})
            elif anchor and adist <= 30:
                # the sentence names a parameter and puts a number right next to
                # it, but the ledger gives that parameter another value: this is
                # the transcription error the section is most likely to contain,
                # and calling it "ambiguous" would hide it
                mismatch.append(_mismatch_row(num, p, anchor, adist, by_name[anchor], hits))
            elif len(hits) == 1:
                # the value exists, but the parameter it belongs to is never named
                # here: "0.999" in a betas list matched max_beta.  Calling that
                # traced would be a false attribution, which is worse than a miss.
                h = hits[0]
                value_only.append({**_num_row(num, p), "entry_id": h["entry_id"],
                                   "entry_name": h["name"],
                                   "evidence": h["value"]["path"] + ":" + h["value"]["locator"],
                                   "note": "value matches a ledger row, but that parameter is not "
                                           "named in this paragraph"})
            else:
                ambiguous.append({**_num_row(num, p),
                                  "candidates": [{"entry_id": h["entry_id"], "name": h["name"],
                                                  "path": h["value"]["path"],
                                                  "locator": h["value"]["locator"]} for h in hits],
                                  "reason": "the value belongs to several parameters and none of "
                                            "them is named in this paragraph"})

    # ------------------------------------------------------------- backward
    written, mentioned_only, not_written = [], [], []
    for e in entries:
        seen_in = [p["index"] for p in paras if e["entry_id"] in para_names.get(p["index"], {}).get(e["name"], [])]
        if not seen_in:
            not_written.append(e)
            continue
        ok = any(t["entry_id"] == e["entry_id"] for t in traced) or \
             any(c["entry_id"] == e["entry_id"] for a in ambiguous for c in a["candidates"])
        (written if ok else mentioned_only).append(e)

    coverage = _coverage(entries, paras, written, mentioned_only, not_written)
    denom = max(1, len(traced) + len(value_only) + len(in_material)
                + len(invented) + len(ambiguous) + len(mismatch))
    return {
        "paragraphs": len(paras),
        "text_numbers": len(traced) + len(value_only) + len(in_material) + len(invented)
                        + len(ambiguous) + len(mismatch) + len(ignored),
        "forward": {
            "traced": traced,
            "value_only": value_only,
            "in_material": in_material,
            "invented": invented,
            "ambiguous": ambiguous,
            "mismatch": mismatch,
            "ignored": ignored,
            "trace_rate": round(len(traced) / denom, 4),
            "material_rate": round((len(traced) + len(value_only) + len(in_material)) / denom, 4),
        },
        "backward": {
            "written": [e["entry_id"] for e in written],
            "mentioned_without_value": [{"entry_id": e["entry_id"], "name": e["name"],
                                         "scope": e["scope"],
                                         "ledger_value": e["values"][0]["raw"]} for e in mentioned_only],
            "not_written": [{"entry_id": e["entry_id"], "name": e["name"], "scope": e["scope"],
                             "ledger_value": e["values"][0]["raw"],
                             "source_kind": e["best_source_kind"],
                             "status": e["status"],
                             "path": e["values"][0]["path"],
                             "locator": e["values"][0]["locator"]} for e in not_written],
            "written_rate": round(len(written) / max(1, len(entries)), 4),
        },
        "coverage": coverage,
        "paragraph_index": [{"index": p["index"], "heading": p["heading"],
                             "params": sorted(para_names.get(p["index"], {})), "chars": len(p["text"])}
                            for p in paras],
    }


def _mismatch_row(num: dict, para: dict, name: str, dist: int,
                  entries: list[dict], hits: list[dict]) -> dict:
    """The paragraph names this parameter and gives it a value the ledger disagrees with.

    ``also_matches`` keeps the record honest: the number may be perfectly correct
    for a different parameter that the sentence happens not to name, and saying so
    turns an accusation into a question the author can answer in one line.
    """
    e = entries[0]
    v = e["values"][0]
    also = [f"{h['name']}={h['value']['raw']}" for h in hits if h["name"] != name]
    return {
        **_num_row(num, para),
        "entry_id": e["entry_id"],
        "entry_name": name,
        "distance": dist,
        "ledger_value": v["raw"],
        "ledger_at": f"{v['path']}:{v['locator']}",
        "also_matches": also[:4],
        "note": "the paragraph names this parameter, but the number next to it is not the "
                "value the ledger gives; either the text or the record is wrong",
    }


def _num_row(num: dict, para: dict) -> dict:
    return {
        "raw": num.get("raw", ""),
        "value": num.get("value"),
        "unit": num.get("unit", ""),
        "family": num.get("family", "none"),
        "paragraph": para["index"],
        "heading": para["heading"],
        "context": num.get("context", "")[:180],
    }


def _is_ignorable(num: dict, ctx: str, present: dict) -> bool:
    return _ignore_reason(num, ctx, present) not in ("", "unclassified")


def _ignore_reason(num: dict, ctx: str, present: dict) -> str:
    raw = str(num.get("raw", "")).replace(",", "")
    left = num.get("left", "") or ""
    right = num.get("right", "") or ""
    if IGNORE_REF.search(left[-8:] + right[:8]):
        return "citation marker"
    if IGNORE_YEAR.match(raw) and re.search(r"(published|since|in)\s*$", left[-12:], re.I):
        return "year"
    if IGNORE_STRUCT.search(left[-24:]):
        return "table/figure/section number"
    if re.search(r"(fid|iou|map|bleu|rouge|psnr|ssim|top)-?\s*$", left[-14:], re.I):
        return "metric label suffix, not a setting"
    if re.search(r"[A-Za-z]/\s*$", left[-3:]):
        return "model name suffix (XL/2, B/4), not a value"
    if num.get("percent_converted") and RELATIVE.search(left[-40:] + right[:20]):
        return "relative improvement, not a setting"
    if BOUND_WORDS.search(left[-28:]) or BOUND_SIGN.search(left[-6:]) or BOUND_CJK.search(left[-8:]):
        return "boundary of the validity domain, not the value of a setting"
    if present:
        return ""
    if re.search(r"(\d\s*[-\u2013]\s*\d|\(\s*\d+\s*\))", ctx):
        return "range or enumeration"
    return "unclassified"


def _value_hits(num: dict, entries: list[dict], present: dict) -> list[dict]:
    hits = []
    for e in entries:
        ok, _note = False, ""
        for v in e["values"]:
            ok, _note = _same_value(num, v, e["name"])
            if ok:
                break
        if ok:
            hits.append({"entry_id": e["entry_id"], "name": e["name"],
                         "value": next(v for v in e["values"]
                                       if _same_value(num, v, e["name"])[0])})
    return hits


def _same_value(num: dict, v: dict, name: str) -> tuple[bool, str]:
    from ledger import equivalent
    a = {"value": num.get("value"), "family": num.get("family", "none")}
    b = {"value": v.get("value"), "family": v.get("family", "none")}
    return equivalent(a, b, name)


def _closest_name(num: dict, para_text: str, names: set[str],
                  idx: dict, max_after: int | None = None) -> tuple[str, int]:
    """The parameter name that owns this number inside the paragraph.

    ``only`` restricts the search to names that actually carry this value. Without
    it, a nearby word such as "steps" wins simply by being close, even though no
    ledger row gives it this value.

    A name *before* the number wins over a name after it: English puts the value
    after its label ("a learning rate of 0.001"), so measuring plain distance let
    the next label steal the number -- "0.001, momentum 0.937" attributed 0.001 to
    momentum, which is exactly the mix-up the check is supposed to report.  A
    name after the number is still used when nothing precedes it, because "8 GPUs"
    and "1400 epochs" are just as common.
    """
    span = num.get("span") or [0, 0]
    pos = span[0]
    pos_end = span[1] if len(span) > 1 else pos
    before, before_d = "", 10 ** 9
    after, after_d = "", 10 ** 9
    for name in set(names):
        for p, n in _name_positions(para_text, idx.get(name, [name])):
            end = p + len(n)
            if end < len(para_text) and para_text[end] == "/":
                continue          # "0.84 steps/sec": a rate unit, not the parameter
            if end <= pos:
                between = para_text[end:pos]
            elif p >= pos_end:
                between = para_text[pos_end:p]
            else:
                return name, 0
            if re.search(r"\d", _MODELLIKE.sub(" ", between)):
                # another number sits between the label and this one, so the label
                # already belongs to it: "patch size 2; at 512x512" does not make
                # 512 a patch size.  Device and model names are not numbers here:
                # "8 A100 GPUs" still labels 8 with GPUs.
                continue
            if end <= pos:
                d = pos - end
                if d < before_d:
                    before, before_d = name, d
            else:
                d = p - pos_end
                if d < after_d:
                    after, after_d = name, d
    if before and before_d <= 40:
        return before, before_d
    if after and max_after is not None and after_d > max_after:
        # "at 512x512 ... requires patch size 4": the label is half a clause away,
        # so it belongs to another statement and cannot anchor this number
        return ("", 10 ** 9) if not before else (before, before_d)
    if after:
        return after, after_d
    return before, before_d


def _nearest_names(num: dict, entries: list[dict], present: dict) -> list[str]:
    """For an untraceable number, say which close values exist, if any."""
    val = num.get("value")
    if val is None:
        return []
    near = []
    for e in entries:
        for v in e["values"]:
            av = v.get("value")
            if av in (None, 0):
                continue
            if 0.5 <= abs(val / av) <= 2.0:
                near.append(f"{e['name']}={v['raw']}")
                break
    return near[:4]


def _coverage(entries: list[dict], paras: list[dict], written: list[dict],
              mentioned: list[dict], not_written: list[dict]) -> dict[str, Any]:
    """Six elements, three states: written / material has it but draft does not / material lacks it."""
    text = "\n".join((p["heading"] or "") + "\n" + p["text"] for p in paras)
    counts: dict[str, dict[str, int]] = {}
    for e in entries:
        el = e["element"]
        counts.setdefault(el, {"written": 0, "mentioned_without_value": 0, "not_written": 0})
    for e in written:
        counts.setdefault(e["element"], {"written": 0, "mentioned_without_value": 0, "not_written": 0})["written"] += 1
    for e in mentioned:
        counts[e["element"]]["mentioned_without_value"] += 1
    for e in not_written:
        counts[e["element"]]["not_written"] += 1

    # elements that are not made of parameters need a text-level judgement
    seq_kinds = [name for name, rx in _SEQ_MARKERS if rx.search(text)]
    heuristics = {
        # two or more distinct sequence markers: a procedure has to be ordered,
        # and one "first" on its own is not an order
        "steps": len(seq_kinds) >= 2,
        "baseline": bool(re.search(r"(baseline|compared with|compared to|对照|基线|相比)", text, re.I)),
        "limits": bool(re.search(r"(limitation|limited to|does not apply|fails when|constraint|局限|限制|不适用于)", text, re.I)),
    }
    for el in ("steps", "setup", "params", "data", "baseline", "limits"):
        st = counts.setdefault(el, {"written": 0, "mentioned_without_value": 0, "not_written": 0})
        if el in heuristics:
            # no ledger rows exist for these elements, so the only honest state
            # is a text-level signal plus a clear 'not machine-checked' flag
            st["text_signal"] = 1 if heuristics[el] else 0
            st["checked_by"] = "text signal only, not machine-checked"
            if el == "steps":
                st["sequence_markers"] = seq_kinds
        elif st["written"]:
            st["checked_by"] = "ledger rows traced to the draft"
        elif st["not_written"]:
            st["checked_by"] = "ledger has rows, draft has none"
        else:
            st["checked_by"] = "no material"
    return counts
