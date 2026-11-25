# 身份策略：什么时候合并，什么时候必须不合并

实体对齐是这一类图最容易出错的地方，而且错误不可见：一个错误的合并会在图上造出一条看似合理的假路径，且和真路径长得一样。因此本 Skill 采取**保守合并 + 全部留痕**：合并需要理由，不合并也需要理由。

## 三层决策

### 第 1 层：同篇别名 → 合并（声明 + 自动缩写识别）

同一篇论文里 `Incheon` 与 `Incheon port`、`CSI` 与 `critical success index` 指同一对象。两条来源，`align.py` 都用并查集合并并记录：

1. **草稿声明**：模型在实体的 `aliases` 里声明，`basis: declared_alias_in_same_paper`。
2. **自动缩写识别（v2 新增）**：`extract.detect_abbreviations` 规则扫描原文的 `全称 (缩写)` 声明（`critical success index (CSI)`、`Weather Research and Forecasting (WRF)`），`basis: abbreviation_pattern`，不依赖模型记得声明缩写。全称取「括号前最短的实义词后缀，使首字母按序构成缩写」，避免把 `Sea using the WRF` 里多余的 `Sea using the` 吞进全称。

```json
{"source_id": "PMC8347079", "type": "LOCATION",
 "surfaces": ["Incheon", "Incheon port"],
 "basis": "declared_alias_in_same_paper", "node_id": "n:..."}
```

**不自动猜同义**：`fog` 与 `sea fog` 在原文里是包含关系而非同义，声明为别名就会把两种对象压成一个。别名必须来自原文的括号定义（`real-time global sea surface temperature (RTG-SST)`）或同篇的明确指代；缩写识别只认「首字母按序匹配」的保守校验，类型不一致时记为 `type_conflicts` 留人工复核，不强行合并。

### 第 2 层：跨篇公共产品 → 合并，但只在产品层

满足任一条件才合并：

- 写法是缩写或带版本号（`WRF`、`ERA5`、`SST`、`FNL_1/4°`）；或
- 草稿给出相同的显式标识符（同一 DOI、同一注册号、同一版本串）。

合并后的节点 `identity_scope: product`，并强制带说明：

> 产品级同一性：同名公共方法/数据集/标准量可跨篇共享；各篇的版本、配置与实验条件可能不同，不视为同一实例。

依据：本题材料明确要求"相同通用方法/材料术语不代表两篇使用了相同物理样品、模型实例、数据集或实验条件"。产品层与实例层分开，既能让"两篇都用 WRF"这件事可查，又不会让读者误以为两次模拟是同一个实验。

### 第 3 层：其余 → 不合并，写候选

普通名词、现象名、指标名（`sea fog`、`visibility`）跨篇一律**各留一个实例节点**，并写：

```json
{"a": {"surface": "sea fog", "source_id": "PMC9359529"},
 "b": {"surface": "sea fog", "source_id": "PMC8347079"},
 "basis": "same_surface_only", "decision": "not_merged",
 "reason": "两篇写法相同，但没有共同标识符，也不属于可共享的公共产品；不合并，保留为待人工判定的候选对齐。"}
```

这样做的代价是查询要跨多个节点聚合（`query.py` 已按同名节点聚合，并在 `limitations` 里写明"同名节点有 2 个，分属不同论文，未合并"）。收益是：**没有任何一个合并是悄悄发生的**。

## 类型冲突

同一写法在两篇被标成不同类型（一处 `METHOD`、一处 `LOCATION`），不合并，记 `type_conflicts`，`decision: kept_separate`。常见原因是一个词在该领域是多义词；按类型拆开比按字面合并安全。

## 判定表

| 情形 | 动作 | 记录 |
|---|---|---|
| 同篇、同类型、声明为别名 | 合并 | `merges[].basis = declared_alias_in_same_paper` |
| 同篇、同类型、原文有 `全称 (缩写)` 声明 | 合并 | `merges[].basis = abbreviation_pattern` |
| 跨篇、同为缩写/版本名 | 合并为 `product` | `merges[].basis = public_product_term` |
| 跨篇、显式标识符相同 | 合并为 `product` | `merges[].basis = shared_identifier` |
| 跨篇、普通名词 | 不合并 | `candidate_alignments[].not_merged` |
| 跨篇、类型不同 | 不合并 | `type_conflicts[]` |
| 同篇、不同类型 | 不合并 | `type_conflicts[]` |

## 为什么要留 `candidate_alignments` 而不是直接丢掉

因为"这两个是不是同一个"有时是科学判断，不是字符串判断。把候选和理由写出来，评审可以自己下结论；直接合并或直接丢弃都把这个判断藏起来了。图谱应当保留争议，而不是替读者裁决。

## 增量更新时的行为

节点 id 是内容哈希：实例节点 = `hash(scope|type|source_id|规范名)`，产品节点 = `hash(scope|type|规范名)`。因此：

- 同一篇论文重跑，已有节点编号不变；
- 新增一篇论文，旧节点编号不变，只新增该篇的实例节点；
- 若新论文里出现一个已有产品名（如 `ERA5`），产品节点被复用，`merges` 新增一条记录；
- 若新论文与旧论文出现同名的普通名词，新增实例节点 + 新增 `candidate_alignments` 条目。

`change_log` 逐条记录 `load / merge / keep_separate / conflict_kept / drop_draft_item / query`，可直接用于写增量说明。
