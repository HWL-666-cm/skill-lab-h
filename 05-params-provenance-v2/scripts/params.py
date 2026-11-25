#!/usr/bin/env python3
"""Parameter candidate extraction.

Two rules, in this order:

1.  **Nothing is decided here.**  This module proposes; ledger.py judges.  A
    candidate that turns out to be a citation number or a section heading is
    dropped later with a stated reason, never here by a silent filter.
2.  **A value without a position is not a candidate.**  Every candidate carries
    ``source`` (relative path) and ``locator`` (line, key path, row).  If a
    reader could not go and look at it, it does not enter the ledger.

Extraction runs per material kind, because the same parameter looks different in
a YAML file, in argparse, in a log line and in a paragraph of prose.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Iterable

import numbers as N

# ---------------------------------------------------------------------- lexicon

REQUIRED_ELEMENTS = ("steps", "setup", "params", "data", "baseline", "limits")


def _hid(*parts: str) -> str:
    return "p" + hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:12]


def name_norm(name: str) -> str:
    """One spelling per parameter, so ``lr`` and ``learning_rate`` collide."""
    s = N.fold(str(name)).strip().lower()
    s = re.sub(r"^(?:--|-)", "", s)
    s = re.sub(r"[\s\-]+", "_", s)
    s = re.sub(r"[^a-z0-9_\u4e00-\u9fff]", "", s)
    return s


def _alias_table(lexicon: dict) -> dict[str, dict]:
    table: dict[str, dict] = {}
    for entry in lexicon.get("params", []):
        canon = entry["canonical"]
        for alias in [canon] + list(entry.get("aliases") or []):
            table[name_norm(alias)] = {
                "canonical": canon, "family": entry.get("family", "other"),
                "tier": entry.get("tier", "core"), "unit": entry.get("unit", ""),
                "element": entry.get("element", ""),
            }
    return table


def lookup(name: str, table: dict[str, dict]) -> dict | None:
    """Exact alias only.  Guessing is done in the lexicon, not here.

    A tail fallback (``train_lr`` -> ``lr``) was tried and removed: on the real
    ultralytics config it turned ``warmup_bias_lr`` and even the boolean ``cos_lr``
    into values of ``learning_rate``, because "lr" is a suffix of all three.  A
    wrong row is worse than a missing one -- the ledger is what every later check
    trusts -- so an unfamiliar name stays its own parameter and the lexicon is
    extended instead.  A dotted key still works, because the caller passes the
    last segment (``optim.lr`` arrives as ``lr``).
    """
    return table.get(name_norm(name))


# ----------------------------------------------------------------- code shapes

_ARG_DEFAULT = re.compile(
    r"""add_argument\(\s*["'](?P<flag>--?[\w\-]+)["'][^)]*?default\s*=\s*(?P<val>[^,)\s]+)""")
_ASSIGN = re.compile(
    r"""^\s*(?:self\.)?(?P<key>[A-Za-z_][\w.\-]{0,40})\s*=\s*(?P<val>-?\d[\d._eE+\-]*)\b""")
_KWARG = re.compile(
    r"""\b(?P<key>[A-Za-z_][\w]{0,32})\s*=\s*(?P<val>-?\d[\d._eE+\-]*)\b""")
_COMMENT_NUM = re.compile(
    r"""#.*?(?P<key>[A-Za-z_][\w\- ]{2,40}?)\s*(?:of|=|:)\s*(?P<val>-?\d[\d._eE+\-]*)""")


_CONTROL = re.compile(r"^\s*(?:assert|if|elif|while|for|return|raise|with|try|except)\b")


def _computed(line: str, end: int) -> bool:
    """Is the number followed by an operator, i.e. part of an expression?

    ``betas = 1.0 / np.linspace(...)`` is not a setting with the value 1.0.  Reading
    it as one put a momentum of 1.0 in the ledger, which then made a correct draft
    look wrong.  Only a bare right-hand side counts as a value.
    """
    rest = line[end:].lstrip()
    return bool(rest) and rest[0] in "/*+-%@"


def code_candidates(unit: dict) -> Iterable[dict]:
    line = unit["text"]
    if line.lstrip().startswith("#"):
        m = _COMMENT_NUM.search(line)
        if m:
            yield {"raw_name": m.group("key"), "value_text": m.group("val"),
                   "shape": "comment", "unit_hint": ""}
        return
    if _CONTROL.match(line):
        # "assert (betas <= 1).all()" is a comparison, not a setting; reading it
        # as `betas = 1` put a momentum of 1.0 in the ledger and accused a correct
        # draft of contradicting it.  But `return DiT(patch_size=4, ...)` is how a
        # model factory defines a variant: those keyword arguments ARE settings,
        # and dropping them collapsed XL/2, XL/4, XL/8 into one value.
        if re.match(r"^\s*return\s+\w+\s*\(", line):
            for m in _KWARG.finditer(line):
                key = m.group("key")
                if key in ("range", "len", "int", "float", "default", "type"):
                    continue
                yield {"raw_name": key, "value_text": m.group("val"),
                       "shape": "kwarg", "unit_hint": ""}
            return
        m = _COMMENT_NUM.search(line)
        if m:
            yield {"raw_name": m.group("key"), "value_text": m.group("val"),
                   "shape": "comment", "unit_hint": ""}
        return
    had_argparse = False
    for m in _ARG_DEFAULT.finditer(line):
        had_argparse = True
        yield {"raw_name": m.group("flag"), "value_text": m.group("val").strip("'\""),
               "shape": "argparse", "unit_hint": ""}
    if had_argparse:
        # the same line also contains `type=int, default=1400`; without this guard
        # the keyword `default` becomes a parameter of its own
        return
    m = _ASSIGN.match(line)
    if m and not _computed(line, m.end()):
        yield {"raw_name": m.group("key"), "value_text": m.group("val"),
               "shape": "assignment", "unit_hint": ""}
    for m in _KWARG.finditer(line):
        key = m.group("key")
        if key in ("range", "len", "int", "float", "print", "f", "str", "default",
                   "type", "choices", "metavar", "help", "required", "dest", "action",
                   "nargs", "const", "kwargs", "args", "seed_used"):
            continue
        if _computed(line, m.end()):
            continue
        yield {"raw_name": key, "value_text": m.group("val"),
               "shape": "kwarg", "unit_hint": ""}


# ----------------------------------------------------------------- prose shape

def prose_candidates(unit: dict, window: int = 60) -> Iterable[dict]:
    """Numbers in prose, kept only when a parameter word sits next to them."""
    text = unit["text"]
    for num in N.find_numbers(text, window=window):
        yield {"num": num, "shape": "prose",
               "left": num.get("left", ""), "right": num.get("right", "")}


_PROSE_PARAM_HINT = re.compile(
    r"(learning\s*rate|batch\s*size|batch|epochs?|steps?|iterations?|seed|dropout|"
    r"weight\s*decay|warm[\s-]*up|momentum|threshold|resolution|imgsz|patch|patience|folds?|"
    r"optimizer|scheduler|precision|fp16|bf16|ema|decay|dim|depth|layers?|heads?|"
    r"timesteps?|betas?|grad(?:ient)?[\s-]*clip|throughput|"
    r"parameters?|samples?|images?|gpus?|cpus?|workers?|temperature|alpha|beta|"
    r"学习率|批大小|批尺寸|轮数|迭代|种子|丢弃|权重衰减|预热|阈值|分辨率|优化器|调度器|"
    r"精度|层数|参数量|样本|图像|显卡|重复)", re.I)


def prose_is_parameter(left: str, right: str) -> tuple[bool, str]:
    """Is this number a setting?  Requires a parameter word within 45 characters.

    A wider window turned every number in a sentence that happened to mention
    "resolution" into an image size, including the 2 in the model name XL/2.
    """
    if re.search(r"[/#\-]\s*$", left[-3:]) and not re.search(r"\d\s*$", left[-3:]):
        return False, ""          # XL/2, B/4, issue #7: part of a name
    if re.search(r"[=:\uff1d]\s*$", left[-3:]):
        # "batch=1 device=0": the number is the value of an explicit key, which the
        # key/value path already records.  Mining it again as prose made the next
        # key's number look like a second value of the first parameter.
        return False, ""
    window = left[-45:] + " " + right[:45]
    m = _PROSE_PARAM_HINT.search(window)
    return (bool(m), m.group(0).lower() if m else "")


# ---------------------------------------------------------------- noise filter

_YEAR = re.compile(r"^(?:19|20)\d{2}$")
_REF = re.compile(r"^\s*\[\d+(?:[,–-]\d+)*\]")
_THROUGHPUT = re.compile(r"^\s*(?:/\s*(?:s|sec|second|min)\b|per\s+second|it/s|steps/s)", re.I)


def noise_reason(unit: dict, raw_name: str, value_text: str, num: dict | None,
                 shape: str) -> str:
    """Why a numeric candidate is not a parameter. Empty string means 'keep'."""
    if _REF.match(unit["text"][:20]):
        return "citation marker"
    if shape == "assignment" and num and num.get("value") == 0:
        # `train_steps = 0` in a training loop is a counter being initialised,
        # not a value anyone can set. A real zero-valued config arrives as a
        # keyword argument or a YAML key, not as a bare assignment.
        return "counter initialisation (0) in code, not a configurable value"
    if num and num.get("value") is not None:
        raw = str(num.get("raw", "")).replace(",", "")
        if _YEAR.match(raw) and shape == "prose":
            ctx = (num.get("left", "") + num.get("right", "")).lower()
            if re.search(r"(et al|19\d\d|20\d\d|\(\s*$|in\s*$|since\s*$)", ctx):
                return "year, not a parameter"
    if re.fullmatch(r"\d{4}\.\d{4,5}", str((num or {}).get("raw", "")).strip()):
        return "arXiv identifier, not a parameter"
    key = name_norm(raw_name)
    if key in ("i", "j", "k", "idx", "index", "n", "m", "x", "y", "z", "tmp"):
        return "loop index or placeholder"
    if unit["kind"] == "manuscript" and shape == "prose":
        if _YEAR.match(str((num or {}).get("raw", ""))):
            return "year, not a parameter"
    return ""


# --------------------------------------------------------------------- scopes

_CMD = re.compile(
    r"\b(?:python3?|torchrun|accelerate\s+launch|deepspeed|bash)\b[^\n]{0,140}?([\w\-]+)\.py")


def scope_of(unit: dict, raw_name: str) -> str:
    """The domain a value lives in. Two equal names in different scopes are not a conflict."""
    key = unit.get("key") or ""
    if key and "." in key:
        parent = ".".join(key.split(".")[:-1])
        return _slug(parent) or "main"
    kind = unit["kind"]
    if kind == "code":
        stem = unit["source"].rsplit("/", 1)[-1].rsplit(".", 1)[0]
        func = unit.get("func") or ""
        # DiT_XL_2(depth=28) and DiT_B_4(depth=12) are different models, not a
        # disagreement about one setting: the enclosing function is the scope.
        # Module-level code is the global setup and shares the "main" scope with
        # a config file's top level, so the two can be compared.
        return _slug(f"{stem}.{func}") if func else "main"
    if kind == "log":
        m = re.search(r"(?:epoch|run|step|fold|trial)\s*[=:#]?\s*(\d+)", unit["text"], re.I)
        if m:
            return f"log/epoch{m.group(1)}"
        return "main"
    if kind == "manuscript":
        # `python sample.py --seed 1` and `torchrun train.py ...` set different
        # things even when the flag names collide: the scope is the command.
        m = _CMD.search(unit["text"])
        if m:
            return "cmd:" + m.group(1)
        return "text"
    if kind == "table":
        cap = (unit.get("caption") or "").strip()
        base = "table:" + (_slug(cap)[:24] if cap else
                           _slug(unit["source"].rsplit("/", 1)[-1].rsplit(".", 1)[0]) or "t")
        # each row is a different configuration (256 vs 512, XL/2 vs B/4)
        return f"{base}:{unit['locator']}"
    return "main"


def _slug(text: str) -> str:
    s = N.fold(str(text)).strip().lower()
    s = re.sub(r"\[[0-9]+\]", "", s)
    s = re.sub(r"[^a-z0-9_.\u4e00-\u9fff]+", "_", s).strip("_")
    return s[:60]


# ---------------------------------------------------------------------- driver

def extract(pack: dict, lexicon: dict, limit_prose: int = 400) -> dict[str, Any]:
    table = _alias_table(lexicon)
    cands: list[dict] = []
    excluded: list[dict] = []
    prose_nums: list[dict] = []
    seen: set[tuple] = set()

    for unit in pack["units"]:
        kind = unit["kind"]
        shaped: list[dict] = []

        if kind in ("config", "table", "log", "manuscript", "other", "readme"):
            if unit.get("key") and unit.get("value_text") not in (None, ""):
                shaped.append({"raw_name": unit["key"].split(".")[-1] or unit["key"],
                               "value_text": str(unit["value_text"]), "shape": "key_value",
                               "unit_hint": "", "full_key": unit["key"]})
            for k, v in _kv_pairs(unit["text"]):
                shaped.append({"raw_name": k, "value_text": v, "shape": "line_kv",
                               "unit_hint": ""})
        if kind == "code":
            shaped.extend(code_candidates(unit))
        if kind == "manuscript":
            for pc in prose_candidates(unit):
                ok, hint = prose_is_parameter(pc["left"], pc["right"])
                if pc["num"].get("device_multiplier"):
                    # "8x A100" is a device count, whatever word happens to be nearby
                    ok, hint = True, "gpus"
                # "0.84 steps/sec" describes throughput, not the step count
                if ok and _THROUGHPUT.match(pc["right"] or ""):
                    hint = "throughput"
                prose_nums.append({
                    "source": unit["source"], "locator": unit["locator"],
                    "raw": pc["num"].get("raw", ""), "value": pc["num"].get("value"),
                    "unit": pc["num"].get("unit", ""),
                    "family": pc["num"].get("family", "none"),
                    "percent_form": bool(pc["num"].get("percent_converted")),
                    "is_parameter_prose": ok, "hint": hint,
                    "context": pc["num"].get("context", "")[:200],
                })
                if ok:
                    shaped.append({"raw_name": hint, "value_text": pc["num"].get("raw", ""),
                                   "shape": "prose", "unit_hint": pc["num"].get("unit", "")})

        for item in shaped:
            raw_name = str(item["raw_name"]).strip()
            if not raw_name or len(raw_name) > 60:
                continue
            cell = str(item["value_text"]).strip()
            if re.search(r"[A-Za-z]{1,4}/\d", cell) and not re.search(r"\d{3,}", cell):
                continue                       # B/4, XL/2: model names
            if re.search(r"https?://|\]\(|^\[\w", cell):
                continue
            num = N.parse_number(item["value_text"])
            hit = lookup(raw_name, table)
            if num is None and item.get("shape") == "key_value":
                # a categorical setting (optimizer: adamw) is still worth keeping
                if hit and not _BOOLEAN.match(str(item["value_text"]).strip()) and \
                        re.fullmatch(r"[A-Za-z\u4e00-\u9fff][\w\-+.]{0,24}", str(item["value_text"])):
                    num = {"value": None, "raw": str(item["value_text"]), "unit": "",
                           "family": "none", "form": "categorical", "approximate": False,
                           "inequality": "", "percent_converted": False}
                else:
                    continue
            if num is None:
                continue
            reason = noise_reason(unit, raw_name, item["value_text"], num, item["shape"])
            scope = scope_of(unit, raw_name)
            canon = hit["canonical"] if hit else name_norm(raw_name)
            dedup = (unit["source"], unit["locator"], canon, str(num.get("raw")))
            if dedup in seen:
                continue
            seen.add(dedup)
            row = {
                "param_id": _hid(unit["source"], unit["locator"], canon, str(num.get("raw"))),
                "name": canon,
                "raw_name": raw_name,
                "family": (hit or {}).get("family", "other"),
                "element": (hit or {}).get("element", ""),
                "tier": _tier_of(hit, item, num),
                "scope": scope,
                "value": num,
                "shape": item["shape"],
                "source": {
                    "kind": _source_kind(unit, item["shape"]),
                    "path": unit["source"],
                    "locator": unit["locator"],
                    "quote": unit["text"][:400],
                    "key": item.get("full_key") or unit.get("key") or "",
                },
                "unit": unit["unit_id"],
            }
            if reason:
                row["excluded_reason"] = reason
                excluded.append(row)
            else:
                cands.append(row)

    cands.sort(key=lambda r: (r["tier"], r["name"], r["scope"], r["source"]["path"],
                              r["source"]["locator"]))
    prose_nums.sort(key=lambda r: (r["source"], int(re.sub(r"\D", "", r["locator"]) or 0)))

    by_family: dict[str, int] = {}
    for c in cands:
        by_family[c["family"]] = by_family.get(c["family"], 0) + 1

    return {
        "candidates": cands,
        "excluded": excluded,
        "manuscript_numbers": prose_nums[:limit_prose * 4],
        "stats": {
            "candidates": len(cands),
            "excluded": len(excluded),
            "prose_numbers": len(prose_nums),
            "by_family": by_family,
            "by_source_kind": _count(c["source"]["kind"] for c in cands),
            "by_tier": _count(c["tier"] for c in cands),
        },
    }


_NOISE_NAME = re.compile(
    r"(axis|index|idx|logvar|mean\d|start|end|scale|flag|debug|tmp|shape|stride|"
    r"channel_in|in_channel)$")

# switch values, not settings: "amp: True" says the feature is on, not that the
# precision is a string called True
_BOOLEAN = re.compile(r"^(?:true|false|yes|no|on|off|none|null|nan)$", re.I)


def _tier_of(hit: dict | None, item: dict, num: dict | None) -> str:
    """core / likely / other, where 'other' never reaches the ledger.

    A name that is not in the lexicon and carries 0, 1, 2 or 3 is an index, a flag
    or a loop bound in nearly every codebase.  Keeping those makes every small
    integer in the draft ambiguous, which is worse than dropping a genuine setting
    (it still shows up in candidates.json).
    """
    if hit:
        return hit.get("tier", "likely")
    if item["shape"] == "prose":
        return "other"
    v = (num or {}).get("value")
    if v is None:
        return "other"
    name = name_norm(item["raw_name"])
    if _NOISE_NAME.search(name):
        return "other"
    if name.startswith("_"):
        # a table column whose label began with a symbol (δ1, ΔE, %): after
        # slugging it is unreadable, and an unreadable row name cannot be checked
        # against anything later
        return "other"
    if float(v).is_integer() and abs(v) <= 3:
        return "other"
    if len(name) <= 2:
        return "other"
    return "likely"


def _kv_pairs(line: str) -> list[tuple[str, str]]:
    """key: value / key=value / --flag value on a free-form line."""
    import materials as M
    return M.kv_from_line(line)


def _count(items: Iterable[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for i in items:
        out[i] = out.get(i, 0) + 1
    return out


def _source_kind(unit: dict, shape: str) -> str:
    """Provenance grade of a candidate, inherited from the file it sits in."""
    if shape == "prose":
        return "manuscript"
    return unit.get("source_kind") or unit.get("kind") or "other"
