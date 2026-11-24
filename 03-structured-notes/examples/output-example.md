# 示意输出（不是正式案例结果）

> 以下为格式演示用的虚构片段，数值与文字仅示意结构，**不是任何论文的真实内容**。实际运行必须由 `/input/case.json` 提供的 PDF 生成。

## paper_card（论文卡片）

| 字段 | 示例值 |
|---|---|
| title | （示例）某海域海雾客观预报技术研究 |
| research_question | 建立本地化海雾客观预报模型并检验 |
| data | 2016–2021 某沿海观测站 + ERA5 逐 3h |
| method | 预报因子初选；配料法／决策树法／指数法；TS 检验 |
| main_findings | 24h 配料法最优（０.４４）；48/72h 决策树最优 |
| limitations | 某海区效果较差；仅检验特定时段 |
| condition_for_conclusion | 检验样本为 2023 年 1–4 月 08 时起报的 118 个样本 |

## claim_notes（一条完整笔记）

```json
{
  "id": "C4",
  "field": "finding",
  "value": "配料法 24h TS 平均为 ０.４４",
  "anchor": {
    "page": 6,
    "section": "２ 检验结果分析",
    "quote": "２４ｈ预报的ＴＳ评分平均为０.４４"
  },
  "section_ref": "２ 检验结果分析",
  "note": "承接上一章的方法介绍，给出 24h 结果"
}
```

## anchor_audit（核验报告示意）

```json
{"overall": "ok", "counts": {"ok": 5, "weak": 0, "mismatch": 0}, "total": 5}
```

真实输出见 `/app/output/result.json`，逐条可核对表见 `/app/output/notes.csv`。
