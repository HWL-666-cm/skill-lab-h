#!/usr/bin/env python3
"""Number normalisation: the physical basis of the "accurate" check.

Why this file exists
--------------------
The task's hardest deduction is "values invented to keep a sentence flowing".
The only machine-checkable form of that is: take every number in the draft and
look for the same number in the material.  That requires a canonical form,
because the same quantity appears as ``1e-4`` in a config, ``1 × 10^-4`` in a
paper, ``1E-04`` in a log and ``0.0001`` in a table caption.  If those four are
not equal after normalisation, every hit becomes a false "invented number".

What it deliberately does NOT do
--------------------------------
* It does not decide whether a number is a hyper-parameter.  That is params.py.
* It does not silently drop a value it cannot read: unparsable strings come back
  with ``value: None`` so the caller can report them instead of guessing.
* It does not convert ``10%`` into ``0.1`` for gain/improvement wording, where a
  percentage means a relative change rather than a fraction.

Stdlib only.
"""

from __future__ import annotations

import math
import re
import unicodedata
from typing import Any

# --------------------------------------------------------------------- unicode

_MINUS = {"\u2212": "-", "\u2013": "-", "\u2014": "-", "\u2010": "-", "\u2011": "-"}
# TRUE superscript characters only. An earlier version also mapped ASCII "0"-"9",
# which turned every digit into "^d" and made every comparison silently wrong.
_SUPER = {"\u2070": "0", "\u00b9": "1", "\u00b2": "2", "\u00b3": "3", "\u2074": "4",
          "\u2075": "5", "\u2076": "6", "\u2077": "7", "\u2078": "8", "\u2079": "9",
          "\u207b": "-", "\u207a": "+"}
_MULT = "\u00d7\u2715\u22c5"          # × ✕ ⋅


def fold(text: str) -> str:
    """Normalise typography but keep the content. Used before number parsing."""
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in _MINUS:
            out.append("-")
            i += 1
        elif ch in _MULT:
            out.append("*")
            i += 1
        elif ch in _SUPER:
            # a run of superscripts becomes one exponent: 10⁻⁴ -> 10^-4
            buf: list[str] = []
            j = i
            while j < n and text[j] in _SUPER:
                buf.append(_SUPER[text[j]])
                j += 1
            out.append("^" + "".join(buf))
            i = j
        elif ch in "\u00a0\u2009\u202f\u2007":
            out.append(" ")
            i += 1
        else:
            out.append(ch)
            i += 1
    return unicodedata.normalize("NFKC", "".join(out))


# ----------------------------------------------------------------------- units

# unit -> (family, factor to family base). "1" means dimensionless.
_UNITS: dict[str, tuple[str, float]] = {
    "": ("none", 1.0),
    "s": ("time", 1.0), "sec": ("time", 1.0), "secs": ("time", 1.0),
    "second": ("time", 1.0), "seconds": ("time", 1.0),
    "ms": ("time", 1e-3), "msec": ("time", 1e-3), "millisecond": ("time", 1e-3),
    "us": ("time", 1e-6), "\u00b5s": ("time", 1e-6),
    "min": ("time", 60.0), "mins": ("time", 60.0), "minute": ("time", 60.0),
    "h": ("time", 3600.0), "hr": ("time", 3600.0), "hour": ("time", 3600.0),
    "hours": ("time", 3600.0),
    "b": ("bytes", 1.0), "byte": ("bytes", 1.0), "bytes": ("bytes", 1.0),
    "kb": ("bytes", 1e3), "mb": ("bytes", 1e6), "gb": ("bytes", 1e9),
    "tb": ("bytes", 1e12),
    "kib": ("bytes", 1024.0), "mib": ("bytes", 1024.0 ** 2),
    "gib": ("bytes", 1024.0 ** 3), "tib": ("bytes", 1024.0 ** 4),
    "m": ("length", 1.0), "meter": ("length", 1.0), "metre": ("length", 1.0),
    "km": ("length", 1e3), "cm": ("length", 1e-2), "mm": ("length", 1e-3),
    "nm": ("length", 1e-9),
    "hz": ("freq", 1.0), "khz": ("freq", 1e3), "mhz": ("freq", 1e6),
    "ghz": ("freq", 1e9),
    "w": ("power", 1.0), "kw": ("power", 1e3),
    "kw\u00b7h": ("energy", 3.6e6), "kwh": ("energy", 3.6e6),
    "j": ("energy", 1.0),
    "deg": ("angle", 1.0), "\u00b0": ("angle", 1.0), "degree": ("angle", 1.0),
    "degrees": ("angle", 1.0), "rad": ("angle", 180.0 / math.pi),
    "%": ("percent", 1.0), "percent": ("percent", 1.0),
    "\u00b0c": ("temp", 1.0), "c": ("temp", 1.0),
    "kelvin": ("temp", 1.0), "\u00b0k": ("temp", 1.0),
    "pa": ("pressure", 1.0), "hpa": ("pressure", 100.0), "kpa": ("pressure", 1e3),
    "mpa": ("pressure", 1e6), "bar": ("pressure", 1e5), "atm": ("pressure", 101325.0),
    "m/s": ("speed", 1.0), "km/h": ("speed", 1.0 / 3.6), "kt": ("speed", 0.514444),
    "kn": ("speed", 0.514444),
    # counting units: "3 epochs" is a quantity, not a bare number
    "epoch": ("count", 1.0), "epochs": ("count", 1.0),
    "step": ("count", 1.0), "steps": ("count", 1.0),
    "iter": ("count", 1.0), "iterations": ("count", 1.0),
    "batch": ("count", 1.0), "batches": ("count", 1.0),
    "layer": ("count", 1.0), "layers": ("count", 1.0),
    "gpu": ("count", 1.0), "gpus": ("count", 1.0),
    "sample": ("count", 1.0), "samples": ("count", 1.0),
    "run": ("count", 1.0), "runs": ("count", 1.0),
    "fold": ("count", 1.0), "folds": ("count", 1.0),
    "trial": ("count", 1.0), "trials": ("count", 1.0),
}

_MULTIWORD_UNITS = (
    "m/s", "km/h", "kw\u00b7h", "kwh", "m s-1", "m s^-1", "gpu-hours", "gpu hours",
    "per gpu", "gpu h",
)


def unit_of(token: str) -> tuple[str, str, float]:
    """Return (raw_unit, family, factor). Unknown unit -> ('', 'none', 1.0)."""
    t = fold(token).strip().lower().rstrip(".,;:")
    if not t:
        return "", "none", 1.0
    if t in _UNITS:
        fam, fac = _UNITS[t]
        return t, fam, fac
    if t.endswith("s") and t[:-1] in _UNITS:      # epochs vs epoch
        fam, fac = _UNITS[t[:-1]]
        return t, fam, fac
    return t, "unknown", 1.0


# ------------------------------------------------------------- number parsing

_SUPRE = re.compile(r"(?<![0-9A-Za-z])(\d+(?:\.\d+)?)\s*\*\s*10\s*\^\s*([-+]?\d+)")
_SUPSYM = re.compile(r"(?<![0-9A-Za-z])(\d+(?:\.\d+)?)\s*\*\s*10\s*\^?\s*\{?\s*([-+]?\d+)\s*\}?")
_PLAIN = re.compile(
    r"(?<![\w.])(?:\d{1,3}(?:[, _]\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)"
    r"(?:[eE]([-+]?\d+))?(?P<mag>[KkMmBb](?![A-Za-z0-9]))?"
    r"(?:[x\u00d7](?:\d+(?:\.\d+)?)?)?(?![\w])")

_INEQ = re.compile(r"^\s*(<=|>=|=<|=>|~=|\u2248|~|<|>|\u2264|\u2265)\s*")
_UNIT_AT = re.compile(
    r"^\s*([A-Za-z\u00b5\u00b0%\u00b7/][A-Za-z0-9\u00b5\u00b0%\u00b7/^*^-]{0,11})")
_APPROX = re.compile(r"(?:\u2248|~|approx\.?|about|around|circa|ca\.|\u7ea6)\s*$", re.I)


def unit_at(rest: str) -> str:
    """The unit immediately following a number, or '' when it is not a known unit."""
    m = _UNIT_AT.match(rest)
    if not m:
        return ""
    tok = m.group(1).rstrip(".,;:")
    _u, fam, _f = unit_of(tok)
    return tok if fam not in ("none", "unknown") else ""


def _to_float(digits: str, exp: str | None) -> float | None:
    cleaned = digits.replace(",", "").replace(" ", "").replace("\u00a0", "")
    try:
        val = float(cleaned)
    except ValueError:
        return None
    # "1e-4" already carries its exponent; applying it twice would give 1e-8
    if exp and "e" not in cleaned.lower():
        try:
            val *= 10.0 ** int(exp)
        except (ValueError, OverflowError):
            return None
    if not math.isfinite(val):
        return None
    return val


def _mk(value: float | None, raw: str, unit_raw: str = "", form: str = "plain",
        approximate: bool = False, inequality: str = "") -> dict[str, Any]:
    _u, family, factor = unit_of(unit_raw)
    out = {
        "value": None if value is None else value * factor,
        "raw": raw,
        "unit": unit_raw,
        "family": family,
        "form": form,
        "approximate": approximate,
        "inequality": inequality,
        "percent_converted": family == "percent",
    }
    if family == "percent" and out["value"] is not None:
        out["value"] /= 100.0
    return out


# wording that makes a percentage a relative change, not a fraction
_RELATIVE_HINT = re.compile(
    r"(gain|improve|increase|decrease|reduc|speedup|speed-up|higher|lower|"
    r"better|worse|error\s+reduction|提升|降低|提高|减少|改善|下降)", re.I)


def parse_number(text: str, keep_percent: bool = False) -> dict[str, Any] | None:
    """Parse one value expression. Returns None when there is no number at all."""
    if text is None:
        return None
    s = fold(str(text)).strip()
    if not s:
        return None
    # "imgsz=640." or "epochs: 100" arriving as one cell: keep the number, not the
    # label.  A leading digit (as in a ratio "1:2") is left alone on purpose.
    s = re.sub(r"^[A-Za-z_][\w.\-]{2,59}\s*[:=]\s*", "", s) or s
    # a sentence-final full stop is punctuation, not part of the value
    s = re.sub(r"(?<=\d)\.$", "", s)
    ineq = ""
    m = _INEQ.match(s)
    if m:
        ineq = {"\u2248": "~", "\u2264": "<=", "\u2265": ">="}.get(m.group(1), m.group(1))
        s = s[m.end():]
    approx = bool(_APPROX.search(s))
    s = re.sub(r"(?:\u2248|~|approx\.?|about|around|circa|ca\.|\u7ea6)\s*$", "", s, flags=re.I).strip()

    # a written-out power of ten wins over its two fragments
    m = _SUPRE.match(s) or _SUPSYM.match(s)
    if m:
        val = _to_float(m.group(1), m.group(2))
        return _mk(val, s, unit_at(s[m.end():]), "sci", approx, ineq)

    # the ordinary case: the number starts the string, a unit may follow it
    m = _PLAIN.match(s)
    if m:
        mag = m.group("mag") or ""
        digits = _digits_of(m.group(0), mag)
        unit_raw = unit_at(s[m.end():])
        val = _to_float(digits, m.group(1))
        num = _mk(val, s, unit_raw, "unit" if unit_raw else "plain", approx, ineq)
        if mag and num.get("value") is not None:
            num["value"] *= _MAGNITUDE.get(mag.lower(), 1.0)
            num["magnitude_suffix"] = mag
        return num

    # an embedded number ("p = 0.05 for ..."): usable, but flagged as embedded
    m = _PLAIN.search(s)
    if not m:
        return None
    mag = m.group("mag") or ""
    digits = _digits_of(m.group(0), mag)
    val = _to_float(digits, m.group(1))
    num = _mk(val, s, unit_at(s[m.end():]), "embedded", approx, ineq)
    if mag and num.get("value") is not None:
        num["value"] *= _MAGNITUDE.get(mag.lower(), 1.0)
        num["magnitude_suffix"] = mag
    return num


def _digits_of(token: str, mag: str) -> str:
    """Strip the magnitude letter and a trailing ``xN`` size pair from a token."""
    t = token
    if mag and t.endswith(mag):
        t = t[: -len(mag)]
    t = re.sub(r"[x\u00d7](?:\d+(?:\.\d+)?)?$", "", t)
    return t


def same(a: dict[str, Any] | None, b: dict[str, Any] | None, rel: float = 1e-9) -> bool:
    """Value equality in canonical units. Unknown/absent values never compare equal."""
    if not a or not b:
        return False
    if a.get("value") is None or b.get("value") is None:
        return False
    fa, fb = a.get("family", "none"), b.get("family", "none")
    # "count" and "none" describe the same number: 1400 epochs is 1400.  Only a
    # clash between different physical families (time vs bytes) is a real mismatch.
    if fa != fb and not {fa, fb} <= {"none", "count"}:
        if "unknown" not in (fa, fb):
            return False
    va, vb = a["value"], b["value"]
    if va == vb:
        return True
    scale = max(abs(va), abs(vb), 1e-30)
    return abs(va - vb) / scale <= rel


def key_of(num: dict[str, Any] | None) -> str:
    """Stable comparison key, used for hashing and for report dedup."""
    if not num or num.get("value") is None:
        return "?"
    v = num["value"]
    if v == int(v) and abs(v) < 1e15:
        return f"{int(v)}|{num.get('family')}"
    return f"{v:.10e}|{num.get('family')}"


# --------------------------------------------------- extracting from free text

# Ordered so that compound scientific forms win over their fragments.
TOKEN_RE = re.compile(
    r"(?P<sci>(?<![\w.])\d+(?:\.\d+)?\s*\*\s*10\s*\^\s*[-+]?\d+(?![\w]))"
    r"|(?P<pct>(?<![\w.])\d+(?:\.\d+)?\s*%)"
    r"|(?P<plain>(?<![\w.])(?:\d{1,3}(?:[, _]\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)"
    r"(?:[eE][-+]?\d+)?(?:[KkMmBb](?![A-Za-z0-9]))?"
    r"(?:[x\u00d7](?:\d+(?:\.\d+)?|(?=\s*[A-Z]\d)))?(?![\w]))"
)

# 400K steps is 400,000 training steps, not 400 kelvin. The single-letter K after a
# bare integer is a magnitude in ML writing, and treating it as a temperature unit
# silently divides a real training budget by a thousand.
_K_SUFFIX = re.compile(r"^\s?([KkMmBb])(?![A-Za-z0-9])")
_MAGNITUDE = {"k": 1e3, "m": 1e6, "b": 1e9}


def with_magnitude(num: dict[str, Any], rest: str) -> dict[str, Any]:
    m = _K_SUFFIX.match(rest)
    if m and num.get("value") is not None:
        scale = _MAGNITUDE.get(m.group(1).lower())
        if scale:
            num["value"] = num["value"] * scale
            num["magnitude_suffix"] = m.group(1)
            num["raw"] = f"{num['raw']}{m.group(1)}"
    return num


def find_numbers(text: str, window: int = 46) -> list[dict[str, Any]]:
    """Every number occurrence with its character span and a context window."""
    folded = fold(text)
    out: list[dict[str, Any]] = []
    for m in TOKEN_RE.finditer(folded):
        raw = m.group(0)
        num = parse_number(raw)
        if not num:
            continue
        # a unit immediately after the token belongs to it
        tail = folded[m.end(): m.end() + 12]
        um = re.match(r"^\s?(ms|s|min|h|hr|hours?|sec|kb|mb|gb|tb|kib|mib|gib|"
                      r"km|cm|mm|nm|hz|khz|mhz|ghz|kwh|kw|w|j|deg|\u00b0c|\u00b0|"
                      r"rad|pa|hpa|kpa|bar|atm|epochs?|steps?|gpu[- ]?hours?)(?![\w])",
                      tail, re.I)
        if um:
            unit_raw = um.group(1)
            _u, family, factor = unit_of(unit_raw)
            if family != "none" and family != "unknown" and num.get("value") is not None:
                num["unit"] = unit_raw
                num["family"] = family
                num["value"] *= factor
                if family == "percent":
                    num["value"] /= 100.0
                    num["percent_converted"] = True
        if re.match(r"^\s*[A-Z]\d", folded[m.end():]):
            # "8x A100": the number counts devices, it is not a resolution
            num["device_multiplier"] = True
        left = folded[max(0, m.start() - window): m.start()]
        right = folded[m.end(): m.end() + window]
        num.update({
            "span": [m.start(), m.end()],
            "context": (left + "[" + raw + "]" + right).replace("\n", " "),
            "left": left.replace("\n", " "),
            "right": right.replace("\n", " "),
        })
        out.append(num)
    return out


def relative_wording(left: str, right: str = "") -> bool:
    return bool(_RELATIVE_HINT.search(left[-40:] + " " + right[:40]))


if __name__ == "__main__":       # tiny manual check
    for s in ("1e-4", "1 \u00d7 10^-4", "0.0001", "1E-04", "1,024", "32", "5%",
              "250 ms", "0.25 s", "1.5 GB", "\u22481e-4", "<= 0.5", "3 epochs"):
        print(f"{s!r:20} ->", parse_number(s))
