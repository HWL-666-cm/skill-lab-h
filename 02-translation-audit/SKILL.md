---
name: translation-audit
description: >-
  科研文献中英翻译与可核验性审计。用在需要把论文/摘要/段落译成中文并保证
  术语一致、段落齐全、数字单位引用不走样时：先按 PDF 版面重建段落（双栏按阅读顺序、
  页眉自适应剔除、跨页续段标记），抽取领域术语候选并锁定译名，再逐段译成双语对照，
  最后用脚本硬核验术语漂移、漏段/错号、数字单位引用否定守恒。
  只做英文/中文互译与核验，不承担论文写作、文献综述或图表复刻。
---

# 文献翻译：术语锁定 + 译文可核验

## 这个 Skill 解决什么

基础 Agent 翻译科研文献时反复出现三类硬伤（有公开研究量化：术语误译占文档级错误的 77–80%）：

1. **术语漂移**：同一个 `lead time` 在摘要叫"提前时间"、正文叫"领先时间"、图注又叫别的。
   写进提示的术语表管不住它。
2. **段落不全**：长文跨页/跨栏/跨章节时漏段、重复、错位，段号对不上原文。
3. **关系走样**：数字写成中文丢了锚点、单位被吞、否定被抹平、引用年份消失。

本 Skill 的做法是把"能机器判死的"做成硬约束：**脚本负责"锁"和"查"，Agent 负责"译"**。
不假装脚本会翻译，也不假装能判译文文采——只保证术语、段落、字面事实三项可核验。

## 何时用 / 不用

**用**：要把一篇论文或明确段落区间译成中文（或中译英）并交付双语对照；
要求术语统一、能回原文定位、可复核。

**不用**：只问一个词/一句话的意思；只做摘要不做翻译；要求改写润色而非翻译。

## 六步流程（顺序不可跳）

| 步 | 做什么 | 谁做 | 产出 |
|---|---|---|---|
| 0 | 读 `case.json`/`task.md`，确认语言方向与范围 | Agent | 边界说明 |
| 1 | PDF→段落级结构（pid/页码/章节/类型） | `scripts/pdf_paragraphs.py` | `paras.json` |
| 2 | 抽术语候选 → 审核收紧 → **填译名锁定** | `term_extract.py` + Agent | `glossary.json` |
| 3 | 按 pid 逐段翻译，守翻译规则 | Agent | `translation.json` |
| 4 | 审计术语/覆盖/锚点/否定 | `scripts/translation_audit.py` | `audit.json` |
| 5 | 修→重审（≤2 轮）→ 组装结果与产物 | Agent + `make_result.py` | `result.json`+`bilingual.md`+`glossary.csv` |

详细执行见 `prompts/translation-workflow.md`。

### 命令速查

```bash
python3 scripts/pdf_paragraphs.py --pdf <原文.pdf> --out /app/work/paras.json
python3 scripts/term_extract.py  --paras /app/work/paras.json --out /app/work/glossary.json
#  ← 此处 Agent 必须审核并填 target、加 forbidden、置 locked=true
python3 scripts/translation_audit.py --paras /app/work/paras.json \
    --glossary /app/work/glossary.json --translation /app/work/translation.json \
    --scope 8,13,16 --out /app/work/audit.json
python3 scripts/make_result.py --case-id <case_id> --case-json /input/case.json \
    --paras /app/work/paras.json --glossary /app/work/glossary.json \
    --translation /app/work/translation.json --audit /app/work/audit.json \
    --out /app/output/result.json
```

## 三个关键设计（为什么这样做）

**1. 从 PDF block 重建段落，不从预提取 txt 猜。**
实测双栏 PDF 的 txt 每行只有 50–64 字符，段落边界已丢失；而 PDF block 本身是段落且带 `x0/y0`，
按 `x0` 分栏、栏内按 `y0` 排序才得到正确阅读顺序。页眉页脚用"跨页重复的短行"自适应识别，
不写死坐标，换期刊版式也能用。

**2. 术语表必须锁定后才翻译。**
脚本只给候选（缩写定义 + 高频名词短语）和出现位置，译名由 Agent 定。
因为术语译名涉及领域约定（`low-visibility procedure` 在民航是"低能见度程序"），脚本不该假装懂。
锁定后 `forbidden` 列表让"漂移"变成可检测的硬错误。

**3. 结构性数字与普通数字分开检查。**
引用年份 `(Author, 2019)`、方括号 `[3]`、公式编号 `(1)` 各有专门检查项；
普通数字（`+2 h`、`89.7 %`）才走数字守恒。混在一起会重复计数并误升级为硬错误。

## 输入与输出

**输入**：`/input/case.json` + `task.md` + 原论文（PDF 给实际文件，读真实内容，不按标签猜）。

**输出**：`/app/output/result.json`（含全部 `output_contract` 字段与 `case_id`）+ `bilingual.md` + `glossary.csv`。

`result.json` 关键字段：`status`（ok/partial/failed，诚实）、`translation`（段落级对照）、
`glossary`、`audit_report`、`source_map`、`task_coverage`、`uncertainties`、`limitations`、`change_log`。
字段全表见 `references/field-dictionary.md`。

## 异常处理

| 异常 | 处置 |
|---|---|
| 无文本层/扫描页 | 标 `low_text_page`，**不编造文本**；同时把该页渲成 `pages/pNN.png`（150 dpi）落盘，`detail` 与 `scan_page_images` 里写明文件名。只说"需 OCR"而拿不出图，等于把活推给一个看不见页面的人 |
| 跨页/跨栏续段 | 标 `continued_from`，Agent 判断是否合并 |
| 术语未定译名 | `glossary_unlocked` 警告，不进一致性检查，但必须补 |
| 局部/分块翻译 | 必须给 `--scope`，否则未译段被正确报成漏段 |
| 公式被拆成碎片 | `kind=formula` 隔离，不译；公式内可译文字单列 |
| 原文疑似笔误 | 按原文译 + `uncertainties` 单列，不悄悄纠正 |
| 译不准 | 译文标 `【待核】` + 进 `uncertainties` |
| 契约字段补不出 | `status` 降 `partial` + 写进 `limitations` |

## 能力边界（必须如实告知使用者）

1. 脚本**不能判译文是否通顺/地道**，只判术语、覆盖、字面锚点。
2. 术语候选需人工审核（可能带修饰语或误收动词）。
3. 否定检测是词频级：整段否定丢失能抓，只丢其中一处可能漏（定为 warning）。
4. 扫描件不在能力范围，只标记不处理。
5. 表格碎片默认不译，需译时人工指定。

## 自查

交付前按 `references/eval-rubric.md` 的清单逐条打勾。最低要求：
`verdict` 不是 `needs_revision`、`status` 诚实、每段可回原文定位、没有把示例当结果。

## 文件结构

```
SKILL.md                      本文件
prompts/translation-workflow.md   六步执行细化
references/field-dictionary.md    字段字典与问题类型全表
references/translation-rules.md   术语/数字/否定/限定的保真规则
references/eval-rubric.md         评分对照与交付自查
scripts/pdf_paragraphs.py     PDF→段落级结构
scripts/term_extract.py       术语候选抽取
scripts/translation_audit.py  译文审计
scripts/make_result.py        结果组装 + 可编辑产物
scripts/run_selftest.py       合成用例自测（13 条）
tests/cases.json              自测用例
examples/                     最小调用示例与输出示意（非正式结果）
GITHUB_URL.txt                本题公开链接
```

依赖：Python 3.10+、PyMuPDF（`pip install pymupdf`）。其余仅标准库。无网络依赖。
