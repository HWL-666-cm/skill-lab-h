# 失败模式：真实文献里的案例，以及本 Skill 用哪一条拦住

这些不是凭空列举，来源见文末。每条写清"错在哪、为什么常见、本 Skill 的拦截点"。

## 1. 同义词塌缩（synonymy collapse）

同一个缩写指向多个对象：`AD` 可以是 Alzheimer's Disease、Atopic Dermatitis、Actinomycin D、Admitting Diagnosis。把它们合并成一个节点，图会变整洁，然后任何涉及其中一个的问题都会得到"自信的胡说"。

**为什么常见**：合并看起来像是在做去重，实际是在做一次有损压缩，而损失在拓扑上不可见——合并后的节点多出几条看似合理的假路径。

**拦截**：跨篇只在产品层（缩写、版本名、显式标识符）合并；普通名词一律不合并并写 `candidate_alignments`；类型冲突单独记录。校验项 `split_identity_explained` 会检查"同名但分属不同篇"的节点是否有解释记录。

## 2. 字面相同但实体类型不同

`APC` 既可能是基因 `adenomatous polyposis coli`，也可能是疾病 `atrial premature complex`。同一写法不同语义，合并即错。

**拦截**：`type_conflicts` 记录 + 按类型拆节点；`signature` 检查拒绝跨类型的边。

## 3. 证据没有强度（evidence without strength）

一条来自预印本单句的关系，和一条被二十篇综述与三期试验支持的关系，若边权相同，下游会把推测当事实。这是"图上的幻觉"最常见的来源：检索层没错，是图本身从未分强度。

**拦截**：每条边强制带 `strength`（6 类，0.2–0.9）与 `attribution`；`cited` 不能标成 `own_result`（`strength_overclaim`）。

## 4. 共现当因果

同一句里出现两个实体，就被抽成一条关系。生物医学抽取的实测里，`cause` 关系的精确率只有约 0.51，错误主要来自"同句共现"和"关系其实发生在别的实体之间"。

**拦截**：`CAUSES` 只在出现明确因果触发词时建立，`ASSOCIATED_WITH` 承担"只有相关"的情形且权重更低；方向由触发词位置决定，`due to / caused by / attributed to` 要求原因在后（`direction_error`）。

## 5. 实体抽取不完整导致关系错位

词典法或通用 NER 常把复合实体切碎：`Cu-Sn/Fe-based coating` 被识别成 `Cu`、`Sn`、`Fe` 三个实体，后续关系就挂错了对象。部分抽取还会让关系在错误的两个实体之间建立。

**拦截**：`label_in_source` 检查"节点名是否真的出现在所引段落"；`endpoint_not_in_quote` 检查两端是否同句；`dropped` 记录所有无法入图的草稿条目。这一条也解释了为什么本 Skill 的规则抽取刻意低召回：宁可少抽，不要把切碎的名词建节点。

## 6. "sameAs 不可传递"被当成可传递

对齐不是把重复项折叠掉，而是断言"这两条记录指同一对象"。这个断言本身是一条可错、可争议、可修订的主张。若直接覆盖合并，事后发现合错（两条细胞系其实不同、两个化合物差一个手性中心）就只能做取证式回滚。

**拦截**：合并必须带 `basis` 与 `members`，节点 id 用内容哈希（可重建）；不合并也写理由。对齐结果与图分开存（`merges` / `candidate_alignments`），撤销一次合并不需要重建整张图。

## 7. 数值被静默平均或择一

两个来源对同一属性给出不同值（不同熔点、不同 IC50、同一模型在两个站点的 R²），若图上只留一个数，读者无从知道存在分歧。

**拦截**：冲突检测按 `(主语, 关系, 条件集合)` 分组；同条件不同值 → `conflicts` 并列保留两侧证据；条件不同 → **不判冲突**（两个站点的 R² 0.99 / 0.97 不是矛盾，是两个条件下的结果）。这条分界是实测修出来的：早期版本按 `(主语, 关系)` 分组，把不同站点的结果误判成冲突。

## 8. 图回答不了的问题，被硬答

最伤的是"schema 里根本没建模那个关系"或"那个实体类型没抽"，而这一点通常在基础设施建好之后才发现。

**拦截**：先从查询反推 schema（本 Skill 的五类查询模板就是最小查询集）；`negative` 查询一律返回 `insufficient_evidence` 并说明原因；`query_results_exist` 检查查询结果引用的节点/边确实存在于图中，不允许返回不存在的 id。

## 9. 自造位置

把"我生成的第 1 页"写成原文页码，或把段落序号写成页码，是这类任务里最常见的造假，且看起来无害。

**拦截**：题面口径是"位置 = 组织方 JATS 段落 ID"；`no_page_field` 检查任何 `page` 字段，`invented_page` 直接失败；段落 id 缺失时生成并标 `id_source: generated`，在 `uncertainty` 里公开。

## 10. 只报"成功"的运行状态

把失败、部分完成、无法判断都写成"完成"，评审无法区分"抽到 3 条"和"只抽到 3 条"。

**拦截**：`status` 三态（complete / partial / blocked）+ `uncertainty` 必须写覆盖情况（例如"11/124 段提供了至少一条关系证据"）+ `validation.top_failures` 原样保留。

---

## 来源

- Upmanyu, S. *Four failure modes of knowledge graphs over messy literature.*（同义词塌缩、证据无强度、时间漂移、schema 答不了的问题）https://sanatanupmanyu.com/blog/knowledge-graphs-failure-modes
- SciXa. *Assembling Knowledge Graphs for Discovery: Construction Pipelines and Their Failure Modes.*（sameAs 不可传递、冲突边与 survivorship）https://scixa.com/article?slug=knowledge-graph-assembly
- Westergaard, D. et al. *From language models to large-scale food and biomedical knowledge graphs.* PMC10185525.（cause 关系精确率约 0.51，共现与"关系发生在别的实体之间"是主要错误源）
- Bravo, À. et al. *Extraction of relations between genes and diseases from text…* BMC Bioinformatics 2015.（缩写歧义：`APC` 基因/疾病；基因标准化精确率从 48.1% 提升到 74.0% 靠缩写-全称对齐）https://doi.org/10.1186/s12859-015-0472-9
- HMEA: *A hierarchical medical knowledge graph entity alignment model…*（`TG` = triglycerides / thyroglobulin 等多义词）https://www.sciencedirect.com/science/article/pii/S093336572500123X
- 东南大学《知识图谱》课程（S11 公开 Skill 的源）：融合三阶段、合并策略、自动合并阈值。https://github.com/npubird/KnowledgeGraphCourse
