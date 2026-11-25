# 输出契约：字段字典与 `output_contract` 的处理

## `result.json` 顶层

| 字段 | 类型 | 含义 | 缺失时 |
|---|---|---|---|
| `case_id` | string | 从 `case.json` 读；读不到用目录名 | 不编造 |
| `task` | string | 固定说明"两篇及以上论文的知识图谱" | — |
| `status` | enum | `complete` / `partial` / `blocked` | — |
| `input` | object | 材料路径、各篇 DOI/标题/年份/许可证、段落 id 方案 | 缺项写 null |
| `sources` | array | `corpus-manifest.json` 的条目（含许可证与来源哈希） | 无 manifest 时由材料重建并记 warning |
| `graph.stats` | object | 节点数、边数、产品层/实例层节点数、合并数、候选对齐数、冲突数 | — |
| `nodes` | array | 见下 | — |
| `edges` | array | 见下 | — |
| `merges` | array | 已执行的合并，含 `basis`、`sources`、`members` | 空数组 |
| `candidate_alignments` | array | 同名但未合并的候选，含 `decision` 与 `reason` | 空数组 |
| `type_conflicts` | array | 同写法不同类型，已拆分 | 空数组 |
| `conflicts` | array | 冲突结论，两侧并列保留 | 空数组 |
| `dropped` | array | 未能入图的草稿条目与原因 | 空数组 |
| `queries` | array | 实际执行的查询、状态、结果子图、证据 | 空数组 |
| `query_summary` | object | total / answered / partial / insufficient_evidence | — |
| `validation` | object | status、counts、top_failures、graph_checks | — |
| `uncertainty` | array | 覆盖情况、生成 id、未合并、冲突、材料限制、查询限制 | 至少写覆盖情况 |
| `change_log` | array | load / merge / keep_separate / conflict_kept / drop_draft_item / query | — |
| `contract_report` | object | 仅当 `case.json` 声明了 `output_contract` | 省略 |

## `nodes[]`

| 字段 | 说明 |
|---|---|
| `id` | 内容哈希：实例节点含 `source_id`，产品节点不含。重跑不变 |
| `label` | 规范名：优先非缩写、非句首大写、词数多者 |
| `type` | 8 类之一 |
| `identity_scope` | `instance`（某篇的一次实验/观测）或 `product`（共享公共产物） |
| `source_ids` | 出现在哪些篇 |
| `aliases` | 其它写法（同篇合并后保留） |
| `evidence[]` | `{source_id, paragraph_id, quote}`，至少一条 |
| `scope_note` | 仅产品层：说明各篇配置可能不同 |

## `edges[]`

| 字段 | 说明 |
|---|---|
| `id` | 内容哈希（含 source_id 与 paragraph_id） |
| `subject` / `object` | 节点 id |
| `subject_label` / `object_label` | 便于阅读的副本 |
| `predicate` | 13 类之一 |
| `evidence[]` | 至少一条，逐字 |
| `strength` | `{class, weight, attribution}` |
| `conditions[]` | 例如 `site=Incheon port`、`features=three hours` |
| `direction_basis` | 方向依据（触发词类型） |

## `output_contract` 的处理

题面要求：`result.json with all original output_contract fields and case_id`。契约在 `case.json` 里，形状不公开，因此按"输入宽容、输出严格"处理：

1. 读声明字段名：列表、字段描述字典、`{"fields": …}` / `{"required": …}` 包装、能解析成上述任一形态的 JSON 字符串，四种都认。
2. 能对上规范字段 → 复制同一份值（如 `claims` → `edges`）。
3. 能算出来 → 派生（如顶层 `evidence` 从节点/边的证据汇总；`evidence` 里绝不含 `page`）。
4. 对不上 → 写 `null`，并记进 `contract_report.missing` 与 `uncertainty`。

**不做的**：为了让字段非空而编内容；把嵌套对象拍平成字符串；改内部字段名（只改顶层）。

## `status` 的判定

| 值 | 条件 | 读者应怎么用 |
|---|---|---|
| `complete` | 所有元素检查通过，且图级检查通过，且 ≥3 个查询有结果 | 可直接引用，仍建议抽查证据 |
| `partial` | 有失败项、或查询不足、或覆盖偏低 | 只能用通过的部分；失败项在 `validation.items` 里逐条列出原因 |
| `blocked` | 材料不可读（无 JSON、无 XML、解析失败） | 不引用任何结论；按 `reason` 修输入后重跑 |

`partial` 不是失败：它表示"交了一部分，并说清哪部分不可靠"。把 `partial` 当 `complete` 用才是失败。

## 与其他产物的关系

- `graph.json` = `result.json` 的 `nodes/edges/merges/conflicts/stats` 子集，供只读图的程序使用。
- `queries.json` = `result.json` 的 `queries` 全集，供只想看问答的读者。
- `validation.json` = 逐项检查，含每个失败项的 `fix` 建议；比 `result.json` 里的摘要细。
- `graph.mmd` / `nodes.csv` / `edges.csv` = 人读视图，可由前两者完全重建，不承载额外信息。
