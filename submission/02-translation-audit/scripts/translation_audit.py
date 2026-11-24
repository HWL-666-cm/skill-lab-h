#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""translation_audit.py — 译文可核验性审计（机器可判定的部分）

设计原则（与 06/03/07 同构）：只把"能判死"的做成硬错误，语义质量不假装能裁决。

四类检查：
  A. coverage       段号一一覆盖：原文正文段 pid 集合 vs 译文 pid 集合。
                    漏段/错号是集合问题，纯机器判定 —— 对应题面"段落全"。
  B. term_execution 术语表是否被真正执行（而不是写在提示里）：
                    - 原文含术语的段落，译文是否用了锁定译名（漏译/漂移）
                    - 是否使用了禁用别名 forbidden
                    - 对应题面"术语稳"与"术语表能否被真正执行"。
  C. anchors        字面锚点守恒：阿拉伯数字、单位、引用年份、公式编号、
                    图表编号在该段译文里是否还在。对应"关系准"里可机器判定的子集。
  D. negation       否定词数量守恒（仅警告，不硬判：中英否定表达不完全对应）。

输入：
  --paras        pdf_paragraphs.py 输出（原文段落）
  --glossary     term_extract.py 输出（target 已由 Agent 填写）
  --translation  译文：JSON {"paragraphs":[{"pid":12,"target":"..."}]}
                 或 Markdown（用 [P12] 或 ## P12 标记段落）
输出：审计报告 JSON（issues + counts + verdict），每条 issue 带证据与定位。
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path

NUM = re.compile(r"\d+(?:\.\d+)?")
UNIT = re.compile(r"(?<![\w.])(km|m|cm|mm|h|d|s|min|%|°C|K|Pa|hPa|m/s|kg|J|W|UTC)(?![\w])", re.I)
CITE_YEAR = re.compile(r"\(([A-Z][A-Za-z\-]+(?:\s+(?:et\s+al\.?|and\s+[A-Z][A-Za-z\-]+))?,\s*)(\d{4})[a-z]?\)")
# 作者在括号外、括号内只有年份的引用格式：`Kneringer et al. (2019)`
YEAR_PAREN = re.compile(r"\((\d{4})[a-z]?\)")
BRACKET_CITE = re.compile(r"\[(\d+(?:\s*[,–\-]\s*\d+)*)\]")
EQ_NO = re.compile(r"\((\d{1,3})\)\s*$")
FIG_TAB_NO = re.compile(r"\b(Fig\.?|Figure|Table|Eq\.?)\s*(\d{1,3})", re.I)
NEG_EN = re.compile(
    r"\b(not|no|never|without|none|neither|nor|cannot|can't|isn't|aren't|wasn't|weren't|"
    r"don't|doesn't|didn't|unless|excluding)\b|\b\w+n't\b", re.I)
NEG_ZH = re.compile(r"[不未无非否莫勿]|没有|无法|不能|并非|决不")


def nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s or "")


def norm_term(s: str) -> str:
    """术语匹配归一：NFKC + 小写 + 拉丁标点当分隔符 + 压空白。

    为什么要把标点变空格：原文 `ordered logistic regression.` 句号紧贴术语，
    若保留标点会导致"带尾空格的术语串"匹配失败（实测误报 term_overused）。
    """
    t = nfkc(s).lower()
    t = re.sub(r"[^\w\s\u4e00-\u9fff]", " ", t)   # 拉丁/中文标点统一变空格
    t = re.sub(r"\s{2,}", " ", t)
    return f" {t.strip()} "


def numbers(s: str) -> list[str]:
    return NUM.findall(nfkc(s))


def parse_translation(path: Path) -> dict[int, str]:
    """返回 {pid: 译文}。支持 JSON 与 Markdown 两种形态。"""
    raw = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(raw)
        out = {}
        for item in data.get("paragraphs", []):
            pid = item.get("pid")
            if isinstance(pid, int):
                out[pid] = item.get("target", "") or item.get("text", "")
        return out

    # Markdown: [P12] ... 或 ## P12 ...
    out: dict[int, str] = {}
    cur = None
    buf: list[str] = []
    for line in raw.splitlines():
        m = re.match(r"^\s*(?:#{1,6}\s*)?\[?P(\d+)\]?\s*[:：]?\s*(.*)$", line)
        if m:
            if cur is not None:
                out[cur] = "\n".join(buf).strip()
            cur = int(m.group(1))
            buf = [m.group(2)]
        elif cur is not None:
            buf.append(line)
    if cur is not None:
        out[cur] = "\n".join(buf).strip()
    return out


def audit(paras_data: dict, glossary: dict, translation: dict[int, str],
          scope: set[int] | None = None) -> dict:
    paras = paras_data["paragraphs"]
    body = [p for p in paras if p["kind"] == "para"]
    # --scope：只审计指定 pid（分块续译/局部验证时用；不给则审计全部正文段）
    if scope:
        body = [p for p in body if p["pid"] in scope]
    body_pids = {p["pid"] for p in body}
    trans_pids = {pid for pid in translation.keys() if not scope or pid in scope}

    issues: list[dict] = []
    iid = 0

    def add(kind: str, severity: str, detail: str, pid=None, evidence: str = ""):
        nonlocal iid
        iid += 1
        issues.append({
            "id": f"I{iid:03d}", "type": kind, "severity": severity,
            "pid": pid, "detail": detail, "evidence": evidence,
        })

    # ---------- A. coverage ----------
    missing = sorted(body_pids - trans_pids)
    if missing:
        add("missing_paragraph", "error",
            f"原文 {len(missing)} 个正文段没有译文（漏段）：pid {missing[:20]}",
            evidence=f"missing_count={len(missing)}")
    orphan = sorted(trans_pids - body_pids)
    if orphan:
        add("orphan_paragraph", "error",
            f"译文含 {len(orphan)} 个原文不存在的正文段号（错号/多译）：pid {orphan[:20]}",
            evidence=f"orphan_count={len(orphan)}")
    empty = sorted(pid for pid in (body_pids & trans_pids) if not translation[pid].strip())
    if empty:
        add("empty_translation", "error",
            f"{len(empty)} 个段落译文为空：pid {empty[:20]}", evidence=f"empty_count={len(empty)}")

    # ---------- B. term execution ----------
    concepts = [c for c in glossary.get("concepts", []) if c.get("target")]
    unlocked = [c for c in glossary.get("concepts", []) if not c.get("target")]
    if unlocked:
        add("glossary_unlocked", "warning",
            f"{len(unlocked)} 个术语候选没有填译名（target 为空），本次未纳入一致性检查。",
            evidence=",".join(c["concept_id"] for c in unlocked[:12]))

    by_pid = {p["pid"]: p for p in body}
    for c in concepts:
        src = nfkc(c["source"]).lower()
        abbr = (c.get("abbr") or "").strip()
        target = c["target"]
        alias_src = [a.lower() for a in c.get("aliases_allowed", [])]
        # 注意：abbr 不进 keys。缩写必须用词边界匹配，否则 ensemble 含 ens 会误命中。
        keys = [src] + alias_src

        def has_source(text: str) -> bool:
            tl = norm_term(text)
            # 1) 缩写：词边界匹配（大小写不敏感）
            if abbr and re.search(rf"\b{re.escape(abbr.lower())}\b", nfkc(text).lower()):
                return True
            # 2) 全称/别名：归一后做子串匹配（连字符当空格）
            for k in keys:
                if k and norm_term(k).strip() and norm_term(k) in tl:
                    return True
            return False

        # 术语应在哪些段出现（原文命中），这些段的译文必须含 target
        for pid, p in by_pid.items():
            if not has_source(p["text"]):
                continue
            tv = translation.get(pid, "")
            if pid not in translation:
                continue  # 漏段已由 coverage 报
            if nfkc(target) not in nfkc(tv):
                add("term_missing_in_translation", "error",
                    f"{c['concept_id']}「{c['source']}」应在 pid {pid} 出现，译文未使用锁定译名「{target}」。",
                    pid=pid, evidence=f"target={target};source_hit=1")
            for fb in c.get("forbidden", []):
                if fb and nfkc(fb) in nfkc(tv):
                    add("forbidden_term_used", "error",
                        f"{c['concept_id']} 译文使用了禁用别名「{fb}」，应为「{target}」。",
                        pid=pid, evidence=f"forbidden={fb}")

        # 反向：原文不含该术语、译文却出现 target，可能是串位/过度套用（仅警告）
        for pid, tv in translation.items():
            if pid not in by_pid:
                continue
            if nfkc(target) in nfkc(tv) and not has_source(by_pid[pid]["text"]):
                add("term_overused", "warning",
                    f"{c['concept_id']}「{target}」出现在 pid {pid}，但该段原文未检出对应术语，需人工确认是否串位。",
                    pid=pid, evidence=f"target={target}")

    # ---------- C. anchors ----------
    for pid in sorted(body_pids & trans_pids):
        src_text = by_pid[pid]["text"]
        tv = translation[pid]
        if not tv.strip():
            continue

        # C1 阿拉伯数字（先剥离"结构性数字"：引用年份/方括号引用号/公式编号，
        # 它们各有专门检查项，否则会被重复计数并误升级为硬错误）
        src_for_num = CITE_YEAR.sub(" ", src_text)
        src_for_num = YEAR_PAREN.sub(" ", src_for_num)
        src_for_num = BRACKET_CITE.sub(" ", src_for_num)
        src_for_num = EQ_NO.sub(" ", src_for_num)
        sn = numbers(src_for_num)
        tn = set(numbers(tv))
        lost = [n for n in sn if n not in tn]
        if lost:
            add("number_lost", "error",
                f"pid {pid} 原文数字未在译文中保留：{lost[:8]}", pid=pid, evidence=",".join(lost[:8]))

        # C2 单位符号
        su = {u.lower() for u in UNIT.findall(src_text)}
        tu = {u.lower() for u in UNIT.findall(tv)}
        ulost = sorted(su - tu)
        if ulost:
            add("unit_lost", "warning",
                f"pid {pid} 单位符号未保留：{ulost}", pid=pid, evidence=",".join(ulost))

        # C3 引用年份（(Author, 2019) 与 Author et al. (2019) 两种格式）
        sy = {m.group(2) for m in CITE_YEAR.finditer(src_text)}
        sy |= {m.group(1) for m in YEAR_PAREN.finditer(src_text)}
        ty_full = set(re.findall(r"\b(?:19|20)\d{2}\b", tv))
        ylost = sorted(y for y in sy if y not in ty_full)
        if ylost:
            add("cite_year_lost", "warning",
                f"pid {pid} 引用年份未保留：{ylost}", pid=pid, evidence=",".join(ylost))

        # C4 方括号数字引用 [n]
        sb = {x for m in BRACKET_CITE.finditer(src_text) for x in re.findall(r"\d+", m.group(1))}
        tb = {x for m in BRACKET_CITE.finditer(tv) for x in re.findall(r"\d+", m.group(1))}
        blost = sorted(sb - tb)
        if blost:
            add("bracket_cite_lost", "warning",
                f"pid {pid} 方括号引用编号未保留：{blost}", pid=pid, evidence=",".join(blost))

        # C5 图表/公式编号（Fig. 2 / Table 1）
        sf = {(m.group(1).lower().rstrip('.'), m.group(2)) for m in FIG_TAB_NO.finditer(src_text)}
        tf = {(m.group(1).lower().rstrip('.'), m.group(2)) for m in FIG_TAB_NO.finditer(tv)}
        flost = sorted(f"{a} {b}" for a, b in (sf - tf))
        if flost:
            add("fig_tab_ref_lost", "warning",
                f"pid {pid} 图表编号未保留：{flost}", pid=pid, evidence=",".join(flost))

        # ---------- D. negation ----------
        sn_n = len(NEG_EN.findall(src_text))
        tn_n = len(NEG_ZH.findall(tv))
        if sn_n and tn_n == 0:
            add("negation_lost", "warning",
                f"pid {pid} 原文有 {sn_n} 处否定，译文未检出否定词，需人工核对是否丢失否定。",
                pid=pid, evidence=f"src_neg={sn_n};tgt_neg=0")

    # ---------- 汇总 ----------
    errs = sum(1 for i in issues if i["severity"] == "error")
    warns = sum(1 for i in issues if i["severity"] == "warning")
    if errs:
        verdict = "needs_revision"
    elif warns:
        verdict = "needs_review"
    else:
        verdict = "ok"

    return {
        "verdict": verdict,
        "counts": {
            "body_paragraphs": len(body_pids),
            "translated_paragraphs": len(trans_pids & body_pids),
            "glossary_concepts": len(concepts),
            "errors": errs,
            "warnings": warns,
            "issues_total": len(issues),
        },
        "issues": issues,
        "coverage": {
            "missing_pids": missing,
            "orphan_pids": orphan,
            "empty_pids": empty,
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--paras", required=True)
    ap.add_argument("--glossary", required=True)
    ap.add_argument("--translation", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--scope", default="", help="只审计指定 pid，逗号分隔，如 8,13,16（局部/分块审计）")
    args = ap.parse_args()

    paras_data = json.loads(Path(args.paras).read_text(encoding="utf-8"))
    glossary = json.loads(Path(args.glossary).read_text(encoding="utf-8"))
    translation = parse_translation(Path(args.translation))
    scope = {int(x) for x in re.findall(r"\d+", args.scope)} if args.scope else None

    report = audit(paras_data, glossary, translation, scope=scope)
    report["inputs"] = {
        "paras": args.paras,
        "glossary": args.glossary,
        "translation": args.translation,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"out": args.out, "verdict": report["verdict"], "counts": report["counts"]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
