# 输出契约与状态机

## `result.json` 结构

| 字段 | 类型 | 含义 |
|---|---|---|
| `case_id` | string | 来自 `case.json`，原样回填 |
| `status` | string | `complete` / `partial` / `blocked` / `incomplete` |
| `limits` | string[] | `status != complete` 时必须非空，逐条说明缺什么 |
| `task` | object | 方向与交付物清单 |
| `methods_markdown` | string | 原稿逐字 + 末尾「数值出处对照」表 |
| `ledger` | object | 台账：`entries[]`、`conflicts[]`、`multi_scope[]`、`stats` |
| `alignment` | object | 前向七类 + 后向三态 + `coverage` 七要素 |
| `gaps` | object | `gaps[]`、`counts`、`by_severity`、`blocking[]` |
| `conflicts` | array | 台账冲突（与 `ledger.conflicts` 同源，便于顶层读取） |
| `coverage` | object | 七要素各自的 `written`/`not_written`/`text_signal`/`checked_by` |
| `validation` | object | `status`、`counts`、`checks[]`、`top_failures[]` |
| `sources` | array | 每个材料文件的路径、种类、读数方式、行数 |
| `uncertainty` | string[] | 读不到的文件、编码不可靠、只有散文的值、未写行数…… |
| `change_log` | array | A/B/C/D 分级：改了什么、依据是什么 |
| `stats` | object | 文件数、不可读数、台账行数、冲突数、正文数字数、溯源率 |

`output_contract` 中声明的字段会按四种形状解析（数组、`{fields}`、`{名:描述}`、`[{name}]`），并做别名映射（`parameters→ledger`、`evidence→evidence_index`、`draft→methods_markdown` 等）。未声明的字段不凭空生成；声明了但本 Skill 没有的字段置 `null` 并写入 `contract_report.missing`。

## 状态机

```
                    ┌─ 有 fail ────────────────► fail
24 项检查 ──────────┼─ 有 not_checked（无 fail）─► incomplete
                    ├─ 有 warn（无上述两者）────► warn
                    └─ 全 pass ─────────────────► pass

交付状态：有阻断缺口 → partial/blocked
         无阻断但门禁 fail → partial
         门禁 warn 或 incomplete → complete + limits 里写明
```

**`not_checked` 永远不计为 pass。** 这是四态设计存在的唯一理由：三态会逼出一个安静的谎。

## 台账状态

`confirmed` / `manuscript_only` / `conflicting` / `prose_multi_value` / `weak_source`，详见 `source-grades.md`。

## 缺口类型

| `kind` | 默认严重度 | 来源 |
|---|---|---|
| `invented_number` | 阻断 | 正文数字在材料中不存在 |
| `conflicting` | 阻断 / 重要 | 台账冲突；硬-硬为阻断，硬-散文为重要 |
| `unparsed_material` | 阻断 | 材料文件读不出来 |
| `value_mismatch` | 重要 | 点名参数但值不符 |
| `not_written` | 重要 / 次要 | 台账有行正文没写；训练设置类为重要 |
| `manuscript_only` | 重要 | 只有散文来源，无硬来源 |
| `ambiguous_value` | 次要 | 值存在但归属不明 |
| `weak_source` | 次要 | 来源等级不足 |
| `missing_element` | 重要 | 七要素缺 steps/baseline/repro/limits |
| `boilerplate_limit` | 重要 | 局限写成套话 |

每条缺口必须同时有 `what`（是什么）、`where`（在哪）、`why`（缺了会怎样）、`ask`（要问作者什么）。`why` 不许写成"受限于数据质量"这类模板——那正是 `boilerplate_limit` 要抓的东西。

## 字节确定性

同一输入两次运行，以下四个文件必须 sha256 完全一致：

- 不写时间戳（`no_timestamp_in_draft` 会检查正文里有没有 `20xx-xx-xxTxx:xx`）
- 实体 id 用内容哈希（`e`/`p`/`g` + sha256 前 10–12 位），不依赖遍历顺序
- JSON 统一 `ensure_ascii=False`、`indent=2`、显式 `\n` 换行
- 排序键一律显式给出（名称、作用域、路径、行号），不依赖字典插入顺序
