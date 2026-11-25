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

> sha256 按 **LF 行尾**计算；若你的 checkout 或打包环节把行尾转成 CRLF，文件 hash 会不同（例如 src.txt 会变成 `53f45196c2eb`），但 `counts` 与 `verdict` 的结论不变。核对时请直接从提交包（`outputs/references/evidence-data/`）取文件算 hash，而不是从本地 checkout。

```json
{"mode":"diff","verdict":"clean",
 "counts":{"before":{"colloquial":4,"translationese":5,"nominalization":1,"filler":3,"error":3,"style":10},
           "after":{"colloquial":0,"translationese":0,"nominalization":0,"filler":0,"error":0,"style":0},
           "resolved":13,"remaining":0,"new":0}}
```

要点：`resolved=13`（13 处全消除）、`new=0`（改稿没有引入新的翻译腔）。`new` 按**计数差**计算——同一短语从 1 处变 2 处会报 `new=1`，不会因为"改前就存在"而漏报（该行为由 `tests/cases.json` 的用例锁进回归）。

被消除的 13 处包括：`With the rapid development of`、`attracted more and more attention`（translationese）、`more and more`（colloquial，与前者是两条独立命中）、`There has a`（error）、`a lot of`、`make an analysis of`（error）、`The reason is because`（error）、`play an important role in`、`It is worth noting that`、`very important`、`众所周知`、`在当今社会`、`具有重要的理论意义`。共 13 条，与 `resolved=13` 一致。

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

## 证据 4｜A/B 对照：裸 Agent 10 处返修 vs 本 Skill 0 处（已填实际数字）

上面三条证据证明脚本能力；这一条证明"增益"。**已跑通的一组 A/B** 见 `references/eval-rubric.md` 第 3 节——输入 `references/evidence-data/ab-src.txt`，条件 A（模拟裸 Agent 典型改坏）与条件 B（本 Skill）分别跑三个审计脚本，结果：

| 指标 | 条件A(裸Agent) | 条件B(本Skill) |
|---|---|---|
| `hedge_audit` flags | 4（`hedge_strengthened`×2、`negation_lost`、`fact_missing`） | 0 |
| `register_audit` findings | 5（口语1/直译2/名词化1/空话1） | 0 |
| `term_audit` drift | 1 | 0 |
| **返修条目合计** | **10** | **0** |

24 分表（11 项可判）填为 A=4/22、B=22/22，差 +18。六个审计 JSON 随附在 `references/evidence-data/ab-*.json`。

诚实边界：条件 A 是**模拟**的裸 Agent 输出（本地无裸模型可调），但两个条件的审计结果都是脚本真实跑出来的；`#10` 重复稳定性在固定文本下测不出基线方，两边标 `—`。

> 说明：平台固定案例、白板与对照结果由平台提供，本 Skill 不预交答案。本文件三条证据为**自建合成文本**的运行记录，用于证明脚本能力，不是平台正式案例的结果。
