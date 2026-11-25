#!/usr/bin/env python3
"""Entry point: prepare -> (draft) -> finish.

    prepare  read materials, propose candidate mentions and edges, write
             parsed.json + candidates.json. No judgement yet.
    auto     build a draft from the candidates with rules only, then finish.
             Honest but low-recall: meant as a floor, not as the good path.
    finish   take a draft (model or human authored), assemble the graph, run the
             queries, gate the result, write the deliverables.
    queries  re-run the query set on an existing graph.json.

Exit codes: 0 pass, 1 partial/blocked (still writes an honest result), 2 bad input.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import align          # noqa: E402
import emit           # noqa: E402
import extract        # noqa: E402
import materials as M  # noqa: E402
import query as query_mod  # noqa: E402
import validate as validate_mod  # noqa: E402


def _read(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _blocked(out_dir: Path, reason: str, detail: str = "") -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {"case_id": None, "status": "blocked", "reason": reason,
               "detail": detail, "nodes": [], "edges": [], "queries": [],
               "uncertainty": [reason], "change_log": []}
    (out_dir / "result.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return payload


def prepare(case_path: Path, out_dir: Path, lexicon: dict, schema: dict,
            limit: int) -> dict:
    parsed = M.load_case(case_path)
    if not parsed["sources"]:
        return _blocked(out_dir, "no readable material",
                        "case 目录里既没有 material JSON，也没有可解析的 JATS XML")
    pack = extract.prepare(parsed, lexicon, schema, limit_per_source=limit)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, obj in (("parsed.json", pack), ("candidates.json", pack)):
        (out_dir / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n",
                                    encoding="utf-8", newline="\n")
    return {"status": "ok", "stats": pack["stats"],
            "sources": [s["source_id"] for s in pack["sources"]],
            "warnings": pack["warnings"]}


def draft_from_candidates(cands: dict, schema: dict) -> dict:
    """Rule-only draft. Everything it emits is checkable, nothing is inferred."""
    entities: dict[tuple, dict] = {}
    edges: list[dict] = []
    for e in cands["candidates"]["edges"]:
        for role in ("subject", "object"):
            surface = e[f"{role}_surface"]
            hint = e[f"{role}_type"]
            key = (e["source_id"], surface.lower(), hint)
            if key not in entities:
                entities[key] = {
                    "key": f"a{len(entities) + 1}",
                    "surface": surface,
                    "type": hint,
                    "source_id": e["source_id"],
                    "paragraph_id": e["paragraph_id"],
                    "quote": e["quote"],
                    "scope": "instance",
                }
        edges.append({
            "subject": entities[(e["source_id"], e["subject_surface"].lower(), e["subject_type"])]["key"],
            "predicate": e["relation"],
            "object": entities[(e["source_id"], e["object_surface"].lower(), e["object_type"])]["key"],
            "source_id": e["source_id"],
            "paragraph_id": e["paragraph_id"],
            "quote": e["quote"],
            "strength": e["strength"],
            "direction_basis": f"trigger {e['trigger']!r} ({e['dir']})",
        })
    return {"case_id": cands["case_id"], "entities": list(entities.values()), "edges": edges,
            "note": "rule-only draft (auto mode): high precision, low recall by design"}


def finish(draft_path: Path, out_dir: Path, schema: dict, cands: dict | None = None) -> dict:
    if cands is None:
        cands_path = out_dir / "candidates.json"
        if not cands_path.is_file():
            return _blocked(out_dir, "candidates missing", "先跑 --stage prepare")
        cands = _read(cands_path)
    draft = _read(draft_path) if draft_path else {}
    graph = align.build_graph(draft, cands, schema)
    queries = query_mod.run_queries(graph, draft.get("queries_spec"))
    report = validate_mod.validate(graph, cands, schema, queries, draft)
    status = "complete" if report["status"] == "pass" else "partial"
    result = emit.build_result(cands["case_id"], cands, graph, queries, report, status)
    result = emit.finalise(cands.get("case_raw") or {}, result)
    written = emit.write_all(out_dir, result, graph, queries, report)
    return {"status": status, "validation": report["status"], "counts": report["counts"],
            "top_failures": report["top_failures"],
            "graph": graph["stats"], "queries": queries["summary"], "written": written}


def main() -> int:
    ap = argparse.ArgumentParser(description="文献知识图谱：prepare / auto / finish")
    ap.add_argument("--case", required=True, help="case.json 或材料目录")
    ap.add_argument("--lexicon", required=True)
    ap.add_argument("--schema", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--stage", choices=["prepare", "auto", "finish", "queries"], default="auto")
    ap.add_argument("--draft", help="finish 阶段的草稿 JSON")
    ap.add_argument("--limit", type=int, default=40, help="每篇最多保留多少条候选关系")
    args = ap.parse_args()

    case_path = Path(args.case)
    out_dir = Path(args.out)
    lexicon = _read(args.lexicon)
    schema = _read(args.schema)

    if args.stage == "prepare":
        info = prepare(case_path, out_dir, lexicon, schema, args.limit)
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0 if info["status"] == "ok" else 2

    if args.stage == "auto":
        info = prepare(case_path, out_dir, lexicon, schema, args.limit)
        if info["status"] != "ok":
            print(json.dumps(info, ensure_ascii=False, indent=2))
            return 2
        draft = draft_from_candidates(_read(out_dir / "candidates.json"), schema)
        dpath = out_dir / "draft_auto.json"
        dpath.write_text(json.dumps(draft, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8", newline="\n")
        info = finish(dpath, out_dir, schema)
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0 if info["status"] == "complete" else 1

    if args.stage == "finish":
        info = finish(Path(args.draft) if args.draft else None, out_dir, schema)
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0 if info.get("status") == "complete" else 1

    # queries stage
    graph_path = out_dir / "graph.json"
    if not graph_path.is_file():
        print(json.dumps({"status": "blocked", "reason": "graph.json missing"}, ensure_ascii=False))
        return 2
    g = _read(graph_path)
    res = query_mod.run_queries(g)
    (out_dir / "queries.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(res["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
