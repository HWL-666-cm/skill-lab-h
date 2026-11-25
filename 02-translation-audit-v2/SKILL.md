---
name: translation-audit-v2
description: 科研文献英译中 Skill。术语表驱动 + 代码级强制执行的翻译流程：术语全篇锁定同一译名、段落级双语对照、数字/单位/公式/引用占位保护、译文核验与强制回填。
---

# 科研文献翻译（translation-audit-v2）

## 1. 用途与触发条件

**用途**：把一篇英文科研论文（或指定段落区间）翻译成可复核的双语对照结果，而不是只给一段"大意"或改写。

**适用任务**：文献英译中、摘要/章节翻译、术语表驱动的整篇翻译、双语对照与译文核验。

**触发条件**：任务要求对英文科研材料做中文翻译，且要求术语一致、段落完整、事实准确、可回到原文核对。

**不适用**：文学/口语化文本的风格化翻译；要求"意译改写"而非"忠实翻译"的任务。

## 2. 四个核心问题与解决方案（必读）

本 Skill 针对题目四个问题各给出**可执行**的解决方案，不是"在提示词里写一句要求"。

| 问题 | 解决方案（可执行、可核验） |
|-|-|
| **术语稳** | ① 确定性抽取候选术语 → ② Agent 确认译名建成 `termbase`（JSON）→ ③ 翻译时只注入本段出现的术语 → ④ 翻译后 `validate_translation.py` 逐段校验"核准译名在位、禁用译名缺席"→ ⑤ 代码**强制回填**禁用译名为核准译名。 |
| **段落全** | 复用多栏阅读顺序提取器 `extract_document.py`，先左栏后右栏、栏内自上而下重建行序，再按行距+首行缩进聚成段落，每段带唯一 `id` 与页码/栏位定位。跨页、跨栏不漏段、不重复、不错位。 |
| **关系准** | 翻译前把数字+单位、文献引用 `[n]`、URL/DOI、公式编号 `(n)` 替换为 `{{P_n}}` 占位符；公式段整体标记 `do_not_translate`。翻译后校验占位符逐一在位，把错位/丢失暴露出来。 |
| **可核验** | 输出段落级双语对照：`source`（原文）↔ `target`（译文）↔ `id/page/column/section`（定位）↔ 译法依据；译不准的段落写进 `uncertainty`，不混成"确定"结果。 |

## 3. 工作流程（两阶段，预算友好）

确定性脚本做"重活"（抽取、分段、术语候选、占位符保护、校验回填），模型请求只花在"确认术语"和"逐段翻译"上。

### 阶段一：确定性准备（0 次模型请求）

```bash
python3 scripts/extract_document.py <material.pdf> /app/work/extracted.json --workdir /app/work/ext
python3 scripts/prepare_translation.py /app/work/extracted.json /app/work/translation_job.json
```

`translation_job.json` 含：
- `segments[]`：每段 `{id, page, column, section, source, protected, protection_map, kind, do_not_translate}`；
- `term_candidates[]`：候选术语（缩略词/专有短语/高频 n-gram，含频次）；
- `document{}`：标题、页数、是否 OCR、警告。

先读 `/input/task.md` 与 `case.json`，确定**要翻译的段落区间/章节**（不必全篇翻译时只翻指定范围）。

### 阶段二：模型翻译（预算内，分批）

1. **确认术语表（1 次请求）**：把 `term_candidates` 交给模型，输出 `termbase`（JSON 数组），每条：
   ```json
   {"source":"fine-tuning","target":"微调","do_not_translate":false,
    "forbidden_alternatives":["精调","调优"]}
   ```
   - 专有名词/模型名/缩写设 `do_not_translate:true`（如 BERT、GLUE、GPT 原文保留）；
   - `forbidden_alternatives` 列出**明确否决**的译名（这是校验器的"红线"）。
2. **逐批翻译**：按段落顺序分批（每批约 30–40 段），把本批术语注入提示词，指令：
   - 忠实直译，不省略、不增写、不改写；
   - `{{P_n}}` 占位符**原样保留**，不得改动、不得遗漏；
   - `kind=formula` / `do_not_translate=true` 的段**原文照抄，不译**；
   - 数字与单位即使未被占位符覆盖，也必须与原文一致。
3. **核验与回填（0 次请求）**：把各段译文写成 `translations.json`（`{段id: 译文}`），运行：
   ```bash
   python3 scripts/validate_translation.py /app/work/translation_job.json /app/work/translations.json /app/work/termbase.json
   ```
   校验器逐段检查：占位符完整、核准译名在位、禁用译名缺席，并**自动把禁用译名替换为核准译名**（`backfill_changes` 记录改动）。
4. **带违规重译**：对 `needs_review` 的段，把**具体违规**（如"你用了『精调』，核准译名是『微调』"）回传给模型重译一次；仍失败则交人工确认并写入 `uncertainty`。
5. **还原占位符**：把译文中 `{{P_n}}` 还原为 `protection_map` 对应的原文（数字/单位/引用/公式编号）。

### 模型请求预算（64 次上限，必须先算账再翻）

平台预算：**64 次模型请求 / 900 秒 / 单次回复 16384 tokens**。逐段一次调用会超限（如 329 段 = 329 次，超上限 5 倍，第 64 次后被截断，后面全是空段，直接丢"结果完整性"）。必须**分块**：

| 阶段 | 请求数 | 说明 |
|-|-:|-|
| 确认术语表 | 1 | 一次给出全部候选术语，返回 termbase |
| 逐块翻译 | ≤ ⌈N/40⌉ | 每块 40 段，N=要翻译的段数 |
| 带违规重译 | ≤ 10 | 校验器 `needs_review` 段，带具体违规重译 |
| **合计** | **≤ 40** | 留 ≥24 次余量 |

- BERT 329 段：1 + ⌈329/40⌉=9 + 10 = **20 次** ≤ 40 ✓
- Decision Transformer 277 段：1 + ⌈277/40⌉=7 + 10 = **18 次** ≤ 40 ✓

**超长/超时兜底**：若段数过大或 900s 将尽，立即输出**已完成的前 N 段**，`status=partial`，把"未译段号范围"写进 `uncertainty` 与 `status_detail`，**不得留空段冒充完整**。先保存诚实的部分成果，再逐块续译。

## 4. 术语表格式与强制执行（核心创新）

术语表是**合同**，不是建议。`validate_translation.py` 用代码校验三条硬规则：

1. **必译术语在位**：源段含 `source` 术语 → 译段必须含 `target`（或 `do_not_translate` 术语原文保留）；
2. **禁用译名缺席**：译段不得出现 `forbidden_alternatives` 中任何词；
3. **强制回填**：发现禁用译名 → 直接替换为核准译名（不依赖模型自觉）。

这解决了"术语表写在提示里却不被执行"的根问题——模型译漂了，代码把它改回来。

## 5. 占位符保护规则

`prepare_translation.py` 在翻译前保护以下要素（翻译后原样还原）：

| 要素 | 正则/规则 | 目的 |
|-|-|-|
| 文献引用 `[12] [26,27] [12-14]` | `\[\d+([,\-–—]\d+)*\]` | 引用编号不改动 |
| URL / DOI / email / arXiv | `https?://…`, `doi:…`, `arXiv:…` | 链接不译 |
| 数字+单位 `91.0% 110M 0.1 m/s` | 数字后接单位表 | 数字单位不错位 |
| 公式编号 `(1) (2)` | 行尾 `(n)` | 编号对应原文 |
| 公式段（整段） | 数学字体/高密度特殊字符 | 数学式不译 |

## 6. 输出格式（/app/output/result.json）

```json
{
  "case_id": "来自 case.json",
  "answer": { "output_contract 声明的每个字段": "真实译文结果" },
  "structured": {
    "termbase": [{"source":"","target":"","do_not_translate":false,"forbidden_alternatives":[]}],
    "bilingual_segments": [
      {"id":1,"page":1,"column":0,"section":"Abstract",
       "source":"原文","target":"译文","protected":"保护后原文",
       "term_notes":"译法依据","status":"accepted|needs_review"}
    ],
    "validation_summary": {"total_segments":0,"accepted":0,"needs_review":0,
                            "placeholder_issues":0,"missing_terms":0,"forbidden_hits":0},
    "document": {"title":"","page_count":0,"ocr_used":false}
  },
  "evidence": [{"item":"术语译法","value":"依据","source":"页码/段落"}],
  "status": "success | partial | failed | refused | unable_to_judge",
  "status_detail": "一句话",
  "uncertainty": [{"item":"","reason":""}],
  "warnings": [],
  "changes": [{"time":"","action":"","detail":""}]
}
```

`bilingual_segments[].id` 与 `translation_job` 段号一一对应，评审可按 `id/page` 指回原文核对。

## 7. 异常处理

| 情况 | 识别 | 处理 |
|-|-|-|
| 无文字层/扫描件 | `pdffonts` 无字体、`pdftohtml` 无 text | `extract_document.py` 自动 OCR；`uncertainty` 标注"OCR 可能错字，译文需对照页图复核" |
| 公式/表格为图片 | 公式段检测失败、无文字 | 渲染页图 `pdftoppm` 让模型看图判读；译不准则标注，不硬译 |
| 原文残缺/乱码 | 含 `\uFFFD` 或大量非词字符 | 该段标记 `needs_review`，写 `warnings`，不把残缺当完整译 |
| 语言混杂 | 原文含中文/多语 | 仅译英文部分，原语言片段占位保留并标注 |
| 术语表冲突 | 同一术语出现两个译名 | 以 `termbase` 首个 `target` 为准，冲突写入 `uncertainty` |
| 模型漂移 | 校验器 `forbidden_hits` 非空 | 强制回填；仍失败带违规重译一次 |

## 8. 最小调用示例

输入：BERT 论文第 1 段（含术语、数字、引用）。

```json
{"id":1,"source":"BERT uses attention and reports 110M parameters with 91.0% accuracy [12].",
 "protected":"BERT uses attention and reports {{P_1}} parameters with {{P_2}} accuracy {{P_0}}.",
 "protection_map":{"{{P_0}}":"[12]","{{P_1}}":"110M","{{P_2}}":"91.0%"}}
```

术语表：`attention→注意力（禁用：关注、注意机制）`；`BERT→do_not_translate`。

模型译文（漂移示例）：`BERT 使用注意机制并报告 91.0% 个参数，准确率 [12]。`

校验器输出：`forbidden_hits=[注意机制]`，`backfill_changes=[注意机制→注意力]`，`placeholder_issues=[{{P_1}} 缺失]` → 带违规重译。

正确译文：`BERT 使用注意力并报告 110M 个参数，准确率 91.0% [12]。`

> 以上为示意输出，标为示例；正式案例译文由平台实际运行产生。
