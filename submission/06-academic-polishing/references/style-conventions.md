# 语域规则（genre conventions）

每条规则写成「规则 → 反例 → 改法」三段。**只有成对给出反例的规则，模型才能稳定执行**；只写"要用学术语气"这类抽象描述，等于没有规则。

## A. 通用（所有学术文体）

| # | 规则 | 反例 | 改法 |
|---|---|---|---|
| A1 | 不用口语化程度副词 | a **pretty** clear trend | a **relatively** clear trend |
| A2 | 不用宣传性形容 | **remarkable / novel breakthrough** | **notable / previously unreported** |
| A3 | 避免绝对化 | **always / never / all** | **generally / rarely / most** |
| A4 | 不用第一人称复数做主语滥用（期刊） | **We think** the data is good | **The data indicate** |
| A5 | 逗号粘连 → 分号或拆句 | X was observed**, and** Y was found | X was observed**;** Y was found |
| A6 | 数量精度不得抬高 | **about 12%** → **12%** | **approximately 12%** |

## B. 期刊论文（English, IMRaD）

- 摘要：不用引用编号，不用图表指向；时态现在时陈述结论，过去时陈述操作。
- 方法：被动语态可接受，但**主语必须明确**（谁做了测量）。
- 结果：只报观察，不解释；`significant` 必须带统计口径（`statistically significant, p < 0.05`）。
- 讨论：允许 `may / suggest`，**不得把结果段的相关性升级为因果**。

## C. 学位论文（中文）

- 用"本文"而非"我们"；章节自指用"本章"。
- 术语首次出现给中英对照：`能见度（visibility）`，后文统一用中文或统一用英文缩写，不混用。
- 慎用"显著"，中文语境里容易被读成"明显"，若指统计显著必须写"统计显著（p<0.05）"。

## D. 基金申请书

- 需要"必要性"叙述，但**不得虚构前期成果**；没有的数据写"拟通过…获取"。
- 避免"国际领先""填补空白"这类无证据断言，改为"拟解决…问题"。

## E. 审稿回复（response to reviewers）

- 逐条对应：`Reviewer #1, Comment 3:` → `Response:` → `Change in manuscript (page X, line Y):`。
- 不同意时先承认关切，再给证据，不用"the reviewer is wrong"。

## F. 中译英

| 问题 | 反例 | 改法 |
|---|---|---|
| 直译腔 | **carry on the research** | **conduct the research** |
| 冗余名词化 | **the improvement of the accuracy was achieved** | **accuracy improved** |
| 连接词滥用 | **Moreover… Furthermore… Additionally…** 连续三段开头 | 只在真正递进处用，其余靠句序承接 |
| 主语缺失 | **Through analysis, it was found…** | **Analysis showed that…** |
| 信息重心后置 | 长状语堆在句首 | 结论前置，条件后置 |

## G. 不可动的四类内容

1. 数字、单位、百分比、样本量、p 值、置信区间
2. 引用编号、作者年份、图表指向、公式编号
3. 专有名词、基因/蛋白/地名/仪器型号的标准写法
4. 否定词的位置（`not all` ≠ `all not`）

改动以上任一项，都必须在 `change_log` 里给 `type` 与 `reason`，并跑 `hedge_audit.py` 复核。
