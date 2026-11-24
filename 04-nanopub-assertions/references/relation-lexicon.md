# 关系词表与方向校验

`assets/relation-lexicon.json` 是唯一的机读来源：实体类型、关系、每种关系的类型签名、触发词都在里面。本文件说明怎么用、怎么扩、方向错了怎么处理。

## 为什么要有类型签名

只判断"A 和 B 有关系"没有用。`Aspirin` 和 `headache` 之间，是 Aspirin 治疗头痛，还是头痛导致吃 Aspirin，语义完全相反。这类主宾互换在关系抽取里叫 role reversal，是持续存在的错误类型，靠词面相似度无法区分。

签名的做法是给每条关系写死允许的主语类型和宾语类型：

```
TREATS: DRUG|INTERVENTION|CHEMICAL|METHOD  ->  DISEASE|CONDITION
```

落进 `Disease -> TREATS -> Drug` 就是方向反了，不需要再跑一遍模型判断。

## 类型清单

| 类型 | 覆盖 | 判定线索 |
|---|---|---|
| DISEASE | 疾病、障碍、异常状态 | disease, disorder, syndrome, deficiency, dysfunction, 疾病, 缺乏 |
| CONDITION | 状态、现象 | condition, state, status, 状况 |
| CHEMICAL | 化学物质 | acid, vitamin, compound, ion, 化合物 |
| DRUG | 药物与制剂 | 后缀 -mab/-nib/-olol/-statin；drug, inhibitor, 抑制剂 |
| GENE | 基因与变异 | gene, allele, mutation, variant, 基因, 突变 |
| PROTEIN | 蛋白与酶 | protein, kinase, receptor, enzyme, 蛋白, 酶 |
| PROCESS | 过程、机制、路径 | process, pathway, growth, transmission, localization, 机制, 传播 |
| MEASURE | 可量化指标 | cost, uncertainty, error, rate, ratio, GDOP, 指标, 误差, 不确定度 |
| INTERVENTION | 干预措施 | therapy, diet, supplement, training, 治疗, 饮食 |
| POPULATION | 人群、样本、受试对象 | patients, adults, mice, 患者, 小鼠 |
| METHOD | 方法、算法、模型 | algorithm, method, model, framework, 算法, 模型 |
| LOCATION | 地点、区域 | region, site, basin, sea, coast, 区域, 海域 |
| TIME | 时间、时段 | season, month, winter, 季节 |
| ENTITY | 未归类 | 兜底 |

`ENTITY` 表示"类型未定"，不是"类型是 ENTITY"。标成 `ENTITY` 时签名无法校验，校验器给 `type_unresolved`（警告，不是失败）。要拿到方向校验的保护，就得标出具体类型。

## 关系清单

| 关系 | 语义 | 签名约束 |
|---|---|---|
| CAUSES | 导致 | 原因类 → 结果类 |
| PREVENTS | 预防、阻止 | 干预类 → 疾病/过程 |
| TREATS | 治疗、缓解 | 药物/干预 → 疾病 |
| INHIBITS | 抑制 | 药物/基因/蛋白 → 蛋白/过程 |
| ACTIVATES | 激活、促进 | 药物/基因/蛋白 → 蛋白/过程 |
| INCREASES | 提高、增加 | 因素/干预 → 指标/过程 |
| DECREASES | 降低、减少 | 因素/干预 → 指标/过程 |
| ASSOCIATED_WITH | 相关，不主张因果 | 任意 → 任意 |
| PREDICTS | 预测 | 指标/方法 → 指标/结果 |
| DERIVED_FROM | 由…计算得出 | 指标/方法 → 指标/方法 |
| PART_OF | 是…的组成部分 | 任意 → 任意 |
| OCCURS_IN | 发生于 | 过程/疾病 → 地点/时间/人群 |
| REQUIRES | 需要、依赖 | 方法/过程 → 指标/方法 |
| ENABLES | 使能、允许 | 方法/指标 → 过程/指标 |
| MEASURES | 测量、量化 | 方法/指标 → 过程/指标 |

完整签名与触发词以 JSON 为准，本表只是速查。

## 方向错的三种处理

校验返回 `direction_error` 时，按顺序试：

1. **反转主宾**。`Disease -> TREATS -> Drug` 改成 `Drug -> TREATS -> Disease`。前提是证据句的主语确实是药物。若证据是"Aspirin was given to patients with headache"这类被动句，施事被省略，反转时要在 `confidence_basis` 注明"由被动句还原施事"。
2. **换逆关系**。有些谓词有天然反向，如 `PART_OF` 对 `HAS_PART`、`OCCURS_IN` 对 `CONTAINS`。词表没有显式逆关系时，改主宾并保留原谓词是更安全的做法。
3. **降级为 ASSOCIATED_WITH**。方向无法从证据确定时，不要硬猜。标 `ASSOCIATED_WITH`、`relation_type: inferred`，`confidence_basis` 写"证据只支持共现，方向未定"。

`type_mismatch`（两个方向都不匹配）通常意味着类型标错了，或这条根本不该有方向：先检查类型，再考虑降级。

## 触发词与共现的区别

`relation_evidence.trigger` 必须是证据句里真实出现的动词或介词短语。校验器会验证它就在 quote 里。

找不到触发词只有两种可能：证据句选错了（应换到带关系动词的那句），或这条关系只是同句共现。后者必须降级为 `ASSOCIATED_WITH` 并标 `inferred`，不能写成 `CAUSES`。

公开的误抽案例里，`fatty acid causes endothelial dysfunction` 就是共现当因果：原文只说两者共同促成另一个疾病，没有任何一句说脂肪酸导致内皮功能障碍。

## 扩展词表

案例主题超出通用科研关系时，按下面顺序扩：

1. 先确认现有 15 条关系是否真的不够。多数情况是关系选错，不是词表不够。
2. 需要新实体类型：在 `entity_types` 加一项，写 `zh`、`cues`，药物类可加 `suffixes`。同步在 `relations` 里把新类型加进相关关系的签名。
3. 需要新关系：在 `relations` 加一项，`subject_types` 和 `object_types` 必填，`*` 表示不限，`cues` 写真实出现的英文与中文触发词。
4. 加完用一条已知正确的断言和一条主宾互换的断言各跑一遍 `validate`，确认前者通过、后者返回 `direction_error`。

不要在脚本里写死关系；所有关系判断都读 JSON，换词表不需要改代码。
