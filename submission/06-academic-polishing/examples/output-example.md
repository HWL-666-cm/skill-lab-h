# 示例输出（示意，非正式案例结果）

> 对应 `examples/case-example.json`。以下内容用于说明"改稿 + 逐句修改说明 + 审计结果"三件套长什么样，**不是赛事正式案例的运行结果**。

## 1. 改稿

The treatment may reduce the incidence of sea fog by approximately 12% in coastal areas [3]; this effect was not statistically significant at inland stations (Fig. 2). Sea fog events were recorded at 14 stations from 2015 to 2020.

## 2. 修改清单

| id | 原文 | 改文 | 类型 | 理由 | risk |
|---|---|---|---|---|---|
| C1 | about 12% | approximately 12% | register | `about` 在期刊正文偏口语；`approximately` 不改变精度 | none |
| C2 | , and this effect | ; this effect | format | 两个独立分句，逗号粘连改为分号 | none |
| C3 | not significant | not statistically significant | term | 补全统计口径，避免被读成"实际无差异" | meaning |
| C4 | Sea-fog | Sea fog | term | 统一到术语表首选写法（原文字面已保留，仅连字符归一） | none |

"刻意未改"的内容放在 `kept` 字段，不进 `change_log`——修改清单里每一条都应是真实发生过的改动，否则第三方逐条核对时会发现"原文=改文"的空记录。

## 3. 未改且需保留的内容

| 内容 | 状态 |
|---|---|
| `may reduce` | 保留——改为 `reduces` 会把可能性变成断言 |
| `[3]` | 保留，位置未动 |
| `Fig. 2` | 保留，格式未动 |
| `12%` | 数值未动，仅修饰词改为 `approximately` |
| `14 stations / 2015 to 2020` | 保留 |

## 4. 审计结果（`scripts/hedge_audit.py` 对上述改稿的输出摘要）

```json
{
  "verdict": "pass",
  "flag_count": 0,
  "numbers": {"ok": true, "missing": {}, "added": {}},
  "citations": {"ok": true, "missing": {}, "added": {}}
}
```

术语回扫（`scripts/term_audit.py --glossary`）：`sea fog` 三处写法已统一，`verdict: pass`。

## 5. 说明

- 该示例的 `verdict: pass` 是脚本对**示例文本**的真实运行结果，可复现；
- 正式案例的结论由平台用自己的固定案例运行产生，本仓库不含、也不得包含预制答案。
