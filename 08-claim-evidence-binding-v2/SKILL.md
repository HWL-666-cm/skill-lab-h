---
name: claim-evidence-binding
description: 写论文的引言与相关工作，并保证每句论断有可回溯的证据——先读材料锚点再起草（证据先行），用断言台账把背景/相关工作/空白/贡献逐句绑定到引用编号、图表号、章节号或材料原句，逐字段核对引用作者与年份，抓出错配、套话、无依据空白和夸大贡献，按缺口回改并记录返修轮次数字，材料不足时明确标注而不编造。当用户要求写引言、整理相关工作、推导研究空白、写贡献条目、补引用或核对引用与贡献是否对得上使用；不用于代写整篇论文、不做语言润色（那是学术润色 Skill）、不虚构文献或数据。
version: 1.1.0
---

# 断言—证据绑定：引言与相关工作写作

## 1. 这个 Skill 解决什么问题

通用模型写引言最常见的失败不是文笔差，而是**句子漂亮但没有出处**：

- 背景用"近年来受到广泛关注"开篇，换成任何论文都成立；
- 相关工作按作者罗列成流水账，没有在同一维度上比较；
- 空白句说"现有研究仍存在不足"，却说不出谁的什么不足；
- 贡献说"显著提升"，正文里找不到对应图表；
- 引用看起来像真的，但年份被写错（**真作者 + 假年份**的"混合幻觉"，浅层检查看不出来）。

本 Skill 把写作拆成两个动作：**先抽取可核对的锚点，再把每句话绑到锚点上**。它是诊断与核对工具，不替作者做语义判断——机器判定的是"可定位性与元数据一致性"，"转述是否真的准确""分组是否深刻"留给人工确认项。

## 2. 什么时候用 / 不用

**用**：写或核对引言、相关工作、研究空白、贡献条目；补引用；核对引用元数据；检查贡献是否对应正文图表。

**不用**：整篇论文代写；纯语言润色；虚构文献或数据；材料本身没有任何可抽取文本时（会诚实返回 blocked）。

## 3. 核心概念：断言台账

每条台账行 = 一个句子 + 它的证据载体：

| 字段 | 含义 |
|---|---|
| `claim_id` / `claim_type` | 断言编号 / 类型（background, related_work, gap, contribution, citation） |
| `text` / `section` | 原句 / 所属小节 |
| `status` | `anchored`（有可解析引用）/ `loose`（有图表号或逐字引文或显式作者判断）/ `unanchored`（什么都没有）/ `unverified`（有引用但解析不到或元数据不符）/ `overclaimed`（强断言无证据） |
| `evidence.citations` | 引用原文、类型、解析到的文献 key、作者、年份 |
| `evidence.figures` | 图/表/章节/公式编号 |
| `evidence.verbatim_source` | 材料中找到的逐字片段及定位符 |
| `scope` | hedge 词、夸大词、是否显式标为作者判断 |
| `metadata_mismatch` | 逐字段比对结果，例如 `year 2019 != material 2020` |

**双向对齐**：

- 前向：成稿每句 → 有锚点吗？元数据对吗？scope 是否被材料支持？
- 后向：材料每个关键工作 / 图表 → 成稿写到了吗？写到了但没引用吗？

**四态门禁**：`pass` / `warn` / `fail` / `not_checked`。`not_checked` 绝不算通过；`fail` 阻断 complete。

## 4. 调用步骤

主入口是 `scripts/run_case.py`，三个阶段：

```bash
PY=python   # 用你环境里的 Python 3，标准库即可；PDF 解析可选 pymupdf/pypdf

# 1) 扫描材料：读出所有可核对锚点，不做判断
python scripts/run_case.py \
  --case /input/case.json \
  --lexicon scripts/../assets/lexicon.json \
  --schema  scripts/../assets/schema.json \
  --out /app/work/out --stage scan

# 2) 写稿（证据先行）：先读 prompts/writing-guide.md 与 /app/work/out/candidates.json，
#    从锚点出发写四节（研究背景 / 相关工作 / 研究空白 / 贡献），保存到 /app/work/draft.md
#    每条论断尽量带 \cite{key}、[n]、(Author, Year)、Fig./表 编号；
#    没有证据的判断要显式写"作者判断"或 hedge；查不到就写 [CITE: 需要什么支撑]，绝不编造。

# 3) 完成：把成稿对齐、出缺口、跑门禁、写全部产物
python scripts/run_case.py \
  --case /input/case.json \
  --lexicon assets/lexicon.json --schema assets/schema.json \
  --out /app/work/round1 --stage finish --draft /app/work/draft.md

# 4) 按缺口回改（v2 核心回路）：读 /app/work/round1/gaps.md，先改 blocking（错配引用），
#    再 major（无证据论断/空白无引用/贡献无锚点），最后 warn；改完保存 draft2，再 finish：
python scripts/run_case.py \
  --case /input/case.json \
  --lexicon assets/lexicon.json --schema assets/schema.json \
  --out /app/work/round2 --stage finish --draft /app/work/draft2.md

# 5) 记返修轮次数字（增益证据，不是自述）：
python scripts/revision_log.py \
  --before /app/work/round1/result.json \
  --after  /app/work/round2/result.json \
  --out /app/output/revision_delta.json
#   输出 unanchored / gaps_total / blocking / key_works_unwritten 的前后差值；
#   把最终稿 intro_related_work.md 与 revision_delta.json 一并放进 /app/output/。

# 可选：规则生成的机械底稿（诚实但生硬，不是好成稿）
python scripts/run_case.py ... --stage auto
# 可选：对已有产物重跑门禁
python scripts/run_case.py ... --stage recheck
```

退出码：`0` pass/warn，`1` fail/partial（产物仍会写出），`2` 输入错误。**回改后若仍有 blocking 或 major，不要声称完成**——在 `limits` 里写清剩下哪类缺口。

### 输入约定

- `--case`：case.json（可读 `case_id`、`title`、`output_contract`、`material_dirs`）或材料目录。
- 材料目录支持：`.tex` / `.bib`（含 `@article{...}` 和 `\bibitem{...}` 两种参考文献形态）、`.md` / `.rst` / `.txt`、JSON/YAML、PDF（需 pymupdf/pypdf/pdftotext 之一）、DOCX（python-docx，可选）。
- `--draft`：Markdown 或 JSON。JSON 可含 `markdown`/`draft`/`text`/`sections` 字段。

### 输出（写到 `--out`，全部 UTF-8、确定性）

| 文件 | 内容 |
|---|---|
| `intro_related_work.md` | 成稿 |
| `claim_ledger.json` | 断言台账：逐句 + 证据 + status |
| `citation_check.json` | 材料引用表、关键工作、错配计数 |
| `coverage.json` | 背景/相关工作/空白/贡献/引用覆盖五类三态 |
| `alignment.json` | 前向 + 后向明细 |
| `validation.json` | 四态门禁逐项结论 |
| `gaps.md` | 人读的缺口与追问清单（每条带 severity 与具体追问） |
| `revision_delta.json` | 回改前后质量账（由 `scripts/revision_log.py` 产出，见第 5 步） |
| `result.json` | 汇总，含 `case_id`、`contribution_map`（每条贡献→章节/图表/引用）与 output_contract 声明的全部字段 |

`output_contract` 若声明了本包未直接生成的字段：同名或同义字段复制；可从台账派生的派生；其余置 `null` 并计入 `uncertainty`——**不会为了让字段看起来满而编造**。

## 5. 支持的引用格式

`\cite{key}` / `\citep{...}` / `\citet{...}`、`[1]` / `[1,3]`、`(Author, Year)`、`Author et al. (2020)`、`（Author2020）`、`Author2020` 连写、中文作者年份。参考文献表支持 BibTeX `@type{key,...}`、内嵌 `\bibitem{key}`、`[1] ...` 编号列表、`Author (Year). Title.` 作者年列表。

## 6. 异常处理（真实测过）

| 情况 | 行为 |
|---|---|
| 材料目录空 / 全不可读 | 写出 `status=blocked` 的 result.json + gaps.md，说明原因 |
| 文献库为空 | `citation_check` 为空，`uncertainty` 写明"无法验证文献真实存在" |
| 引用在材料里查不到 | `status=unverified`，gaps 里追问作者/年份/编号 |
| 真作者 + 错年份 | 绑定到该作者文献并报 `year X != material Y`（混合幻觉检查） |
| 目标期刊格式未知 | 不猜格式；输出统一 Markdown + JSON，格式要求由作者指定 |
| 中英切换 | 中文与英文句子、引用、套话、hedge 词表都已覆盖 |
| 空白无依据 | `gap_without_citation` warn（无锚点）/ `gap_derivation` warn（材料无局限可推），追问"由谁的什么局限推出" |
| 未提供 draft | `status=partial` 且必带 `limits[]`，不假装完成 |
| 扫描 PDF / OCR 失败 | `unreadable` 列出文件，`uncertainty` 写明锚点可能不完整 |

## 7. 已知边界（必须诚实）

1. 机器只判**可定位性与元数据一致性**，判不了"转述是否与原文意思一致""分组是否深刻"——这两项在 gaps.md 留给人工，产物不会写"已验证准确"。
2. 材料没有参考文献表时，只能核对正文引用编号与作者年份，无法验证文献是否真实存在。
3. 扫描 PDF 文本层缺失时，引用锚点抽取会退化，明确写进 uncertainty。
4. 套话词和夸大词只作诊断信号，**不自动删除或改写**——自动删会伤语义。
5. 规则底稿（`--stage auto`）只是机械复述，不是可投稿成稿；好成稿由 Harness/Agent 依据材料写。

## 8. 依赖

Python 3.10+ 标准库即可跑 scan/finish/自测。可选：`pymupdf`/`pypdf` 或 `pdftotext`（PDF）、`python-docx`（DOCX）、`PyYAML`（若需 YAML 材料字段抽取）。无网络依赖，不调用任何外部 API。资源占用：≤50 文本文件、单文件 ≤500KB、总计 ≤2MB。

## 9. 最小示例

`assets/examples/` 下有一组完整可跑示例：`case.json`（标 `"example": true`）、`material/paper.tex` + `material/refs.bib`、`draft.md`（示意成稿）、`result.json`（示意输出，标 `example: true`）。跑法：

```bash
python scripts/run_case.py --case assets/examples/case.json \
  --lexicon assets/lexicon.json --schema assets/schema.json \
  --out /tmp/example_out --stage finish --draft assets/examples/draft.md
```

示意输出只说明接口与流程，**不是任何正式案例的答案**。

## 10. 自测与验证

```bash
python assets/tests/run_selftest.py
```

当前 27/27 通过，覆盖：标题/LaTeX 注释不当断言、`et al.`/`Fig.` 不切碎句子、中文括号引用、引用重叠去重、好稿全绑定、坏稿抓错年份、混合幻觉精确报字段、夸大断言、无稿 partial 带 limits、空材料 blocked、两次运行 8 文件字节一致，以及 v2 新增的**四节齐全 coverage 必为 written、`## 相关工作` 下挂 `###` 分组时 related_work 仍须 written**（两条章节识别回归）。

详细验证记录见 `references/validation-notes.md`（随包附带，说明每个缺陷是怎么在真实运行中暴露并修掉的）。
