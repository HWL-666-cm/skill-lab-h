#!/usr/bin/env python3
"""Gate the result against the schema.  Checks are executable, not decorative."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def validate(result: dict, schema: dict, work_dir: Path | None = None,
             out_dir: Path | None = None) -> dict:
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str, severity: str = "fail") -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail,
                       "severity": severity})

    add("has_case_id", bool(str(result.get("case_id", "")).strip()),
        "case_id is " + str(result.get("case_id", "")))

    srcs = result.get("sources") or []
    add("has_sources", bool(srcs), f"{len(srcs)} source entries")

    arts = result.get("artifacts") or []
    art_ok = bool(arts)
    if out_dir and arts:
        art_ok = all((out_dir / a["path"]).is_file()
                     for a in arts if isinstance(a, dict) and a.get("path"))
    add("has_artifacts", art_ok, f"{len(arts)} editable artifacts")

    man = result.get("build_manifest") or {}
    man_ok = all(k in man for k in ("engine", "distribution", "commands",
                                    "rounds", "source_hashes"))
    add("has_build_manifest", man_ok,
        f"engine={man.get('engine')} rounds={man.get('rounds')}")

    led = result.get("error_ledger") or {}
    findings = led.get("findings") or []
    led_ok = bool(findings) or led.get("build_ok") is True
    malformed = [f for f in findings if not all(
        k in f for k in ("location", "root_cause", "fix", "reverify"))]
    add("has_error_ledger", led_ok and not malformed,
        f"{len(findings)} findings, {len(malformed)} malformed")

    changes = result.get("changes") or []
    built_ok = bool((result.get("error_ledger") or {}).get("build_ok"))
    add("has_changes", bool(changes) or built_ok,
        f"{sum(1 for c in changes if c.get('applied'))} applied / "
        f"{sum(1 for c in changes if not c.get('applied'))} proposed"
        + (" (clean build needs no change)" if not changes and built_ok else ""),
        "warn")

    unc = result.get("uncertainty") or []
    add("has_uncertainty", bool(unc) or result.get("status") == "complete",
        f"{len(unc)} uncertainty entries", "warn")

    build_ok = bool(led.get("build_ok") or
                    (result.get("build_manifest", {}).get("commands") and
                     all(c.get("returncode") == 0 for c in
                         result["build_manifest"]["commands"])))
    add("compiled", build_ok, "final build converged" if build_ok else
        "build did not converge")

    rep = result.get("reproduce") or {}
    verdict = rep.get("verdict", "")
    add("reproduced", verdict in ("verified", "verified_failure", "partial"),
        f"reproduction verdict={verdict}", "warn")

    # A fabricated result would claim complete while the build failed, or claim
    # no uncertainty while changes were only proposed.  Both are detectable.
    fake = (result.get("status") == "complete" and not build_ok) or \
           (result.get("status") == "complete" and
            any(c.get("applied") is False for c in changes) and not unc)
    add("no_fabrication", not fake,
        "status consistent with build/reproduction evidence")

    severities = {c["name"]: c["severity"] for c in (schema.get("checks") or [])}
    for c in checks:
        c["severity"] = severities.get(c["name"], c["severity"])
    fails = [c["name"] for c in checks if not c["ok"] and c["severity"] == "fail"]
    warns = [c["name"] for c in checks if not c["ok"] and c["severity"] == "warn"]
    status = "pass" if not fails and not warns else ("warn" if not fails else "fail")
    return {"status": status, "checks": checks, "counts": {
        "pass": sum(1 for c in checks if c["ok"]),
        "fail": len(fails), "warn": len(warns)},
        "top_failures": fails + warns}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--result", required=True)
    ap.add_argument("--schema", required=True)
    a = ap.parse_args()
    r = json.loads(Path(a.result).read_text(encoding="utf-8"))
    s = json.loads(Path(a.schema).read_text(encoding="utf-8"))
    out = validate(r, s)
    print(json.dumps({"status": out["status"], "counts": out["counts"],
                      "top": out["top_failures"]}, ensure_ascii=False, indent=2))
