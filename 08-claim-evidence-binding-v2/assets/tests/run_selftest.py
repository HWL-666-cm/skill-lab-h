#!/usr/bin/env python3
"""Self-test for the claim-evidence binding Skill.

Every assertion here corresponds to a real failure found during development,
not to an imagined edge case.  Run: python assets/tests/run_selftest.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import align as A          # noqa: E402
import claims as C         # noqa: E402
import materials as M      # noqa: E402

LEX = json.loads((ROOT / "assets" / "lexicon.json").read_text(encoding="utf-8"))
SCHEMA = json.loads((ROOT / "assets" / "schema.json").read_text(encoding="utf-8"))
CASE = ROOT / "assets" / "examples" / "case.json"
# Fixtures live INSIDE the package: the self-test must also pass when the
# Skill is loaded from a cold directory (e.g. /skills/weekly-skill), where no
# developer scratch files exist.
GOOD = Path(__file__).resolve().parent / "draft_good.md"
BAD = Path(__file__).resolve().parent / "draft_bad.md"

passed = 0
failed: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    global passed
    if cond:
        passed += 1
    else:
        failed.append(f"{name}: {detail}")


def run(case, out, draft=None):
    cmd = [sys.executable, str(ROOT / "scripts" / "run_case.py"),
           "--case", str(case), "--lexicon", str(ROOT / "assets" / "lexicon.json"),
           "--schema", str(ROOT / "assets" / "schema.json"),
           "--out", str(out), "--stage", "finish"]
    if draft:
        cmd += ["--draft", str(draft)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return json.loads(r.stdout)
    except Exception:
        return {"status": "ERR", "stdout": r.stdout[:300], "stderr": r.stderr[:300]}


# --- 1. material extraction ---
pack = M.read_material(ROOT / "assets" / "examples" / "material")
cands = C.extract(pack, LEX)
check("refs found", cands["stats"]["references"] >= 4, str(cands["stats"]))
check("figure anchors found", cands["stats"]["figures"] >= 2, str(cands["stats"]))
check("no unreadable", len(pack["unreadable"]) == 0)

# --- 2. sentence splitting (real bug: headings + abbreviations) ---
sents = C._sentences("## 研究背景\nSmith et al. (2020) did X. Fig. 1 shows Y.")
check("heading not a claim", all(not s.startswith("#") for s in sents), str(sents))
check("et al. not split", any("did X" in s and "Smith" in s for s in sents), str(sents))
check("Fig. not split", any("Fig. 1" in s and "shows Y" in s for s in sents), str(sents))

# --- 3. citation parsing (real bug: Optional group None) ---
pats = A._compile_cite_patterns(LEX)
found = A._find_citations("（Smith2020）和 Smith et al. (2020)", pats)
check("fullwidth citation found", any("Smith2020" in c["raw"] for c in found), str(found))
check("all values non-null", all(isinstance(c["value"], str) for c in found))
check("overlap dedup", not any(c["raw"] == "(2020)" for c in found), str(found))

# --- 4. alignment good draft ---
with tempfile.TemporaryDirectory() as td:
    good = run(CASE, Path(td) / "good", GOOD)
    check("good complete", good.get("status") == "complete", str(good)[:300])
    check("good trace_rate 1.0", good.get("alignment", {}).get("trace_rate") == 1.0, str(good.get("alignment")))
    check("good no fail", not good.get("top_failures"), str(good.get("top_failures")))
    gres = json.loads((Path(td) / "good" / "result.json").read_text(encoding="utf-8"))
    check("contract satisfied", not (gres.get("contract_report") or {}).get("missing"), str(gres.get("contract_report")))
    check("case_id present", gres.get("case_id") == "example_claim_binding")

    # --- 4b. section completeness regression (B1/B2) ---
    # B1: 四节齐全时 coverage 四个节都必须 written（旧版 background/related_work/contribution 被判 missing）
    cov = gres.get("coverage") or {}
    missing4 = [s for s in ("background", "related_work", "gap", "contribution")
                if cov.get(s, {}).get("state") != "written"]
    check("four sections written", not missing4, f"missing={missing4}")
    # B2: ## 相关工作 下挂两个 ### 分组时，related_work 仍须 written（旧版被分组标题吞掉）
    check("grouped related_work written", cov.get("related_work", {}).get("state") == "written",
          str(cov.get("related_work")))

    bad = run(CASE, Path(td) / "bad", BAD)
    check("bad partial", bad.get("status") == "partial", str(bad)[:300])
    check("bad catches metadata mismatch", "citation_metadata_mismatch" in bad.get("top_failures", []), str(bad.get("top_failures")))
    bres = json.loads((Path(td) / "bad" / "result.json").read_text(encoding="utf-8"))
    mm = [r for r in bres["claim_ledger"]["rows"] if r.get("metadata_mismatch")]
    check("mixed hallucination exact", any("2019" in x and "2020" in x for r in mm for x in r["metadata_mismatch"]), str(mm))
    check("overclaim flagged", bres["alignment"]["forward"]["by_status"].get("overclaimed", 0) >= 1)

    # --- 5. no draft -> partial with limits ---
    nd = run(CASE, Path(td) / "nodraft")
    check("no draft partial", nd.get("status") == "partial", str(nd)[:200])
    nres = json.loads((Path(td) / "nodraft" / "result.json").read_text(encoding="utf-8"))
    check("partial has limits", bool(nres.get("limits")), str(nres.get("limits")))

    # --- 6. empty material -> blocked ---
    empty = Path(td) / "empty"
    empty.mkdir()
    eb = run(empty, Path(td) / "out_empty")
    check("empty blocked", eb.get("status") == "blocked", str(eb)[:200])

    # --- 7. determinism ---
    d1, d2 = Path(td) / "d1", Path(td) / "d2"
    run(CASE, d1, GOOD); run(CASE, d2, GOOD)
    names = sorted(p.name for p in d1.iterdir())
    check("determinism file set", names == sorted(p.name for p in d2.iterdir()))
    diff = [n for n in names if (d1 / n).read_bytes() != (d2 / n).read_bytes()]
    check("determinism bytes", not diff, str(diff))

# --- 8. no prepared answers in package ---
assets = ROOT / "assets" / "examples"
check("example marked", json.loads((assets / "case.json").read_text(encoding="utf-8")).get("example") is True)
check("no formal result at package root", not (ROOT / "result.json").exists())

print(f"SELFTEST {passed}/{passed + len(failed)}")
for f in failed:
    print(" FAIL", f)
sys.exit(1 if failed else 0)
