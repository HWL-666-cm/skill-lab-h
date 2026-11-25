# 字段字典与导出结构

三份产物：`result.json`（主结果）、`assertions.trig`（四图 RDF）、`validation.json`（逐条检查）。断言由 Agent 以**嵌套字段**写进 `/app/work/nanopubs.json`，`emit.to_legacy_claim()` 转成四图渲染所需格式。

## nanopubs.json 断言单项（Agent 填写，嵌套命名）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | string | 是 | 断言标识，`A01` 递增 |
| `assertion.subject` | string | 是 | 主体名词短语（如 `BERT LARGE`） |
| `assertion.predicate` | string | 是 | 受控关系名，小写，取自 `resources/predicates.json` 的 `relations` 键（16 个） |
| `assertion.object` | string | 是 | 客体名词短语（如 `80.5 GLUE score`） |
| `assertion.subject_type` | string | 否 | 显式类型（纠正自动猜测，如 `CQL`→`METHOD`）；留空则按标签自动猜 |
| `assertion.object_type` | string | 否 | 显式类型（如 `MDP tuple`→`ENTITY`）；留空则按标签自动猜 |
| `assertion.condition` | string | 否 | 限定条件/适用范围（如 `on GLUE benchmark`） |
| `assertion.negation` | bool | 是 | 是否否定 |
| `assertion.modality` | string | 是 | `fact` / `claim` / `hypothesis` |
| `evidence.quote` | string | 是 | 逐字原文，最短支撑片段 |
| `evidence.location.section` | string | 否 | 章节（如 `4.1`） |
| `evidence.location.page` | int | 是 | 页码，从 1 开始 |
| `evidence.location.line` | int | 否 | 视觉行 id |
| `evidence.evidence_type` | string | 是 | `direct`（直接陈述）/ `indirect`（需推理） |
| `provenance.wasDerivedFrom` | object | 否 | `paper`、`section`、`page` |
| `pubinfo.paper` | string | 是 | 论文标题 |
| `pubinfo.authors` | array | 否 | 作者列表 |
| `pubinfo.year` | int | 否 | 年份 |
| `pubinfo.version` | string | 否 | 版本（如 `v2`） |
| `pubinfo.identifier` | string | 是 | DOI / arXiv / URL |
| `confidence.basis` | string | 是 | 为何可信：直接引文 / 共现推断 / 被弱化词削弱 |
| `confidence.level` | string | 是 | `high` / `medium` / `low` |

## 嵌套 → 四图转换（emit.to_legacy_claim）

| 嵌套字段 | 四图/legacy 字段 |
|---|---|
| `assertion.subject`（string） | `subject = {"label", "type"}`（type 优先取 `subject_type`，否则由 entity_types 词表 cue 猜出） |
| `assertion.predicate`（小写） | `predicate`（转大写，如 `achieves` → `ACHIEVES`） |
| `assertion.object`（string） | `object = {"label", "type"}`（type 优先取 `object_type`，否则猜出） |
| `assertion.condition` | `qualifiers.scope[]` |
| `assertion.negation` | `text` 中加 `does not`，`qualifiers.polarity` 记 loss |
| `evidence.location.page` | `evidence.page` |
| `evidence.location.line` / `sentence_id` | `evidence.sentence_id`（validate 定位后回填） |
| `pubinfo.identifier` | `source.iri`（`prov:wasDerivedFrom` 指向它） |
| `pubinfo.paper` / `authors` / `year` | `source.name` / `sources[]` / `provenance` |

## result.json 顶层结构

| 字段 | 类型 | 说明 |
|---|---|---|
| `case_id` | string | 来自 `/input/case.json` 的 `case_id` 或 `id` |
| `status` | string | `pass` / `partial` / `fail` / `blocked`；与 `validation.status` 一致 |
| `task` | string | 固定 `nanopublication-assertion-extraction` |
| `input` | object | `file`、`pages`、`paragraphs`、`sentences` |
| `assertions` | array | 断言列表，一条一个对象（含 text/aida/subject/predicate/object/qualifiers/evidence/provenance/confidence_basis/relation_type/status/issues） |
| `sources` | array | `name`、`iri`、`doi`、`title`、`year` |
| `validation` | object | `status`、`counts`、`top_failures`、`items[]`、`structure` |
| `uncertainty` | array | 未报告项、无法判断项、材料冲突项 |
| `contract_report` | object | `declared`、`native`、`aliased`、`derived`、`missing` |

`assertions[]` 单项经 `emit.build_assertions()` 生成，字段见 v1 约定：`id`、`text`（AIDA 句）、`aida`（四判据布尔值）、`subject`/`object`（`{label,type}`）、`predicate`（大写）、`predicate_iri`、`qualifiers`、`evidence`（`quote`/`page`/`sentence_id`/`char_span`）、`provenance`、`confidence_basis`、`relation_type`、`status`、`issues`。

## assertions.trig（四图 RDF）

一条断言一个 nanopublication，四条命名图：`<base>/Head`、`<base>/assertion`、`<base>/provenance`、`<base>/pubinfo`。`base` 是断言内容（text + predicate + 主宾标签 + quote）的 SHA-256 前 12 位，形如 `urn:np:draft:231b21e2ed37`；同样输入重跑字节一致。

断言图谓词：`rdf:type hycl:AIDA-Sentence`、`rdfs:label`、`prov:wasDerivedFrom`、`cito:hasQuotedText` / `cito:hasQuotedTextEnd`、`cito:quotes`、`rdf:subject/predicate/object`、`rel:charSpan`。

**草稿 IRI 不是 trusty URI，未签名；发布前须先签名得到新 trusty URI，本 Skill 不做签名。**

## output_contract 补齐（contract.py）

若 `/input/case.json` 自带 `output_contract`，`contract.py` 把声明的顶层字段名补进 `result.json`：

| 情况 | 处理 | 记在 |
|---|---|---|
| 名字本身是规范键（`case_id`、`status`、`uncertainty`…） | 不动 | `native` |
| 名字是同义词（`claims`→`assertions`、`source_metadata`→`sources`） | 复制规范字段值 | `aliased` |
| 顶层要 `evidence` 一类证据字段 | 从各断言 `evidence` 聚合索引 | `derived` |
| 名字对不上任何字段 | 写 `null`，追加 `uncertainty` | `missing` |

三条硬规则：规范字段不删；对不上的名字不猜（写 `null`）；断言对象内部键名不变，只在顶层补齐。

## 状态取值

| 状态 | 含义 |
|---|---|
| `pass` | 有断言且全部通过校验，TriG 结构合法 |
| `partial` | 无断言（骨架阶段）或部分断言未过 |
| `fail` | 输入不可用、断言全不过、或 TriG 结构无效 |
| `blocked` | 找不到 PDF / 无文本引擎 / 声明文件缺失 |

**不变量：`assertions` 为空或 `assertions.trig` 为空时，绝不写 `pass`。**
