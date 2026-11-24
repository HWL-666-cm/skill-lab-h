---
name: 10-knowledge-graph
description: "把一组真实论文（JATS 正文或平台给的 material.json）抽成带证据的文献知识图谱：每个节点和每条边都能回到 source_id + paragraph_id 和逐字原文，跨篇同名术语按显式策略决定合不合并（合并只在产品层并留记录，其余记为待判定），同一主张在不同条件下的数值并列保留、不取平均，最后交付可查询的 result.json / graph.json 与至少 3 个真实查询结果。用户说\"把这两篇论文做成知识图谱\"\"抽取实体和关系并给出原文依据\"\"同一个术语在两篇里是不是同一个对象\"\"每个节点每条边都要能回到原文\"\"给我几个能实际跑的图谱查询\"\"新论文加进来时保留已有编号\"时使用。"
version: 1.0.0
agent_created: true
---

# 文献知识图谱：抽得准、连得对、对得齐、回得去

把两篇（或多篇）论文转成一张能追问、能回查的图。四件事各有一个把关点：实体是否真在原文出现、关系方向是否与原文一致、同名对象是否该合并、每个节点和边能否回到具体段落和原句。

不追求把图谱做全，追求**每一条边都站得住**：宁可少抽，也不让推测、共现和转述混进图里。

## 何时用

- "把这两篇论文做成知识图谱""抽取实体和关系，并给出原文依据"
- "同一个术语在两篇里是不是同一个对象""别把不同实验的对象合并"
- "每个节点、每条边都要能回到原文""这条边出自哪一段"
- "给我几个能实际跑的查询，要带证据"
- "新论文加进来，保留已有节点编号，说明新增/合并/冲突"

**不适用**：只问单篇内容摘要（用阅读/问答类 Skill）；只要文献列表和引用格式（用引用管理类 Skill）；要求图像像素、补充附件或底层实验数据（本材料不含）。

## 输入

平台在运行时把材料放在 `/input`，通常是：

| 文件 | 内容 | 本 Skill 的用法 |
|---|---|---|
| `corpus-manifest.json` | 每篇的 DOI、作者、来源哈希、许可证 | 写进 `sources`，许可证缺失也照实记，不猜 |
| `material.json` | 全部论文的段落总索引 | 主入口，优先读它 |
| `primary-material.json` / `secondary-material.json` | 分篇材料 | 没有总索引时按篇读 |
| `case.json` | `case_id`、材料路径、可能的 `output_contract` | 决定输出字段名 |

读取器对字段名是宽容的：`sources/papers/documents/items`、`paragraphs/paras/blocks`、`text/content/body`、`paragraph_id/pid/id` 都能认。**只有 JATS XML 时也能直接读**，按 `<sec>` 路径、`<abstract>`、`<caption>` 切段。

两条硬规矩：

1. **位置只用 `source_id + paragraph_id`。** 题面明确：位置是组织方 JATS 段落 ID，不是 PDF 页码。材料里没有 PDF 页码，任何 `page` 字段都会被校验器判失败——包括"自建第 1 页"。
2. **段落没有 id 时生成稳定 id，并标 `id_source: generated`。** 生成不等于伪造：`uncertainty` 里会写明哪几篇的 id 是生成的，评审能分清哪些来自出版方、哪些来自本工具。

若只拿到 PDF：先用环境提供的 pdf-text-tool 转成"篇-段"文本 JSON，再交给本 Skill；本 Skill 不内置 PDF 解析，避免把版面判断混进证据链。

## 本体（先定义，再抽取）

`assets/schema.json` 固定 8 类实体、13 类关系，每个关系都有定义域/值域：

- 实体：`PHENOMENON` 现象、`METHOD` 方法、`DATASET` 数据、`VARIABLE` 变量或指标、`LOCATION` 地点、`TIME_PERIOD` 时段、`VALUE` 数值、`PERSON` 研究者。
- 关系：`APPLIES_METHOD`、`TARGETS`、`EVALUATES`、`ACHIEVES`、`CAUSES`、`ASSOCIATED_WITH`、`IMPROVES_ON`、`OCCURS_AT`、`OBSERVED_DURING`、`MEASURED_BY`、`PART_OF`、`DEFINED_AS`、`CONTRADICTS`。

三条不许破的规则：

1. **没有 `RELATED_TO` 兜底。** 写不出具体动词就不建边。`ASSOCIATED_WITH` 只能用于原文确实只表达"相关/共变"的句子，且它的权重低于因果。
2. **`CAUSES` 只用于原文明确的因果**，同句共现不算。反向表述（`due to`、`caused by`、`attributed to`、`formed by`）要把原因放在主语侧。
3. **要扩展本体**（例如材料里有"订正""同化"这类新关系）就在 `schema.json` 里加类型并写清 domain/range，再重跑；不要在草稿里临时造谓词——校验器会按 `unknown_predicate` 拒绝。

## 身份策略（本题的核心）

字面相同不等于同一对象。策略分三层，全部留痕：

1. **同篇别名合并**：一篇里 `Incheon` 与 `Incheon port`、`CSI` 与 `critical success index` 若在草稿里声明为别名，用并查集合并为一个节点，记录 `basis: declared_alias_in_same_paper`。
2. **跨篇只在"产品层"合并**：缩写、带版本号的公共产物（`ERA5`、`WRF`、`SST`）或显式标识符一致时，合并为一个 `identity_scope: product` 节点，并写 `scope_note`：各篇的版本、配置、实验条件可能不同，不视为同一实例。`merges` 里逐条记录 `basis` 与涉及篇目。
3. **其余一律不合并**：普通名词、现象名、指标名（`sea fog`、`visibility`）跨篇保留为**每篇一个** `instance` 节点，同时写一条 `candidate_alignments`：`decision: not_merged`，附理由"没有共同标识符，也不属于可共享的公共产品"。

类型不同但写法相同时（一处当方法、一处当地点），拆成两个节点并记 `type_conflicts`。**不强迫每个别名都合并，也不让字面相同的两个对象悄悄变成一个。**

## 证据规则

- **逐字**：`quote` 必须是所引段落里连续的一段原文。跨句时用 `…` 分成片段，每段都要逐字命中且顺序一致；校验器记 `contiguous: false`。
- **可定位**：`source_id + paragraph_id` 必须能在材料里找到；找不到即 `paragraph_not_found`。
- **两端在引文中**：主语和宾语的写法（含别名）都要出现在同一段引文里，否则只算"端点缺席"，降为警告。
- **数值有出处**：`VALUE` 节点里的每个数字都要在引文中出现，否则 `fabricated_number`。
- **证据强度按来源定，不按作者意愿定**：

| 类别 | 权重 | 含义 | 判定 |
|---|---:|---|---|
| `own_result` | 0.9 | 本文自己的结果 | 有第一人称或 `this study`，且无引用标记 |
| `own_method` | 0.8 | 本文采用的方法/配置 | 同上 |
| `review` | 0.5 | 领域常识式陈述 | "generally/typically" |
| `cited` | 0.4 | 转述他人工作，不能当本文结论 | 有 `[n]`、`et al.`、`previous studies` |
| `hypothesis` | 0.2 | 推测 | "may/might/could/suggest" |
| `background` | 0.3 | 背景铺垫 | 以上都不命中 |

  引用标记挂在工具版本上（`WRF (v.3.9.1.1: [24])`）且句中有第一人称时，仍算本文方法；句中没有第一人称却标成本文结果，判 `strength_overclaim`。

## 冲突与条件

- **先按条件分组，再判冲突。** 同一主语、同一关系、同一组 `conditions`（地点、时段、预测时长、变量）下出现不同值，才记 `conflicts`；条件不同的两个数值只是"不同条件下的结果"，不得互相覆盖、不得取平均。
- 冲突两侧都保留：`sides` 里各带 `source_id`、`paragraph_id`、`quote`，`resolution: kept_both`。
- 同一对实体出现相反因果方向时记 `direction_conflict`，不合并成一条无向边。
- **没发现冲突要说"没发现"**，并注明"未记录不等于不存在"。

## 流程

```bash
# 0) 看一眼材料结构（可选）
python scripts/materials.py --case /input/case.json

# 1) prepare：切段、切句、提候选（不做判断）
python scripts/run_case.py --case /input/case.json \
  --lexicon assets/lexicon.json --schema assets/schema.json \
  --out /app/output --stage prepare
# 产出 parsed.json / candidates.json：候选提及带字符跨度与所在段落

# 2) draft：写草稿（由模型或人按 schema 写，字段见下）
#    允许的写法：只用 candidates.json 里出现过的原句作 quote

# 3) finish：组装、对齐、查询、校验、导出
python scripts/run_case.py --case /input/case.json \
  --lexicon assets/lexicon.json --schema assets/schema.json \
  --out /app/output --stage finish --draft /app/work/draft.json
```

没有模型时可用 `--stage auto` 走纯规则草稿：精度优先、召回低，产出会标 `status: partial`，并在 `uncertainty` 里写明覆盖不足。**auto 是下限，不是推荐路径。**

草稿格式（最小）：

```json
{
  "entities": [
    {"key": "a", "surface": "sea fog", "type": "PHENOMENON", "source_id": "PMC9359529",
     "paragraph_id": "p007", "quote": "In this study, the numerical model WRF ... sea fog simulation.",
     "aliases": [], "identifier": null, "scope": "instance"}
  ],
  "edges": [
    {"subject": "a", "predicate": "APPLIES_METHOD", "object": "b",
     "source_id": "PMC9359529", "paragraph_id": "p007", "quote": "...",
     "strength": {"class": "own_method", "weight": 0.8, "attribution": "this_paper"},
     "conditions": ["variable=SST"]}
  ],
  "queries_spec": [
    {"id": "Q1", "type": "method_comparison", "phenomenon": "sea fog",
     "question": "哪些方法被用于 sea fog，各自报告了什么？"}
  ]
}
```

## 查询

`scripts/query.py` 在图谱上真跑，不返回套话。五类模板：

| 类型 | 回答什么 | 不能回答时 |
|---|---|---|
| `entity_profile` | 某名称的全部节点、关系与证据 | 无此节点 → `insufficient_evidence` |
| `path` | 两实体间 ≤3 跳的证据路径 | 无路径 → 明确说"共现不等于关系" |
| `method_comparison` | 同一现象下各方法及其数值 | 跨篇数值 → `comparable: false` 并说明原因 |
| `conflicts` | 冲突结论与未决同名合并 | 无 → "未发现"且注明不等于不存在 |
| `negative` | 材料不支持的问题 | 一律 `insufficient_evidence`，不推断 |

`queries_spec` 为空时自动生成 3~5 个查询。**至少 3 个查询要有真实结果与证据 id**，否则 `queries_executed` 不过。

## 输出

写到 `--out`（平台约定 `/app/output`）：

| 文件 | 内容 |
|---|---|
| `result.json` | `case_id`、`status`、`input`、`sources`、`graph.stats`、`nodes`、`edges`、`merges`、`candidate_alignments`、`conflicts`、`queries`、`validation`、`uncertainty`、`change_log` |
| `graph.json` | 同一张图的独立副本，便于只读图 |
| `queries.json` | 查询、状态、结果子图、证据 |
| `validation.json` | 逐项检查与原因、修复建议 |
| `graph.mmd` | mermaid 视图，便于人看 |
| `nodes.csv` / `edges.csv` | 表的形态，便于抽查与二次处理 |

`status` 三态：`complete`（校验全过）、`partial`（有失败项或覆盖不足，失败项保留并说明）、`blocked`（材料不可读，写明原因且不编内容）。

`result.json` 的字段名遵守 `case.json` 里的 `output_contract`：能对上的直接复制同名值，能从图里算的派生（如 `evidence` 由节点/边证据汇总），对不上的写 `null` 并记入 `uncertainty` 与 `contract_report.missing`。**不为了填满字段而编内容。**

## 异常处置

| 情况 | 处置 |
|---|---|
| 材料缺失或无法解析 | `status: blocked`，写清尝试过的路径与原因，不出空图 |
| 只有 JATS XML、无段落 id | 生成稳定 id 并标 `generated`，不宣称是出版方 id |
| 实体同名 | 按身份策略处理：产品层合并并记录，其余不合并并记录 |
| 关系证据冲突 | 两侧并列保留，写 `conflicts`，不选边 |
| 查询无结果 | `insufficient_evidence` + 原因，不用相邻内容凑答案 |
| 草稿条目无法入图 | 记 `dropped` 与原因，不静默丢弃 |
| 输出目录已有文件 | 只覆盖本 Skill 生成的那 7 个文件名，不动其他文件 |

## 自检

```bash
python assets/tests/run_selftest.py       # 34 项：证据匹配、身份策略、条件冲突、方向、页码、契约、确定性
python scripts/validate.py --graph /app/output/graph.json --case /input/case.json \
  --schema assets/schema.json --out /app/output/validation.json   # 单独复检已有图
```

同一输入两次运行，7 个产物字节一致；不一致说明混入了时间戳或随机顺序。

## 运行环境

- Python 3.9+，脚本只用标准库。
- 不联网、不写原始材料、不调用外部服务。
- 不依赖图数据库：图是 JSON，查询在内存里跑，评审可直接读文件复核。

## 最小示例

`assets/examples/` 有一组完整示例：`case.json`（输入形态）、`result.json`（一份带 `example: true` 标记的两条边结果）、`queries.json`。示例只说明接口与字段形状，**不是平台固定案例的答案**。

## 已知边界

- 规则抽取召回偏低（真实语料上约每百句 1~2 条边），覆盖率写在 `uncertainty`，不假装抽全。
- 证据要求连续命中：跨页、跨栏被切断的句子必须拆成两条。
- 表格单元格、图内像素、补充附件不能作证据；`caption` 只作现象/配置级证据。
- 中文材料的指代消解弱于英文，中文案例要人工复核合并决定。
- 不做本体推理与链路补全：图里没有的边就是没有，不预测。
