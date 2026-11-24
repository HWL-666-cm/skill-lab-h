# 字段字典与导出结构

三份产物：`result.json`（主结果）、`assertions.trig`（四图 RDF）、`validation.json`（逐条检查）。另有 `repair.json` 是给下一轮改写用的定位信息。

## result.json

| 字段 | 类型 | 说明 |
|---|---|---|
| `case_id` | string | 来自 `/input/case.json` 的 `case_id` 或 `id`，缺省用 PDF 文件名 |
| `status` | string | `pass` / `partial` / `fail` / `blocked`，与 `validation.status` 一致 |
| `task` | string | 固定 `nanopublication-assertion-extraction` |
| `input` | object | `file`、`pages`、`paragraphs`、`sentences` |
| `assertions` | array | 断言列表，一条一个对象 |
| `sources` | array | 来源列表：`name`、`iri`、`doi`、`title`、`year` |
| `validation` | object | `status`、`counts`、`top_failures`、`structure` |
| `uncertainty` | array | 未报告项、无法判断项、材料冲突项，逐条写明 |

## assertions[] 单项

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | string | 是 | 断言标识，建议 `A01` 递增 |
| `text` | string | 是 | AIDA 句，5–500 字符，以句号结尾 |
| `aida` | object | 是 | 四判据布尔值：`atomic`、`independent`、`declarative`、`absolute` |
| `subject` | object | 是 | `label`（完整名词短语）、`type`（词表类型） |
| `predicate` | string | 是 | 受控关系名 |
| `predicate_iri` | string | 是 | `https://w3id.org/np/rel/<RELATION>` |
| `object` | object | 是 | 同 subject |
| `qualifiers` | object | 是 | `scope`（数组）、`polarity`、`population` |
| `evidence.quote` | string | 是 | 逐字原文，5–500 字符 |
| `evidence.quote_end` | string | 否 | 长段落首尾引用时的结束片段 |
| `evidence.page` | int | 是 | 页码，从 1 开始 |
| `evidence.paragraph` | int | 否 | 段号 |
| `evidence.sentence_id` | string | 是 | 形如 `P181S02` |
| `evidence.char_span` | array | 是 | `[起, 止]`，相对全篇规范化文本 |
| `provenance` | object | 是 | `doi`、`title`、`authors`、`year`、`source`；取不到的键省略 |
| `confidence_basis` | string | 是 | 为什么可信：直接引文 / 共现推断 / 被弱化词削弱 / 无直接证据 |
| `relation_type` | string | 是 | `direct` 或 `inferred` |
| `status` | string | 是 | `verified` / `warning` / `failed` / `unchecked` |
| `issues` | array | 是 | 每条 `{code, detail, fix}`，通过时为空数组 |

## validation.json

| 字段 | 说明 |
|---|---|
| `status` | `pass`（无 failed）/ `partial`（有过有不过）/ `fail`（全不过或结构无效） |
| `n_assertions` | 总条数 |
| `counts` | `pass` / `warn` / `fail` 三档计数 |
| `top_failures` | 按出现次数排序的失败代码，用于决定先修哪类 |
| `items[]` | 每条断言的 `id`、`verdict`、`checks`、`fixes` |
| `structure` | `ok`、`n_nanopubs`、`issues`；只在传入 `--trig` 时出现 |

`checks` 的键固定为：`aida`、`quote`、`entities`、`relation`、`trigger`、`scope`、`paste`、`confidence`。每项含 `ok`、`code`、`detail`、`fix`；`quote` 另含 `located_page`、`pid`、`sid`、`char_span`、`sentence_text`。

## assertions.trig

一条断言一个 nanopublication。每条包含四个命名图：

```
<base>/Head        声明 np:Nanopublication 与三个 has* 链接
<base>/assertion   AIDA 句、rdf:Statement 结构化三元组、实体标签
<base>/provenance  断言与来源的 prov 关系、生成活动
<base>/pubinfo     来源、标签、npx:hasNanopubType
```

`base` 是断言内容（`text` + `predicate` + 主宾标签 + `quote`）的 SHA-256 前 12 位，形如 `urn:np:draft:231b21e2ed37`。同样的输入重跑得到同样的 IRI，文件字节一致。

断言图里用到的谓词：

| 谓词 | 用途 |
|---|---|
| `rdf:type hycl:AIDA-Sentence` | 标记这是 AIDA 句 |
| `rdfs:label` | 句子原文 |
| `prov:wasDerivedFrom` | 来源 IRI |
| `cito:hasQuotedText` / `cito:hasQuotedTextEnd` | 证据片段 |
| `cito:quotes` | 引用来源 |
| `rdf:subject` / `rdf:predicate` / `rdf:object` | 结构化三元组（标准 reification） |
| `rel:charSpan` | 字符跨度 |

AIDA 句 IRI 规则：`http://purl.org/aida/` 加句子，空格换成 `+`，末尾句号保留，其余非安全字符百分号编码。

**草稿 IRI 不是 trusty URI，文件未签名。** 要发布必须先签名得到新的 trusty URI，本 Skill 不做签名与发布。

## 与平台契约的对应

题面列出的结构层次与本文件的字段对应如下：

| 题面要求 | 本文件字段 |
|---|---|
| 断言 | `assertions[].text` |
| 主体与关系 | `subject`、`predicate`、`object` |
| 证据片段 | `evidence.quote` |
| 证据位置 | `evidence.page`、`sentence_id`、`char_span` |
| 来源元数据 | `provenance`、`sources` |
| 置信度依据 | `confidence_basis` |
| 标识符 | `assertions[].id`、AIDA 句 IRI、nanopub base |
| 输入标识 | `case_id`、`input` |
| 运行状态 | `status` |
| 不确定性 | `uncertainty` |

若 `/input/case.json` 自带 `output_contract`，`scripts/contract.py` 会把声明的**顶层**字段名补进 `result.json`：

| 情况 | 处理 | `contract_report` 记在哪 |
|---|---|---|
| 名字本身就是规范键（`case_id`、`status`、`uncertainty`…） | 不动 | `native` |
| 名字是同义词（`claims`→`assertions`、`source_metadata`→`sources`） | 复制规范字段的值 | `aliased` |
| 顶层要 `evidence` 一类证据字段 | 从各条断言的 `evidence` 聚合出索引 | `derived` |
| 名字对不上任何字段 | 写 `null`，并追加一条 `uncertainty` | `missing` |

三条硬规则：规范字段一个都不删；对不上的名字**不猜内容**（写 `null` 而不是编造）；断言对象内部键名不变，只在顶层补齐。

契约的原始内容同时原样记进 `candidates.json` 的 `output_contract` 键，便于复核"声明了什么"与"实际给了什么"是否一致。

## 状态取值

| 状态 | 含义 |
|---|---|
| `pass` | 所有断言通过全部检查，结构合法 |
| `partial` | 有断言通过、有断言未通过；结果可用但要按 `repair.json` 修 |
| `fail` | 无断言通过，或 TriG 结构无效 |
| `blocked` | 输入不可用：找不到 PDF、无文本引擎、声明文件缺失 |
