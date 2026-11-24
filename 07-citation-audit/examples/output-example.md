# 示意输出（不是答案）

> 以下内容演示接口和字段形态。输入是上一条 `case-example.json` 的虚构数据，**不冒充平台固定案例结果**。

## 调用

```bash
python3 scripts/citation_audit.py --manuscript example.md --bib example.bib.json --out audit.json
python3 scripts/make_result.py --case-id example-07 --case-json case.json \
  --manuscript example.md --revised example.md --bib example.bib.json \
  --audit audit.json --out result.json
```

## 审计结果（示意）

```
[citation_audit] ok | citations=2 entries=2 errors=0 warnings=0
```

`audit.json` 的关键字段：

```json
{
  "version": "1.0",
  "inputs": {"citation_style": "numeric", "has_reference_section": true},
  "counts": {"citations_in_text": 2, "entries_in_bib": 2, "errors": 0, "warnings": 0},
  "numbering": {"first_seen": [1, 2], "continuous": true, "proposed": {"1": 1, "2": 2}},
  "verdict": "ok"
}
```

## `result.json` 形态（示意）

- `status`: `ok`
- `edited_manuscript`: 可继续编辑的修订稿全文
- `citation_issues`: `[]`
- `bibliography`: 与输入一致的 2 条文献记录
- `numbering_plan`: 上文的 `numbering`
- `source_map`: 稿件/文献库/审计报告的路径与计数
- `change_log`: `[]`
- `limitations`: `[]`

## 若输入有问题时

同一稿件把 `[2]` 改成 `[9]`（文献库没有 9），审计会返回 `verdict=needs_revision`，并给出：

```json
{"type": "dangling_citation", "severity": "error", "token": "9",
 "evidence": {"line": 1, "available_orders": [1, 2]},
 "suggestion": "补上该条文献或修正编号；禁止保留指向不存在条目的引用。"}
```

此时 `make_result.py` 输出的 `status=partial`，`limitations` 明确写出"发现 1 处硬错误"。
