#!/usr/bin/env python3
"""Assemble and write the final deliverables.

The editable source is copied into <out>/source/ so reviewers can continue
editing it.  We do NOT ship compiled PDF/PNG here: the task's whitelist is for
Skill resources, and a runtime PDF is recorded by hash in the manifest instead
of being handed off as a fake 'answer'.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import build as B
import contract as C

COPY_SUFFIXES = {".tex", ".bib", ".cls", ".sty", ".bst", ".bbx", ".cbx",
                 ".cfg", ".def", ".fd", ".md", ".txt"}


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")


def copy_editable_sources(work: Path, out_dir: Path) -> list[dict]:
    src = work / "src"
    dst = out_dir / "source"
    if dst.exists():
        shutil.rmtree(dst)
    rows: list[dict] = []
    if not src.is_dir():
        return rows
    for p in sorted(src.rglob("*"), key=lambda x: str(x).lower()):
        if not p.is_file() or p.suffix.lower() not in COPY_SUFFIXES:
            continue
        rel = p.relative_to(src)
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, target)
        rows.append({
            "path": "source/" + rel.as_posix(),
            "role": ("main_tex" if p.name == Path(src.name).name else "support"),
            "sha256": B.sha256_file(target),
            "bytes": target.stat().st_size,
        })
    return rows


def sanitize_profile(profile: dict) -> dict:
    """Strip machine-specific absolute paths from the deliverable.

    The result must be portable: a reviewer on another machine should be able
    to read the same JSON, so case paths are represented relative to the case
    root instead of as paths on the machine that ran the build.
    """
    out = dict(profile)
    out["root"] = "<case_root>"
    if out.get("main_tex"):
        out["main_tex"] = Path(out["main_tex"]).name
    out["files"] = [{
        **{k: v for k, v in f.items() if k != "path"},
        "path": f.get("name") or Path(str(f.get("path", ""))).name,
    } for f in profile.get("files", []) if isinstance(f, dict)]
    return out


def build_result(case_id: str, profile: dict, repair_result: dict,
                 manifest: dict, reproduce: dict, validation: dict,
                 case_raw: dict | None = None, runtime_seconds: float = 0.0,
                 work_dir: str | Path | None = None,
                 out_dir: str | Path | None = None,
                 audit: dict | None = None) -> dict:
    rr = repair_result or {}
    final_build = rr.get("final_build") or {}
    ledger = rr.get("final_ledger") or {}
    changes = rr.get("changes") or []
    audit = audit or {"findings": [], "counts": {}, "status": "clean"}

    artifacts = copy_editable_sources(Path(work_dir), Path(out_dir)) \
        if work_dir and out_dir else []

    clean_profile = sanitize_profile(profile)
    sources = [{
        "path": f.get("path", ""), "kind": f.get("kind", ""),
        "role": f.get("role", ""), "bytes": f.get("bytes", 0),
    } for f in clean_profile.get("files", [])]
    if clean_profile.get("main_tex"):
        sources.append({"path": clean_profile["main_tex"], "kind": "main_tex",
                        "role": "root document", "bytes": 0})

    unresolved = [f for f in ledger.get("findings", [])
                  if f.get("severity") == "blocking"]
    applied = [c for c in changes if c.get("applied")]
    needs_human = [c for c in changes if not c.get("applied")]
    major_left = [f for f in ledger.get("findings", [])
                  if f.get("severity") == "major"]
    audit_major = [f for f in audit.get("findings", [])
                   if f.get("severity") == "major"]

    uncertainty: list[str] = []
    if needs_human:
        uncertainty.append(
            f"{len(needs_human)} proposed change(s) need human judgement "
            "(numeric values, math semantics, label keys or template rules were not guessed)")
    if not final_build.get("ok"):
        uncertainty.append("final build did not converge; see error_ledger and build logs")
    remaining = [f for f in ledger.get("findings", [])
                 if f.get("severity") in ("major", "minor") and
                 f.get("id") not in {c.get("finding_id") for c in changes if c.get("applied")}]
    if remaining:
        uncertainty.append(
            f"{len(remaining)} warning(s) remain after the build "
            f"({', '.join(sorted({f.get('category', '') for f in remaining}))}); "
            "locations and fixes are in error_ledger.json")
    if reproduce.get("verdict") == "failed":
        uncertainty.append("independent reproduction did not match core checks")
    if reproduce.get("verdict") == "partial":
        uncertainty.append("reproduction matched core checks but PDF bytes or diagnostics differed")
    if audit.get("findings"):
        uncertainty.append(
            f"source audit: {audit['counts'].get('major', 0)} major, "
            f"{audit['counts'].get('minor', 0)} minor structural issue(s); "
            "see audit.json (report-only, source not rewritten)")
    if profile.get("issues"):
        uncertainty.extend(profile["issues"])
    if not artifacts:
        uncertainty.append("no editable source was produced")

    if not profile.get("main_tex") and not profile.get("inline_source_present"):
        status = "blocked"
    elif final_build.get("ok") and not unresolved and not major_left and \
            not audit_major and \
            reproduce.get("verdict") in ("verified", "partial"):
        status = "complete"
    else:
        status = "partial"

    limits = []
    if status != "complete":
        limits.append("see error_ledger / reproduction checks for the blocking factor")
    if major_left:
        limits.append(f"{len(major_left)} major finding(s) remain (undefined "
                      "reference/citation or similar) — final output is not yet correct")
    if audit_major:
        limits.append(f"{len(audit_major)} major source-audit issue(s): " + ", ".join(
            sorted({f.get('kind', '') for f in audit_major})))
    if needs_human:
        limits.append("human review required for: " + ", ".join(
            sorted({c.get("category", "") for c in needs_human})))

    result = {
        "case_id": case_id,
        "status": status,
        "project_profile": clean_profile,
        "sources": sources,
        "artifacts": artifacts,
        "error_ledger": ledger,
        "changes": changes,
        "build_manifest": manifest,
        "reproduce": reproduce,
        "audit": audit,
        "validation": validation,
        "uncertainty": uncertainty,
        "limits": limits,
        "changes_summary": {
            "applied": len(applied), "proposed_only": len(needs_human),
            "source_files_changed": rr.get("source_diffs", []),
        },
        "runtime_seconds": round(runtime_seconds, 2),
        "example": bool((case_raw or {}).get("example")),
    }
    if result["example"]:
        result["example_note"] = "EXAMPLE-NOT-A-OFFICIAL-CASE"
    return result


def write_all(out_dir: str | Path, result: dict, repair_result: dict,
              case_raw: dict) -> list[str]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name, obj in (("result.json", result),
                      ("error_ledger.json", (repair_result or {}).get("final_ledger", {})),
                      ("build_manifest.json", result.get("build_manifest", {})),
                      ("reproduce.json", result.get("reproduce", {})),
                      ("audit.json", result.get("audit", {}))):
        _write_json(out / name, obj)

    changes = (repair_result or {}).get("changes", [])
    md = ["# 修复台账 —— " + str(result.get("case_id", "")), "",
          "只自动执行确定性修复；需领域判断的项标为“待人工确认”，不猜数值或符号。", ""]
    if not changes:
        md.append("无改动。")
    for c in changes:
        md.append(f"## {c.get('id','')} · {c.get('category','')} · "
                  f"{'已应用' if c.get('applied') else '待人工确认'}")
        md.append("")
        md.append(f"- 位置：{c.get('location','') or '（日志未给出行号）'}")
        md.append(f"- 根因：{c.get('reason','')}")
        md.append(f"- 动作：{c.get('action','')}")
        md.append(f"- 复验：{result.get('build_manifest',{}).get('engine','')} 重编并检查该位置")
        md.append("")
    (out / "changes.md").write_text("\n".join(md) + "\n",
                                    encoding="utf-8", newline="\n")

    # Honour the declared output_contract, without inventing values.
    result, _report = C.apply(result, case_raw.get("output_contract"), None)
    _write_json(out / "result.json", result)
    return ["result.json", "error_ledger.json", "build_manifest.json",
            "reproduce.json", "audit.json", "changes.md"]
