---
name: pdf-structure-audit-v2
description: 科研 PDF 文献结构化解析 Skill。把论文解析成可复核的结构化结果：正文逐字提取、多栏阅读顺序还原、表格拆解、章节层级、公式行定位、扫描件 OCR。
---

# 科研 PDF 文献解析（pdf-structure-audit-v2）

## 1. 用途与触发条件

**用途**：把一份科研 PDF 解析成结构化、可复核的结果，而不是给一段"看起来像全文"的文本。

**触发条件**（满足任一即应调用本 Skill）：
- 需要从 PDF 提取正文、摘要、章节、表格、公式、图注、脚注、参考文献；
- 需要按原文版面顺序阅读双栏/多栏论文，纠正串栏、错行、漏段；
- 需要拆解复杂表格（跨行跨列、合并单元格、多层表头、跨页续表）；
- 需要定位公式行并保留其上下标、希腊字母与特殊符号原文（不保证公式编号，编号可能在版面右侧单独成块）；
- 需要处理扫描版/无文字层 PDF 的 OCR；
- 需要"回答问题，同时给出原文证据定位"的文献阅读任务。

**核心原则（贯穿全流程）**：
1. 实际输入文件与原论文是事实依据；不依据错误的领域标签补造数据。
2. 每个关键结论必须能指回原文（页码、段落、图表、字段或公式位置）。
3. 读不出、无法判断、材料缺失的部分**如实标注**，绝不靠猜补齐。

## 2. 输入 / 输出契约

### 输入（评测环境固定）
- `/input/case.json`：案例输入。含 `case_id`、材料路径/说明、`output_contract`（题面要求的输出字段）。
- `/input/task.md`：题面任务说明（本案例具体要回答/提取/核验什么）。

### 输出（写入 `/app/output/result.json`）
必须包含以下字段，`output_contract` 中声明的每个字段都要出现在 `answer` 中：

```json
{
  "case_id": "案例标识（来自 case.json）",
  "answer": { "output_contract 中声明的每个字段": "真实答案" },
  "structured": { "title": "", "authors": "", "sections": [],
                  "reading_order": [{"page":1,"column":0,"y0":0.1,"text":"..."}],
                  "tables": [], "formulas": [], "captions": [],
                  "references": [], "footnotes": [], "document": {} },
  "evidence": [ { "item": "结论", "value": "依据", "source": "页码/区块/字段定位" } ],
  "status": "success | partial | failed | refused | unable_to_judge",
  "status_detail": "一句话说明",
  "uncertainty": [ { "item": "", "reason": "" } ],
  "warnings": [],
  "changes": [ { "time": "", "action": "", "detail": "" } ]
}
```

`reading_order` 是**可核验的阅读顺序序列**：每项带 `page`（物理页）、`column`（-1=通栏，0/1=左/右栏）、`y0`（归一化纵坐标）、`text`。评审可据此核对"先左栏后右栏、栏内自上而下"是否成立。

**状态取值约定**：
- `success`：任务完成且关键结论可复核；
- `partial`：完成部分任务，其余明确说明限制；
- `failed`：解析失败（附真实错误）；
- `refused`：材料不足以作答，拒绝编造；
- `unable_to_judge`：材料未报告该信息，无法判断。

## 3. 依赖与资源

评测运行环境为固定镜像，已预装（Harbor Runtime contract 声明）：
- `pdfinfo / pdftohtml / pdftotext / pdffonts / pdftoppm`（poppler-utils，`pdf-text-tool` 与 `pdf-render-tool`）
- `python3`（`scientific-python`）
- 可选 `tesseract`（`ocr-tool`，扫描版 PDF 时用）

本 Skill 自带脚本：
- `scripts/extract_pdf.py`：核心解析器（结构化提取 + 版面分析 + 分栏 + 表格/公式/图注/参考文献识别 + OCR 降级）。
- `scripts/run.py`：评测环境入口（读 case.json/task.md → 跑解析 → 写 result.json 草稿）。

**无需额外安装**；脚本只用标准库与上述系统工具。

## 4. 调用步骤（Agent 执行流程）

### 步骤 1：识别输入与问题边界
1. 读 `/input/case.json` 与 `/input/task.md`。
2. 确认 `case_id`、材料路径、`output_contract` 字段、任务要回答/提取的具体问题。
3. 用 `pdfinfo` 看页数、页面尺寸、是否加密；用 `pdffonts` 判断是否有文字层。

### 步骤 2：运行确定性解析
```bash
python3 scripts/run.py          # 生成 /app/output/result.json 草稿
python3 scripts/extract_pdf.py  /path/to/input.pdf  /app/work/extract.json --workdir /app/work
```
`extract_pdf.py` 输出结构化结果（标题/作者/章节/段落/阅读顺序/表格/公式/图注/参考文献/脚注，均带页码与归一化坐标）。

**两阶段设计（预算友好的关键）**：确定性脚本 `extract_pdf.py` 完成版面/坐标/结构的"重活"（提得全、排得对、拆得清、核得回的结构骨架）；Agent 用渲染页图做语义核验与答题，把有限的 64 次模型请求花在"校验与回答"上，而不是从零重排文字。

### 步骤 3：渲染页面核对版面（关键）
```bash
pdftoppm -r 150 -png /path/to/input.pdf /app/work/page
```
用渲染出的页面图像**逐页目视核对**：
- 分栏与阅读顺序是否正确（`columns_by_page` 仅作参考，以图像为准）；
- 表格行列归属是否被误拆/误并；
- 公式符号是否失真；
- 页眉页脚是否混入正文（应分离）；
- 扫描页/乱码页是否被识别。

发现错误时，用 `extract_pdf.py` 输出的坐标与页码重新对齐，手工修正 `structured` 中的对应条目。

### 步骤 4：按题面回答并写证据
1. 针对 `task.md` 的每个问题/字段，从 `structured` 中定位原文依据。
2. 把答案写入 `answer.<output_contract 字段>`。
3. 每个关键结论在 `evidence` 中记录：`item`（结论）、`value`（依据片段）、`source`（页码/段落/图/表/公式编号）。
4. 无法判断/未报告的写入 `uncertainty`，状态改 `unable_to_judge` 或 `partial`。

### 步骤 5：写回最终结果
把完整结果写入 `/app/output/result.json`（含 `case_id`、全部 `output_contract` 字段、`status`、`evidence`、`uncertainty`、`changes`）。

## 5. 异常处理

| 情况 | 识别方法 | 处理 |
|-|-|-|
| 加密 PDF | `pdfinfo` 的 `Encrypted:` 非空 | 尝试 `pdftotext`；仍失败则 `status=failed`，`status_detail` 记录加密原因 |
| 无文字层/扫描件 | `pdffonts` 无字体，或 `pdftohtml` 无 `<text>` | 自动降级 `pdftoppm` + `tesseract` OCR；在 `uncertainty` 标注"OCR 可能错字，关键结论需对照页图复核" |
| 乱码/缺字 | 提取文本含 `\uFFFD` 或大量非词字符 | 标注该页，改用渲染页图 OCR 复核 |
| 页码错乱 | 提取页码与页脚实际页码不一致 | 以 `pdfinfo` 页序为准，脚注/引用定位用"物理页 + 区块"双重定位 |
| 工具缺失 | `pdfinfo/pdftohtml/tesseract` 不存在 | 在 `warnings` 记录缺失工具，改用 `pdftotext -tsv` 降级 |
| 栏位误判 | 通栏图/题注、窄栏缝导致自动分栏不准 | **必须**用渲染页图目视核对 `reading_order`，以图像为准修正；`column` 字段仅作参考 |

**预算注意**：评测预算 64 次模型请求、900 秒、单响应 16384 token。优先让确定性脚本干活，模型只做核对与答题；及时保存部分结果（partial），不要等全部完成才写文件。

## 6. 最小调用示例（示意输出，非正式案例结果）

> 以下为**示例**，用于说明接口与流程，不冒充任何正式案例答案。

**输入**（`/input/case.json` 示意）：
```json
{ "case_id": "demo-001", "material": "/input/demo.pdf",
  "output_contract": { "title": "论文标题", "method": "方法概述", "table_1": "表1内容" } }
```

**调用**：
```bash
python3 scripts/run.py
```

**示意输出**（`/app/output/result.json` 节选）：
```json
{
  "case_id": "demo-001",
  "answer": { "title": "示例论文标题", "method": "示例方法概述", "table_1": "示例表格" },
  "structured": { "title": "示例论文标题", "sections": [{"heading":"1 Introduction","page":1}] },
  "evidence": [ { "item": "论文标题", "value": "示例论文标题", "source": "第1页，区块(0.18,0.11)" } ],
  "status": "success",
  "uncertainty": [],
  "changes": []
}
```

## 7. 适用场景与限制

**适用**：有文字层的科研论文、技术报告、学位论文（单栏/双栏/多栏）；扫描件可用 OCR 兜底。

**限制**：
- 不要求理解图表/公式的科学含义，只按结构元素识别与保真；
- 对重度排版（复杂 float 布局、脚注与正文交织、多页大表）可能需人工/模型二次核对；
- OCR 结果置信度有限，关键结论必须回原文图像复核。
