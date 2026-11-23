---
name: academic-hedge-safe-polish
description: 学术文本润色与改写，且保证"没改坏"——逐句给出原文/改文/修改类型/理由，并用脚本审计限定强度、数值单位、引用编号、术语在全篇是否被悄悄改变。当用户要求润色、改写、校对、统一术语、按期刊语域重写摘要或章节，或把中文稿改成英文学术表达时使用。不用于纯知识问答、不用于代写整篇论文、不用于虚构数据或参考文献。
---

# 学术语言润色（限定强度守恒版）

## 1. 这个 Skill 解决什么问题

通用改写工具最常见的失败不是"改得不通顺"，而是**改得太顺，把结论改强了**：

- 原句 `may be associated with` → 改成 `is associated with`，相关性变成因果断言；
- 原句 `in this cohort` → 改成 `in general`，结论适用范围放大；
- 原句 `did not significantly differ` → 改成 `were similar`，阴性结果被说成阳性等价；
- 数字、单位、引用编号在重排句序时被顺手改动或丢失，读者无法回溯。

因此本 Skill 的核心约束是**最小编辑（minimal edit）**：只在能明确指出"改了什么、为什么改"时才动笔；凡是会改变命题强度的位置，必须有审计证据支持，而不是凭语感。

方法落地为三张守恒表，全部可脚本核验：

| 守恒表 | 守住什么 | 校验工具 |
|---|---|---|
| 限定强度表 | 情态动词、限定词、范围词、否定范围的强度不增不减 | `scripts/hedge_audit.py` |
| 术语表 | 同一概念全篇同一写法；缩写首次出现定义唯一 | `scripts/term_audit.py` |
| 硬事实表 | 数字、单位、百分比、引用编号、图表指向逐字对齐 | `scripts/hedge_audit.py`（fact 段） |

## 2. 触发条件

**应当触发**：用户给出成段文本（中文或英文）并要求润色／修改／校对／统一术语／符合某期刊或学位论文语域／中译英；或用户贴出审稿意见要求逐条改稿。

**不应触发**：用户只是问概念、要文献综述、要一段全新的正文、要翻译非学术文本。这些情况直接按普通问答处理，**不要擅自改写用户提供的文本**——未被要求就动笔，是本 Skill 最主要的误触发。

**判定口径**：输入中存在"待改文本"且存在"改的动作"两个要素才触发。只有其一，先问一句再动手。

## 3. 运行时输入

平台在每个案例下把输入放在 `/input/case.json`，题面在同目录 `task.md`。字段名可能随案例变化，按语义读取，不要假设固定键名：

| 语义 | 常见键名 | 缺失时怎么办 |
|---|---|---|
| 待改原文 | `source_text` / `text` / `manuscript` / `input` | 依次尝试；都没有则读 `/input/` 下唯一文本文件 |
| 任务说明 | `instruction` / `task` / `requirement` | 回退到 `task.md` 正文 |
| 目标文体 | `genre` / `style` / `venue` | 从任务说明抽取；抽不到按"期刊论文"默认并在结果中标注假设 |
| 术语表 | `glossary` / `terms` / `terminology` | 由 `term_audit.py` 自动发现，标注"自动生成，需人工确认" |
| 案例标识 | `case_id` / `id` | 用输入文件路径的哈希前 8 位，标注为合成 ID |

**硬规则：材料里没有的事实、数字、引用，一律不得新增。** 需要补充才能成句时，写成 `[需作者确认：…]` 占位，并计入 `uncertainties`。

**环境探测（第一步就做，别假设）**：

| 项 | 探测方式 | 兜底 |
|---|---|---|
| Python 命令 | `python3 --version` 失败就试 `python --version` | 两个都没有：跳过脚本，只用提示词流程，并在 `limitations` 说明"审计未运行" |
| 本 Skill 安装路径 | 依次找 `/skills/weekly-skill`、`./skills/*/`、脚本同级的上一级目录 | 用绝对路径调用脚本，不要依赖 `cd` |
| 输出目录 | `/app/output` 不存在则创建 | 创建失败时退到 `/app/work/output` 并在 `limitations` 写明 |
| 输入编码 | `utf-8` 优先，失败依次试 `utf-8-sig`、`gb18030` | 脚本的 `read_text()` 已内置这条链路 |

**预算账（必须算，否则会中途被截断）**：64 次模型请求、900 秒。分块编辑每块 1 次调用，若文本 6000 字、每块 1200 字，就是 5 次；再加复核与组装，总计控制在 **≤40 次**，留够余量。**超长文本优先"交前 N 块 + 标 partial"，不要试图一次全改。**

## 4. 执行流程

工作目录 `/app/work`，产物写 `/app/output`。预算 64 次模型请求、900 秒、单次回复 16384 token，因此流程设计为**一遍通读 + 分块编辑 + 脚本复检**，不做反复试写。

**第 1 步｜建立基线（不调用模型）**
```bash
python3 scripts/term_audit.py --input /app/work/source.txt --out /app/work/terms_before.json
python3 scripts/hedge_audit.py --original /app/work/source.txt --revised /app/work/source.txt --out /app/work/facts_before.json
```
先跑一遍"自己对自己"，把原文的术语变体、数值、引用编号全部列出来，作为后续比对的基线。这一步是纯本地计算，不消耗模型额度。

**第 2 步｜通读并锁定不可动清单**
通读全文，先写下三份清单，再动笔：
- 不可动的数字与单位（含样本量、p 值、置信区间、剂量、时间）
- 不可动的引用编号与图表指向（`[12]`、`Fig. 3`、`Table 2`、`式(4)`）
- 必须全篇统一的术语（含缩写首次出现位置）

**第 3 步｜分块编辑（模型调用集中在此）**
按段落或小标题切块，每块一次调用，单块不超过 1200 字。**实际使用的提示词在 `prompts/pass1-edit.md`**，把 `{{BLOCK_TEXT}}`、`{{GLOSSARY_SLICE}}`、`{{STYLE_RULES_SLICE}}`、`{{GENRE}}` 四处占位符替换后直接使用，不要另写一套。每块要求模型返回**结构化 JSON**，不是自由文本：

```json
{
  "revised": "改后的完整段落",
  "changes": [
    {"original": "原句或原短语", "revised": "改后", "type": "grammar|term|register|hedge|logic|format",
     "reason": "为什么改，指向具体规则或错误", "risk": "none|hedge|meaning"}
  ],
  "kept": ["刻意未改的可疑之处及理由"],
  "uncertainties": ["需要作者确认的点"]
}
```

**分块而非整篇**的理由：单次回复 16384 token，整篇一次改必然截断；分块还能让每块的修改记录就近绑定原文，避免"改完找不到对应句"。

**第 4 步｜术语回扫（本 Skill 的关键差异点）**
全部块改完后，用**改后全文**重跑术语审计，与基线比对：
```bash
python3 scripts/term_audit.py --input /app/work/revised.txt --glossary /app/work/terms_before.json --out /app/work/terms_after.json
```
只修 `status=drift` 的项，且修法与术语表一致；不要因为"读起来更顺"而临时改术语。

**第 5 步｜限定强度与事实复检**
```bash
python3 scripts/hedge_audit.py --original /app/work/source.txt --revised /app/work/revised.txt --out /app/work/facts_after.json
```
脚本会给出每一项的 `delta` 与 `flags`。处理规则：

| 脚本结论 | 处置 |
|---|---|
| 数字/单位/引用 `missing` 或 `added` | **必须回改**，逐字恢复原样 |
| 限定强度 `strengthened`（净强化） | 回改到原强度；确属原文笔误才保留，并写进 `uncertainties` |
| 限定强度 `weakened` | 同上，尤其"阴性结果"不得被削弱成"无差异"以外的新说法 |
| 新增术语变体 | 回改到术语表写法 |

回改**不要重写整段**——把脚本的 `flags` / `drift` 原样填进 `prompts/pass2-verify.md`，只让它给出"哪处、改回什么、为什么"。理由：第二次整段改写会引入新的偏移，而脚本只认"这一处有没有回改对"。

**第 6 步｜组装结果**
```bash
python3 scripts/make_result.py --case-id <CASE_ID> --revised /app/work/revised.txt \
  --changes /app/work/changes.json --audit /app/work/facts_after.json \
  --terms /app/work/terms_after.json --out /app/output/result.json
```
同时把可编辑稿写成 `/app/output/polished.md`，修改清单写成 `/app/output/changes.csv`（便于第三方逐条核对）。

## 5. 输出契约

`/app/output/result.json` 必须包含下列字段，缺一不可：

```json
{
  "case_id": "案例标识，原样回传",
  "status": "ok | partial | failed",
  "target_deliverable": {
    "kind": "revised_text",
    "path": "/app/output/polished.md",
    "genre_assumption": "期刊论文（若输入未指定）",
    "word_count_delta": 0
  },
  "change_log": [
    {"id": "C1", "paragraph": 1, "original": "...", "revised": "...",
     "type": "hedge", "reason": "...", "risk": "hedge", "audit_ref": "facts_after.json#hedge.may"}
  ],
  "term_table": [
    {"concept": "海雾", "preferred": "sea fog", "variants_found": ["sea-fog", "Sea Fog"],
     "first_occurrence": "Abstract, sentence 2", "status": "unified | drift | auto"}
  ],
  "fact_map": [
    {"value": "1 km", "where": ["Results, para 2"], "source": "原文 Results 段", "changed": false}
  ],
  "uncertainties": ["材料不足或需人工确认的点，逐条说明"],
  "assumptions": ["文体/术语/口径上的默认假设"],
  "limitations": ["本次未覆盖的处理项"],
  "audit": {"hedge": {...}, "terms": {...}, "facts": {...}}
}
```

**状态口径**：`ok` = 全部段落已处理且审计通过；`partial` = 有段落未处理或审计有未解决项，必须在 `limitations` 列出；`failed` = 无法读取输入，只写失败原因，不写任何编造内容。**不得把 partial 写成 ok。**

**字段优先级**：若 `/input/case.json` 自带 `output_contract`，**以它为准**——本节的字段只作补充，不覆盖平台定义。逐个字段产出、字段名照抄、`required: true` 缺一个即算 `partial`。合并规则与自检代码见 `references/output-contract.md`。

## 6. 异常处理

| 情况 | 处置 |
|---|---|
| 输入超长（>15000 字） | 分块处理，先交前 N 块并在 `status=partial` 中说明剩余范围 |
| 编码混乱 / 全角半角混杂 | 先规范化再改；规范动作记入 `change_log`（type=format） |
| 公式与引用混杂 | 公式整体视为不可动块，用占位符 `⟦EQ1⟧` 保护，改完回填 |
| 中英日混排 | 只处理目标语言段，其他语言段原样保留并标注"未处理" |
| 术语表内部冲突 | 不自行裁决，两条写法都保留到 `uncertainties`，请作者定 |
| 目标文体不明 | 按期刊论文处理，并在 `assumptions` 声明；不擅自按"更口语"或"更华丽"改写 |
| 脚本报错 | 记入 `limitations` 并继续，不因工具失败放弃已完成的改稿 |

## 7. 最小调用示例（示意，非正式案例结果）

输入（片段）：
> The treatment **may reduce** the incidence of sea fog by **about 12%** in coastal areas **[3]**, and this effect **was not significant** in inland stations (Fig. 2).

错误改法（基础 Agent 常见）：
> The treatment reduces the incidence of sea fog by 12% in coastal areas [3], and this effect was similar in inland stations (Fig. 2).

三处被改坏：`may reduce`→`reduces`（可能性变断言）、`about 12%`→`12%`（精度抬高）、`not significant`→`similar`（阴性结论被改写）。

本 Skill 输出（示意）：
> The treatment **may reduce** the incidence of sea fog by **approximately 12%** in coastal areas **[3]**; this effect **was not statistically significant** at inland stations (Fig. 2).

对应 `change_log`：

| id | 原文 | 改文 | 类型 | 理由 | risk |
|---|---|---|---|---|---|
| C1 | about 12% | approximately 12% | register | `about` 在期刊正文偏口语，改 `approximately`，精度不变 | none |
| C2 | , and this effect | ; this effect | format | 两个独立分句用分号，避免逗号粘连 | none |
| C3 | not significant | not statistically significant | term | 补全统计口径，避免与"实际无差异"混淆 | meaning（已核实原文含统计检验语境，可保留） |

`may reduce`、`[3]`、`Fig. 2`、`12%` 全部原样保留，脚本审计应显示这三项 `delta=0`。

## 8. 自查（提交或交付前必做）

| # | 动作 | 通过标准 |
|---|---|---|
| 1 | 跑 `python3 scripts/run_selftest.py`（或 `python`） | 4 条用例全 PASS；有 FAIL 说明审计脚本坏了，先修脚本再动文本 |
| 2 | 确认 `result.json` 有 `case_id`，且 `output_contract` 的必需字段齐全 | 缺一即改 `status` 为 `partial` |
| 3 | 抽查 5 处 `change_log` | 每处都能在原文里搜到 `original`，改文里搜到 `revised` |
| 4 | 看 `audit.flags` 是否为空 | 非空则要么已回改，要么在 `uncertainties` 写明为何保留 |
| 5 | 同一段重复跑一次 | 两次结论一致；不一致说明规则不稳定，需收紧词表约束 |

**为什么把自测放第一条**：脚本是这套方法的地基。地基坏了，"没改坏"的结论就是假的——先证明工具能抓错，再证明文本没错。

## 9. 局限

- 只在**句级/段级**保真；跨章节的论证结构调整不在本 Skill 范围。
- 限定强度审计基于词表，**同义但不在词表内的表达可能漏检**，需人工抽查。
- 不判断学科事实是否正确（例如 12% 这个数是否真实），只保证数字未被改动。
- 不生成参考文献条目、不校验文献真实性，那属于引用管理题的范围。

## 10. 维护

| 文件 | 作用 | 改动时要同步什么 |
|---|---|---|
| `prompts/pass1-edit.md` | 分块编辑的实际提示词 | 改约束就同步 `SKILL.md` 第 4 节流程 |
| `prompts/pass2-verify.md` | 按脚本报告回改 | 改报告格式就同步 `scripts/hedge_audit.py` 的输出字段 |
| `references/hedge-lexicon.md` | 五族词表 | 改权重必须同步 `scripts/hedge_audit.py` 的 `LEXICON`，两处不一致会误报 |
| `references/style-conventions.md` | 文体规则（规则—反例—改法三段式） | 只加"规则"不给反例，模型无法稳定执行 |
| `references/output-contract.md` | 与平台 `output_contract` 的字段映射 | 平台改字段名时先改这里 |
| `references/eval-rubric.md` | 对照实验设计与自评表 | 自评表权重变了要重跑一遍对照 |
| `tests/cases.json` | 4 条已知错误的合成用例 | 加词表就加对应用例，否则新规则未被验证 |
| `scripts/run_selftest.py` | 一条命令验证脚本能抓错 | 新增脚本要接进这里 |

- 版本：v1.1（2026-11-23）。v1.0 → v1.1 变动：补 `prompts/` 两份实际提示词、字段合并规则、对照实验设计与自评表、自测用例与 `run_selftest.py`、预算账与环境探测；修正术语审计对短词二元组的漏抓。
