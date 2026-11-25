# AIDA 细则与改写对照

AIDA 出自 Kuhn 等人对 nanopublication 的扩展（arXiv:1303.2446）：句子必须 Atomic、Independent、Declarative、Absolute。四条的原文定义很短，但落地时几乎每条都有坑。

## Atomic：一句话一个可判断真假的命题

判据不是"这句话长不长"，而是"能不能拆成两句、且两句各自仍能判断真假"。

| 坏 | 为什么 | 好 |
|---|---|---|
| We present an approximation algorithm and prove that its cost is at most 28.9 times the optimal cost while guaranteeing that the uncertainty is at most 5.5U. | 三个结论挤在一句：算法存在、成本因子、不确定度因子 | 拆成三条：算法存在 / 成本 28.9 倍 / 不确定度 5.5 倍 |
| The radius of the circle is 6 m, the radius of the measurement area is 10 m. | 逗号连接两个独立测量 | 两条各写一个半径 |
| Bearing noise is small; therefore the uncertainty decreases. | 分号连接因果 | 一条写噪声大小，一条写因果（但因果需证据支持） |

机械可查的三种情况：长度超过 500 字符、含分号、`and` 后接第二个谓语动词（prove / show / guarantee / ensure / require）。这三种直接判 `atomic` 失败。

`while ...ing`、`thereby`、`therefore` 引导的从句通常带第二个结论，需要检查是否该拆。

## Independent：脱离上下文能读懂

句子里不能有只能靠上文才能确定所指的成分。

| 坏 | 问题 | 好 |
|---|---|---|
| This suggests that age is associated with higher incidence. | `This` 指前一句 | Age is associated with a higher incidence. |
| These two factors can be traded off. | `These two factors` 需要上文的两个因子 | The cost factor and the uncertainty factor trade off against each other. |
| 该结果表明雾季提前。 | `该` 指前文 | 黄海海雾季起始时间提前。 |
| We found that the treatment reduces inflammation. | `We` 指向作者 | The treatment reduces inflammation. |

开头是 This / These / Those / That / It / Such / They / Both / The former / The latter / 该 / 其 / 此 / 这 / 上述 时判 `leading_pronoun`；含 we / our / us / I / 我们 / 本文 / 本研究 时判 `first_person`。

改写指代词时必须回读上一句找到它指的名词短语，找不到就说明原文本身不完整，这条不该做成独立断言。

## Declarative：完整陈述句

以句号结尾，理论上可判真假。疑问句、感叹句、无谓语的短语都不行。

`no_full_stop`、`question`、`exclamation` 由标点直接判定。以 Is / Are / Was / Do / Can / Should 开头判 `inverted_question`。

## Absolute：剥离置信度与发现过程，但保留适用范围

这是四条里最容易做错的一条，因为它要求**同时做两件相反的事**：删掉一些修饰，保留另一些修饰。

原文说的是"忽略真值的不确定性和它是怎么被发现的"，并明确要"通常用现在时"。它没说要把限定条件删掉。

### 该删的三类

| 类型 | 词例 | 去哪 |
|---|---|---|
| 真值不确定性 | probably, possibly, likely, may, might, could, suggest, indicate, seem, appear, 可能, 或许, 似乎, 提示 | `confidence_basis` |
| 发现过程 | we present, we found, this study, our results, results indicate, 本文, 本研究, 结果表明, 研究发现 | `provenance` |
| 时态痕迹 | was, were, found, showed, observed, measured（描述获取过程时） | 改写为现在时 |

### 必须留的三类

| 类型 | 词例 | 去哪 |
|---|---|---|
| 适用范围 | in mice, in patients, for adults, at 20 °C, in the field, 在…条件下 | `qualifiers.scope` 且出现在 `text` |
| 前提条件 | given a fixed U⋆, under the assumption that…, when σ is small | `qualifiers.scope` |
| 极性 | deficiency, lack, reduction, increase, elevated, impaired, 缺乏, 升高 | `qualifiers.polarity` 且出现在 `text` |

### 一个真实例子

原文：

> Given a ﬁxed U⋆, the estimation performance is robust to the change in the bearing noise.

三种写法：

| 写法 | 判定 | 原因 |
|---|---|---|
| Given a fixed uncertainty threshold, the estimation performance is robust to changes in the bearing noise. | 通过 | 前提条件保留 |
| The estimation performance is robust to changes in the bearing noise. | `scope_dropped` | 丢了"给定固定阈值"，断言变宽，与原文不符 |
| It is robust to bearing noise. | 判据全失 | 指代 + 丢条件 + 丢主体 |

第一条才是对的。第二条看起来更"绝对"、更像 AIDA，但它把论文的限定偷掉了，是本题最主要的失分方式。

### 校验怎么抓

`check_scope_loss` 拿**证据所在整句**（不是被截短的 quote）去比：证据里有 `in mice` 而断言里没有对应词，判 `scope_dropped`；证据里有 `deficiency` 而断言里没有任何极性词，判 `polarity_dropped`；证据有数字而断言里的数字对不上，判 `number_mismatch`。

用整句而不是 quote，是因为模型常把 quote 截到只剩主句，截短后限定条件自然不在 quote 里，用 quote 比就永远查不出来。

## 中文论文注意

- 中文没有空格分词，`text_present` 用 2 字以上汉字块匹配，短词容易误命中，主体名尽量写全。
- 中文指代词（该/其/此/上述）判定已覆盖，但"这"作限定词（这五种方法）会误判，需人工复核。
- 中文置信词覆盖可能/或许/似乎/提示/有望，不含"存在…的可能"这类句式，需人工补。
- 中文句末用 。！？ 判句，`no_full_stop` 对中文按 。 判定。

## 自查

写完一条断言，按顺序问四句：

1. 这句话能拆成两句、两句各自还能判真假吗？能就拆。
2. 不看上一句，读者知道 This / 该 / 我们 指什么吗？不知道就换名词。
3. 有主语和谓语、以句号结尾吗？
4. 删掉的修饰里，有没有把"在什么条件下成立"也删掉了？删了要补回来。
