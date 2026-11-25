# 断言—证据对齐规则

## 前向：成稿句子 → 证据

按强度从高到低判定：

| status | 条件 |
|---|---|
| `anchored` | 有引用锚点，且能在材料文献表里解析到对应条目，元数据逐字段一致 |
| `loose` | 有图表/章节/公式编号，或有材料逐字引文，或显式标为"作者判断" |
| `unverified` | 有引用但解析不到条目，或元数据不符 |
| `unanchored` | 以上都没有 |
| `overclaimed` | 强断言词（`overclaim_terms`）且没有 hedge、又属 unanchored/unverified |

**注意**：`unverified` 与 `unanchored` 是两种不同失败——前者"写了引用但查不到"，后者"根本没写证据"。gaps.md 分别追问。

## 后向：材料条目 → 成稿

| status | 条件 |
|---|---|
| `written` | 关键工作被提到，且有引用锚点或年份 |
| `mentioned_without_anchor` | 提到了但无可定位锚点 |
| `not_written` | 完全没出现 |

覆盖对象：材料文献表的每个 key work + 每个图/表锚点。

## 元数据逐字段核对

对每个解析到的引用：

1. 从引用原文抽年份；与材料 `fields.year` 比对 → 不符记 `year X != material Y`
2. 作者匹配（用于"真作者 + 错年份"的混合幻觉绑定）：引用里的姓氏出现在材料 `fields.author` 里即视为同一文献的候选
3. 引用 key 直接匹配（BibTeX key / bibitem key / 编号）

**为什么不只比 key**：成稿可能用 `(Author, Year)` 而非 `\cite{key}`；只比 key 会漏掉这类引用。

## 四态门禁

`pass` / `warn` / `fail` / `not_checked`。

- `not_checked`：没有可判定对象（如成稿没有空白句 → `gap_without_citation` 记 not_checked），**不算通过**
- `fail`：阻断 complete，写 partial + limits
- `warn`：可 complete，但写进 gaps.md 供人工确认

完整检查项见 `assets/schema.json` 的 `gate_checks`。

## claim-scope 分级

`scope_levels`：方向 / 量级 / 确定性 / 因果 / 泛化。台账的 `scope` 字段记录 hedge 词与夸大词，帮助人工判断"句子强度是否被材料支持"。机器不替作者决定 hedge 是否恰当。
