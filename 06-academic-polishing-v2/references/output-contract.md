# 输出契约：如何与平台 `output_contract` 对齐

平台在 `/input/case.json` 里可能自带 `output_contract`（字段名、类型、是否必需）。**以它为准，本 Skill 的字段是补充，不是替代。** 合并顺序如下。

## 1. 合并规则（按优先级）

| 优先级 | 来源 | 处理方式 |
|---|---|---|
| 1（最高） | `case.json` 的 `output_contract` | 逐个字段产出；字段名、层级、类型照抄；`required: true` 的缺一个就算 `status=partial` |
| 2 | `case.json` 的其他约束（`genre`、`audience`、`word_limit`、`format`） | 作为生成约束写进 `assumptions` 并在产物中执行 |
| 3 | 本 Skill 的默认字段（见 SKILL.md 第 5 节） | 平台没定义的才补，**不覆盖**平台定义 |

**判据**：`result.json` 的顶层必须有 `case_id`，且 `output_contract` 里的每个必需字段在顶层或其指定路径下都能取到。

这一步由 `make_result.py` **实际执行**，不是人工自检：调用时传 `--case-json /input/case.json`，脚本读取契约、按 `CONTRACT_ALIASES` 把默认字段补成平台字段名，把结果写进 `result.json` 的 `output_contract_alignment`（含 `filled_from_aliases`、`missing_required`）；只要有 `required: true` 的字段补不出来，`status` 自动降为 `partial`。**不要手工往 result.json 里加字段来"通过"检查**——那会绕过契约校验，评审看不到真实的缺项。

```bash
python3 scripts/make_result.py --case-id <CASE_ID> --case-json /input/case.json \
  --revised /app/work/revised.txt --changes /app/work/changes.json \
  --audit /app/work/facts_after.json --terms /app/work/terms_after.json \
  --task-items /app/work/task_items.json --out /app/output/result.json
```

## 2. 本 Skill 字段与常见 `output_contract` 字段的对应

| 平台常见字段 | 本 Skill 里从哪来 | 注意 |
|---|---|---|
| `revised_text` / `polished` / `final_text` | `target_deliverable.path` 指向的 `polished.md` 全文 | 同时内联进 `result.json`，别只给路径——评审可能只读 JSON |
| `changes` / `edit_log` / `diff` | `change_log` | 每条必须含 `original`/`revised`/`type`/`reason` 四要素 |
| `glossary` / `terminology` | `term_table` | 至少含 `concept`/`preferred`/`variants_found` |
| `evidence` / `sources` | `fact_map` | 数字与引用逐条，标明是否被改动 |
| `uncertainty` / `notes` | `uncertainties` | 材料缺口、冲突、需人工确认项 |
| `task_coverage` / `task_items` | `task_coverage` | 每条任务项的 `done`/`pending`，对应"结果完整性" |
| `status` | `status` | 只能是 `ok` / `partial` / `failed` |

`revised_text` 同时内联进 `result.json` 顶层（值就是改稿全文），不只放在 `target_deliverable.path`——评审可能只读 JSON，不打开文件。

## 3. 三种失败情形的写法

| 情形 | 写法 | 不能做什么 |
|---|---|---|
| 输入缺失（读不到 `case.json` 或正文） | `status="failed"`，`uncertainties` 写清缺什么 | 不能凭空生成一段文本冒充结果 |
| 只做了一部分（超长/分块未完成） | `status="partial"`，`limitations` 写清剩下哪几段 | 不能把 partial 写成 ok |
| 材料自相矛盾（如术语表两处冲突） | 两说都保留，写进 `uncertainties`，请作者裁定 | 不能自己选一个当"正确答案" |

## 4. 产物落盘位置

| 文件 | 路径 | 说明 |
|---|---|---|
| 结构化结果 | `/app/output/result.json` | 必需，含 `case_id` |
| 可编辑改稿 | `/app/output/polished.md` | 必需，正文全文 |
| 修改清单 | `/app/output/changes.csv` | 由 `make_result.py` 自动生成 |
| 审计报告 | `/app/output/audit_hedge.json`、`audit_terms.json` | 建议保留，作为"没改坏"的证据 |

## 5. 一个容易犯的错

把 `result.json` 写成"对本次运行的说明"（"我做了 A、B、C"）而不是"本次运行的结果"。评审要的是**能直接拿去用的文本 + 能逐条回溯的修改记录**，自述性文字不算得分项。
