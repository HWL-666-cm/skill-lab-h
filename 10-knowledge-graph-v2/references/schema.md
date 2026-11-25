# 本体：8 类实体、13 类关系

先定义再抽取。没有本体的抽取会把图做成"带箭头的词云"：节点名不一致、关系全是 `RELATED_TO`、无法验证方向。

## 实体类型

| 类型 | 中文 | 判据 | 常见错法 |
|---|---|---|---|
| `PHENOMENON` | 现象 | 自然现象或过程（海雾、平流雾、上升流、消散） | 把"雾预报"整体当现象；预报是任务，不是现象 |
| `METHOD` | 方法 | 模式、算法、方案、反演技术 | 把 `model` 这类裸词建成节点；应是"numerical model""WRF" |
| `DATASET` | 数据 | 观测网、再分析、浮标、探空、航次 | 把数据产品和使用它的实验混成一个节点 |
| `VARIABLE` | 变量/指标 | 物理量或评价指标（能见度、RMSE、CSI） | 把"RMSE = 1.83°C"整串当变量；数值应建 `VALUE` |
| `LOCATION` | 地点 | 海区、港口、站点、模式区域 | 把"东南沿海"这种方位描述当正式地名 |
| `TIME_PERIOD` | 时段 | 研究时段、季节、个例日期 | 把论文里的表号当时间 |
| `VALUE` | 数值 | 带单位的定量结果，数字必须出现在证据句中 | 把两个站点的值合成一个"平均值" |
| `PERSON` | 研究者 | 仅在需要区分"谁的主张"时建节点 | 把作者列表全建成节点 |

## 关系类型

方向写作「主语 → 宾语」。

| 关系 | domain → range | 含义 | 反向触发词 |
|---|---|---|---|
| `APPLIES_METHOD` | 现象/数据/变量/地点 → 方法 | 某对象由某方法处理 | `was used for`、`using` |
| `TARGETS` | 方法 → 现象/变量 | 方法的预报/预测目标 | — |
| `EVALUATES` | 方法 → 变量/数据 | 用某量或数据检验效果 | `compared with/against` |
| `ACHIEVES` | 方法 → 数值 | 方法取得的定量结果 | — |
| `CAUSES` | 现象/变量 → 现象/变量 | 原文明确的因果 | `due to`、`caused by`、`attributed to`、`formed by` |
| `ASSOCIATED_WITH` | 任意 → 任意 | 只表达相关/共变，权重低于因果 | — |
| `IMPROVES_ON` | 方法 → 方法 | 明确比较并判优劣 | `worse than`、`outperformed by` |
| `OCCURS_AT` | 现象/变量 → 地点 | 出现地点 | — |
| `OBSERVED_DURING` | 现象/变量/方法/地点/数据 → 时段 | 对应时段 | — |
| `MEASURED_BY` | 变量 → 方法/数据 | 由某手段测得或派生 | `measured by`、`derived from` |
| `PART_OF` | 地点 → 地点 | 包含关系 | — |
| `DEFINED_AS` | 现象/变量 → 数值 | 判定阈值（如雾 = 能见度 ≤ 1100 m） | `define … as` |
| `CONTRADICTS` | 任意 → 任意 | **由冲突检测生成**，不由抽取生成 | — |

## 为什么不用 `RELATED_TO`

`RELATED_TO` 把"使用""优于""导致""共现"压成同一种边，下游无法区分，评审也无法核对方向。**写不出具体动词就不建边**：少一条边只是召回损失，错一条边会污染所有经过它的路径。

`ASSOCIATED_WITH` 是唯一的宽关系，但有三条限制：只在原文确实只说"相关/共变"时用；权重低于因果；查询时不能当因果返回。

## 需要扩展本体时

1. 在 `assets/schema.json` 的 `relation_types` 里加条目，写清 `domain`、`range`、`definition`、`examples`。
2. 若新类型来自材料（例如"同化""订正"），把它的原文触发词写进 `definition`，不要改 `scripts/extract.py` 里的规则表——规则表只服务候选生成，草稿才是判定层。
3. 重跑 `python assets/tests/run_selftest.py`，确认 `signature` 检查仍覆盖新类型。
4. 不要为了容纳某条难写的边而放宽 `domain/range`；放宽等于取消类型检查。

## 类型不匹配的处理

校验器按 `domain/range` 拒绝（`type_mismatch`）。常见修法：换更准确的关系（`SST → RTG-SST` 用 `MEASURED_BY` 而不是 `APPLIES_METHOD`），或改节点类型（`RTG-SST` 是数据而不是方法）。两者都不行时，说明这条断言本身写错了。
