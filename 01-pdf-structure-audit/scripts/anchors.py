#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""anchors.py — "核得回"的执行层：拿每个单元的 bbox 回到 PDF 里重抽一次字，比对得上才算数。

为什么非要回抽一遍：
1) 结构识别、表格重建、公式拼接都是**推断**。推断可能错，而"每条结果都能指回原文"是本题
   的硬指标。最便宜、最硬的验证方式就是：拿记下来的 bbox，再去 PDF 同一位置抽一次字，
   如果和记录的文字对不上，说明这个 bbox 是错的（或文字被改过），必须标出来而不是放着。
2) 覆盖率用"词元交集 / 记录词元"，不用整串相等：同一 bbox 重抽时空白、连字符、上下标
   合并方式都可能不同，整串相等会大面积假失败；词元覆盖率能容忍这些排版差异，又能抓
   真正的错位（抽到的是隔壁栏的字）。
3) 阈值按单元类型分开：正文/标题/题注要求 0.85；公式因为碎片拼接顺序本来就不稳，
   要求 0.5 并且额外保留 PNG 供目检——不能用一个阈值把两类混在一起判。
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pdfcore

PUNCT = re.compile(r"[^\w\u4e00-\u9fff]+", re.U)


def tokens(text: str) -> list[str]:
    t = pdfcore.nfkc(text).lower()
    t = PUNCT.sub(" ", t)
    return [x for x in t.split() if x]


def _clip_text(page, bbox) -> str:
    try:
        words = page.get_text("words", clip=page.rect & _rect(bbox))
    except Exception:
        return ""
    return " ".join(w[4] for w in words)


def _rect(bbox):
    import pymupdf
    return pymupdf.Rect(bbox[0], bbox[1], bbox[2], bbox[3])


def coverage(record: str, clip: str) -> float:
    a, b = tokens(record), set(tokens(clip))
    if not a:
        return 1.0
    hit = sum(1 for t in a if t in b)
    return hit / len(a)


def _units(doc: dict) -> list[dict]:
    """把所有"该能指回原文"的单元摊平，带类型与阈值。"""
    units = []
    for pg in doc["pages"]:
        for p in pg["paras"]:
            role = p.get("role")
            if role in ("empty",):
                continue
            thr = 0.85
            if role == "formula":
                thr = 0.5
            elif role in ("table_cell",):
                thr = 0.7
            units.append({
                "id": p["id"], "kind": role or "para", "page": pg["no"],
                "bbox": p["bbox"], "text": p["text"], "threshold": thr,
                "section": p.get("section"),
            })
    for t in doc.get("tables", []):
        for key, cell in t.get("cells", {}).items():
            units.append({
                "id": f"{t['id']}:c{key}", "kind": "table_cell_bbox", "page": t["page"],
                "bbox": cell["bbox"], "text": cell["text"], "threshold": 0.7,
            })
    for f in doc.get("formulas", []):
        units.append({
            "id": f["id"], "kind": "formula", "page": f["page"],
            "bbox": f["bbox"], "text": f["text_raw"], "threshold": 0.5,
        })
    return units


def audit(pdf, doc: dict) -> dict:
    units = _units(doc)
    results, fails = [], []
    for u in units:
        page = pdf.doc[u["page"] - 1] if 0 < u["page"] <= pdf.doc.page_count else None
        if page is None:
            results.append({**{k: u[k] for k in ("id", "kind", "page")},
                            "coverage": 0.0, "ok": False, "reason": "page_out_of_range"})
            fails.append(u["id"])
            continue
        b = u["bbox"]
        inside = (0 <= b[0] < page.rect.width and 0 <= b[1] < page.rect.height
                  and b[2] <= page.rect.width + 1 and b[3] <= page.rect.height + 1)
        clip = _clip_text(page, b)
        cov = coverage(u["text"], clip)
        ok = bool(inside and cov >= u["threshold"])
        reason = None
        if not inside:
            reason = "bbox_outside_page"
        elif cov < u["threshold"]:
            reason = f"coverage {cov:.2f} < {u['threshold']}"
        results.append({
            "id": u["id"], "kind": u["kind"], "page": u["page"], "bbox": b,
            "coverage": round(cov, 3), "threshold": u["threshold"],
            "ok": ok, "reason": reason,
        })
        if not ok:
            fails.append(u["id"])

    total = len(results)
    passed = sum(1 for r in results if r["ok"])
    by_kind: dict[str, dict] = {}
    for r in results:
        k = by_kind.setdefault(r["kind"], {"total": 0, "ok": 0})
        k["total"] += 1
        k["ok"] += 1 if r["ok"] else 0
    return {
        "total_units": total,
        "passed": passed,
        "failed": total - passed,
        # 没有任何可核验单元时（例如整篇是无文字层扫描件）不能写 0.0：
        # 0.0 会被读成"全都核验失败"，而事实是"没有东西可核验"。None 才是诚实的，
        # 下游 decide_status 也据此把状态降到 partial 而不是 needs_review。
        "pass_rate": round(passed / total, 4) if total else None,
        "by_kind": by_kind,
        "failures": [r for r in results if not r["ok"]][:80],
        "results": results,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="锚点回验：用 bbox 回抽原文，验证每个单元可核")
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--doc", required=True, help="含 paras/tables/formulas 的 document.json")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    pdf = pdfcore.PdfDoc(args.pdf)
    doc = json.loads(Path(args.doc).read_text(encoding="utf-8"))
    rep = audit(pdf, doc)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: rep[k] for k in ("total_units", "passed", "failed", "pass_rate", "by_kind")},
                     ensure_ascii=False, indent=1))
    if rep["failures"]:
        print("failures sample:", json.dumps(rep["failures"][:5], ensure_ascii=False, indent=1))
    pdf.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
