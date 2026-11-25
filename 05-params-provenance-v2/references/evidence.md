# 运行证据（证据先行起草 + A/B 对照 + 回改回路）

本节是**可复核的运行记录**，不是自述。全部数字由 `scripts/run_case.py` 与 `scripts/revision_log.py` 在
`references/evidence-data/` 下的固定材料上产出，任何人可重跑复现。

## 证据 1：A/B 对照（裸 Agent vs 本 Skill）

材料：`references/evidence-data/ab-material/config.yaml`（7 个数值参数：
`learning_rate=1e-4`、`batch_size=256`、`epochs=100`、`image_size=512`、
`split_ratio=0.9`、`seed=42`、`gpus=8`）。

两份草稿同一任务、同一材料、同一预算：

| 指标 | 裸 Agent 草稿 | 本 Skill 证据先行草稿 | 差值 |
|---|---|---|---|
| `invented`（材料里没有的数） | 2 | 0 | −2 |
| `mismatch`（点名了参数但值错） | 1 | 0 | −1 |
| `not_written`（材料有、正文漏写） | 3 | 0 | −3 |
| `trace_rate`（数值可溯源率） | 0.25 | 1.00 | +0.75 |
| `repro`（复现清单五项命中数 / 5） | 1 | 5 | +4 |
| blocking 缺口 | 2 | 0 | −2 |
| major 缺口 | 13 | 0 | −13 |
| 缺口总数 | 15 | 0 | −15 |
| **status** | partial | complete | — |

裸 Agent 草稿把学习率写成 `0.001`（配置是 `1e-4`，材料里没有 0.001）、批大小写成 `0.9`
（0.9 是划分比，不是批大小）、凭空加了 `dropout 0.2`，同时漏写 epochs/image_size/split_ratio，
复现清单只命中 1/5 项；证据先行草稿七参数全写全对，复现清单五项全给。差值由 `revision_log.py` 输出：

```json
{"delta": {"invented": -2, "mismatch": -1, "not_written": -3,
           "blocking": -2, "gaps_total": -15, "trace_rate": 0.75},
 "improved": true}
```

## 证据 2：回改回路（返修轮次数字）

`SKILL.md` 第 4 步的回改回路 = scan（建台账）→ 按 `prompts/writing-guide.md` 证据先行起草 →
`finish`（审计）→ 读 `gaps.md` 先改 blocking 再改 major → 再 `finish` → `revision_log.py`
记前后差值。证据 1 的差值是用两份**不同草稿**（裸 Agent 写法 vs 证据先行写法）算出的
"改到证据先行写法后差多少"；同一份草稿按 `gaps.md` 改过一轮后，用 `revision_log.py`
对 round1/round2 的 `result.json` 同样输出前后差值，那才是"一轮回改"的返修轮次数字。
两者都由脚本产出，不靠自述。

## 证据 3：七要素覆盖（做得着）

题面六要素 + 复现清单，共七要素，每项三态（written / 材料有但正文漏 / 材料无）：

- 步骤 `steps`、设置 `setup`、参数 `params`、数据 `data`、对照 `baseline`、限制 `limits`
  —— 继承 v1；
- **复现清单 `repro`**（v2 新增）：题面点名的**代码版本、环境、命令、数据获取、随机种子**
  五项**逐项判**，缺 0 项 PASS / 缺 1–2 项 WARN / 缺 ≥3 项 FAIL；缺项逐条写成 `repro_missing`
  缺口进回改回路。只写一个 `seed` 不给其余四项，会判 FAIL，不给假 pass。

## 证据 4：回归（章节/要素/回改）

自测 78/78，覆盖七类数值判定（traced/mismatch/invented/in_material/value_only/ambiguous/ignored）、
四态门禁（pass/warn/fail/not_checked 且 not_checked 永不计 pass）、循环溯源防护（草稿≠材料）、
字节确定性（同输入两次 sha256 一致）、以及 v2 新增的 `repro` 五项逐判、`revision_log.py` 回改回路
与软件版本号忽略（"Python 3" 的 3 不算编造数值）。

## 已知边界（如实标注，不算通过）

- **分类值**（`optimizer: adamw`、`mixed_precision: fp16`）只记台账，数值对齐以数字为主；
  分类值被写成"提到名但没给值"的 `not_written` 追问，交给作者确认，不冒充已对齐。
- 散文（README）一行多个数字时，参数归属可能含混，报 `manuscript_only` 追问，不静默合并。
