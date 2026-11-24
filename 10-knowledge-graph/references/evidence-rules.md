# 证据规则：怎么引才算"回得去"

本题的位置单位是**组织方 JATS 段落 ID**，不是 PDF 页码。材料里没有页码，因此任何 `page` 字段都是编造，校验器一律判 `invented_page`——哪怕它写的是"自建第 1 页"。

## 一条合格的证据

```json
{"source_id": "PMC9359529", "paragraph_id": "p007",
 "quote": "In this study, the numerical model WRF (v.3.9.1.1: [24]) was used for the sea fog simulation."}
```

三个条件同时成立才算合格：

1. `source_id` 与 `paragraph_id` 能在材料里找到（否则 `paragraph_not_found`）；
2. `quote` 是该段里**连续的一段原文**（否则 `evidence_drift`）；
3. 主语和宾语的写法都出现在这段引文里（否则 `endpoint_not_in_quote`，降为警告）。

## 逐字的三条细则

- **不要整理引文。** 删掉从句、改时态、补代词、把 `e.g.` 换成"例如"，都会让引文变成"语义正确但在原文里搜不到"。人工阅读看不出问题，机器一比就暴露——这正是对照实验里基线失败最多的一项（9/9 条边全部 `evidence_drift`）。
- **跨句用 `…`。** `"A … B"` 会被拆成两段分别匹配，各自必须逐字且顺序一致，记 `contiguous: false`。不要用省略号掩盖删改。
- **排版差异会自动归一。** 连字 `ﬁ/ﬂ`、弯引号、各种破折号、不间断空格、全角半角，在比对前统一折叠，所以 `ﬁxed` 能匹配 `fixed`。这条是实测踩出来的：不折叠时 PDF 里的 `ﬁ` 让合法引文全部匹配失败。

## 数值证据

`VALUE` 节点的每个数字都要出现在引文里（`numeric_grounded`）。三种常见错法：

| 错法 | 例子 | 结果 |
|---|---|---|
| 四舍五入 | 原文 `0.965`，节点写 `0.97` | `fabricated_number` |
| 单位换算 | 原文 `1.83°C`，节点写 `1.8 K` | `fabricated_number` |
| 合并范围 | 原文 `0.82 and 0.96`（一个区间），拆成两个节点 | 看起来像冲突，实际是拆错 |

把区间整体建成一个 `VALUE`（`"0.82 and 0.96"`），比拆成两个值更忠实。

## 证据强度与归属

强度按来源判定，不由作者意愿决定：

| 类别 | 权重 | 判定信号 |
|---|---:|---|
| `own_result` | 0.9 | 第一人称/`this study`，且无引用标记 |
| `own_method` | 0.8 | 同上，描述方法或配置 |
| `review` | 0.5 | `generally`、`typically`、`is known to` |
| `cited` | 0.4 | `[n]`、`et al.`、`previous studies`、`was reported` |
| `hypothesis` | 0.2 | `may`、`might`、`could`、`suggest` |
| `background` | 0.3 | 以上都不命中 |

两个容易判错的分界：

1. **引用标记挂在工具上，不算转述。** `WRF (v.3.9.1.1: [24])` 里的 `[24]` 是在引用模式版本的出处，不是在转述别人的结论。句中有第一人称时判为本文方法；没有第一人称却标 `own_result` 才判 `strength_overclaim`。
2. **`cited` 的边不能当本文结论用。** 例如 `CWM 与 sea fog 强相关` 这句出自 `As reported in Cho et al. [13]`，强度只能是 0.4，`attribution: cited_work`；同一对实体在本文结论段还有一条 `CAUSES`，强度 0.9。两条并存，查询时分别标出——这就是"区分作者自述与他人转述"的落地方式。

## 什么不能当证据

| 材料 | 能否作证据 | 原因 |
|---|---|---|
| 正文段落 | 能 | — |
| 摘要 | 能 | 但覆盖面窄，结论常缺条件 |
| 图表标题（caption） | 能，仅限现象/配置级 | 图内像素值不在材料里，不能从中读数 |
| 表格单元格 | 不能（本材料未提供单元格索引） | 若只有 caption，只能支持"存在该表"这类断言 |
| 补充附件 | 不能 | 材料不含 |
| 模型常识 | 不能 | 不是原文 |

## 定位失败时怎么办

- `paragraph_not_found`：先跑 `python scripts/materials.py --case /input/case.json` 看真实段落 id；不要改成"看起来像"的 id。
- `evidence_drift`：从该段复制原文；不要为了迁就已有引文去改段落文本（材料是只读的）。
- `endpoint_not_in_quote`：把引文扩到同时含两端；若两端确实不在同一句，这条断言应拆成两条，或改用中间的桥接实体（**不要**把两段拼成一句）。
