#!/usr/bin/env python3
"""Quality gate. Runs before anything is exported.

Every check returns a code, a plain-language reason and a fix. A failed check is
not deleted from the output: it stays attached to the item so a reader can see
what is weak, which is the difference between "partial" and "looks complete".
"""

from __future__ import annotations

import json
import re
from typing import Any

import materials as M

DIRECTIONAL = {"APPLIES_METHOD", "TARGETS", "EVALUATES", "ACHIEVES", "CAUSES",
               "IMPROVES_ON", "OCCURS_AT", "OBSERVED_DURING", "MEASURED_BY", "PART_OF"}
REVERSE_HINT = re.compile(
    r"\b(due to|caused by|as a result of|attributable to|attributed to|driven by|because of|"
    r"formed by|result(?:s|ed)? from)\b", re.I)
# Predicates whose direction is carried by a verb: position relative to that verb
# is what decides. For the rest (a value listed before its model, a method named
# after its target in passive voice) linear order carries no information.
ACTIVE = {
    "CAUSES": re.compile(r"\b(lead(?:s|ing)? to|led to|result(?:s|ing)? in|resulted in|caus(?:e|es|ed|ing)|"
                         r"trigger(?:s|ed|ing)?|induc(?:e|es|ed|ing))\b", re.I),
    "IMPROVES_ON": re.compile(r"\b(outperform(?:s|ed)?|better than|superior to|improv(?:e|es|ed) (?:on|over))\b", re.I),
}
PASSIVE = {
    "CAUSES": REVERSE_HINT,
    "IMPROVES_ON": re.compile(r"\b(worse than|inferior to|outperformed by)\b", re.I),
}
OWN_VOICE = re.compile(r"\b(we|our|in this study|this study|the present study)\b", re.I)
CITATION = re.compile(r"\[\d{1,3}(?:[,\-]\d{1,3})*\]")
ELIDE = re.compile(r"…|\.\.\.")


def _ok(code: str = "ok", detail: str = "", **extra) -> dict:
    return {"ok": True, "code": code, "detail": detail, "fix": "", **extra}


def _bad(code: str, detail: str, fix: str, severity: str = "fail", **extra) -> dict:
    return {"ok": False, "code": code, "detail": detail, "fix": fix, "severity": severity, **extra}


def match_quote(quote: str, text: str) -> dict:
    """Is the quote verbatim in the paragraph? Ellipses split it into fragments."""
    q = M.norm_text(quote)
    t = M.norm_text(text)
    if not q:
        return {"ok": False, "contiguous": False, "fragments": 0}
    frags = [f.strip() for f in ELIDE.split(q) if f.strip()]
    pos, spans = 0, []
    for frag in frags:
        idx = t.find(frag, pos)
        if idx < 0:
            return {"ok": False, "contiguous": False, "fragments": len(frags), "missing": frag[:80]}
        spans.append((idx, idx + len(frag)))
        pos = idx + len(frag)
    return {
        "ok": True,
        "contiguous": len(frags) == 1,
        "fragments": len(frags),
        "char_span": [spans[0][0], spans[-1][1]],
    }


def _has_page_key(obj: Any) -> list[str]:
    """Any evidence-shaped dict carrying `page` violates the 'no invented page' rule."""
    hits: list[str] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(k, str) and k.lower() in {"page", "page_number", "page_num", "pdf_page"}:
                    hits.append(path or "root")
                walk(v, f"{path}/{k}" if path else k)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    walk(obj, "")
    return hits


def validate(graph: dict, parsed: dict, schema: dict, queries: dict | None = None,
             draft: dict | None = None) -> dict:
    idx = M.paragraph_index(parsed)
    node_by_id = {n["id"]: n for n in graph["nodes"]}
    item_nodes, item_edges = [], []
    known_types = set(schema["entity_types"])
    relations = schema["relation_types"]

    # ------------------------------------------------------------------ nodes
    for n in graph["nodes"]:
        checks: dict[str, dict] = {}
        evs = n.get("evidence") or []
        checks["evidence_present"] = (
            _ok() if evs else _bad("missing_evidence", "节点没有任何证据",
                                   "补一段原文短引并写明 source_id 与 paragraph_id")
        )
        bad_paras, label_seen = [], False
        for ev in evs:
            key = (ev.get("source_id"), ev.get("paragraph_id"))
            para = idx.get(key)
            if not para:
                bad_paras.append(f"{key[0]}/{key[1]}")
                continue
            if n["label"].lower() in para["text"].lower():
                label_seen = True
        checks["paragraph_exists"] = (
            _ok() if not bad_paras else _bad("paragraph_not_found",
                                             f"段落不存在：{', '.join(bad_paras[:4])}",
                                             "核对 paragraph_id 是否来自 material.json")
        )
        checks["label_in_source"] = (
            _ok() if (label_seen or not evs) else _bad(
                "label_not_in_source", f"节点名 {n['label']!r} 未出现在所引段落中",
                "改回原文的写法，或用 aliases 记录别名", severity="warn")
        )
        checks["type_known"] = (
            _ok() if n["type"] in known_types else _bad(
                "unknown_type", f"类型 {n['type']} 不在 schema 中", "改用 schema.json 里的类型")
        )
        checks["no_page_field"] = (
            _ok() if not _has_page_key(evs) else _bad(
                "invented_page", "证据里出现 page 字段",
                "本题位置只允许 source_id + paragraph_id；删除 page")
        )
        verdict = "fail" if any(not c["ok"] and c.get("severity", "fail") == "fail" for c in checks.values()) \
            else ("warn" if any(not c["ok"] for c in checks.values()) else "pass")
        item_nodes.append({"id": n["id"], "kind": "node", "label": n["label"],
                           "type": n["type"], "verdict": verdict, "checks": checks})

    # ------------------------------------------------------------------ edges
    for e in graph["edges"]:
        checks: dict[str, dict] = {}
        evs = e.get("evidence") or []
        pred = e["predicate"]
        s_node, o_node = node_by_id.get(e["subject"]), node_by_id.get(e["object"])

        checks["evidence_present"] = (
            _ok() if evs else _bad("missing_evidence", "边没有证据", "补原文短引")
        )
        checks["predicate_known"] = (
            _ok() if pred in relations else _bad("unknown_predicate", f"关系 {pred} 不在 schema 中",
                                                 "改用 schema 里的具体动词，不要用 RELATED_TO")
        )
        if not s_node or not o_node:
            checks["endpoints"] = _bad("dangling_edge", "边指向不存在的节点", "重建节点表")
        else:
            dom = set(relations.get(pred, {}).get("domain", []))
            rng = set(relations.get(pred, {}).get("range", []))
            ok_types = ("*" in dom or not dom or s_node["type"] in dom) and \
                       ("*" in rng or not rng or o_node["type"] in rng)
            checks["signature"] = (
                _ok() if ok_types else _bad(
                    "type_mismatch",
                    f"{s_node['type']} -> {o_node['type']} 不符合 {pred} 的定义域/值域",
                    "改关系类型，或把节点类型改对")
            )
            checks["self_loop"] = (
                _bad("self_loop", "主语宾语为同一节点", "删除该边") if e["subject"] == e["object"] else _ok()
            )

        best = None
        for ev in evs:
            para = idx.get((ev.get("source_id"), ev.get("paragraph_id")))
            if not para:
                continue
            m = match_quote(ev.get("quote", ""), para["text"])
            if m["ok"] and (best is None or m.get("char_span", [0])[0] < best["char_span"][0]):
                best = {**m, "ev": ev, "para": para}
        if best is None:
            checks["quote_verbatim"] = _bad(
                "evidence_drift",
                "引文在所引段落中找不到（逐字比对失败）",
                "从该段落复制原文，不要改写；跨句时用 … 分开且每段都要逐字")
        else:
            checks["quote_verbatim"] = _ok(detail=f"命中 {best['para']['paragraph_id']}",
                                           char_span=best["char_span"],
                                           contiguous=best["contiguous"])
            quote = M.norm_text(best["ev"].get("quote", ""))
            para_text = best["para"]["text"]
            def first_pos(node: dict | None) -> int:
                """Position of any declared name of the node (label or alias)."""
                if not node:
                    return -1
                names = [node.get("label", "")] + list(node.get("aliases") or [])
                pos = [quote.lower().find(x.lower()) for x in names if x]
                pos = [p for p in pos if p >= 0]
                return min(pos) if pos else -1

            si, oi = first_pos(s_node), first_pos(o_node)
            active = ACTIVE.get(pred)
            passive = PASSIVE.get(pred)
            if si < 0 or oi < 0:
                checks["direction"] = _bad(
                    "endpoint_not_in_quote",
                    "主语或宾语的写法（含别名）没有出现在引文里",
                    "引文补全到同时包含两端；或把节点名改成原文写法", severity="warn")
            elif passive is not None and passive.search(quote):
                ok = si > oi if pred == "CAUSES" else si < oi
                checks["direction"] = (
                    _ok(detail="passive trigger: cause follows effect") if ok else
                    _bad("direction_error", "被动触发词表明因果顺序与本条相反",
                         "把主语与宾语对调；'caused by / attributed to' 后面才是原因"))
            elif active is not None and active.search(quote):
                ok = si < oi
                checks["direction"] = (
                    _ok(detail="active trigger: subject precedes object") if ok else
                    _bad("direction_error", "主动触发词表明主宾顺序与本条相反",
                         "核对主语与宾语；必要时对调"))
            elif pred in DIRECTIONAL:
                checks["direction"] = _ok(
                    detail="两端同句出现；该关系由触发词而非线性顺序承载，未作顺序判定")
            else:
                checks["direction"] = _ok(detail="symmetric or record-level relation")

            # strength must follow the evidence, not the author's wish
            st = e.get("strength") or {}
            # A citation marker attached to a tool version ("WRF (v.3.9.1.1: [24])")
            # credits the tool, not the claim. First-person voice wins.
            cited = (bool(CITATION.search(quote)) or bool(
                re.search(r"\b(reported by|previous stud|et al\.)\b", quote, re.I))) \
                and not OWN_VOICE.search(quote)
            if cited and st.get("class") in {"own_result", "own_method"}:
                checks["strength"] = _bad(
                    "strength_overclaim",
                    "引文含引用标记，却标成本文结果",
                    "改为 cited，attribution 设为 cited_work")
            elif st.get("class") not in schema["evidence_strength"]:
                checks["strength"] = _bad("strength_unknown", f"证据强度 {st.get('class')} 未定义",
                                          "使用 schema 中定义的强度类")
            else:
                checks["strength"] = _ok(detail=f"{st.get('class')} ({st.get('weight')})")

            # a reported number must exist in the quote
            if o_node and o_node["type"] == "VALUE":
                nums = re.findall(r"\d+(?:\.\d+)?", o_node.get("label", ""))
                missing = [x for x in nums if x not in quote]
                checks["numeric_grounded"] = (
                    _ok() if not missing else _bad(
                        "fabricated_number", f"数值 {missing} 不在引文中",
                        "只写引文里出现的数字，或把引文补到包含该数字")
                )
            checks["no_page_field"] = (
                _ok() if not _has_page_key(evs) else _bad(
                    "invented_page", "证据里出现 page 字段", "删除 page，只保留 paragraph_id")
            )

        verdict = "fail" if any(not c["ok"] and c.get("severity", "fail") == "fail" for c in checks.values()) \
            else ("warn" if any(not c["ok"] for c in checks.values()) else "pass")
        item_edges.append({"id": e["id"], "kind": "edge",
                           "label": f"{e.get('subject_label')} -{pred}-> {e.get('object_label')}",
                           "verdict": verdict, "checks": checks})

    # ------------------------------------------------------------ graph level
    graph_checks: dict[str, dict] = {}
    merges = graph.get("merges") or []
    prod_multi = [n for n in graph["nodes"]
                  if n.get("identity_scope") == "product" and len(n.get("source_ids", [])) > 1]
    graph_checks["product_merge_recorded"] = (
        _ok() if all(any(m["node_id"] == n["id"] for m in merges) for n in prod_multi) else _bad(
            "unrecorded_merge", "有跨篇产品级节点没有对应合并记录", "为每个跨篇合并写 basis")
    )
    # same label, different ids, different sources -> must be an explained decision
    label_groups: dict[str, set] = {}
    for n in graph["nodes"]:
        label_groups.setdefault(n["label"].lower(), set()).add(tuple(n.get("source_ids", [])))
    split_labels = [lab for lab, srcs in label_groups.items() if len(srcs) > 1]
    explained = {c["a"]["surface"].lower() for c in graph.get("candidate_alignments", [])} | \
                {t["surface"].lower() for t in graph.get("type_conflicts", [])}
    unexplained = [x for x in split_labels if x not in explained]
    graph_checks["split_identity_explained"] = (
        _ok() if not unexplained else _bad(
            "unexplained_split", f"同名节点跨篇未合并且无记录：{unexplained[:4]}",
            "补 candidate_alignments 或 merge 记录，说明为什么不合并")
    )

    # divergent values must surface as a conflict record
    # same grouping rule as the detector: conditions are part of the claim
    by_pair: dict[tuple, set] = {}
    for e in graph["edges"]:
        if e["predicate"] in {"ACHIEVES", "CAUSES", "DEFINED_AS"}:
            key = (e["subject"], e["predicate"], tuple(sorted(e.get("conditions") or [])))
            by_pair.setdefault(key, set()).add(e["object"])
    need = [k for k, v in by_pair.items() if len(v) > 1]
    have = {(c["subject"], c["predicate"], tuple(sorted(c.get("conditions") or [])))
            for c in graph.get("conflicts", [])}
    graph_checks["conflict_recorded"] = (
        _ok() if all(k in have for k in need) else _bad(
            "missing_conflict", f"有 {len([k for k in need if k not in have])} 组不同结果未记为冲突",
            "为每组并列保留两条边，并写 conflict 记录")
    )

    if queries is not None:
        qs = queries.get("queries") or []
        ok_q = [q for q in qs if q.get("status") in {"answered", "partial", "insufficient_evidence"}]
        graph_checks["queries_executed"] = (
            _ok() if len(ok_q) >= 3 else _bad(
                "queries_missing", f"实际执行且带状态的查询只有 {len(ok_q)} 个（要求 ≥3）",
                "执行至少 3 个查询并记录状态与证据")
        )
        dangling_q = []
        edge_ids = {e["id"] for e in graph["edges"]}
        node_ids = {n["id"] for n in graph["nodes"]}
        for q in ok_q:
            for rid in q.get("edge_ids", []):
                if rid not in edge_ids:
                    dangling_q.append((q.get("id"), rid))
            for rid in q.get("node_ids", []):
                if rid not in node_ids:
                    dangling_q.append((q.get("id"), rid))
        graph_checks["query_results_exist"] = (
            _ok() if not dangling_q else _bad(
                "query_dangling", f"查询结果引用了不存在的元素：{dangling_q[:3]}",
                "查询只能返回图里真实存在的节点与边")
        )

    if draft is not None:
        drops = graph.get("dropped") or []
        graph_checks["draft_fully_used"] = (
            _ok() if not drops else _bad(
                "dropped_items", f"{len(drops)} 条草稿条目未能进入图谱",
                "查看 dropped 的原因，补实体或修正引用", severity="warn")
        )

    all_items = item_nodes + item_edges
    counts = {"pass": sum(1 for i in all_items if i["verdict"] == "pass"),
              "warn": sum(1 for i in all_items if i["verdict"] == "warn"),
              "fail": sum(1 for i in all_items if i["verdict"] == "fail")}
    fails = [c["code"] for i in all_items for c in i["checks"].values() if not c["ok"]]
    from collections import Counter
    top = Counter(fails).most_common(8)
    graph_fail = [k for k, v in graph_checks.items() if not v["ok"] and v.get("severity", "fail") == "fail"]
    status = "fail" if (counts["fail"] or graph_fail) else ("warn" if counts["warn"] else "pass")

    return {
        "status": status,
        "counts": counts,
        "n_assertions": len(all_items),
        "top_failures": [{"code": c, "count": n} for c, n in top],
        "graph_checks": graph_checks,
        "items": all_items,
        "summary": {
            "nodes_pass_rate": round(counts["pass"] / max(1, len(all_items)), 4),
            "graph_checks_passed": sum(1 for v in graph_checks.values() if v["ok"]),
            "graph_checks_total": len(graph_checks),
        },
    }


def main() -> int:
    """CLI: re-check an existing graph.json without rebuilding it."""
    import argparse
    import json as _json
    from pathlib import Path as _Path
    ap = argparse.ArgumentParser(description="复检已生成的图谱")
    ap.add_argument("--graph", required=True)
    ap.add_argument("--case", required=True)
    ap.add_argument("--schema", required=True)
    ap.add_argument("--queries", help="已有 queries.json（可选）")
    ap.add_argument("--out", help="把报告写到这里（可选）")
    args = ap.parse_args()
    graph = _json.loads(_Path(args.graph).read_text(encoding="utf-8"))
    parsed = M.load_case(_Path(args.case))
    schema = _json.loads(_Path(args.schema).read_text(encoding="utf-8"))
    queries = _json.loads(_Path(args.queries).read_text(encoding="utf-8")) if args.queries else None
    report = validate(graph, parsed, schema, queries)
    if args.out:
        _Path(args.out).write_text(_json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                   encoding="utf-8", newline="\n")
    print(_json.dumps({"status": report["status"], "counts": report["counts"],
                       "top_failures": report["top_failures"]}, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
