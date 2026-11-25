# 运行证据（可复核，不是自述）

题面写明「文字自述不能替代实际运行证据」。本文件记录本 Skill 三条**可本地复现**的运行证据，全部给出输入、命令、输出与 sha256。评审可逐条重跑核对；三条证据分别对应评分维度「结果正确性」「增益可验证性」「创新证据」。

复现前置：`cd` 到本 Skill 根目录，`python3`（或 `python`）可用、只用标准库、不联网。全部输入与输出随附在 `references/evidence-data/`。

## 证据 1｜语域审计：直译腔/口语腔/名词化 13 处 → 0 处

输入两段文本（原文 `src.txt` 带 13 处语域问题，改稿 `revised.txt` 已清除），跑 diff 模式：

```bash
python3 scripts/register_audit.py --original references/evidence-data/src.txt \
  --revised references/evidence-data/revised.txt --out /tmp/register_diff.json
```

- 原文 sha256 前 12 位：`45a527385891`
- 改稿 sha256 前 12 位：`6e86d9b3162b`
- 输出（随附 `references/evidence-data/register_diff.json`）：

```json
{"mode":"diff","verdict":"clean",
 "counts":{"before":{"colloquial":4,"translationese":5,"nominalization":1,"filler":3,"error":3,"style":10},
           "after":{"colloquial":0,"translationese":0,"nominalization":0,"filler":0,"error":0,"style":0},
           "resolved":13,"remaining":0,"new":0}}
```

要点：`resolved=13`（13 处全消除）、`new=0`（改稿没有引入新的翻译腔）。`new` 按**计数差**计算——同一短语从 1 处变 2 处会报 `new=1`，不会因为"改前就存在"而漏报（该行为由 `tests/cases.json` 的用例锁进回归）。

被消除的 13 处包括：`With the rapid development of`、`attracted more and more attention`、`There has a`（error）、`a lot of`、`make an analysis of`（error）、`The reason is because`（error）、`play an important role in`、`It is worth noting that`、`very important`、`众所周知`、`在当今社会`、`具有重要的理论意义`。

## 证据 2｜守恒审计：把"可能"改成断言、删掉"约"被当场报出

同一段原文与"改坏版"，跑三层守恒复检：

```bash
python3 scripts/hedge_audit.py --original references/evidence-data/conserv-src.txt \
  --revised references/evidence-data/conserv-bad.txt --out /tmp/conserv_audit.json --quiet
```

- 原文：`The treatment may reduce the incidence of sea fog by about 12% in coastal areas [3].`
- 改坏版：`The treatment reduces the incidence of sea fog by 12% in coastal areas [3].`
- 输出（随附 `references/evidence-data/conserv_audit.json`）：`verdict=review`、`flag_count=2`，两处 `hedge_strengthened`（`may`→删、`about`→删）。

这演示的是题面「没改坏」里的头号失败：`may reduce`→`reduces` 把可能性变断言、`about 12%`→`12%` 把精度抬高。脚本按**有限集合 + 留痕核对**抓出，不依赖词表外表达。

## 证据 3｜自测：14 条用例全过，含负样本防误报

```bash
python3 scripts/run_selftest.py
```

输出 `用例 14 条，通过 14 条，失败 0 条`。14 条 = 8 守恒 + 1 术语 + 5 语域。其中 5 条语域含 **2 条负样本**：

- `register-math-term`：`with respect to each parameter`（数学固定搭配）**不得**报 filler；
- `register-cn-normal`：`在误差控制方面`（正常中文表达）**不得**报 translationese。

负样本的价值：只放"故意写错"的正例，自测永远测不出"把对的判成错的"。这两条锁死两条已知误报（曾在早期版本命中，已从 `register_audit.py` 的 `PATTERNS` 移除）。

## 对照实验怎么跑（把「使用增益」落成数字）

三条证据证明了脚本能力。要证明"加载 Skill 比裸 Agent 好"，按 `references/eval-rubric.md` 的 24 分表成对跑：

| 步 | 做什么 | 记录 |
|---|---|---|
| 1 | 取一段 300–800 字真实学术文本 + 术语表，固定哈希 | 原文/术语表 sha256 |
| 2 | 条件 A（裸 Agent）：只给「请润色这段并说明改了什么」 | 输出全文、`hedge_audit` 与 `register_audit` 的 flag 数 |
| 3 | 条件 B（本 Skill）：分块编辑 + 守恒复检 + 语域复检 | 同上 |
| 4 | 两份去来源标记，交给同一评分人盲评（24 分表） | 打分 |
| 5 | 数两边"仍需人工返修"条目 | 返修数 |

平台用固定案例跑裸 Agent 与本 Skill 时，就是第 2/3 步的自动化版；本 Skill 的 `hedge_audit.py`/`term_audit.py`/`register_audit.py` 把"返修条目"变成可点数的 flag，评审可直接读 JSON，不必逐句人肉比对。

> 说明：平台固定案例、白板与对照结果由平台提供，本 Skill 不预交答案。本文件三条证据为**自建合成文本**的运行记录，用于证明脚本能力，不是平台正式案例的结果。
