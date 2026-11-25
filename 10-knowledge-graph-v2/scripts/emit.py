#!/usr/bin/env python3
"""Write the deliverables: result.json, graph.json, queries.json, validation.json
plus a readable mermaid view and two flat CSV tables.

Everything here is a pure function of (graph, queries, validation, parsed), so
two runs over the same input produce byte-identical files. That property is what
lets a reviewer diff two attempts instead of trusting a description.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import contract


def _csv_rows(nodes: list[dict], edges: list[dict]) -> tuple[list[list[str]], list[list[str]]]:
    n_rows = [["node_id", "label", "type", "identity_scope", "source_ids", "aliases", "n_evidence"]]
    for n in nodes:
        n_rows.append([n["id"], n["label"], n["type"], n["identity_scope"],
                       ";".join(n.get("source_ids") or []), ";".join(n.get("aliases") or []),
                       str(len(n.get("evidence") or []))])
    e_rows = [["edge_id", "subject", "predicate", "object", "source_id", "paragraph_id",
               "strength", "weight", "attribution", "quote"]]
    for e in edges:
        ev = (e.get("evidence") or [{}])[0]
        st = e.get("strength") or {}
        e_rows.append([e["id"], e.get("subject_label") or "", e["predicate"],
                       e.get("object_label") or "", str(ev.get("source_id") or ""),
                       str(ev.get("paragraph_id") or ""), str(st.get("class") or ""),
                       str(st.get("weight") or ""), str(st.get("attribution") or ""),
                       str(ev.get("quote") or "")])
    return n_rows, e_rows


def _mermaid(graph: dict, limit: int = 45) -> str:
    nodes = {n["id"]: n for n in graph["nodes"]}
    keep: set[str] = set()
    lines = ["graph LR"]
    for n in graph["nodes"][:limit]:
        keep.add(n["id"])
        label = n["label"].replace('"', "'")
        shape = {"PHENOMENON": "([{}])", "METHOD": "[{}]", "DATASET": "[({})]",
                 "VARIABLE": "({})", "LOCATION": "[[{}]]", "TIME_PERIOD": "{{{}}}",
                 "VALUE": "(({}))"}.get(n["type"], "[{}]")
        lines.append(f'  {n["id"]}[{shape.format(label)}]:::{n["type"]}')
    for e in graph["edges"]:
        if e["subject"] in keep and e["object"] in keep:
            lines.append(f'  {e["subject"]} -->|{e["predicate"]}| {e["object"]}')
    types = sorted({n["type"] for n in graph["nodes"]})
    for t in types:
        lines.append(f"  classDef {t} fill:#eef2f7,stroke:#4a6fa5,color:#10243d;")
    return "\n".join(lines) + "\n"


def build_result(case_id: str, parsed: dict, graph: dict, queries: dict,
                 report: dict, status: str) -> dict:
    total_paras = sum(len(s["paragraphs"]) for s in parsed["sources"])
    used_paras = {ev["paragraph_id"] for e in graph["edges"] for ev in e.get("evidence") or []
                  if ev.get("paragraph_id")}
    uncertainty: list[str] = list(parsed.get("warnings") or [])

    if graph.get("candidate_alignments"):
        uncertainty.append(
            f"{len(graph['candidate_alignments'])} 组同名实体跨篇未合并：缺共同标识符，属有意保留。")
    if graph.get("conflicts"):
        uncertainty.append(
            f"{len(graph['conflicts'])} 条冲突结论并列保留，未取平均，也未选边。")
    if graph.get("dropped"):
        uncertainty.append(f"{len(graph['dropped'])} 条草稿条目未进入图谱，原因见 dropped。")
    uncertainty.append(
        f"关系覆盖：{len(used_paras)}/{total_paras} 段提供了至少一条关系证据；"
        "未覆盖段落不代表没有信息，只代表本轮没有抽出可校验的断言。")
    uncertainty.append(
        "材料为 JATS 正文，行内公式与上下标已线性化；未提供图像像素、补充附件与底层实验数据，"
        "相关数值不作推断。")
    for q in queries.get("queries") or []:
        for lim in q.get("limitations") or []:
            uncertainty.append(f"查询 {q.get('id')} 的限制：{lim}")

    manifest_role = {str(m.get("source_id")): m.get("role", "primary")
                     for m in (parsed.get("manifest") or []) if isinstance(m, dict)}
    change_log = [{"action": "load", "source_id": s["source_id"],
                   "role": manifest_role.get(s["source_id"], s.get("role", "primary")),
                   "paragraphs": len(s["paragraphs"]),
                   "generated_ids": sum(1 for p in s["paragraphs"] if p["id_source"] == "generated")}
                  for s in parsed["sources"]]
    change_log.append({
        "action": "incremental_note",
        "detail": ("节点 id 为内容哈希（type+canonical surface+source），后加入的论文不会重排既有节点编号；"
                   "secondary 材料作为增量：其新增节点/边带新 source_id，跨篇合并与不合并分别写入 merges 与 candidate_alignments。"),
    })
    change_log += [{"action": "merge", "node_id": m.get("node_id"),
                    "label": m.get("label") or " / ".join(m.get("surfaces") or []),
                    "basis": m.get("basis"),
                    "identity_scope": m.get("identity_scope", "instance")}
                   for m in graph.get("merges") or []]
    change_log += [{"action": "keep_separate", "surface": c["a"]["surface"],
                    "sources": [c["a"]["source_id"], c["b"]["source_id"]],
                    "reason": c["reason"]} for c in graph.get("candidate_alignments") or []]
    change_log += [{"action": "conflict_kept", "conflict_id": c["id"], "kind": c["kind"],
                    "subject": c.get("subject_label")} for c in graph.get("conflicts") or []]
    change_log += [{"action": "drop_draft_item", "reason": d["reason"]}
                   for d in graph.get("dropped") or []]
    change_log += [{"action": "query", "id": q.get("id"), "status": q.get("status")}
                   for q in queries.get("queries") or []]

    result = {
        "case_id": case_id,
        "task": "literature knowledge graph over the supplied paper set",
        "status": status,
        "input": {
            "materials": parsed.get("input_dir"),
            "sources": [{"source_id": s["source_id"], "doi": s.get("doi"),
                         "title": s.get("title"), "year": s.get("year"),
                         "license": s.get("license")} for s in parsed["sources"]],
            "paragraph_id_scheme": "organizer JATS paragraph_id; generated ids are labelled id_source=generated",
        },
        "sources": parsed["manifest"],
        "graph": {"stats": graph["stats"], "schema_version": None},
        "nodes": graph["nodes"],
        "edges": graph["edges"],
        "merges": graph.get("merges") or [],
        "candidate_alignments": graph.get("candidate_alignments") or [],
        "type_conflicts": graph.get("type_conflicts") or [],
        "conflicts": graph.get("conflicts") or [],
        "dropped": graph.get("dropped") or [],
        "queries": queries.get("queries") or [],
        "query_summary": queries.get("summary"),
        "validation": {
            "status": report["status"],
            "counts": report["counts"],
            "top_failures": report["top_failures"],
            "graph_checks": report["graph_checks"],
            "summary": report["summary"],
        },
        "uncertainty": uncertainty,
        "change_log": change_log,
    }
    result["graph"]["schema_version"] = "1.0.0"
    return result


def write_all(out_dir: Path, result: dict, graph: dict, queries: dict,
              report: dict) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = {}

    def dump(name: str, obj: Any) -> None:
        path = out_dir / name
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
                        encoding="utf-8", newline="\n")
        written[name] = len(path.read_bytes())

    dump("result.json", result)
    dump("graph.json", graph)
    dump("queries.json", queries)
    dump("validation.json", report)

    (out_dir / "graph.mmd").write_text(_mermaid(graph), encoding="utf-8", newline="\n")
    n_rows, e_rows = _csv_rows(graph["nodes"], graph["edges"])
    for name, rows in (("nodes.csv", n_rows), ("edges.csv", e_rows)):
        with open(out_dir / name, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh, lineterminator="\n")
            w.writerows(rows)
    written["graph.mmd"] = len((out_dir / "graph.mmd").read_bytes())
    written["nodes.csv"] = len((out_dir / "nodes.csv").read_bytes())
    written["edges.csv"] = len((out_dir / "edges.csv").read_bytes())
    return written


def finalise(case_raw: dict, result: dict) -> dict:
    """Apply the case's output_contract, if it declared one."""
    contract_spec = case_raw.get("output_contract") or case_raw.get("outputContract")
    out, rep = contract.apply(result, contract_spec)
    return out
