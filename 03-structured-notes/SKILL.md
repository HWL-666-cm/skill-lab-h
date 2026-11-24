---
name: structured-paper-notes-anchored
description: 把真实科研论文（PDF 或文本）变成可回链、可比较、可继续复用的结构化笔记——按论文本身章节骨架对齐，用统一卡片字段记录研究问题/数据/方法/发现/局限及其成立条件，并为每条结论保留页码+章节+原文片段的锚点，再用脚本逐条核验锚点是否真指向原文。当用户要求读论文、做文献笔记、论文卡片、章节摘要、知识点提取、带出处问答，或要把多篇论文并排比较时使用。不用于代写论文、虚构文献、或只做无出处的通读摘要。
---

# 结构化论文笔记（锚点可核验版）

## 1. 这个 Skill 解决什么问题

基础 Agent 读论文做笔记，最常见四种失败，正好对应评分四个问题：

| 失败 | 后果 | 本 Skill 的对策 | 对应评分 |
|---|---|---|---|
| 套通用摘要模板（Introduction/Methods/Results/Conclusion 四段），不论文实际章节 | 论文的论证顺序被打乱，章节对不上 | 先从 PDF 抽**论文本身的章节骨架**，笔记一级结构跟随它 | 对得上 |
| 把"TS=0.44"抄下来，不记它成立于哪一时段、哪一样本 | 数字离开条件不可比，下次用不上 | 每个主要 finding 强制配一条 `condition` claim | 留得住 |
| 写"见第 3 页"或"Methods"，但那页根本没有这句话 | 无法复核，等于没给出处 | 每条 claim 带 `page`+`section`+`quote`，脚本逐条回原文核验 | 找得回 |
| 笔记是一段压缩摘要，字段不统一、不能并排比较 | 下次写作/阅读无法直接复用 | 统一 `paper_card` 七字段 + `claim` 六字段，输出 JSON + CSV | 用得上 |

核心约束：**每条结论必须能回原文**。回不去的，要么降级为页级锚点并标注，要么进 `uncertainties`，绝不当事实写。

## 2. 触发条件

**应当触发**：用户给出论文（PDF/文本）并要求做笔记、总结、卡片、章节摘要、知识点清单、带出处问答、多篇比较。

**不应触发**：用户要代写一篇论文、要虚构参考文献、只要一句无出处的口语概括。这些情况按普通问答处理。

**判定口径**：输入有"论文材料"且有"整理/提取/总结/问答"动作才触发；只有其一，先问一句再动手。

## 3. 运行时输入

平台在每个案例下把输入放在 `/input/case.json`，题面在同目录 `task.md`。按语义读，不假设固定键名：

| 语义 | 常见键名 | 缺失时怎么办 |
|---|---|---|
| 论文材料 | `material` / `paper` / `pdf` / `document` / `text` | 依次尝试；都没有则读 `/input/` 下唯一 PDF/文本文件 |
| 任务说明 | `instruction` / `task` / `requirement` / `question` | 回退到 `task.md` 正文 |
| 案例标识 | `case_id` / `id` | 用输入文件哈希前 8 位合成，标注为合成 ID |
| 输出契约 | `output_contract` | 由 `make_result.py` 读取并对齐，见第 5 节 |

**输入是 PDF 时**：直接读原始 PDF，不要用文件名、标签或 case.json 里的摘要代替正文——题面明确 PDF 案例给的是原始文件、没有预提取答案层。先跑 `pdf_extract.py`；提取出的表格若列错位，看页面图像核对；扫描件走 OCR。

**硬规则**：材料里没有的事实、数值、结论，一律不得新增。需要补充才能成句时，写进 `uncertainties`，不生成 claim。

**环境探测（第一步就做，别假设）**：

| 项 | 探测方式 | 兜底 |
|---|---|---|
| Python 命令 | `python3 --version` 失败就试 `python --version` | 都没有：跳过脚本，只按提示词流程做，并在 `limitations` 写明"锚点未脚本核验" |
| PDF 解析库 | `python3 -c "import pymupdf"` 失败试 `import fitz` | 都没有：用平台 `pdf-text-tool` 提取带页码文本，转成与 `pdf_extract.py` 同结构的 JSON（pages/sections/issues） |
| 本 Skill 路径 | 依次找 `/skills/weekly-skill`、`./skills/*/`、脚本同级上一级 | 用绝对路径调用，不依赖 `cd` |
| 输出目录 | `/app/output` 不存在则创建 | 创建失败退到 `/app/work/output` 并写进 `limitations` |
| 输入编码 | utf-8 优先，依次试 utf-8-sig、gb18030 | `make_result.py` 已内置这条链路 |

**预算账**：64 次模型请求、900 秒、单次 16384 token。脚本（抽取/核验/组装）不消耗模型额度；模型调用只用在"按章节写笔记"。按章节分块，每章 1 次调用，控制在 ≤32 次，留足余量给核验和回改。**超长论文优先"交前 N 章 + 标 partial"，不要试图一次写完整篇。**

## 4. 执行流程

工作目录 `/app/work`，产物写 `/app/output`。

**第 1 步｜PDF 抽取（不调用模型）**
```bash
python3 scripts/pdf_extract.py --pdf /input/paper.pdf --out /app/work/extracted.json
```
产出三样：逐页文本（带物理页码）、章节骨架（heading/page/level/number）、异常页标记（乱码/图片页）。
- 章节骨架用两条信号抓标题：字体加粗/中文黑体 + 数字编号；编号与标题分两行时会合并。
- 抓错的行（图题、表内数字、站号）已在脚本后处理里过滤；仍可能有个别残留，第 2 步人工剔除。
- **异常页不要硬读**：`issues` 里标了 `garbled_or_formula` / `low_text_page` 的页，只允许锚到页，不做逐字 quote。

**第 2 步｜拆任务项清单 + 定卡片字段**

把 `instruction` / `task.md` 要求做的动作逐句抽成 `/app/work/task_items.json`：
```json
{"items":[{"id":"T1","action":"按章节做笔记","scope":"全部章节","from":"instruction 第1句","status":"pending"}]}
```
**为什么必须有这张清单**：评分"结果完整性"按任务项覆盖给分。只在脑子里记，容易漏掉"还要给局限""还要给出处"。落成 JSON 后，第 6 步逐条对照，没 `done` 的进 `limitations`，status 不能写 ok。任务没要求的动作不要自己加——加了就要做，白耗预算。

同时按 `references/field-dictionary.md` 准备七字段论文卡片骨架。

**第 3 步｜按章节写笔记（模型调用集中在此）**

按 `extracted.json` 的 `sections` 切块，每章一次调用，使用 `prompts/extract-notes.md`，替换 `{{SECTION_OUTLINE}}`、`{{PAGE_TEXT}}`、`{{TASK_ITEMS_SLICE}}`、`{{KNOWN_ISSUES}}` 四处占位符。每块要求返回严格 JSON（见提示词），不要自由文本。

**为什么要按论文本身章节切块，而不是按通用模板切**：章节是作者安排的论证顺序，"结果为什么这样"往往在上游方法章的条件里。按通用模板切会把条件和结论拆散，正是评分"对得上"要扣分的。

每章产出后合并成 `/app/work/notes.json`，`claims` 汇总所有章节的条目。

**第 4 步｜锚点核验（不调用模型）**
```bash
python3 scripts/anchor_audit.py --extracted /app/work/extracted.json \
  --notes /app/work/notes.json --out /app/work/anchor_audit.json
```
脚本逐条查页码存在性、quote 回原文、数值回原文、章节一致性。规则细节与已知边界见 `references/anchor-format.md`。

处理规则：
| 脚本结论 | 处置 |
|---|---|
| `mismatch` + `quote_not_found` | 把 quote 改成原文里真有的片段；改不出就删 quote 并降级为页级锚点 + 进 uncertainties |
| `mismatch` + `numbers_not_on_page` | 数值按原文逐字改正；**不要改页码去迁就数值** |
| `weak` + `missing_page` | 补物理页码；确实定位不到就保留 weak 并写进 limitations |
| `weak` + `page_shifted` | 检查是否印刷页码当成物理页码，补 `page_map` |
| warning `section_page_mismatch` | 人工确认章节归属，不改 verdict |

**第 5 步｜回改后再核验一次**：对第 4 步改过的 claim 重跑 `anchor_audit.py`，确认 mismatch 归零。仍有的写进 limitations，不藏。

**第 6 步｜组装结果**
```bash
python3 scripts/make_result.py --case-id <CASE_ID> --case-json /input/case.json \
  --notes /app/work/notes.json --extracted /app/work/extracted.json \
  --audit /app/work/anchor_audit.json --task-items /app/work/task_items.json \
  --out /app/output/result.json
```
产出 `/app/output/result.json`、`/app/output/notes.csv`（逐条可核对表）。有 task item 未 done、有 weak/mismatch、有异常页，`status` 一律 `partial`。

## 5. 输出契约

`/app/output/result.json` 至少包含：

```json
{
  "case_id": "原样回传",
  "status": "ok | partial | failed",
  "paper_card": {"title":"", "research_question":"", "data":"", "method":"",
                 "main_findings":"", "limitations":"", "condition_for_conclusion":""},
  "section_outline": [{"heading":"２ 检验结果分析","page":6,"level":1,"number":"2"}],
  "claim_notes": [
    {"id":"C4","field":"finding","value":"配料法 24h TS 平均为 ０.４４",
     "anchor":{"page":6,"section":"２ 检验结果分析","quote":"２４ｈ预报的ＴＳ评分平均为０.４４"},
     "section_ref":"２ 检验结果分析","note":"承接上一章方法，给出 24h 结果",
     "anchor_verdict":"ok","anchor_flags":[]}
  ],
  "source_map": [{"source":"/input/paper.pdf","page_count":9,"issue_pages":[4,5,6],"page_map":{}}],
  "uncertainties": ["未报告/冲突/读不出的点，逐条写"],
  "assumptions": ["页码口径等默认假设"],
  "limitations": ["本次未覆盖的处理项"],
  "audit": {"anchor":{"ok":5,"weak":0,"mismatch":0},"overall":"ok"},
  "task_coverage": [{"id":"T1","action":"...","status":"done|pending"}]
}
```

**状态口径**：`ok` = 锚点全 ok、任务项全 done；`partial` = 有 weak/mismatch/未完成任务项/异常页；`failed` = PDF 读不出或无法提取文本。**不得把 partial 写成 ok。**

**字段优先级**：若 `/input/case.json` 自带 `output_contract`，以它为准——本节字段作补充。`make_result.py` 用别名映射补字段，必需字段补不出就把 status 降为 `partial`，并在 `output_contract_alignment` 里记录缺了什么。

## 6. 异常处理

| 情况 | 处置 |
|---|---|
| 扫描件 / 无文本层 | `pdf_extract.py` 报 low_text_page 并自动导出该页图片到 `pages/pNN.png`（150 dpi，文件名写在 `detail` 与 `scan_page_images`）→ 用平台 `ocr-tool` 识别这些图，标注"OCR 转录"，数值不当文本抽取；没导出图就别声称"建议人工核对" |
| 双栏错序 | 章节骨架按 heading 排，正文按栏读；列错位时看页面图像确认，写进 assumptions |
| 图表公式缺失 / 乱码 | 标 `issue_page`，锚点只到页、quote 留空、进 uncertainties，不猜内容 |
| 超长论文（>30 页） | 分章处理，先交前 N 章 + status=partial，说明剩余章节 |
| 非中文论文 | 字段值用原文语言，不强行翻译；`field` 仍用固定中文枚举便于比较 |
| 同一指标数值冲突 | 两条 claim 都留，各带页码，进 uncertainties 说明冲突，不自行选一个 |
| 加密 / 权限受限 PDF | 无法读取 → status=failed，只写原因，不编造任何内容 |
| 脚本报错 | 记入 limitations 继续，不因工具失败放弃已完成的笔记 |

## 7. 最小调用示例（示意，非正式案例结果）

输入：`examples/case-example.json`（虚构示例）。
调用：
```bash
python3 scripts/pdf_extract.py --pdf /input/paper.pdf --out /app/work/extracted.json
# 按章节写 notes.json（见 prompts/extract-notes.md）
python3 scripts/anchor_audit.py --extracted /app/work/extracted.json --notes /app/work/notes.json --out /app/work/anchor_audit.json
python3 scripts/make_result.py --case-id demo --notes /app/work/notes.json --extracted /app/work/extracted.json --audit /app/work/anchor_audit.json --out /app/output/result.json
```
输出示意见 `examples/output-example.md`——**标注为示例，不冒充正式案例结果**。

## 8. 自查（提交或交付前必做）

| # | 动作 | 通过标准 |
|---|---|---|
| 1 | 跑 `python3 scripts/run_selftest.py` | 5/5 PASS；有 FAIL 说明核验脚本坏了，先修脚本 |
| 2 | 确认 `result.json` 有 case_id，锚点报告无未解释的 mismatch | mismatch 必须已回改或写进 limitations |
| 3 | 抽查 5 条 claim 的 quote | 每条都能在原文对应页搜到（NFKC 后） |
| 4 | 核对 `section_outline` 与论文目录 | 一级章节同序，没有凭空多出的通用章节 |
| 5 | 每个主要 finding 是否都有 `condition` claim | 缺了就没"留得住"，补上 |
| 6 | 核对 task_coverage | 有 pending 却写 status=ok 即不合格 |
| 7 | 同一 PDF 重复跑一次抽取 | 章节骨架一致；不一致说明规则不稳，收紧判定 |

**为什么自测放第一条**：核验脚本是整套方法的地基。地基坏了，"锚点可回链"的结论就是假的——先证明它能抓错，再证明笔记没错。

## 9. 局限

- 锚点核验只查"能不能在原文找到"，不判断笔记内容在学科上是否正确。
- 图片/表格里的数值需 OCR 转录，脚本不自动读图。
- 页码 ±1 页容错意味着写偏一页不会被抓，高精度场景需人工抽查。
- 不做跨论文的结论综合，只保证单篇笔记可比较。

## 10. 维护

| 文件 | 作用 | 改动时同步什么 |
|---|---|---|
| `scripts/pdf_extract.py` | PDF→带页码文本+章节骨架+异常标记 | 改标题规则要重跑三篇代表论文验证误抓率 |
| `scripts/anchor_audit.py` | 锚点逐条核验 | 改 verdict 判定要同步 `tests/cases.json` |
| `scripts/make_result.py` | 组装 result.json + 契约适配 | 平台改契约先改 `CONTRACT_ALIASES` |
| `scripts/run_selftest.py` | 一条命令验证核验脚本 | 新规则要加对应用例 |
| `prompts/extract-notes.md` | 按章节写笔记的实际提示词 | 改字段要求要同步 `references/field-dictionary.md` |
| `references/field-dictionary.md` | 七字段 + 六类 claim 字典 | 字段增减要同步提示词与 make_result |
| `references/anchor-format.md` | 锚点三层粒度与核验规则 | 改规则要同步 anchor_audit 与自测用例 |
| `tests/cases.json` | 5 条合成用例 | 加规则就加用例，否则新规则未验证 |

Skill 版本由仓库提交记录管理，不在正文内标注。
