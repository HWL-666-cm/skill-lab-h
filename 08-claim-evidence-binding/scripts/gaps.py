#!/usr/bin/env python3
"""Build the human-facing gap / follow-up list from alignment results."""
from __future__ import annotations


def build(cands: dict, al: dict, pack: dict, draft: str) -> dict:
    gaps: list[dict] = []
    f = al.get("forward", {})
    b = al.get("backward", {})

    for r in f.get("rows", []):
        s = r.get("status", "")
        if s == "unanchored":
            gaps.append({"severity": "major", "type": "claim_without_evidence",
                         "where": r.get("section", ""),
                         "text": r.get("sentence", "")[:200],
                         "question": "这句话的论断依据是什么？请给文献编号、图表号，或明确标为作者判断。"})
        elif s == "unverified":
            gaps.append({"severity": "major", "type": "citation_untraceable",
                         "where": r.get("section", ""),
                         "text": r.get("sentence", "")[:200],
                         "question": "引用 " + ", ".join(c["raw"] for c in r.get("citations", [])) +
                                     " 在材料文献表中找不到对应条目，请核对作者/年份/编号。"})
        elif r.get("metadata_mismatch"):
            gaps.append({"severity": "blocking", "type": "citation_metadata_mismatch",
                         "where": r.get("section", ""),
                         "text": r.get("sentence", "")[:200],
                         "question": "；".join(r["metadata_mismatch"])})
        if s == "overclaimed":
            gaps.append({"severity": "major", "type": "overclaim",
                         "where": r.get("section", ""),
                         "text": r.get("sentence", "")[:200],
                         "question": "强断言词 " + ", ".join(r.get("overclaim_terms", [])) +
                                     " 无证据支撑，请补证据或改为 hedge 表述。"})
        if r.get("cliche_terms") and r.get("claim_type") == "background":
            gaps.append({"severity": "warn", "type": "cliche_background",
                         "where": r.get("section", ""),
                         "text": r.get("sentence", "")[:200],
                         "question": "背景套话 " + ", ".join(r["cliche_terms"][:3]) +
                                     "，请替换为材料中的具体问题或约束。"})
        if r.get("claim_type") == "gap" and not r.get("citations") and not r.get("verbatim_source"):
            gaps.append({"severity": "major", "type": "gap_without_citation",
                         "where": r.get("section", ""),
                         "text": r.get("sentence", "")[:200],
                         "question": "空白由谁的什么局限推出？请挂到具体文献。"})
        if r.get("claim_type") == "contribution" and not r.get("figures") and not r.get("verbatim_source"):
            gaps.append({"severity": "major", "type": "contribution_without_anchor",
                         "where": r.get("section", ""),
                         "text": r.get("sentence", "")[:200],
                         "question": "这条贡献对应哪个图表/章节/实验结果？"})

    for r in b.get("rows", []):
        if r.get("status") == "not_written":
            gaps.append({"severity": "warn", "type": f"key_{r.get('kind','item')}_not_written",
                         "where": "backward check", "text": str(r.get("label") or r.get("title") or r.get("author", ""))[:200],
                         "question": "材料中的这一项未在成稿出现，请确认是否应覆盖。"})
        elif r.get("status") == "mentioned_without_anchor":
            gaps.append({"severity": "warn", "type": "mentioned_without_citation",
                         "where": "backward check", "text": str(r.get("author") or r.get("label", ""))[:200],
                         "question": "提到了该工作但没有可定位的引用锚点。"})

    by_sev: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for g in gaps:
        by_sev[g["severity"]] = by_sev.get(g["severity"], 0) + 1
        by_type[g["type"]] = by_type.get(g["type"], 0) + 1
    return {"gaps": gaps, "by_severity": by_sev, "by_type": by_type,
            "blocking": by_sev.get("blocking", 0)}


def markdown(gp: dict, case_id: str) -> str:
    lines = [f"# 断言—证据缺口与追问清单 —— {case_id}", "",
             f"共 {len(gp['gaps'])} 项：blocking {gp['by_severity'].get('blocking',0)} / "
             f"major {gp['by_severity'].get('major',0)} / warn {gp['by_severity'].get('warn',0)}", ""]
    for i, g in enumerate(gp["gaps"], 1):
        lines.append(f"## {i}. [{g['severity']}] {g['type']}")
        lines.append(f"- 位置：{g['where']}")
        lines.append(f"- 原文：{g['text']}")
        lines.append(f"- 追问：{g['question']}")
        lines.append("")
    if not gp["gaps"]:
        lines.append("没有发现缺口。注意：机器只核对可定位性与元数据，语义准确性仍需人工确认。")
    return "\n".join(lines) + "\n"
