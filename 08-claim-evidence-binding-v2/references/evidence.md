# 运行证据（章节识别修复 + A/B 对照 + 回改回路）

本文件是**实际跑通**的可复现证据，不是模板。命令在 `scripts/` 与 `assets/tests/` 下，输入在 `references/evidence-data/` 与 `assets/examples/`。

## 证据 1：B1/B2 章节识别修复

v1 的两个 bug：`align.py` 把已归一化的节名二次送进词表匹配（词表里没有 "background"/"related_work" 这个词），导致 background/related_work/contribution 全判 `other`；`_draft_sections` 不处理标题层级，`### 问题设定` 把父节 `## 相关工作` 吞成 0 句。

修复后同一份示例草稿（四节齐全 + 相关工作下挂两个 `###` 分组）：

```bash
python3 scripts/run_case.py --case assets/examples/case.json \
  --lexicon assets/lexicon.json --schema assets/schema.json \
  --out /tmp/ex --stage finish --draft assets/examples/draft.md
```

| 节 | 修复前 coverage | 修复后 coverage |
|-|-|-|
| background | missing | **written** |
| related_work（含 `###` 分组） | missing | **written** |
| gap | written | written |
| contribution | missing | **written** |

`assets/examples/result.json` 已用修复后代码重生成（coverage 四节 written），不再是"把 bug 印在名片上"的旧版。

## 证据 2：A/B 对照（增益可验证性）

同一份材料（`assets/examples/material/`），裸 Agent 写法 vs 本 Skill 证据先行写法：

```bash
python3 scripts/run_case.py --case assets/examples/case.json \
  --lexicon assets/lexicon.json --schema assets/schema.json \
  --out /tmp/ab-base --stage finish --draft references/evidence-data/ab-baseline-draft.md
python3 scripts/run_case.py --case assets/examples/case.json \
  --lexicon assets/lexicon.json --schema assets/schema.json \
  --out /tmp/ab-skill --stage finish --draft references/evidence-data/ab-skill-draft.md
python3 scripts/revision_log.py --before /tmp/ab-base/result.json \
  --after /tmp/ab-skill/result.json --out /tmp/revision_delta.json
```

| 指标 | 裸 Agent（套话/无依据空白/夸大） | 本 Skill（证据先行） | 差值 |
|-|-|-|-|
| 未锚定句（unanchored+unverified+overclaimed） | 4 | 0 | −4 |
| 夸大断言（overclaimed） | 2 | 0 | −2 |
| 缺口总数 | 20 | 4 | −16 |
| 其中 major | 6 | 0 | −6 |
| 其中 warn | 14 | 4 | −10 |
| 未覆盖关键工作 | 3 | 0 | −3 |
| **status** | partial | complete | — |
| trace_rate | 0.0 | 1.0 | — |

裸 Agent 的成稿是**套话背景 + 无依据空白 + 夸大贡献**的典型翻车；本 Skill 证据先行 + 按缺口回改后，所有论断落地、major 归零。`revision_log.py` 输出的 delta 就是"比基线好多少"的机器口径，不是自述。

## 证据 3：回改回路（返修轮次数字）

`SKILL.md` 第 4 步的回改回路 = scan（取锚点）→ 写（证据先行）→ finish（审计）→ 按 `gaps.md` 回改 → 再 finish → `revision_log.py` 记前后差值。上面的 delta（−4 未锚定、−16 缺口、−6 major）就是一轮回改的质量账。

## 自测

```bash
python3 assets/tests/run_selftest.py   # 27/27
```

新增 2 条章节识别回归：四节齐全 coverage 四节必须 written；`## 相关工作` 下挂 `###` 分组时 related_work 仍须 written。
