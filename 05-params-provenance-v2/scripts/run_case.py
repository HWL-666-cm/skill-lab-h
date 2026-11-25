#!/usr/bin/env python3
"""Entry point: scan -> (write a draft) -> finish.

    scan     read every material file, propose parameter candidates with positions.
             No judgement: it says "these numbers exist here", not "this is correct".
    auto     build a draft from the ledger with rules only, then finish.  Honest but
             mechanical: it is a floor for the harness, never the good path.
    finish   take a draft (model or human authored), build the ledger, align both
             ways, raise gaps, run the gate, write the deliverables.
    recheck  re-run the gate on an existing output directory.

Exit codes: 0 pass/warn, 1 fail/incomplete (a result is still written), 2 bad input.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import align as align_mod       # noqa: E402
import emit                     # noqa: E402
import gaps as gaps_mod         # noqa: E402
import ledger as ledger_mod     # noqa: E402
import materials as M           # noqa: E402
import params as params_mod     # noqa: E402
import validate as validate_mod  # noqa: E402


def _read(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# The draft and our own deliverables must never be read back as material.
# A draft that lives next to the case files would otherwise supply its own
# numbers as "evidence", and a second run would read the previous result.json.
# Both are circular provenance: the report would agree with itself rather than
# with the materials the author actually supplied.
OUTPUT_LIKE = {
    "result.json", "validation.json", "alignment.json", "gaps.json", "gaps.md",
    "ledger.json", "material_map.json", "candidates.json", "methods.md",
    "parameter_ledger.csv", "draft_auto.md",
}


def skip_set(root: Path, out_dir: Path | None = None,
             draft_path: str | Path | None = None) -> set[str]:
    """Exact relative paths to exclude from material reading.

    By path, not by file name: a genuine manuscript may legitimately be called
    ``methods.md``, and silently dropping it would lose the very text we were
    asked to check.  Only the specific draft the caller names and the specific
    output directory this run writes to are excluded.
    """
    root = Path(root).resolve()
    skip: set[str] = set()
    if out_dir:
        out = Path(out_dir).resolve()
        if out != root and root in out.parents:
            skip.add(out.relative_to(root).as_posix())   # whole output subtree
        elif out == root:
            skip.update(OUTPUT_LIKE)                      # in-place examples
    if draft_path:
        p = Path(draft_path).resolve()
        try:
            skip.add(p.relative_to(root).as_posix())
        except ValueError:
            skip.add(p.name)                              # draft outside the case
    return skip


def resolve_case(case_path: Path) -> tuple[dict, Path, str]:
    case_path = Path(case_path)
    if case_path.is_dir():
        root = case_path
        for name in ("case.json", "input.json"):
            if (root / name).is_file():
                return _read(root / name), root, root.name
        return {}, root, root.name
    raw = _read(case_path) if case_path.is_file() else {}
    return raw, case_path.parent, str(raw.get("case_id") or case_path.parent.name)


def read_draft(path: str | Path | None) -> str:
    if not path:
        return ""
    p = Path(path)
    if not p.is_file():
        return ""
    if p.suffix.lower() == ".json":
        d = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(d, str):
            return d
        if isinstance(d, dict):
            for key in ("markdown", "draft", "text", "methods", "manuscript", "section"):
                if isinstance(d.get(key), str):
                    return d[key]
            secs = d.get("sections")
            if isinstance(secs, list):
                parts: list[str] = []
                for s in secs:
                    if isinstance(s, str):
                        parts.append(s)
                        continue
                    head = s.get("heading") or s.get("title") or ""
                    if head:
                        parts.append("## " + str(head))
                    for pg in s.get("paragraphs") or []:
                        parts.append(pg if isinstance(pg, str) else str(pg.get("text") or ""))
                return "\n\n".join(parts)
        return ""
    return p.read_text(encoding="utf-8")


def _blocked(out_dir: Path, case_id: str, reason: str, detail: str = "") -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {"case_id": case_id, "status": "blocked", "reason": reason, "detail": detail,
               "limits": [reason], "ledger": {"entries": []},
               "alignment": {"forward": {}, "backward": {}, "coverage": {}},
               "gaps": {"gaps": []}, "validation": {"status": "fail", "checks": []},
               "sources": [], "uncertainty": [reason], "change_log": []}
    (out_dir / "result.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    (out_dir / "gaps.md").write_text(
        f"# 材料缺口与追问清单 —— {case_id}\n\n运行被阻断：{reason}\n\n{detail}\n",
        encoding="utf-8", newline="\n")
    return payload


def scan(case_path: Path, out_dir: Path, lexicon: dict, schema: dict) -> dict:
    case_raw, root, case_id = resolve_case(case_path)
    pack = M.read_material(root, skip_files=skip_set(root, out_dir),
                          extra_roots=case_raw.get("material_dirs") or [])
    if not pack["units"]:
        _blocked(out_dir, case_id, "no readable material",
                 f"{root} 下没有可读的材料文件（任何格式都没有内容）")
        return {"status": "blocked", "case_id": case_id}

    cands = params_mod.extract(pack, lexicon)
    out_dir.mkdir(parents=True, exist_ok=True)
    material_map = {
        "case_id": case_id,
        "root": str(root),
        "files": pack["files"],
        "stats": pack["stats"],
        "unreadable": pack["unreadable"],
    }
    for name, obj in (("material_map.json", material_map), ("candidates.json", cands)):
        (out_dir / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n",
                                    encoding="utf-8", newline="\n")
    return {"status": "ok", "case_id": case_id, "stats": pack["stats"],
            "candidates": cands["stats"], "unreadable": pack["unreadable"],
            "warnings": _merge_warnings(pack)}


def _merge_warnings(pack: dict) -> list[str]:
    out = []
    for f in pack["files"]:
        if f.get("note"):
            out.append(f"{f['source']}: {f['note']}")
    for u in pack.get("unreadable", []):
        out.append(f"{u['source']}: {u['reason']}")
    return out


def auto_draft(ledger: dict) -> str:
    """Rule-only floor. It restates the ledger; it does not write a section."""
    lines = ["## Parameter summary (rule-generated floor, not a finished section)", ""]
    for e in ledger["entries"]:
        if e["status"] == "manuscript_only":
            continue
        v = e["values"][0]
        lines.append(f"- {e['name']} in scope `{e['scope']}` is {v['raw']}"
                     f"{(' ' + v['unit']) if v['unit'] else ''}; "
                     f"source {v['path']}:{v['locator']} ({v['source_kind']}).")
    if len(lines) == 2:
        lines.append("- no parameter with a non-prose source was found")
    return "\n".join(lines)


def finish(case_path: Path, draft_path: str | Path | None, out_dir: Path,
           lexicon: dict, schema: dict) -> dict:
    case_raw, root, case_id = resolve_case(case_path)
    pack = M.read_material(root, skip_files=skip_set(root, out_dir, draft_path),
                          extra_roots=case_raw.get("material_dirs") or [])
    cands_path = out_dir / "candidates.json"
    if pack["units"]:
        cands = params_mod.extract(pack, lexicon)
    elif cands_path.is_file():
        cands = _read(cands_path)
        pack = M.read_material(root, skip_files=skip_set(root, out_dir, draft_path))
    else:
        return _blocked(out_dir, case_id, "no readable material", "先跑 --stage scan")

    draft_text = read_draft(draft_path)
    led = ledger_mod.build(cands, schema)
    al = align_mod.align(led, draft_text, lexicon, cands, pack)
    gp = gaps_mod.build(led, al, pack, draft_text)

    extra: list[str] = []
    if not draft_text.strip():
        extra.append("no draft was supplied, so every ledger row is reported as not written; "
                     "this is a scan of the material, not a review of a section")
    # a provisional result is needed before the gate can judge honesty fields
    placeholder = {"status": "incomplete", "counts": {"fail": 0}, "checks": [], "top_failures": []}
    provisional = emit.build_result(case_id, pack, led, al, gp, placeholder, "complete",
                                    draft_text, extra)
    report = validate_mod.validate(led, al, gp, pack, draft_text, provisional)
    status = "complete" if report["status"] in ("pass", "warn") and not gp["by_severity"]["blocking"] \
        else "partial"

    result = emit.build_result(case_id, pack, led, al, gp, report, status, draft_text, extra)
    result = emit.finalise(case_raw, result, pack)
    # the gate looked at status before the contract ran; re-state after
    report2 = validate_mod.validate(led, al, gp, pack, draft_text, result)
    result["validation"] = {"status": report2["status"], "counts": report2["counts"],
                            "checks": report2["checks"], "top_failures": report2["top_failures"]}
    if report2["counts"]["fail"] or gp["by_severity"]["blocking"]:
        result["status"] = "partial"
        result["limits"] = [f"{report2['counts']['fail']} gate checks failed"] if report2["counts"]["fail"] else result["limits"]
    written = emit.write_all(out_dir, result, led, al, gp, report2)
    return {"status": result["status"], "validation": report2["status"],
            "counts": report2["counts"], "top_failures": report2["top_failures"],
            "ledger": led["stats"], "alignment": {"trace_rate": al["forward"]["trace_rate"],
                                                 "invented": len(al["forward"]["invented"]),
                                                 "not_written": len(al["backward"]["not_written"])},
            "gaps": {"total": len(gp["gaps"]), "blocking": gp["by_severity"]["blocking"]},
            "written": written}


def main() -> int:
    ap = argparse.ArgumentParser(description="methods & experiment section: scan / auto / finish")
    ap.add_argument("--case", required=True, help="case.json or the material directory")
    ap.add_argument("--lexicon", required=True)
    ap.add_argument("--schema", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--stage", choices=["scan", "auto", "finish", "recheck"], default="auto")
    ap.add_argument("--draft", help="draft markdown or json for the finish stage")
    args = ap.parse_args()

    case_path, out_dir = Path(args.case), Path(args.out)
    lexicon, schema = _read(args.lexicon), _read(args.schema)

    if args.stage == "scan":
        info = scan(case_path, out_dir, lexicon, schema)
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0 if info["status"] == "ok" else 2

    if args.stage == "auto":
        info = scan(case_path, out_dir, lexicon, schema)
        if info["status"] != "ok":
            print(json.dumps(info, ensure_ascii=False, indent=2))
            return 2
        _, root, _cid = resolve_case(case_path)
        pack = M.read_material(root, skip_files=skip_set(root, out_dir))
        led = ledger_mod.build(_read(out_dir / "candidates.json"), schema)
        dpath = out_dir / "draft_auto.md"
        dpath.write_text(auto_draft(led) + "\n", encoding="utf-8", newline="\n")
        info = finish(case_path, dpath, out_dir, lexicon, schema)
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0 if info["status"] == "complete" else 1

    if args.stage == "finish":
        info = finish(case_path, args.draft, out_dir, lexicon, schema)
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0 if info.get("status") == "complete" else 1

    # recheck
    need = [out_dir / n for n in ("ledger.json", "alignment.json", "gaps.json")]
    if not all(p.is_file() for p in need):
        print(json.dumps({"status": "blocked", "reason": "run finish first"}, ensure_ascii=False))
        return 2
    _, root, _cid = resolve_case(case_path)
    pack = M.read_material(root, skip_files=skip_set(root, out_dir))
    draft = (out_dir / "methods.md").read_text(encoding="utf-8") if (out_dir / "methods.md").is_file() else ""
    led = _read(out_dir / "ledger.json")
    al = _read(out_dir / "alignment.json")
    gp = _read(out_dir / "gaps.json")
    res = _read(out_dir / "result.json") if (out_dir / "result.json").is_file() else {}
    rep = validate_mod.validate(led, al, gp, pack, draft, res)
    print(json.dumps({"status": rep["status"], "counts": rep["counts"],
                      "top": rep["top_failures"]}, ensure_ascii=False, indent=2))
    return 0 if rep["status"] in ("pass", "warn") else 1


if __name__ == "__main__":
    raise SystemExit(main())
