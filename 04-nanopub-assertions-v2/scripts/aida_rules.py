"""Mechanical checks for AIDA sentences.

Every check returns issues plus a concrete fix hint. The module never rewrites
the sentence itself: rewriting needs the surrounding context, which belongs to
the model. What this module guarantees is that no sentence passes as AIDA while
still carrying a pronoun, a hedge or a discovery verb, and that scope markers
(in mice, at 20 C, for adults) are never mistaken for hedges.
"""

from __future__ import annotations

import re

MAX_SENTENCE = 500
MIN_SENTENCE = 5

PRONOUN_SUBJECT = re.compile(
    r"^\s*(this|these|those|that|it|such|they|both|the\s+former|the\s+latter|"
    r"该|其|此|这|上述|前述|前者|后者|它们|它)\b",
    re.IGNORECASE,
)

FIRST_PERSON = re.compile(
    r"\b(we|our|us|ours|i|my|me)\b|我们|本文|本研究|笔者",
    re.IGNORECASE,
)

HEDGE = {
    "probably": "probability", "possibly": "probability", "perhaps": "probability",
    "likely": "probability", "unlikely": "probability", "presumably": "probability",
    "arguably": "probability", "tentatively": "probability", "apparently": "probability",
    "may": "modality", "might": "modality", "could": "modality", "would": "modality",
    "seems": "appearance", "seem": "appearance", "appears": "appearance",
    "appear": "appearance", "suggests": "inference", "suggest": "inference",
    "indicates": "inference", "indicate": "inference", "implies": "inference",
    "可能": "probability", "或许": "probability", "也许": "probability",
    "似乎": "appearance", "大概": "probability", "有望": "probability",
    "提示": "inference", "推测": "inference", "估计": "inference",
}

DISCOVERY = [
    r"\bwe\s+(found|find|show|showed|shown|present|presented|report|reported|"
    r"propose|proposed|demonstrate|demonstrated|observe|observed|measure|measured|"
    r"develop|developed|introduce|introduced|study|studied|consider|considered)\b",
    r"\b(this|the\s+present|our)\s+(paper|study|work|article|research|analysis|"
    r"experiment|experiments|results?|data)\b",
    r"\b(results?|experiments?|data|analyses|measurements?)\s+"
    r"(show|showed|shows|indicate|indicated|indicatess|suggest|suggested|reveal|revealed|"
    r"confirm|confirmed|demonstrate|demonstrated)\b",
    r"\b(as|which)\s+(shown|reported|described|discussed|illustrated|seen)\b",
    r"本文|本研究|我们|笔者|实验表明|结果表明|研究发现|结果显示|研究表明|数据表明",
]

SCOPE_MARKERS = [
    r"\b(?:in|on|at|under|within|during|among|across)\s+(?:the\s+)?"
    r"(?:mice|rats|humans|patients|adults|children|infants|cells|vitro|vivo|"
    r"field|simulations?|experiments?|trials?|cohorts?)\b[^,.;:]{0,25}",
    r"\b(?:at|to|of)\s+\d+(?:\.\d+)?\s*(?:°C|K|m|km|mm|cm|%|hours?|days?|weeks?|months?|years?)\b",
    r"\bfor\s+(?:adults|children|patients|males|females|each|all)\b[^,.;:]{0,20}",
    r"\b(?:when|if|given)\s+(?:a|an|the)?\s*[^,.;:]{3,40}",
    r"\bwithin\s+(?:a\s+)?[^,.;:]{3,30}\b(?:range|bound|threshold|radius|area)\b",
    r"在[^，。；]{1,25}(?:条件下|范围内|情况下|环境中|期间|时)",
    r"对于[^，。；]{1,25}",
    r"当[^，。；]{1,25}时",
]

SCOPE_STOP = (
    "for example", "in conclusion", "in addition", "in fact", "in general",
    "in particular", "in this paper", "in this study", "in these experiments",
    "in the experiments", "in figure", "in fig", "in table", "according to",
    "in summary", "in contrast", "in practice", "in total", "in all cases",
)

SCOPE_HINT = re.compile("|".join(SCOPE_MARKERS), re.IGNORECASE)

POLARITY = {
    "deficiency": "loss", "deficient": "loss", "lack": "loss", "absence": "loss",
    "absent": "loss", "loss": "loss", "impaired": "loss", "impairment": "loss",
    "reduction": "loss", "reduced": "loss", "decrease": "loss", "decreased": "loss",
    "lower": "loss", "downregulation": "loss", "underexpression": "loss",
    "insufficiency": "loss",
    "increase": "gain", "increased": "gain", "elevated": "gain", "elevation": "gain",
    "higher": "gain", "excess": "gain", "overexpression": "gain",
    "upregulation": "gain", "accumulation": "gain", "supplementation": "gain",
    "缺乏": "loss", "缺失": "loss", "减少": "loss", "降低": "loss", "下降": "loss",
    "损伤": "loss", "不足": "loss",
    "增加": "gain", "升高": "gain", "上升": "gain", "过量": "gain", "积累": "gain",
}

STOPWORDS = {
    "this", "these", "those", "that", "such", "the", "a", "an", "it", "its",
}


def _issue(code: str, detail: str, fix: str, where: str = "") -> dict:
    return {"code": code, "detail": detail, "fix": fix, "where": where}


def check_atomic(text: str) -> dict:
    issues = []
    stripped = text.strip()
    if len(stripped) > MAX_SENTENCE:
        issues.append(_issue(
            "too_long",
            f"{len(stripped)} characters exceeds the 500 limit",
            "Split into shorter sentences; keep one claim per sentence.",
        ))
    if re.search(r"[;；]", stripped):
        issues.append(_issue(
            "semicolon",
            "semicolon usually joins two independent claims",
            "Split at the semicolon and keep the clause that carries the claim.",
        ))
    if re.search(r",\s+and\s+.*\b(is|are|was|were|has|have|can|will|does|do)\b", stripped, re.I):
        issues.append(_issue(
            "coordinated_clause",
            "', and' introduces a second predicate",
            "Test whether each side can be true or false alone; if so, split.",
        ))
    if re.search(r"\band\s+(prove|proves|proved|show|shows|showed|guarantee|guarantees|"
                 r"ensure|ensures|demonstrate|demonstrates|require|requires|allow|allows)\b",
                 stripped, re.I):
        issues.append(_issue(
            "coordinated_verb",
            "'and' joins a second verb phrase, so two claims share one sentence",
            "Split into separate sentences, one claim each.",
        ))
    if re.search(r"\bwhile\s+\w+ing\b|\bthereby\b|\btherefore\b", stripped, re.I):
        issues.append(_issue(
            "extra_clause",
            "subordinate or consequent clause adds a second claim",
            "Keep the main claim; move the consequence to its own sentence.",
        ))
    if re.search(r"\b(whereas|while)\b[^,]{5,}", stripped, re.I) and stripped.count(",") >= 1:
        issues.append(_issue(
            "contrast_clause",
            "contrast connective joins two propositions",
            "Keep the contrast as a qualifier, or split into two claims.",
        ))
    if stripped.count(".") > 1 and not re.search(r"\d\.\d|\bet al\.|\be\.g\.|\bi\.e\.", stripped):
        issues.append(_issue(
            "multi_sentence",
            "more than one sentence-final full stop",
            "Keep exactly one claim and one full stop.",
        ))
    return {"ok": not issues, "issues": issues}


def check_independent(text: str) -> dict:
    issues = []
    stripped = text.strip()
    m = PRONOUN_SUBJECT.match(stripped)
    if m:
        issues.append(_issue(
            "leading_pronoun",
            f"starts with '{m.group(0).strip()}', which needs the previous sentence",
            f"Replace '{m.group(0).strip()}' with the noun phrase it points to. "
            "Read the preceding sentence to recover it; never guess.",
            m.group(0).strip(),
        ))
    m = FIRST_PERSON.search(stripped)
    if m:
        issues.append(_issue(
            "first_person",
            f"contains '{m.group(0)}', a reference to the authors",
            "Name the object of study instead of the authors; move attribution to provenance.",
            m.group(0),
        ))
    return {"ok": not issues, "issues": issues}


def check_declarative(text: str) -> dict:
    issues = []
    stripped = text.strip()
    if not stripped:
        return {"ok": False, "issues": [_issue("empty", "no text", "Provide the sentence.")]}
    if stripped.endswith(("?", "？")):
        issues.append(_issue(
            "question", "ends as a question",
            "Rewrite as a statement that could be true or false.",
        ))
    if stripped.endswith(("!", "！")):
        issues.append(_issue(
            "exclamation", "ends as an exclamation",
            "Rewrite as a neutral statement.",
        ))
    if re.match(r"^(is|are|was|were|do|does|did|can|could|should|would|will|has|have)\b",
                stripped, re.I):
        issues.append(_issue(
            "inverted_question", "opens with an auxiliary verb",
            "Rewrite in subject-first order.",
        ))
    if not stripped.endswith((".", "。", "！", "？", "!", "?")):
        issues.append(_issue(
            "no_full_stop", "does not end with sentence-final punctuation",
            "Close the sentence with a full stop.",
        ))
    if len(stripped) < MIN_SENTENCE:
        issues.append(_issue(
            "too_short", f"{len(stripped)} characters is below the 5 character minimum",
            "Provide a complete claim.",
        ))
    return {"ok": not issues, "issues": issues}


def find_scope(text: str) -> list[str]:
    """Return scope phrases that must survive absolutisation."""
    found = []
    for m in SCOPE_HINT.finditer(text):
        span = m.group(0).strip()
        low = span.lower()
        if not span or any(low.startswith(s) for s in SCOPE_STOP):
            continue
        if low not in {s.lower() for s in found}:
            found.append(span)
    return found


def check_absolute(text: str) -> dict:
    issues = []
    stripped = text.strip()
    scope = find_scope(stripped)
    scope_norm = " ".join(scope).lower()
    for word, kind in HEDGE.items():
        for m in re.finditer(rf"\b{re.escape(word)}\b" if word.isascii() else re.escape(word),
                             stripped, re.IGNORECASE):
            hit = m.group(0)
            tail = stripped[m.start():m.end() + 40].lower()
            if hit.lower() in scope_norm or any(hit.lower() in s.lower() for s in scope):
                continue
            if kind == "modality" and re.match(r"^(may|might|could|would)\s+\w+", tail) is None:
                pass
            issues.append(_issue(
                f"hedge_{kind}",
                f"'{hit}' expresses uncertainty about the claim",
                f"Remove '{hit}' and record the confidence in confidence_basis; "
                "do not delete the scope phrase it sits in.",
                hit,
            ))
    for pattern in DISCOVERY:
        m = re.search(pattern, stripped, re.IGNORECASE)
        if m:
            issues.append(_issue(
                "discovery_process",
                f"'{m.group(0)}' describes how the claim was obtained",
                "Remove it from the sentence and put the source in provenance.",
                m.group(0),
            ))
            break
    if re.search(r"\b(was|were|found|showed|observed|measured|reported)\b", stripped, re.I):
        issues.append(_issue(
            "past_tense",
            "past tense usually carries the discovery process",
            "Prefer present tense for the claim itself; keep past tense only inside evidence.",
        ))
    return {"ok": not issues, "issues": issues, "scope_found": scope}


def check_aida(text: str) -> dict:
    """Run all four AIDA criteria and return issues with fix hints."""
    parts = {
        "atomic": check_atomic(text),
        "independent": check_independent(text),
        "declarative": check_declarative(text),
        "absolute": check_absolute(text),
    }
    codes = [i["code"] for p in parts.values() for i in p["issues"]]
    hard = {"leading_pronoun", "first_person", "question", "exclamation",
            "no_full_stop", "too_long", "multi_sentence", "semicolon", "empty"}
    verdict = "fail" if hard & set(codes) else ("warn" if codes else "pass")
    return {
        "sentence": text.strip(),
        "length": len(text.strip()),
        "criteria": parts,
        "verdict": verdict,
        "scope_must_keep": parts["absolute"]["scope_found"],
        "issue_codes": codes,
    }


def polarity_kind(word: str) -> str | None:
    return POLARITY.get(word.lower())


def polarity_tokens(text: str) -> list[str]:
    """Return polarity words present in `text`, both English and Chinese."""
    hits = []
    for m in re.finditer(r"[A-Za-z]+|[\u4e00-\u9fff]{2,6}", text):
        tok = m.group(0)
        if tok.lower() in POLARITY:
            hits.append(tok)
            continue
        for cn, _kind in POLARITY.items():
            if not cn.isascii() and cn in tok:
                hits.append(cn)
                break
    return hits


def number_tokens(text: str) -> list[str]:
    return re.findall(r"\d+(?:\.\d+)?%?", text)


def check_scope_loss(claim: str, quote: str) -> dict:
    """Flag claims that dropped a scope phrase or a polarity word from evidence."""
    issues = []
    claim_low = claim.lower()
    quote_low = quote.lower()

    for phrase in find_scope(quote):
        core = re.sub(r"^(in|on|at|for|under|within|during|among|across|when|while|where|if)\s+",
                      "", phrase.strip(), flags=re.I).strip()
        if len(core) < 3:
            continue
        key = core.split()[0].lower().strip(",.;:")
        if len(key) < 3:
            continue
        if key not in claim_low and phrase.lower() not in claim_low:
            issues.append(_issue(
                "scope_dropped",
                f"evidence limits the claim with '{phrase}' but the claim omits it",
                f"Add the scope to the claim or to qualifiers (scope): '{phrase}'.",
                phrase,
            ))

    q_pol = {p.lower() for p in polarity_tokens(quote)}
    c_pol = {p.lower() for p in polarity_tokens(claim)}
    if q_pol and not (q_pol & c_pol):
        kinds_q = {polarity_kind(p) for p in q_pol}
        kinds_c = {polarity_kind(p) for p in c_pol}
        if kinds_q - kinds_c:
            issues.append(_issue(
                "polarity_dropped",
                f"evidence contains {sorted(q_pol)} but the claim has no matching polarity word",
                "Keep the direction word (deficiency / increase / reduction) in the claim "
                "or in qualifiers; dropping it flips the meaning.",
                ",".join(sorted(q_pol)),
            ))

    q_nums = set(number_tokens(quote))
    c_nums = set(number_tokens(claim))
    if c_nums and q_nums and not (c_nums & q_nums):
        issues.append(_issue(
            "number_mismatch",
            f"claim numbers {sorted(c_nums)} do not appear in the evidence {sorted(q_nums)}",
            "Use only numbers copied verbatim from the evidence.",
            ",".join(sorted(c_nums)),
        ))
    return {"ok": not issues, "issues": issues}


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json

    ap = argparse.ArgumentParser(description="Check a sentence against AIDA.")
    ap.add_argument("sentence")
    ap.add_argument("--quote", help="evidence quote, to also test scope and polarity")
    args = ap.parse_args(argv)
    out = check_aida(args.sentence)
    if args.quote:
        out["scope_loss"] = check_scope_loss(args.sentence, args.quote)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out["verdict"] != "fail" else 1


if __name__ == "__main__":
    raise SystemExit(main())
