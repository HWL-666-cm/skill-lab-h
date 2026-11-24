# 限定强度词表（hedge lexicon）

供 `scripts/hedge_audit.py` 使用，也是人工抽查时的对照清单。权重含义：**负值＝弱化，正值＝强化**，同一家族内可加权求和，跨家族不可相加。

## 1. possibility｜可能性情态

| 弱（-1） | 中（-0.5） | 替代写法 |
|---|---|---|
| may, might, could, possibly, perhaps, potentially, 可能, 或许, 也许, 有可能 | can | it is possible that, there is a possibility that |

**常见改坏**：`may reduce` → `reduces`。原句说的是"可能降低"，改后成了"确实降低"，这是**把可能性变成断言**，属于最严重的语义偏移。

## 2. evidential｜证据强度

| 弱（-1 ~ -0.8） | 强（+0.2 ~ +1.5） |
|---|---|
| suggest(s), indicate(s), appear(s), seem(s), tend(s) to, 提示, 暗示, 似乎, 倾向于 | demonstrate(s), show(s), confirm(s), establish(es), prove(s), 表明, 证实, 确认, 证明 |

**常见改坏**：`The data suggest that` → `The data demonstrate that`。观察性数据只能 suggest，改成 demonstrate 等于宣称因果已证。

**注意**：`表明` 在中文里强度含糊，本表给 +0.2（略偏强）；若原文用 `提示` 而改文换成 `表明`，脚本会报强化，需回改。

## 3. certainty / scope｜断言与适用范围

| 收窄（负） | 放大（正） |
|---|---|
| in this cohort, in this study, in our sample, under these conditions, at present, currently, preliminary, limited to, only, 本队列, 本研究, 本样本, 初步, 仅, 目前 | generally, in general, universally, always, all, 普遍, 始终, 所有 |

**常见改坏**：`in this cohort` → 直接删掉；`at present` → 删掉。删限定条件等于**把单中心结果说成普适结论**，这类改动在摘要里最常见，也最容易被审稿人抓。

## 4. negation｜否定与阴性结果（不参与加权，只查数量）

`not significant` / `no significant` / `did not differ` / `non-significant` / `no difference` / `无显著` / `不显著` / `未见差异` / `站不住` / `不成立` / `尚不多见` / `仍然少见` / `鲜见` / `少见` / `尚未见`

中文的"鲜见""尚不多见""站不住"表达的是否定或收窄判断，与"not significant"同类，按**出现次数**守恒（改后不得多于不得少于原文）；正向放大词（`十分常见`、`十分普遍`、`广泛存在`、`均如此`）归在 scope 家族按强度加权。两族职责不同，同一个词不要同时放进两族，否则会双重计数。

**规则**：改后数量**不得少于**原文。阴性结果被改写成"similar""comparable""no effect"都算丢失——`similar` 是等价性判断，`not significant` 是检验未达阈值，两者在统计上不同。

## 5. 扩充词表的方法

1. 从自己领域的 20 篇高被引论文里抽取情态与限定表达，按上面四个家族归类；
2. 同时在 `LEXICON` 里加词与权重，两处必须同步，否则审计与文档不一致；
3. 加词后跑一次 `--original a --revised a` 自检，确认基线 `flag_count=0`，否则说明新词有重叠匹配。
