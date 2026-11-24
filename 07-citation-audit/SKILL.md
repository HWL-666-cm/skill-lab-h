---
name: citation-audit
description: 参考文献与引用管理 Skill。对一份稿件和一份文献库做正文—文末双向一致性核验、编号连锁重排、可解释去重与字段/来源审计，产出可编辑稿件、同步文献表和逐条可回溯的改动记录。适用于引用插入定位、编号更新、文献去重、格式字段补齐与来源一致性检查。纯离线、标准库实现。
---

# 引用审计与整理（Citation Audit）

## 1. 用途与适用条件

把一份稿件和一份文献库整理成**引用可回溯、编号能同步、改动有依据**的成品。

适用：
- 正文引用标记与文末列表对不上（悬空引用、未用条目、跳号、乱序）
- 插删调序后需要重排编号、同步图表注与附录引用
- 同一文献以中英文题名、预印本/正式版、不同数据库导出形式重复出现
- 需要检查 DOI 格式、预印本类型标识、电子资源访问日期等字段
- 需要一份能交给第三方的"改了什么、依据是什么"记录

不适用：联网检索新文献、核验 DOI 是否真实解析、判定论断与文献的语义相关性、按具体期刊细则做全量排版。这些需要外部服务或人工确认，本 Skill **不会伪造已完成**。

## 2. 目录结构

```
SKILL.md                          本文件
prompts/audit-workflow.md         Agent 执行提示词（加载后按此顺序做）
scripts/citation_audit.py         核心审计：双向一致性 / 编号 / 去重 / 字段
scripts/make_result.py            组装 result.json（含 output_contract 适配）
scripts/run_selftest.py           13 条合成自测
tests/cases.json                  自测用例（合成数据，不含论文原文）
references/field-dictionary.md    文献库字段字典与规范化规则
references/dedup-and-styles.md    去重判据与引用位置/格式要点
references/eval-rubric.md         评分点对照与交付自查表
examples/case-example.json        最小调用示例（虚构，不是答案）
examples/output-example.md        示意输出（明确标注非答案）
GITHUB_URL.txt                    公开仓库链接
```

运行环境：Python 3.9+，**只用标准库**，不联网，不装包。

## 3. 输入

| 输入 | 说明 |
|---|---|
| 稿件 | `.md`/`.txt` 或正文文本。支持 `[1]`、`[2,3]`、`[1-3]` 顺序编码制与 `\cite{key}` / `[@key]` 键式；可带"参考文献"段 |
| 文献库 | `.json`：条目数组、`{key: entry}` 映射、或 `{"entries": [...]}` 包装。字段见 `references/field-dictionary.md` |
| 目标规范 | 从题面/用户指令读取（如 GB/T 7714—2015），不假设固定值 |
| `case.json` | 平台运行时提供，含 `output_contract` 和 `case_id`；本地可用示例 |

**先读实际文件再动手**，不要根据文件名或标签猜内容。

## 4. 执行步骤

### 第 1 步：探测
确认稿件路径、文献库路径、引用制式、目标规范。把制式记在心里，后面解释结果要用。

### 第 2 步：审计
```bash
python3 scripts/citation_audit.py \
  --manuscript /app/work/manuscript.md \
  --bib /app/work/references.json \
  --out /app/work/audit.json
```

脚本做四类检查：

1. **正反双向闭包**：正文引用在库里找不到 → `dangling_citation`（硬错误）；库里条目正文没引 → `unused_entry`（警告）。稿件自带"参考文献"段时，列表行不被当作正文引用，而是单独核验列表与库是否同步（`reference_list_gap` / `reference_list_mismatch`）。
2. **编号**：跳号、乱序、重复占用、非法编号；给出按首次出现顺序的 `numbering.proposed`。**悬空编号不进入重排映射**——先补/删，再重排。
3. **去重**：规范化 DOI 相同且元数据无冲突 → 给合并字段与保留/删除键；DOI 相同但元数据冲突 → 保留两条待人工确认；题名+作者+年份一致但 DOI 不同 → 只提示疑似，不自动合并。
4. **字段与来源**：预印本误标 `[J]`、DOI 缺 `https://doi.org/` 前缀、电子资源缺访问日期、缺必需字段；引用落在图题行或过短句末 → 位置警告。

所有字符串比较先做 NFKC 规范化（中文全角、英文 ligature 不影响判定）。**硬错误必须修，警告列入人工确认项。**

### 第 3 步：修订
按 `change_log` 逐条改稿件与文献库：补悬空条目或删无效引用；用 `numbering.proposed` 同步正文与文末；合并重复条目时保留更完整的字段并在 `duplicate_decisions` 留下依据；更正预印本类型与 DOI 前缀。

**红线**：不编造文献、DOI、卷期页；缺字段写 `unavailable` 并列为人工确认；不把弱证据当成合并依据。

### 第 4 步：组装结果
```bash
python3 scripts/make_result.py \
  --case-id <输入 case_id> --case-json /input/case.json \
  --manuscript <原稿> --revised <修订稿> \
  --bib <文献库> --audit /app/work/audit.json \
  --out /app/output/result.json
```

`result.json` 含：`case_id`、`status`、可编辑稿件 `edited_manuscript`、`citation_issues`、`audit_report`、`numbering_plan`、`dedup_decisions`、**同步后的 `bibliography`**、`source_map`、`uncertainties`、`limitations`、`change_log`。若平台 `output_contract` 声明了别的字段名，按 `references/field-dictionary.md` 的别名表补齐；补不出的必需字段会让 `status` 降为 `partial`/`failed` 并写进 limitations——不伪造字段。

同时输出可编辑产物 `edited_manuscript.md` 和 `change_log.csv`。

### 第 5 步：自查
按 `references/eval-rubric.md` 逐条核对。`status=partial` 时必须在 limitations 说明未做完的部分。

## 5. 输出约定

- `/app/output/result.json`：主结果，含输入标识、主产物、来源定位、运行状态、不确定性。
- `/app/output/edited_manuscript.md`：可继续编辑的修订稿。
- `/app/output/change_log.csv`：逐条改动与依据。
- `/app/work/audit.json`：完整审计轨迹（错误、警告、证据、重排映射、去重决策）。

`status` 口径：`ok`=无硬错误无警告；`review_warnings`=仅有警告；`partial`=有硬错误或契约字段缺失；`failed`=无实质结果。

## 6. 异常处理

| 情况 | 处理 |
|---|---|
| 稿件为空 | `empty_manuscript` 硬错误，不返回 ok |
| 稿件无引用标记 | `no_citations_found` 警告，确认是否真的无需来源 |
| 文献库为空 | 所有正文引用判 `dangling_citation` |
| 字段缺失 | `missing_required_field` 硬错误；缺卷期页等只提示，不臆造 |
| `order` 非法 | `invalid_order` 硬错误，要求改成整数或删除 |
| 混合引用风格 | 按各自规则分别核验，在 `inputs.citation_style` 标 `mixed` |
| DOI 解析失败/无网络 | 不声称核验过真实性；列为 limitation |
| 预印本平台不在关键词表 | 用 `is_preprint: true` 显式标记兜底 |

## 7. 自测与验证证据

```bash
python3 scripts/run_selftest.py   # 13/13 passed
```

自测覆盖悬空引用、未用条目、跳号乱序、同 DOI 合并、冲突不合并、预印本误标、DOI 缺前缀、全角规范化、弱证据只提示、干净输入、文末列表错号、键式 `\cite{}`、小数点不切句。

本地验证另做了 A/B 对照：同一批真实公开著录字段构造的草稿，B 版 12 条问题（5 硬错误），A 版修订后 0 条；验证了确定性（同输入两次哈希一致）、三种文献库输入形态、异常输入不崩溃。详见项目内的验证报告（不进提交包）。

## 8. 已知边界

1. 不判定论断与文献的**语义**是否匹配，只做引用位置的启发式警告；语义匹配需人工确认。
2. 弱证据去重**不自动合并**，冲突元数据保留两条，避免误合并同名作者的不同文献。
3. **不联网**核验 DOI 真实性与条目存在性，只核验给定文献库快照内部的一致性。
4. 顺序编码制支持编号重排；键式引用只做双向核验；著者—出版年制和脚注制不做编号重排。
5. 目标期刊的细则（作者缩写、文种分组、页码区间写法）需人工按规范处理，脚本不猜测。
