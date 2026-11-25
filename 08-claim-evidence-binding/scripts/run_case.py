#!/usr/bin/env python3
"""Entry point for claim-evidence binding: scan -> auto -> finish.

    scan     read every material file, extract checkable anchors (references,
             figures, limitations, contributions, key works).  No judgement.
    auto     build a rule-only draft from the anchors, then finish.  Honest but
             mechanical: a floor for the Harness, not the good path.
    finish   take a draft (model or human authored), align both ways, raise
             gaps, run the four-state gate, write all deliverables.
    recheck  re-run the gate on an existing output directory.

Exit codes: 0 pass/warn, 1 fail/incomplete (a result is still written), 2 bad input.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import align as align_mod   # noqa: E402
import claims as claims_mod  # noqa: E402
import emit                 # noqa: E402
import gaps as gaps_mod     # noqa: E402
import materials as M       # noqa: E402
import validate as validate_mod  # noqa: E402


def _read(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


OUTPUT_LIKE = {
    "result.json", "validation.json", "alignment.json", "claim_ledger.json",
    "citation_check.json", "coverage.json", "gaps.json", "gaps.md",
    "material_map.json", "candidates.json", "intro_related_work.md",
    "draft_auto.md", "sources.json",
}


def skip_set(root: Path, out_dir: Path | None = None,
             draft_path: str | Path | None = None) -> set[str]:
    """Exclude our own outputs and the named draft by exact relative path.

    By path, never by filename: a genuine manuscript may legitimately be called
    ``introduction.md`` and must not be silently dropped.
    """
    root = Path(root).resolve()
    skip: set[str] = set()
    if out_dir:
        out = Path(out_dir).resolve()
        if out != root and root in out.parents:
            skip.add(out.relative_to(root).as_posix())
        elif out == root:
            skip.update(OUTPUT_LIKE)
    if draft_path:
        p = Path(draft_path).resolve()
        try:
            skip.add(p.relative_to(root).as_posix())
        except ValueError:
            skip.add(p.name)
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
            for key in ("markdown", "draft", "text", "intro_related_work",
                        "intro_related_work_markdown", "manuscript"):
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
               "limits": [reason], "claim_ledger": {"rows": []},
               "alignment": {"forward": {"rows": [], "by_status": {}},
                             "backward": {"rows": [], "by_status": {}}},
               "gaps": [], "validation": {"status": "fail", "checks": [], "counts": {}},
               "sources": [], "uncertainty": [reason], "change_log": []}
    (out_dir / "result.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    (out_dir / "gaps.md").write_text(
        f"# 缺口清单 —— {case_id}\n\n运行被阻断：{reason}\n\n{detail}\n",
        encoding="utf-8", newline="\n")
    return payload


def scan(case_path: Path, out_dir: Path, lexicon: dict) -> dict:
    case_raw, root, case_id = resolve_case(case_path)
    pack = M.read_material(root, skip_files=skip_set(root, out_dir),
                           extra_roots=case_raw.get("material_dirs") or [])
    if not pack["units"]:
        _blocked(out_dir, case_id, "no readable material",
                 f"{root} 下没有可读材料（任何格式都没有内容）")
        return {"status": "blocked", "case_id": case_id}
    cands = claims_mod.extract(pack, lexicon)
    out_dir.mkdir(parents=True, exist_ok=True)
    material_map = {"case_id": case_id, "root": str(root), "files": pack["files"],
                    "stats": pack["stats"], "unreadable": pack["unreadable"]}
    _write_json(out_dir / "material_map.json", material_map)
    _write_json(out_dir / "candidates.json", cands)
    return {"status": "ok", "case_id": case_id, "stats": pack["stats"],
            "anchors": cands["stats"], "unreadable": pack["unreadable"]}


def _write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")


def finish(case_path: Path, draft_path: str | Path | None, out_dir: Path,
           lexicon: dict, schema: dict) -> dict:
    case_raw, root, case_id = resolve_case(case_path)
    pack = M.read_material(root, skip_files=skip_set(root, out_dir, draft_path),
                           extra_roots=case_raw.get("material_dirs") or [])
    cands_path = out_dir / "candidates.json"
    if pack["units"]:
        cands = claims_mod.extract(pack, lexicon)
    elif cands_path.is_file():
        cands = _read(cands_path)
        pack = M.read_material(root, skip_files=skip_set(root, out_dir, draft_path))
    else:
        return _blocked(out_dir, case_id, "no readable material", "先跑 --stage scan")

    draft_text = read_draft(draft_path)
    al = align_mod.align(cands, draft_text, lexicon, pack)
    gp = gaps_mod.build(cands, al, pack, draft_text)

    extra: list[str] = []
    if not draft_text.strip():
        extra.append("no draft was supplied, so every claim is unanchored; "
                     "this is a material scan, not a review of a section")
    placeholder = {"status": "incomplete", "counts": {"fail": 0},
                   "checks": [], "top_failures": []}
    provisional = emit.build_result(case_id, pack, cands, al, gp, placeholder,
                                    "complete", draft_text, extra, schema)
    report = validate_mod.validate(cands, al, gp, pack, draft_text, provisional, schema)
    status = "complete" if report["status"] in ("pass", "warn") \
        and not gp["by_severity"].get("blocking", 0) else "partial"
    # A scan without a draft is not a finished section.  The gate has no claim
    # rows to fail, so without this guard it would wrongly say "complete".
    if not draft_text.strip():
        status = "partial"

    result = emit.build_result(case_id, pack, cands, al, gp, report, status,
                               draft_text, extra, schema)
    result = emit.finalise(case_raw, result, pack)
    report2 = validate_mod.validate(cands, al, gp, pack, draft_text, result, schema)
    result["validation"] = {"status": report2["status"], "counts": report2["counts"],
                            "checks": report2["checks"], "top_failures": report2["top_failures"]}
    if report2["counts"].get("fail") or gp["by_severity"].get("blocking", 0):
        result["status"] = "partial"
        if not result.get("limits"):
            result["limits"] = ["gate failed: " + ", ".join(report2["top_failures"][:5])]
    written = emit.write_all(out_dir, result, cands, al, gp)
    return {"status": result["status"], "validation": report2["status"],
            "counts": report2["counts"], "top_failures": report2["top_failures"],
            "anchors": cands["stats"], "alignment": {"trace_rate": al["forward"]["trace_rate"],
                                                     "by_status": al["forward"]["by_status"]},
            "gaps": {"total": len(gp["gaps"]), "blocking": gp["by_severity"].get("blocking", 0)},
            "written": written}


def main() -> int:
    ap = argparse.ArgumentParser(description="claim-evidence binding: scan / auto / finish / recheck")
    ap.add_argument("--case", required=True, help="case.json or material directory")
    ap.add_argument("--lexicon", required=True)
    ap.add_argument("--schema", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--stage", choices=["scan", "auto", "finish", "recheck"], default="auto")
    ap.add_argument("--draft", help="draft markdown or json for finish")
    args = ap.parse_args()

    case_path, out_dir = Path(args.case), Path(args.out)
    lexicon, schema = _read(args.lexicon), _read(args.schema)

    if args.stage == "scan":
        info = scan(case_path, out_dir, lexicon)
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0 if info["status"] == "ok" else 2

    if args.stage == "auto":
        info = scan(case_path, out_dir, lexicon)
        if info["status"] != "ok":
            print(json.dumps(info, ensure_ascii=False, indent=2))
            return 2
        case_raw, _root, _cid = resolve_case(case_path)
        cands = _read(out_dir / "candidates.json")
        pack = M.read_material(case_path if case_path.is_dir() else case_path.parent,
                               skip_files=skip_set(case_path if case_path.is_dir() else case_path.parent, out_dir))
        # a rule-only alignment over an empty draft, just to lay out the sections
        cands0 = dict(cands)
        al0 = {"forward": {"rows": [], "by_status": {}, "trace_rate": 0.0},
               "backward": {"rows": [], "by_status": {}}}
        dpath = out_dir / "draft_auto.md"
        dpath.write_text(emit.draft_from_ledger(al0, cands0, case_raw) + "\n",
                         encoding="utf-8", newline="\n")
        info = finish(case_path, dpath, out_dir, lexicon, schema)
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0 if info["status"] == "complete" else 1

    if args.stage == "finish":
        info = finish(case_path, args.draft, out_dir, lexicon, schema)
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0 if info.get("status") == "complete" else 1

    # recheck
    need = [out_dir / n for n in ("candidates.json", "alignment.json", "gaps.json")]
    if not all(p.is_file() for p in need):
        print(json.dumps({"status": "blocked", "reason": "run finish first"}, ensure_ascii=False))
        return 2
    _cr, root, _cid = resolve_case(case_path)
    pack = M.read_material(root, skip_files=skip_set(root, out_dir))
    draft = (out_dir / "intro_related_work.md").read_text(encoding="utf-8") \
        if (out_dir / "intro_related_work.md").is_file() else ""
    cands = _read(out_dir / "candidates.json")
    al = _read(out_dir / "alignment.json")
    res = _read(out_dir / "result.json") if (out_dir / "result.json").is_file() else {}
    gp = gaps_mod.build(cands, al, pack, draft)
    rep = validate_mod.validate(cands, al, gp, pack, draft, res, schema)
    print(json.dumps({"status": rep["status"], "counts": rep["counts"],
                      "top": rep["top_failures"]}, ensure_ascii=False, indent=2))
    return 0 if rep["status"] in ("pass", "warn") else 1


if __name__ == "__main__":
    raise SystemExit(main())
