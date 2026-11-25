---
name: structured-notes-v2
description: 科研文献结构化笔记 Skill。按论文自身章节树生成字段化、带证据标记与原文锚点的可检索笔记：论文卡片、章节总结、知识点条目，区分作者主张与文中证据，保留方法前提与局限。
---

# 文献总结与结构化笔记（structured-notes-v2）

## 1. 用途与触发条件

**用途**：把一篇科研论文整理成"可复核、可检索、可继续复用"的结构化笔记，而不是一段压缩后的通读摘要。

**适用任务**：单篇论文总结、章节摘要、论文卡片整理、知识点提取、多篇论文并排比较、为综述/写作积累可复用素材。

**触发条件**：任务要求对科研材料做总结、结构化笔记、要点提取、证据整理，且要求能回到原文核对。

**不适用**：纯翻译（见 translation-audit-v2）、纯文献文档解析（见 pdf-structure-audit-v2）、只需一段口头概括而不需要回原文的场合。

## 2. 四个核心问题与解决方案（必读）

| 问题 | 解决方案（可执行、可核验） |
|-|-|
| **对得上** | 笔记骨架 = `section_tree`（论文自身章节树，含 `3 → 3.1 → 3.1.1` 层级路径），逐章按"目的/内容/结果"提炼，**不套用**"摘要-方法-结论"通用模板；章节承接关系写进每章"承接"字段。 |
| **留得住** | 论文卡片统一字段：研究问题、数据、方法、**方法成立的前提条件**、主要发现、关键数值（带单位/基线/条件）、局限、**未报告项**；关键论断用五类证据标记区分"作者主张/文中证据/外部背景/分析判断/待验证"。 |
| **找得回** | 每条笔记带稳定锚点 `{section, page, paragraph, figure, table}`，锚点粒度与可核验性匹配；数值、变量、方法条件必须落到具体段落/图表/公式。 |
| **用得上** | 输出字段化 JSON：`paper_card` + `section_notes[]` + `knowledge_points[]`，知识点条目 `{term, type, definition, evidence_marker, concept_source}` 可检索、可去重、可跨论文比较。 |

## 3. 工作流程（两阶段，预算友好）

### 阶段一：确定性骨架（0 次模型请求）

```bash
python3 scripts/extract_document.py <paper.pdf> /app/work/extracted.json --workdir /app/work/ext
python3 scripts/build_skeleton.py /app/work/extracted.json /app/work/skeleton.json
```

`skeleton.json` 产出：`section_tree`（章节树）、`paper_card`（空字段模板）、`paragraphs[]`（带 `id/page/column/section`）、`figures_tables[]`（图注/表格/公式锚点）、`references[]`。

先读 `/input/task.md` 与 `case.json`，确定任务要求（整篇总结 / 指定章节 / 论文卡片 / 知识点提取）。

### 阶段二：模型填内容（预算内）

1. **读骨架 + 渲染页图核对章节**：用 `pdftoppm` 渲染页图，核对 `section_tree` 与原文一致（确定性章节树偶有标题/脚注噪声，以页图为准修正）。
2. **填论文卡片（1 次请求）**：按字段填 `research_question/data/method/method_conditions/main_findings/key_numbers/limitations/unreported`；每条带锚点与证据标记。
3. **逐章生成章节笔记（分批，每批 3–4 章）**：每章写"目的/内容/结果/承接"，带章节锚点。
4. **提取知识点条目（1–2 次请求）**：概念/变量/方法/结论拆成条目，同义术语归并，带证据标记与概念来源。
5. **自检**：缺失信息一律写"未报告"，不补造；不确定项写 `uncertainty`。

### 模型请求预算（64 次上限）

| 阶段 | 请求数 |
|-|-:|
| 核对章节 + 填论文卡片 | 1–2 |
| 章节笔记（每批 3–4 章，31 节点约 8–10 批） | ≤ 10 |
| 知识点提取 + 归并 | 1–2 |
| 复核/补漏 | ≤ 5 |
| **合计** | **≤ 20**，留 ≥44 次余量 |

超时/超长兜底：先输出已完成章节 + `status=partial`，未完成章节写进 `uncertainty`，不留空章节冒充完整。

## 4. 笔记 Schema（字段化核心）

### 4.1 论文卡片 paper_card

```json
{
  "title": "", "authors": "", "year": "", "source": "",
  "research_question": "研究要解决什么问题",
  "objectives": ["研究目标"],
  "data": "数据/样本/对象",
  "method": "方法概述",
  "method_conditions": ["让结论成立的前提条件：数据集、样本规模、超参、评测协议、硬件等"],
  "main_findings": [{"claim": "结论", "anchor": "§5, p.7", "evidence_marker": "文中证据"}],
  "key_numbers": [{"value": "97.0", "unit": "F1", "baseline": "GPT", "condition": "GLUE", "anchor": "Table 1"}],
  "limitations": ["局限/适用范围"],
  "unreported": ["原文未报告的信息"]
}
```

### 4.2 章节笔记 section_notes[]

```json
{
  "section_path": "3.1", "heading": "Pre-training BERT",
  "purpose": "本章目的", "content": "本章内容/论证",
  "results": "本章结果/结论（若适用）",
  "bridge": "与上一章/下一章的承接关系",
  "anchor": {"page": 3, "page_range": [3, 5]}
}
```

### 4.3 知识点条目 knowledge_points[]

```json
{
  "id": "kp-1", "term": "masked language model",
  "type": "concept|variable|method|finding|limitation",
  "definition": "定义/说明",
  "evidence_marker": "作者主张|文中证据|外部背景|分析判断|待验证",
  "concept_source": "论文定义|外部来源|LLM综合",
  "anchor": {"section": "3.1", "page": 4, "paragraph": 15}
}
```

## 5. 证据标记规则（区分"作者说了什么"与"论文展示了什么"）

每条关键论断必须打一个证据标记，杜绝"把作者主张当成已证实事实"：

| 标记 | 含义 |
|-|-|
| 【作者主张】 | 论文作者声称的观点（待验证主张，非既成事实） |
| 【文中证据】 | 论文实际展示的证据（实验结果、数据、表格、公式） |
| 【外部背景】 | 来自论文外部的背景知识 |
| 【分析判断】 | 笔记整理者本人的分析/评价/推断 |
| 【待验证】 | 需回到原文进一步核验的内容 |

概念来源三标签：`论文定义`（论文内的定义）/ `外部来源`（外部知识）/ `LLM综合`（模型综合理解，最不可靠）。

## 6. 锚点格式

稳定锚点，粒度与可核验性匹配，写进每条笔记：

- 章节：`§3.1`、`§Method`；段落：`p.7 ¶3`（页码+段号）；图表：`Fig.3`、`Table 2`；公式：`Eq.(4)`。
- 无固定页码的材料：用章节标题 + 可检索原句定位。
- 阅读器页序与印刷页码不一致时，同时记录两者（`PDF p.9 / 原文 p.126`）。

## 7. 输出格式（/app/output/result.json）

```json
{
  "case_id": "来自 case.json",
  "answer": { "output_contract 声明的每个字段": "真实笔记结果" },
  "structured": {
    "paper_card": { "...": "论文卡片字段" },
    "section_notes": [ { "...": "章节笔记" } ],
    "knowledge_points": [ { "...": "知识点条目" } ],
    "section_tree": [ {"heading":"","level":1,"page":1,"path":"1"} ],
    "document": {"title":"","page_count":0,"ocr_used":false}
  },
  "evidence": [{"item":"结论","value":"依据","source":"§/页/段/图表"}],
  "status": "success | partial | failed | refused | unable_to_judge",
  "status_detail": "一句话",
  "uncertainty": [{"item":"","reason":""}],
  "warnings": [],
  "changes": [{"time":"","action":"","detail":""}]
}
```

## 8. 异常处理

| 情况 | 识别 | 处理 |
|-|-|-|
| 无文字层/扫描件 | `pdffonts` 无字体 | `extract_document.py` 自动 OCR；笔记标注"OCR 可能错字，关键数值需对照页图复核" |
| 双栏错序 | 章节树与页图不符 | 以渲染页图为准重排，`changes` 记录 |
| 图表/公式为图片 | 表格/公式检测失败 | 渲染页图让模型判读；判读不准则写 `uncertainty`，不硬填 |
| 超长文 | 段数巨大 | 先出前 N 章 + `partial`，续写后补全 |
| 原文缺失信息 | 某字段无内容 | 写"未报告"，`unreported` 记录，不补造 |
| 加密/权限受限 | `pdfinfo` 标记 Encrypted | `status=failed`，记录加密原因 |

## 9. 最小调用示例

输入：BERT 论文 skeleton（章节树 + 段落 + 图表锚点）。

论文卡片（示意，标为示例）：
```json
{
  "research_question": "如何训练深度双向 Transformer 语言模型，并在多任务上取得 SOTA",
  "method_conditions": ["BooksCorpus(800M词)+English Wikipedia(2500M词)", "Masked LM 15%", "NSP"],
  "main_findings": [{"claim": "BERT LARGE 在 GLUE 达 80.5 分", "anchor": "Table 1", "evidence_marker": "文中证据"}],
  "limitations": ["基于 pre-training 语料分布，领域外泛化未充分评估"],
  "unreported": ["训练硬件能耗", "推理延迟"]
}
```

知识点条目（示意）：
```json
{"id":"kp-1","term":"masked language model","type":"concept",
 "definition":"随机掩码部分 token 并预测，实现双向预训练",
 "evidence_marker":"论文定义","concept_source":"论文定义","anchor":{"section":"3.1","page":4}}
```

> 以上为示意输出，标为示例；正式案例笔记由平台实际运行产生。
