# 源码级正确性审计（编译通过 ≠ 改得对）

`diagnose.py` 是**日志驱动**、在编译期跑：它回答"编译得通吗、错在哪一行"。
`audit.py` 是**源码驱动**、在编译成功后跑：它回答"改得对吗、交得可用吗"。

两者互补：前者抓编译错误，后者抓"编译干净但产物错误/脆弱"的问题——这正是
"改得对"（公式符号与编号、表格数值与列宽、交叉引用与参考文献、版式）与
"交得可用"（结构清楚、可维护）要考察的部分。

## 四类检查

| 检查 | 抓什么 | 编译期能否发现 | 审计的价值 |
|---|---|---|---|
| citation | `\cite*` 键 vs `.bib` 条目键：缺失 / 未引用 / 近音拼写错 | 缺失会报 `Citation undefined`（已抓） | 补上**未引用条目**与**近音候选**，帮人定位到底该补哪个键 |
| cross_ref | `\label` vs `\ref/\eqref/\pageref/\autoref`：指向不存在 / 从未被引用 | 指向不存在会报 `Reference undefined`（已抓） | 给出**具体的 label 键**与近音候选，并列出**从未被引用的 label** |
| layout | `\resizebox/\adjustbox/\scalebox` 硬缩放、表格内 `\tiny/\scriptsize`、`\label` 在 `\caption` 之前、`[H]/[!h]` 强固定浮动体 | **编译不报错**，但产物错误或难维护 | 这些是 flonat 等成熟编译 Skill 的"source-pathology"清单，本包此前没有 |
| — | 表格列数（`{lr}` 声明 vs 每行 `&` 数） | 会报 `Extra alignment tab`（已抓） | 不重复实现 |

## 严重度与状态

- `major`：最终产物里的真实缺陷（缺失引用键、指向不存在的 label、硬缩放、label 在 caption 前）。
  - 会让 `result.status` 从 `complete` 降为 `partial`——因为这些是"改得对"没满足，不能自报"完成"。
- `minor`：卫生/可维护性建议（未引用的 bib 条目、未使用的 label、表格缩字号、强固定浮动体）。

审计**只报告、不改写**：`findings[]` 每条带 `location`（file:line）与 `suggestion`，作为
评审证据，不给脚本"改数值/改符号/改引用键"的授权。

## 与 diagnose 的判据边界

同一个未定义引用，`diagnose` 从日志看到"Reference undefined"（major），`audit` 从源码
看到"`\ref` 指向不存在的 `\label`"（major）。两条证据一致时，`emit.py` 只把它算一次
（都进 `major_left`/`audit_major`，status 降为 partial 一次），不重复扣。

## 实现要点（避免回归）

- **行号映射**：多个 `.tex` 拼接后按字符建 offset 表，`\input/\include` 的子文件也能报准
  `file:line`（不要求 `-file-line-error`）。
- **近音候选**：编辑距离 ≤2 才提示"可能是 X 的拼写错误"，距离更远就只说"补条目"，
  不误导。
- **`*{N}{...}` 列宽**：本模块不解析列数（编译期已抓 `Extra alignment tab`），不重复。
- **不触碰 `.cls/.sty`**：只审 `.tex` 与 `.bib`，模板类文件的内容属于组织方，不在审计范围。
