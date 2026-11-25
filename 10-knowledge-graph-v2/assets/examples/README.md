# 示例说明

| 文件 | 内容 |
|---|---|
| `case.json` | 输入形状示例（含 `output_contract` 的写法）。路径由运行时替换，本文件不含答案 |
| `result.json` | 一次真实运行的完整结果：32 节点、21 边、2 组别名合并、2 组未合并候选、0 冲突、5 个查询 |
| `graph.json` | 同一张图，便于只读 |
| `queries.json` | 5 个查询的执行结果（4 个有答案，1 个明确答不了） |

材料为两篇 CC-BY 4.0 论文的 JATS 正文，出处见 `result.json` 的 `sources`。

**这是示例，不是平台固定案例的结果。** 复现方式见 `SKILL.md` 的"流程"一节。

## v2 增量（相对本示例的 v1 版本）

- 别名合并新增**自动缩写识别**（`basis: abbreviation_pattern`），不再只靠模型在草稿里声明；示例 `result.json` 是 v1 快照，未包含该 basis，但同一批材料重跑会自动多出 `全称 (缩写)` 的合并记录。
- `change_log` 每条 `load` 带 `role`（primary/secondary），并新增 `incremental_note` 说明节点 id 的内容哈希稳定性。
- 自测新增 10 项：缩写识别（3）、增量编号稳定（3）、增益对照（4），合计 44 项全过（`python assets/tests/run_selftest.py`）。
