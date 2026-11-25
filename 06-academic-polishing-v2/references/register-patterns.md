# 语域四类问题模式表（"说得像"与"中英文表达质量"）

`scripts/register_audit.py` 按下面的固定模式穷举，命中即报。四类问题对应评分维度「学术语气与语域」和「中英文表达质量」：改后的文本不能仍是口语腔、宣传腔、直译腔，也不能把动词压成名词的官僚腔。

severity 两档：`error`（硬错误，应当改）与 `style`（语域问题，建议改，少数语境可保留）。`style` 保留时写进 `uncertainties`。

## 1. colloquial —— 口语/宣传腔

| 模式 | 示例 | 改法 |
|---|---|---|
| `a lot of / lots of / a bunch of` | a lot of methods | many / numerous / 具体数量 |
| `really / actually / basically / nowadays` | actually, this works | 删除或改为具体表述 |
| `very/quite/pretty + 形容词` | very important | 更精确的形容词或具体数值 |
| `more and more / less and less` | more and more attention | increasingly / progressively / 具体趋势 |
| `get`（获得义） | we get the result | obtain / become（按语境） |
| `众所周知 / 不言而喻` | 众所周知，…… | 删除，或改为引用具体文献 |

## 2. translationese —— 直译腔/中式英语

| 模式 | 示例 | 改法 |
|---|---|---|
| `with the development of` | With the rapid development of … | 删除开场白，直接陈述现象 |
| `with the improvement of` | With the improvement of … | 删除开场白，直接陈述现象 |
| `there has/have a/an` | There has a lot of methods | there is / there are（主谓一致） |
| `the reason is because` | The reason is because … | the reason is that …，或直接 because |
| `combine … together` | combine them together | combine（together 冗余） |
| `according to my/our opinion` | According to our opinion | 删除，或 we argue / we find |
| `play an important role in` | … plays an important role in … | is essential for / drives / accounts for |
| `has attracted much attention` | … has attracted wide attention | 删除热度开场，直接陈述缺口 |
| `随着……的发展 / 在……方面` | 随着社会的发展 | 删除直译开场 |

## 3. nominalization —— 冗余名词化（"轻动词 + 名词"压掉真动词）

| 模式 | 示例 | 改法 |
|---|---|---|
| `make a(n) … of/with` | made a comparison with | compare |
| `give a(n) … of` | give a description of | describe |
| `carry out a(n) …` | carried out an investigation | investigate |
| `conduct a(n) … of/on` | conducted a study of | study |
| `perform a(n) … of/on` | performed an analysis of | analyze |
| `in the process of` | in the process of filtering | during / while + 动词 |
| `for the purpose of / with the aim of` | for the purpose of evaluation | to / in order to |

动词直接作谓语比"轻动词 + 抽象名词"短、直接、不官僚，是学术写作的通用偏好。

## 4. filler —— 空话套话

| 模式 | 示例 | 改法 |
|---|---|---|
| `It is worth noting that` | It is worth noting that … | 删除，或把要点写成主句 |
| `It should be noted that` | It should be noted that … | 删除，或把要点写成主句 |
| `as is well known / it goes without saying / needless to say` | As is well known, … | 删除（宣称"众所周知"不给引用） |
| `with regard to / with respect to` | with respect to the data | regarding / about / for |
| `在当今社会 / 具有重要的…意义` | 在当今社会，…… | 删除空话，改为具体贡献 |

## 为什么用固定模式而不是模型语感

语域判断若交给模型，同一句话可能一次说"口语"一次说"学术"，结论漂移。固定模式穷举的好处：同一输入永远报同一处、给同一改法，可复核、可回归。代价是模式表外的表达会漏检——所以这张表只覆盖高频表达，且 `register_audit.py` 的 `PATTERNS` 与本文必须同改。
