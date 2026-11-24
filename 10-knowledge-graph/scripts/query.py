#!/usr/bin/env python3
"""Run real queries over the assembled graph.

A query is "real" here only if it walks the graph and returns the ids and the
evidence it used. The `insufficient_evidence` status is a first-class result:
a graph that cannot answer must say so instead of producing a plausible string.
"""

from __future__ import annotations

import json
import re
from collections import deque
from typing import Any

import materials as M


def _index(graph: dict) -> dict:
    nodes = {n["id"]: n for n in graph["nodes"]}
    by_label: dict[str, list[str]] = {}
    for n in graph["nodes"]:
        for name in [n["label"]] + list(n.get("aliases") or []):
            by_label.setdefault(M.norm_key(name), []).append(n["id"])
    incident: dict[str, list[dict]] = {}
    for e in graph["edges"]:
        incident.setdefault(e["subject"], []).append(e)
        incident.setdefault(e["object"], []).append(e)
    return {"nodes": nodes, "by_label": by_label, "incident": incident}


def find_nodes(ix: dict, name: str) -> list[str]:
    """All nodes carrying this name. A term can legitimately exist once per paper."""
    ids = ix["by_label"].get(M.norm_key(name)) or []
    return sorted(set(ids), key=lambda i: (ix["nodes"][i]["identity_scope"] != "product",
                                          ix["nodes"][i]["label"].lower(), i))


def find_node(ix: dict, name: str) -> str | None:
    ids = find_nodes(ix, name)
    return ids[0] if ids else None


def entity_profile(graph: dict, ix: dict, name: str) -> dict:
    ids = find_nodes(ix, name)
    if not ids:
        return {"status": "insufficient_evidence",
                "answer": f"图谱中没有与 {name!r} 对应的节点。",
                "limitations": ["该名称未在本次材料中被抽取为实体；不代表原文没有提到。"]}
    edges, evidence, per_node = [], [], []
    for nid in ids:
        node = ix["nodes"][nid]
        own = ix["incident"].get(nid, [])
        edges.extend(own)
        evidence.extend(node.get("evidence", []))
        per_node.append(f"{node['label']}（{node['type']}，{node['identity_scope']}，"
                        f"来源 {','.join(node['source_ids'])}）{len(own)} 条关系")
    limitations = []
    if len(ids) > 1:
        limitations.append(f"同名节点有 {len(ids)} 个，分属不同论文，未合并；上面的关系统计是它们的并集。")
    if not edges:
        limitations.append("节点存在但没有已抽取的关系。")
    return {
        "status": "answered" if edges else "partial",
        "answer": "；".join(per_node),
        "node_ids": ids,
        "edge_ids": [e["id"] for e in edges],
        "evidence": evidence,
        "limitations": limitations,
    }


def path_query(graph: dict, ix: dict, a: str, b: str, max_hops: int = 3) -> dict:
    starts, goals = find_nodes(ix, a), find_nodes(ix, b)
    if not starts or not goals:
        missing = [x for x, s in ((a, starts), (b, goals)) if not s]
        return {"status": "insufficient_evidence",
                "answer": f"缺少节点：{', '.join(missing)}",
                "limitations": ["端点不在图谱中，无法给出路径。"]}
    goals = set(goals)
    sa = starts[0]
    sb = next(iter(goals))
    prev: dict[str, tuple[str, dict]] = {x: ("", {}) for x in starts}
    q = deque([(x, 0) for x in starts])
    found = False
    while q and not found:
        cur, depth = q.popleft()
        if depth >= max_hops:
            continue
        for e in ix["incident"].get(cur, []):
            nxt = e["object"] if e["subject"] == cur else e["subject"]
            if nxt in prev:
                continue
            prev[nxt] = (cur, e)
            if nxt in goals:
                sb = nxt
                found = True
                break
            q.append((nxt, depth + 1))
    if not found:
        return {"status": "insufficient_evidence",
                "answer": f"{a} 与 {b} 之间在 {max_hops} 跳内没有证据路径。",
                "limitations": ["两篇论文未把这两个对象在同一断言中联系起来；共现不等于关系。"]}
    chain, cur = [], sb
    while prev[cur][0]:
        parent, edge = prev[cur]
        chain.append(edge)
        cur = parent
    chain.reverse()
    sa = cur
    render, cur = [ix["nodes"][sa]["label"]], sa
    for e in chain:
        nxt = e["object"] if e["subject"] == cur else e["subject"]
        render.append(f"-{e['predicate']}-> {ix['nodes'][nxt]['label']}")
        cur = nxt
    return {
        "status": "answered",
        "answer": " ".join(render),
        "node_ids": [sa, sb],
        "edge_ids": [e["id"] for e in chain],
        "evidence": [ev for e in chain for ev in e.get("evidence", [])],
        "limitations": [] if all(e["strength"]["class"] != "hypothesis" for e in chain)
        else ["路径中有推测性证据，不能当作已确立的机制。"],
    }


def method_comparison(graph: dict, ix: dict, phenomenon: str) -> dict:
    pids = find_nodes(ix, phenomenon)
    if not pids:
        return {"status": "insufficient_evidence", "answer": f"没有 {phenomenon!r} 节点。",
                "limitations": ["现象未被抽取，无法比较方法。"]}
    methods: dict[str, dict] = {}
    for pid in pids:
        for e in ix["incident"].get(pid, []):
            if e["predicate"] in {"APPLIES_METHOD", "TARGETS"}:
                mid = e["object"] if e["subject"] == pid else e["subject"]
                node = ix["nodes"].get(mid)
                if node and node["type"] == "METHOD":
                    rec = methods.setdefault(mid, {"method": node["label"], "edges": [],
                                                   "scope": node["identity_scope"],
                                                   "values": [], "value_edges": [], "sources": []})
                    rec["edges"].append(e["id"])
                    rec["sources"] = sorted(set(rec["sources"]) |
                                            {ev["source_id"] for ev in e.get("evidence", [])})
    if not methods:
        return {"status": "insufficient_evidence",
                "answer": f"图谱中没有把方法与 {phenomenon!r} 连起来的断言。",
                "limitations": ["抽取到的关系不足以回答方法比较。"]}
    for mid, rec in methods.items():
        for e in ix["incident"].get(mid, []):
            if e["predicate"] == "ACHIEVES":
                rec["values"].append(e["object_label"])
                rec["value_edges"].append(e["id"])
                rec["sources"] = sorted(set(rec["sources"]) | {ev["source_id"] for ev in e.get("evidence", [])})
    comparable, why = True, []
    source_sets = {m: tuple(rec["sources"]) for m, rec in methods.items()}
    if len(set(source_sets.values())) > 1:
        comparable = False
        why.append("各方法的结果来自不同论文，观测时段、地点与数据划分未统一，不能直接排名。")
    if any(not rec["values"] for rec in methods.values()):
        comparable = False
        why.append("至少一个方法没有可核验的数值结果。")
    return {
        "status": "answered" if methods else "partial",
        "answer": "；".join(f"{rec['method']} 报告 {', '.join(rec['values']) or '无数值'}" for rec in methods.values()),
        "comparable": comparable,
        "not_comparable_because": why,
        "node_ids": pids + list(methods),
        "edge_ids": [eid for rec in methods.values() for eid in rec["edges"] + rec["value_edges"]],
        "evidence": [ev for e in graph["edges"] if e["id"] in
                     {x for rec in methods.values() for x in rec["edges"] + rec["value_edges"]}
                     for ev in e.get("evidence", [])],
        "limitations": why,
    }


def conflict_query(graph: dict) -> dict:
    conflicts = graph.get("conflicts") or []
    pending = graph.get("candidate_alignments") or []
    if not conflicts and not pending:
        return {"status": "answered", "answer": "没有记录到冲突或未决合并。",
                "node_ids": [], "edge_ids": [], "evidence": [],
                "limitations": ["未记录不等于不存在：只说明已抽取的断言之间没有发现冲突。"]}
    parts = [f"{len(conflicts)} 条冲突"]
    if conflicts:
        parts.append("涉及：" + "、".join(sorted({c.get("subject_label") or c["subject"]
                                                  for c in conflicts})))
    if pending:
        parts.append(f"{len(pending)} 组同名未合并：" +
                     "、".join(sorted({f"{c['a']['surface']}（{c['a']['source_id']} / {c['b']['source_id']}）"
                                       for c in pending})))
    return {
        "status": "answered",
        "answer": "；".join(parts),
        "node_ids": sorted({c["subject"] for c in conflicts}),
        "edge_ids": [],
        "evidence": [s for c in conflicts for s in c.get("sides", [])],
        "conflicts": conflicts,
        "candidate_alignments": pending,
        "limitations": [],
    }


def negative_query(graph: dict, ix: dict, question: str) -> dict:
    """Answer only if the question's terms exist; otherwise say it cannot be answered."""
    words = re.findall(r"[a-z0-9]{4,}", question.lower())
    vocab = set()
    for n in graph["nodes"]:
        vocab |= set(re.findall(r"[a-z0-9]{4,}", n["label"].lower()))
    overlap = [w for w in words if w in vocab]
    if overlap:
        return {"status": "partial",
                "answer": f"问题涉及图谱中已有的词 {overlap}，但这属于开放问题，图谱只记录了材料中的断言。",
                "limitations": ["需要人工读取原文或补充材料才能回答。"]}
    return {"status": "insufficient_evidence",
            "answer": "材料中没有支持该问题的断言。",
            "limitations": ["图谱不含该问题的实体或时段；不据此推断，也不补造数据。"]}


def default_spec(graph: dict) -> list[dict]:
    """Three queries that any two-paper graph should be able to attempt."""
    deg: dict[str, int] = {}
    for e in graph["edges"]:
        for x in (e["subject"], e["object"]):
            deg[x] = deg.get(x, 0) + 1
    nodes = {n["id"]: n for n in graph["nodes"]}
    phenomena = [n for n in graph["nodes"] if n["type"] == "PHENOMENON"]
    methods = [n for n in graph["nodes"] if n["type"] == "METHOD"]
    phenomena.sort(key=lambda n: -deg.get(n["id"], 0))
    methods.sort(key=lambda n: -deg.get(n["id"], 0))
    spec = []
    if phenomena:
        spec.append({"id": "Q1", "type": "method_comparison",
                     "question": f"哪些方法被用于 {phenomena[0]['label']}，各自报告了什么结果？",
                     "phenomenon": phenomena[0]["label"]})
    if len(methods) >= 1 and phenomena:
        spec.append({"id": "Q2", "type": "path",
                     "question": f"{methods[0]['label']} 与 {phenomena[0]['label']} 之间有什么证据链？",
                     "a": methods[0]["label"], "b": phenomena[0]["label"]})
    spec.append({"id": "Q3", "type": "conflicts",
                 "question": "两篇论文之间有哪些冲突结论或未决的同名合并？"})
    spec.append({"id": "Q4", "type": "negative",
                 "question": "研究时段之后（例如 2025 年）该区域的海雾频率是多少？"})
    if phenomena:
        spec.append({"id": "Q5", "type": "entity_profile",
                     "question": f"{phenomena[0]['label']} 在材料中有哪些证据？",
                     "name": phenomena[0]["label"]})
    return spec


def run_queries(graph: dict, spec: list[dict] | None = None) -> dict:
    ix = _index(graph)
    spec = spec or default_spec(graph)
    out = []
    for q in spec:
        qtype = q.get("type")
        if qtype == "entity_profile":
            res = entity_profile(graph, ix, q.get("name", ""))
        elif qtype == "path":
            res = path_query(graph, ix, q.get("a", ""), q.get("b", ""), int(q.get("max_hops", 3)))
        elif qtype == "method_comparison":
            res = method_comparison(graph, ix, q.get("phenomenon", ""))
        elif qtype == "conflicts":
            res = conflict_query(graph)
        elif qtype == "negative":
            res = negative_query(graph, ix, q.get("question", ""))
        else:
            res = {"status": "insufficient_evidence", "answer": f"未知查询类型 {qtype}",
                   "limitations": ["查询模板未实现，未返回任何结果。"]}
        out.append({"id": q.get("id"), "question": q.get("question"), "type": qtype,
                    **res,
                    "node_ids": res.get("node_ids", []),
                    "edge_ids": res.get("edge_ids", []),
                    "evidence": (res.get("evidence") or [])[:20]})
    return {
        "queries": out,
        "summary": {
            "total": len(out),
            "answered": sum(1 for q in out if q["status"] == "answered"),
            "partial": sum(1 for q in out if q["status"] == "partial"),
            "insufficient_evidence": sum(1 for q in out if q["status"] == "insufficient_evidence"),
        },
    }


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="在已构建的图谱上执行查询")
    ap.add_argument("--graph", required=True)
    ap.add_argument("--spec")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    g = json.loads(__import__("pathlib").Path(args.graph).read_text(encoding="utf-8"))
    spec = json.loads(__import__("pathlib").Path(args.spec).read_text(encoding="utf-8")) if args.spec else None
    res = run_queries(g, spec.get("queries") if isinstance(spec, dict) else spec)
    __import__("pathlib").Path(args.out).write_text(json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(res["summary"], ensure_ascii=False))
