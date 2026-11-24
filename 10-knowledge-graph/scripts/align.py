#!/usr/bin/env python3
"""Assemble nodes and edges from a draft, with an explicit identity policy.

The policy is the point of this file:

* Aliases are resolved with a union-find over the declared names *within one
  paper*. A paper that says "Incheon" and "Incheon port" means one place; the
  union is recorded so the decision can be audited.
* Across papers nothing is merged on string equality. A name shared by two
  papers is merged only when it denotes a public product (acronym, versioned
  name) or when an explicit identifier matches, and then only at `product`
  scope. Everything else stays split and is written into
  `candidate_alignments` with the reason.
* A node's `identity_scope` says what kind of identity it claims: `instance`
  (this paper's run / observation) or `product` (the shared artefact).
* Conflicting values are grouped by *conditions* first. Two accuracies measured
  at different sites are not a contradiction; the same claim under the same
  conditions with different values is. Nothing is averaged or overwritten.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

import materials as M

ABBREV_RE = re.compile(r"^[A-Z][A-Za-z0-9]{1,9}(?:-[A-Z0-9]{1,6})?$")
PRODUCT_TYPES = {"METHOD", "DATASET", "VARIABLE"}


def _hid(prefix: str, *parts: str) -> str:
    return prefix + hashlib.sha1("\u0001".join(parts).encode("utf-8")).hexdigest()[:10]


def _looks_like_product(surface: str) -> bool:
    s = surface.strip()
    if ABBREV_RE.match(s) and sum(1 for c in s if c.isupper()) >= 2:
        return True
    return bool(re.search(r"\d", s) and re.match(r"^[A-Z]", s))


def _canonical(ents: list[dict]) -> dict:
    def score(e: dict) -> tuple:
        surface = e.get("surface", "")
        abbrev = 0 if ABBREV_RE.match(surface) else 1
        lowercase = 1 if surface[:1].islower() else 0
        return (abbrev, lowercase, len(surface.split()), len(surface))
    return max(ents, key=score)


class _DSU:
    def __init__(self, n: int) -> None:
        self.p = list(range(n))

    def find(self, x: int) -> int:
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)


def build_graph(draft: dict, parsed: dict, schema: dict) -> dict:
    sources = {s["source_id"]: s for s in parsed["sources"]}
    # work on copies: a draft handed in by a model must not be mutated, or the
    # caller cannot serialise or re-use it afterwards
    ents: list[dict] = []
    for i, raw in enumerate(draft.get("entities") or []):
        if not raw.get("surface") or not raw.get("type"):
            continue
        e = dict(raw)
        e.setdefault("key", f"k{i + 1}")
        e["names"] = {M.norm_key(n) for n in [e["surface"]] + list(e.get("aliases") or []) if n}
        e["scope"] = e.get("scope") or "instance"
        ents.append(e)

    dsu = _DSU(len(ents))
    name_index: dict[str, list[int]] = {}
    for i, e in enumerate(ents):
        for nm in e["names"]:
            name_index.setdefault(nm, []).append(i)

    # 1) within one source and one type: co-referring names are one entity
    alias_merges: list[dict] = []
    for nm, idxs in name_index.items():
        buckets: dict[tuple, list[int]] = {}
        for i in idxs:
            buckets.setdefault((ents[i]["source_id"], ents[i]["type"]), []).append(i)
        for (sid, etype), group in buckets.items():
            if len(group) > 1:
                for j in group[1:]:
                    dsu.union(group[0], j)
                surfaces = sorted({ents[i]["surface"] for i in group})
                if len(surfaces) > 1:
                    alias_merges.append({"source_id": sid, "type": etype,
                                         "surfaces": surfaces, "basis": "declared_alias_in_same_paper"})

    # 2) across papers: policy decides, never string equality alone
    candidate_alignments: list[dict] = []
    type_conflicts: list[dict] = []
    cross_merges: list[dict] = []

    for nm, idxs in name_index.items():
        roots: dict[int, list[int]] = {}
        for i in idxs:
            roots.setdefault(dsu.find(i), []).append(i)
        if len(roots) < 2:
            continue
        srcs = {ents[g[0]]["source_id"] for g in roots.values()}
        if len(srcs) < 2:
            continue
        types = {ents[g[0]]["type"] for g in roots.values()}
        if len(types) > 1:
            type_conflicts.append({
                "surface": ents[idxs[0]]["surface"], "types": sorted(types),
                "sources": sorted(srcs), "decision": "kept_separate",
                "reason": "同一写法在两篇被标成不同类型，按类型拆开，不因字面相同而合并",
            })
            continue
        etype = types.pop()
        groups = list(roots.values())
        labels = [_canonical([ents[i] for i in g])["surface"] for g in groups]
        id_values = {ents[i].get("identifier") for g in groups for i in g if ents[i].get("identifier")}
        all_have_identifier = all(any(ents[i].get("identifier") for i in g) for g in groups)
        shared_id = bool(id_values) and all_have_identifier and len(id_values) == 1
        productish = etype in PRODUCT_TYPES and all(_looks_like_product(x) for x in labels)
        if productish or shared_id:
            for g in groups[1:]:
                dsu.union(idxs[0], g[0])
            cross_merges.append({
                "label": _canonical([ents[i] for g in groups for i in g])["surface"],
                "type": etype, "sources": sorted(srcs),
                "basis": "shared_identifier" if shared_id else "public_product_term",
                "identity_scope": "product", "members": len(groups),
            })
        else:
            for a in range(len(groups)):
                for b in range(a + 1, len(groups)):
                    candidate_alignments.append({
                        "a": {"surface": labels[a], "source_id": ents[groups[a][0]]["source_id"]},
                        "b": {"surface": labels[b], "source_id": ents[groups[b][0]]["source_id"]},
                        "basis": "same_surface_only", "decision": "not_merged",
                        "reason": "两篇写法相同，但没有共同标识符，也不属于可共享的公共产品；"
                                  "不合并，保留为待人工判定的候选对齐。",
                    })

    # 3) materialise nodes
    comps: dict[int, list[int]] = {}
    for i in range(len(ents)):
        comps.setdefault(dsu.find(i), []).append(i)

    nodes: list[dict] = []
    key_to_node: dict[str, str] = {}
    merges: list[dict] = []
    for members in comps.values():
        group = [ents[i] for i in members]
        etype = group[0]["type"]
        src_ids = sorted({e["source_id"] for e in group})
        canon = _canonical(group)
        scope = "product" if len(src_ids) > 1 else "instance"
        nid = (_hid("n:", "product", etype, M.norm_key(canon["surface"])) if scope == "product"
               else _hid("n:", "instance", etype, src_ids[0], M.norm_key(canon["surface"])))
        evidence, seen = [], set()
        for e in group:
            sig = (e["source_id"], e.get("paragraph_id"), M.norm_text(e.get("quote") or ""))
            if sig not in seen:
                seen.add(sig)
                rec = {"source_id": e["source_id"], "paragraph_id": e.get("paragraph_id"),
                       "quote": M.norm_text(e.get("quote") or "")}
                # keep a declared page so the gate can reject it, instead of
                # silently dropping the evidence that the draft got it wrong
                for k in ("page", "page_number", "pdf_page"):
                    if e.get(k) is not None:
                        rec[k] = e[k]
                        break
                evidence.append(rec)
        node = {
            "id": nid, "label": canon["surface"], "type": etype,
            "identity_scope": scope, "source_ids": src_ids,
            "aliases": sorted({e["surface"] for e in group} - {canon["surface"]}),
            "evidence": evidence,
        }
        if scope == "product":
            node["scope_note"] = ("产品级同一性：同名公共方法/数据集/标准量可跨篇共享；"
                                  "各篇的版本、配置与实验条件可能不同，不视为同一实例。")
            merges.append({"node_id": nid, "label": node["label"], "type": etype,
                           "sources": src_ids, "basis": "public_product_term",
                           "identity_scope": "product", "members": len(group)})
        nodes.append(node)
        for e in group:
            key_to_node[e["key"]] = nid

    for m in alias_merges:
        for n in nodes:
            if m["source_id"] in n["source_ids"] and n["type"] == m["type"] and \
                    set(m["surfaces"]) <= ({n["label"]} | set(n["aliases"])):
                m["node_id"] = n["id"]
                m["label"] = n["label"]
                m["identity_scope"] = n["identity_scope"]
                break

    uniq: dict[str, dict] = {}
    for n in nodes:
        if n["id"] in uniq:
            prev = uniq[n["id"]]
            prev["aliases"] = sorted(set(prev["aliases"]) | set(n["aliases"]))
            prev["source_ids"] = sorted(set(prev["source_ids"]) | set(n["source_ids"]))
        else:
            uniq[n["id"]] = n
    nodes = list(uniq.values())
    node_by_id = {n["id"]: n for n in nodes}

    # ----------------------------------------------------------------- edges
    edges, dropped = [], []
    for raw in draft.get("edges") or []:
        pred = raw.get("predicate") or raw.get("relation")
        s_id = key_to_node.get(raw.get("subject"))
        o_id = key_to_node.get(raw.get("object"))
        if not pred or not s_id or not o_id:
            dropped.append({"raw": raw, "reason": "主语、宾语或关系类型缺失，或引用了不存在的实体键"})
            continue
        if s_id == o_id:
            dropped.append({"raw": raw, "reason": "主语与宾语落到同一节点（自环）"})
            continue
        eid = _hid("e:", s_id, pred, o_id, str(raw.get("source_id")), str(raw.get("paragraph_id")))
        ev = {"source_id": raw.get("source_id"), "paragraph_id": raw.get("paragraph_id"),
              "quote": M.norm_text(raw.get("quote") or "")}
        if raw.get("char_span"):
            ev["char_span"] = raw["char_span"]
        for k in ("page", "page_number", "pdf_page"):
            if raw.get(k) is not None:
                ev[k] = raw[k]
                break
        edges.append({
            "id": eid, "subject": s_id, "predicate": pred, "object": o_id,
            "subject_label": node_by_id[s_id]["label"], "object_label": node_by_id[o_id]["label"],
            "evidence": [ev],
            "strength": raw.get("strength") or {"class": "background", "weight": 0.3,
                                                "attribution": "this_paper"},
            "conditions": raw.get("conditions") or [],
            "direction_basis": raw.get("direction_basis") or "subject precedes trigger in the quoted sentence",
        })

    euniq: dict[str, dict] = {}
    for e in edges:
        if e["id"] in euniq:
            prev = euniq[e["id"]]
            merged = {(x["source_id"], x["paragraph_id"], x["quote"]): x for x in prev["evidence"]}
            for x in e["evidence"]:
                merged[(x["source_id"], x["paragraph_id"], x["quote"])] = x
            prev["evidence"] = list(merged.values())
        else:
            euniq[e["id"]] = e
    edges = sorted(euniq.values(), key=lambda e: (e["predicate"], e["subject"]))

    conflicts = detect_conflicts(edges, node_by_id, schema)

    return {
        "nodes": sorted(nodes, key=lambda n: (n["type"], n["label"].lower())),
        "edges": edges,
        "merges": merges + [m for m in alias_merges if m.get("node_id")],
        "candidate_alignments": candidate_alignments,
        "type_conflicts": type_conflicts,
        "conflicts": conflicts,
        "dropped": dropped,
        "stats": {
            "nodes": len(nodes), "edges": len(edges), "sources": len(sources),
            "product_nodes": sum(1 for n in nodes if n["identity_scope"] == "product"),
            "instance_nodes": sum(1 for n in nodes if n["identity_scope"] == "instance"),
            "merges": len(merges), "alias_merges": len([m for m in alias_merges if m.get("node_id")]),
            "candidate_alignments": len(candidate_alignments),
            "conflicts": len(conflicts),
        },
    }


_POLARITY_UP = re.compile(r"\b(increas|higher|enhanc|strengthen|positive(?:ly)?|promot|rise|rising)\w*", re.I)
_POLARITY_DOWN = re.compile(r"\b(decreas|lower|reduc|weaken|negative(?:ly)?|inhibit|fall|declin)\w*", re.I)


def detect_conflicts(edges: list[dict], node_by_id: dict, schema: dict) -> list[dict]:
    """Only claims made under the same conditions can contradict each other."""
    out: list[dict] = []
    groups: dict[tuple, list[dict]] = {}
    for e in edges:
        if e["predicate"] in {"ACHIEVES", "CAUSES", "DEFINED_AS"}:
            key = (e["subject"], e["predicate"], tuple(sorted(e.get("conditions") or [])))
            groups.setdefault(key, []).append(e)

    for (subj, pred, conds), group in groups.items():
        values = {e["object_label"] for e in group}
        if len(values) < 2:
            continue
        quotes = " ".join(x["evidence"][0]["quote"] for x in group)
        reasons = ["同一主语在同一关系下给出了不同的值"]
        if pred == "CAUSES" and _POLARITY_UP.search(quotes) and _POLARITY_DOWN.search(quotes):
            reasons.append("对同一因果关系的方向或极性表述相反")
        out.append({
            "id": _hid("c:", subj, pred, "|".join(sorted(values))),
            "subject": subj, "subject_label": node_by_id.get(subj, {}).get("label"),
            "predicate": pred, "kind": "divergent_claim", "reasons": reasons,
            "conditions": list(conds),
            "sides": [{"object": e["object"], "object_label": e["object_label"],
                       "source_id": e["evidence"][0]["source_id"],
                       "paragraph_id": e["evidence"][0]["paragraph_id"],
                       "quote": e["evidence"][0]["quote"]} for e in group],
            "resolution": "kept_both",
            "note": "两条主张并列保留，不取平均、不选边；引用时必须同时给出两侧证据。",
        })

    seen: dict[tuple, dict] = {}
    for e in edges:
        if e["predicate"] != "CAUSES":
            continue
        fwd, rev = (e["subject"], e["object"]), (e["object"], e["subject"])
        if rev in seen:
            other = seen[rev]
            out.append({
                "id": _hid("c:", fwd[0], "CAUSES", fwd[1]),
                "subject": e["subject"], "subject_label": e["subject_label"],
                "predicate": "CAUSES", "kind": "direction_conflict",
                "reasons": ["两篇对同一对实体给出相反的因果方向"], "conditions": [],
                "sides": [
                    {"object": e["object"], "object_label": e["object_label"],
                     "source_id": e["evidence"][0]["source_id"],
                     "paragraph_id": e["evidence"][0]["paragraph_id"],
                     "quote": e["evidence"][0]["quote"]},
                    {"object": other["object"], "object_label": other["object_label"],
                     "source_id": other["evidence"][0]["source_id"],
                     "paragraph_id": other["evidence"][0]["paragraph_id"],
                     "quote": other["evidence"][0]["quote"]},
                ],
                "resolution": "kept_both",
                "note": "方向冲突单独标出，不合并成一条无向边。",
            })
        else:
            seen[fwd] = e
    return out
