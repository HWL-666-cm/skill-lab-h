# 输出契约与字段 semantics

## 平台契约优先

`output_contract` 由平台在运行时写进 `case.json`，字段名事先不可知。`scripts/contract.py` 支持三种形状：

```json
{"output_contract": ["a", "b"]}
{"output_contract": {"fields": ["a", "b"]}}
{"output_contract": {"a": "说明", "b": "说明"}}
```

对每一个声明的字段：

1. 我们已经用等价名字产出 → 用 `ALIASES` 映射复制过去；
2. 可从已有数据派生 → 派生（`sources` / `artifacts`）；
3. 都没有 → 置 `null`，写进 `contract_report.missing`，并在 `uncertainty` 里说明。

**绝不为了让字段看起来填满而编造值**。这是"材料不足要明确标注"的硬要求。

## 我们稳定产出的核心字段

| 字段 | 含义 |
|---|---|
| `case_id` | 平台给的输入标识，原样保留 |
| `status` | `complete` / `partial` / `blocked` |
| `sources` | 实际读取的输入文件（相对 case 根） |
| `artifacts` | 可编辑源码，`out/source/` 下的相对路径 + sha256 |
| `error_ledger` | `findings[]`：位置、类别、严重度、根因、修复、复验、出现轮次 |
| `changes` | 每条改动：位置、动作、根因、是否应用、是否需要人工 |
| `build_manifest` | 发行版、引擎与版本、命令、轮次、源码哈希、PDF 记录 |
| `reproduce` | 独立复现的 verdict 与逐项检查 |
| `validation` | 门禁检查结果与计数 |
| `uncertainty` | 未解决警告、需人工项、材料缺口 |
| `limits` | 为什么不是 `complete` |

## 常见别名映射

| 平台可能写的字段 | 映射到 |
|---|---|
| `errors` / `diagnostics` / `issues` | `error_ledger` |
| `fixes` / `repairs` / `change_log` | `changes` |
| `manifest` / `environment` / `versions` | `build_manifest` |
| `tex_source` / `latex` / `manuscript` / `source` | `artifacts` |
| `reproducibility` / `reproduction` | `reproduce` |
| `inputs` / `materials` | `sources` |

## 状态判定的严格性

- `complete` 需要同时满足：编译收敛、无未解决阻断项、复现 verdict 为 `verified` 或 `partial`。
- 只要还有 `blocking` finding，或编译没过，就是 `partial`。
- 没有源码/环境不可用才写 `blocked`。

门禁 `validate.py` 会反向检查"是否撒谎"：如果 `status=complete` 但编译没过，或声称无不确定性却存在 `applied:false` 的改动，`no_fabrication` 直接 fail。
