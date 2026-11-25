# 输出契约处理规则

平台的 `output_contract` 由案例作者声明，字段名不可预知。本 Skill 的处理策略与 05 题一致：**契约写死的东西不能被静默忽略**。

## 三种契约形态

```
{"output_contract": ["a", "b"]}
{"output_contract": {"fields": ["a", "b"]}}
{"output_contract": {"a": "说明", "b": "说明"}}
{"output_contract": [{"name": "a"}, {"field": "b"}]}
```

`contract.py:declared_fields()` 递归抽取字段名（深度 ≤4）。

## 每个声明字段的处理（按优先级）

1. **同名/同义已有** → 直接复制（`ALIASES` 表：如 `draft`/`manuscript`/`introduction` → `intro_related_work_markdown`；`claims`/`assertions` → `claim_ledger`）
2. **可派生** → 从台账派生（`evidence_index` 从 claim_ledger 生成）
3. **都没有** → 置 `null`，加入 `contract_report.missing`，并在 `uncertainty` 写明

**绝不为了让字段看起来满足契约而编造值**——这是题面"材料不足明确标注，不新增材料外事实"的直接落地。

## 结果文件固定字段（不论契约怎么写）

`case_id`、`status`、`intro_related_work_markdown`、`claim_ledger`、`citation_check`、`coverage`、`alignment`、`validation`、`gaps`、`sources`、`uncertainty`、`change_log`。

status 取值：`complete` / `partial` / `blocked`。partial 必带 `limits[]`，blocked 必带 `reason`。

## 确定性

两次运行同一输入，8 个输出文件（intro_related_work.md、claim_ledger.json、citation_check.json、coverage.json、alignment.json、validation.json、gaps.md、result.json）逐字节一致。已由自测验证。

实现要点：不用当前时间、不用随机数、字典按插入顺序序列化、逐行读取材料保持顺序。
