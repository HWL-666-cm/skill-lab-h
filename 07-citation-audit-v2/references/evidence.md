# 运行证据（A/B 对照 + status 修复 + 渲染 + 论断召回）

本文件是**实际跑通**的可复现证据，不是模板。所有输入/输出在 `references/evidence-data/`，命令可逐条重跑。文本文件行尾均为 LF，sha256 以 LF 计。

## 证据 1：status 只依据修订稿（v2 核心修复）

旧版 bug：`make_result.py` 用原稿审计的错误数判 `status`，修订稿修干净仍报 `partial`。
v2 对修订稿重跑审计，原稿问题数移入 `issues_found_in_input`：

```bash
python3 scripts/make_result.py --case-id ab-demo \
  --manuscript references/evidence-data/ab-baseline.md \
  --revised     references/evidence-data/ab-skill.md \
  --bib         references/evidence-data/ab-skill-bib.json \
  --audit       /tmp/ab-base-audit.json --out /tmp/ab-result.json
```

| 项 | 值 |
|-|-|
| 原稿硬错误（`issues_found_in_input.errors`） | 3 |
| 修订稿硬错误 | 0 |
| 修订稿警告 | 1（weak_placement，启发式边界） |
| **status** | **review_warnings**（旧版会判 partial） |

## 证据 2：A/B 对照（增益可验证性）

同一份事实底稿 + 同一文献库（含 1 组同 DOI 的预印本/正式版重复），裸 Agent 改写 vs 本 Skill 修订：

```bash
python3 scripts/citation_audit.py --manuscript references/evidence-data/ab-baseline.md \
  --bib references/evidence-data/ab-bib.json --out /tmp/ab-base-audit.json
python3 scripts/citation_audit.py --manuscript references/evidence-data/ab-skill.md \
  --bib references/evidence-data/ab-skill-bib.json --out /tmp/ab-skill-audit.json
```

| 返工维度 | 裸 Agent | 本 Skill |
|-|-|-|
| 悬空引用（`[5]` 指向不存在条目） | 1 硬错误 | 0 |
| 编号断裂（跳号/首现乱序） | 1 硬错误 | 0 |
| 重复条目未归并（同 DOI 预印本 vs 正式版） | 1 硬错误 | 0 |
| DOI 缺 `https://doi.org/` 前缀 | 4 警告 | 0 |
| 未用条目 | 2 警告 | 0 |
| 弱引用位置（启发式） | 1 警告 | 1 警告 |
| **合计返工条目** | **10（3 硬 + 7 警）** | **1（0 硬 + 1 警）** |

去重判据可解释：`wrf2018`（正式版）与 `wrf2018-preprint`（预印本）DOI 相同但题名/作者格式冲突，审计标记 `duplicate_conflict`（不自动合并）；Skill 保留正式版、删除预印本，依据 = 同 DOI + 正式版字段更全。

## 证据 3：格式转换（render.py）

```bash
python3 scripts/render.py --bib references/evidence-data/ab-skill-bib.json \
  --style gbt7714 --out /tmp/ab-refs-gbt.txt
python3 scripts/render.py --bib references/evidence-data/ab-skill-bib.json \
  --style apa --out /tmp/ab-refs-apa.txt
```

GB/T 7714—2015 输出（3 条，0 缺字段）：四人以上"等/et al."、卷(期):页、`[J]` 标识齐全。缺字段时 `completeness` 标记缺项，不臆造。

## 证据 4：论断句规则召回（claim_recall.py，挂得对的规则侧）

```bash
python3 scripts/claim_recall.py --input references/evidence-data/ab-baseline.md \
  --out /tmp/ab-claims.json
```

从基线稿捞出 2 条候选论断句（含数字/强断言），其中 1 条未带引用（"准确率已达 92%"）、1 条已带引用。规则先收窄，模型只对这 ≤20 句候选逐句确认，控制请求预算。

## 证据数据文件（LF sha256）

| 文件 | sha256（前 12 位） |
|-|-|
| ab-src.md | 336c88258ccb |
| ab-bib.json | ab81ddf76a42 |
| ab-baseline.md | 2a93b648ae7d |
| ab-skill.md | 1efab0b6216a |
| ab-skill-bib.json | e707105e9c13 |

## 自测

```bash
python3 scripts/run_selftest.py
```

覆盖 v1 全部 13 条 + v2 新增的修订稿 status 判定、逐条 source_map、GB/T 7714/APA 渲染、论断句规则召回。
