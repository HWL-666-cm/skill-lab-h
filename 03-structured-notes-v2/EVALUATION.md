# 阅读10｜文献总结与结构化笔记 —— 本地验证与评估报告

> 本报告为本 Skill 在自建验证语料上的**确定性组件**实测结果。正式 3 案例与笔记内容质量由平台运行产生，此处不冒充正式成绩。

## 1. 验证语料（自建）

| 文档 | 页 | 结构特征 |
|-|-:|-|
| BERT（arXiv 1810.04805） | 16 | 双栏、6 章 + 子节、表 1–6、附录 |
| Decision Transformer（arXiv 2106.01345） | 21 | 单栏为主、7 章、含 Contents 目录页 |

## 2. 四个问题逐项验证

### 2.1 对得上 —— 章节树驱动（主攻）

确定性脚本从论文提取**章节层级树**（含 `3 → 3.1 → 3.1.1` 路径），笔记骨架 = 论文自身结构，非通用模板。BERT 实测章节树（节选）：

```
[1] 1 Introduction
[2] 2 Related Work
    [2.1] Unsupervised Feature-based Approaches
    [2.2] Unsupervised Fine-tuning Approaches
    [2.3] Transfer Learning from Supervised Data
[3] 3 BERT
    [3.1] Pre-training BERT
    [3.2] Fine-tuning BERT
[4] 4 Experiments
    [4.1] GLUE   [4.2] SQuAD v1.1
[5.1][5.2][5.3] Effect of ... / Model Size / Feature-based
[6] 6 Conclusion  [References]  [Appendix]
```

层级路径、父子关系正确（`2 → 2.1/2.2/2.3`，`3 → 3.1/3.2`）。标题/脚注/表格行噪声已由 `_filter_sections`（标题/arXiv/URL/小写开头/数值行/页底脚注）过滤，BERT 从原始 63 个候选收敛到 31 个，核心章节零丢失。

### 2.2 留得住 —— 字段化论文卡片 + 方法前提

`paper_card` 字段覆盖题目要求的"研究问题、数据、方法条件、主要发现、局限"：

```
research_question / objectives / data / method / method_conditions[] /
main_findings[] / key_numbers[] / limitations[] / unreported[]
```

其中 `method_conditions`（方法成立的前提条件）与 `unreported`（未报告项）是**防止"留不住前提/补造数据"**的关键字段。`key_numbers` 要求带 `value/unit/baseline/condition/anchor`，避免"只有数值、没有基线和条件"的失效笔记。

### 2.3 找得回 —— 锚点回链

实测锚点能力：

| 文档 | 视觉行（行级锚点，未做段聚合） | 图表/公式锚点 | 参考文献 |
|-|-:|-:|-:|
| BERT | 1323 | 114 | 4 |
| Decision Transformer | 830 | 242 | 38 |

> 上表为**视觉行数**（extractor 把每个视觉行记为一个条目，行级锚点 `{id, page, column, section}`）。阅读03 用 `group_lines_to_paragraphs` 把同一批 1323 行聚合为 329 段；**本题为保留行级精度，未聚合**。图注/表格/公式单独列 `figures_tables[]`，供"每条笔记指回原文"。

### 2.4 用得上 —— 字段化 + 证据标记 + 知识点条目

- `paper_card` / `section_notes[]` / `knowledge_points[]` 三层 JSON，可检索、可跨论文比较；
- 证据五标记【作者主张/文中证据/外部背景/分析判断/待验证】区分"作者说了什么"与"论文展示了什么"；
- 概念来源三标签【论文定义/外部来源/LLM综合】标注可靠度；
- 知识点条目 `{term, type, definition, evidence_marker, concept_source, anchor}` 支持同义术语归并。

## 3. 使用增益（与基础 Agent 对照，机制层面）

| 维度 | 基础 Agent（无 Skill） | 加载本 Skill |
|-|-|-|
| 结构对齐 | 套用"摘要-方法-结论"通用模板，脱离论文章节 | 章节树驱动，逐章提炼，承接关系显式 |
| 前提保留 | 易丢失"结论成立的前提条件" | `method_conditions` 字段强制记录 |
| 证据区分 | 作者主张与证据混在一起 | 五类证据标记分开 |
| 锚点回链 | 笼统"见原文" | `§/页/段/图表` 稳定锚点 |
| 可复用 | 长文摘要不可检索 | 字段化 JSON + 知识点条目 |

## 4. 诚实标注的不足

1. **章节树仍有噪声**：BERT 树含 ~8 个非章节条目（副标题"Language Understanding"、正文行"Results are presented..."、表格数据行、附录 FAQ），需 Agent 依渲染页图校正（SKILL.md 已写"以页图为准修正"）。
2. **笔记内容质量**取决于运行时模型，本 Skill 负责"结构 + 字段 + 锚点 + 证据标记约束"，本地无法测真实笔记内容（无 LLM API），不虚构评分。
3. **双栏复杂 float 版面**的章节归属偶有偏差，Agent 用渲染页图复核。

## 5. 结论

本 Skill 已形成"确定性章节树 + 字段化骨架 + 模型填内容"的最小闭环，四个问题各有**可执行、可核验**的解决方案。下一步：建 GitHub 仓库 → dry-run 预检 →（确认后）提交。
