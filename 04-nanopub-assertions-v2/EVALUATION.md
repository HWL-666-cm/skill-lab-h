# 阅读14｜Nanopublication —— 本地验证与评估报告

> 本报告为本 Skill 在自建验证语料上的**确定性组件**实测结果。正式 3 案例与断言内容质量由平台运行产生，此处不冒充正式成绩。

## 1. 验证语料（自建）

| 文档 | 页 | 用途 |
|-|-:|-|
| BERT（arXiv 1810.04805） | 16 | 断言拆分、证据定位、来源元数据 |

## 2. 四个问题逐项验证

### 2.1 拆得细 —— 原子 SPO 断言（主攻）

每条断言 = 一个 `subject + predicate + object`，可独立判断真假。拆解规则（SKILL.md §4）处理复合句：

| 结构 | 拆解 |
|-|-|
| 并列 "A and B improve C" | → `A improves C` + `B improves C` |
| 因果 "A causes B, which improves C" | → `A causes B` + `B improves C` |
| 让步 "A improves C when D" | → 主断言 + `condition="when D"` |
| 否定 "A does not improve C" | → `negation=true`（不反向改写） |

`subject` 含 and/or 时质量检查器报 `subject_confusion`（主体混淆），强制拆多条。

### 2.2 对得上 —— 最小充分证据绑定

每条断言绑定 `evidence.quote`（原文最短支撑片段）+ `location{session,page,line}` + `evidence_type`（direct/indirect）。实测 BERT 提取 1323 视觉行（带 `id/page/column/section`），63 个章节候选，供证据精确定位。

### 2.3 追得回 —— 来源元数据链路

`provenance.wasDerivedFrom`（源自哪篇/哪章/哪页）+ `pubinfo`（论文/作者/年份/版本/DOI/arXiv）形成完整链路。实测提取：标题 "BERT: Pre-training of Deep Bidirectional Transformers..."、作者 "Language Understanding"（首页作者块）。

### 2.4 读得懂 —— 受控词表 + 结构与词表校验

**受控关系词表**（16 个标准谓词，`resources/predicates.json`）：`achieves/improves/reduces/uses/proposes/evaluates/trained_on/fine_tuned_on/causes/is_a/compared_with/shows/outperforms/consists_of/correlates_with/prevents`，每个带 `verbs` 自然语言映射。

**结构与词表校验**（`nanopub_schema.py` 实测，只判结构/词表，不判语义）：

| 输入断言 | 判定 |
|-|-|
| 完整断言（SPO+证据+来源齐全，predicate=achieves） | `ok` |
| 全空断言 | `error`：subject_object_empty + predicate 缺失 + evidence_quote_empty + 来源缺失（6 项） |
| subject="A and B"（多主体线索） | `warning`：subject_conjunction + identifier_missing |
| predicate="freeform_verb"（非词表） | `error`：predicate_out_of_vocab |

脚本给出**可复现的结构/词表判定**（字段缺失/词表越界/主体混淆线索/来源缺失）；语义质量（断言是否真的过宽、证据是否真的充分）由 Agent 按 SKILL.md §5.2 的判据复核，脚本不冒充语义判断。

## 3. 使用增益（与基础 Agent 对照，机制层面）

| 维度 | 基础 Agent（无 Skill） | 加载本 Skill |
|-|-|-|
| 拆得细 | 整段结论塞进一个"断言"字段 | SPO 原子断言，复合句拆分 |
| 对得上 | 证据笼统"见原文" | 最小片段 + section/page/line |
| 追得回 | 来源缺失 | provenance + pubinfo 全链路 |
| 读得懂 | 自然语言不可解析 | 受控词表 + 字段化 JSON |

## 4. 诚实标注的不足

1. **断言内容质量**取决于运行时模型（SPO 拆分、证据片段选择），本地无法测真实断言（无 LLM API），不虚构评分。
2. **受控词表 16 谓词**覆盖常见科研关系，但特定领域（生物医学基因-疾病关联等）可能需要扩展词表，已声明维护方式。
3. **证据跨图表**（证据在表格/图注）时定位粒度依赖 extractor 的图表检测，复杂版面需 Agent 用渲染页图核对。

## 5. 结论

本 Skill 已形成"确定性章节/段落提取 + 受控关系词表 + 结构与词表校验 + 模型拆断言"的最小闭环，四个问题各有**可执行、可核验**的解决方案，主攻方向（断言拆解 + 证据绑定）有明确机制证据。下一步：建 GitHub 仓库 → dry-run 预检 →（确认后）提交。
