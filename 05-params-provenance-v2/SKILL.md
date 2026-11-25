---
name: 05-params-provenance-v2
description: "从配置文件、日志、代码里抽取参数与实验设置，先建参数台账（每行 = 参数名 + 作用域 + 值 + 来源分级 + 文件:行定位符 + 逐字原文），再证据先行起草方法与实验章节，双向对齐（正文数值 → 台账；台账 → 正文），抓出编造数值、数值不符、材料参数漏写、复现清单缺失，按缺口回改并记录返修轮次数字，用四态门禁交付可核查的 methods.md、参数台账 CSV、追问清单与校验报告。会区分「材料里没有这个数」「有这个数但没点名参数」「点名的参数值不符」「同一参数在两个文件里不一致」，并明确拒绝在没有来源时补一个像样的数。用户说\"帮我写方法章节\"\"检查方法章节里的数值有没有出处\"\"每个超参都要能指到配置文件的哪一行\"\"把训练参数整理成带出处的表\"\"这段实验设置漏了什么参数\"\"审一下我写的复现章节\"时使用。"
version: 1.1.0
agent_created: true
---

# 参数溯源：写得全、写得准

一份方法章节最容易被读者当场证伪的地方不是结论，而是数字：学习率、批大小、轮数、数据划分、评测口径。作者写的时候心里有数，读者复现的时候只有一个字符串。本 Skill 把这件事变成一次可核查的机械过程：

**材料里每个能设的值 → 一行台账；正文里每个数字 → 一行台账。两个方向都查，缺哪边报哪边。**

不追求把文章写漂亮。追求**每个数字都能被第三方打开文件、翻到那一行、看到那个值**。查不到就如实说查不到，不补一个"看起来合理"的数。

## 何时用

- "帮我检查方法章节里的数值有没有出处""审一下实验设置这段"
- "每个超参都要能指到配置文件的哪一行""把训练参数整理成带来源的表"
- "论文写的学习率和代码里的不一致，哪个是对的"
- "这段复现步骤漏了什么参数""为什么别人照着我写的复现不出来"
- 投稿前自查、复现包（reproducibility package）整理、代码与论文对齐

**不适用**：只需要润色语言（用润色类 Skill）；需要核对参考文献是否真实存在（用引用核查类 Skill）；需要读懂 PDF 版式或表格结构（用 PDF 结构类 Skill）；需要判断实验结论是否成立（本 Skill 只查数值有无出处，不验实验是否真跑过）。

## 输入

平台在运行时把材料放在 `/input`，把正文草稿放在 `case.json` 指定的字段或 `/input` 下的 Markdown 里。材料可以是：

| 材料 | 例 | 台账里怎么用 |
|---|---|---|
| 配置文件 | `config.yaml`、`default.yaml`、`*.toml` | 最强来源：键路径直接成为定位符 `key:train.learning_rate` |
| 训练日志 | `run.log`、`*.out` | 强来源：按 `epoch/step` 行取作用域，与配置交叉验证 |
| 代码默认值 | `train.py` 的 argparse `default=`、`lr=1e-4` | 强来源：模块级归全局域，函数内归 `<文件>.<函数>` 域 |
| 论文/README | `.md`、`.tex`、`.pdf`、`.docx` | 弱来源：只证明"文章这么写"，不证明"运行用的是这个" |
| 结果表 | README 或 `.tex` 里的表格 | 弱来源：按列名绑定，每行一个作用域（XL/2 与 B/4 不是矛盾） |
| 作者口头确认 | `notes.md` 里写明 | 最强，但必须记录是谁在什么时候确认的 |

**读不到就报读不到。** PDF 没有可用解码器、编码不可靠、文件损坏，都写进 `uncertainty` 与缺口清单，绝不从文件名猜内容。

## 输出

| 文件 | 内容 | 给谁看 |
|---|---|---|
| `methods.md` | 原稿逐字保留 + 末尾「数值出处对照」表（每值 → 参数 → 文件:行） | 作者自查、审稿人抽查 |
| `parameter_ledger.csv` | 一行一个值：参数名、作用域、值、状态、来源分级、路径、行号、原文 | 复现包附录 |
| `gaps.md` | 缺口与追问，分阻断/重要/次要，每条含「缺了会怎样」+「要问作者什么」 | 作者、合作者 |
| `validation.json` | 24 项门禁的四态结果（pass/warn/fail/not_checked） | 交付前自检 |
| `result.json` | 上述全部 + `output_contract` 声明的每个字段 + `case_id` | 机器读取 |

`output_contract` 里出现的字段名一律按声明输出；本 Skill 没有的字段置 `null` 并在 `contract_report.missing` 里写明，绝不编造一个看起来对的值。

## 工作流

三步，顺序不能换。每一步都在为下一步减少一种错误。

### 第一步：建台账（把"值"变成"值 + 位置 + 分级"）

正文里的 `1e-4` 只是一个字符串。台账行才是可核查的事实：它同时记住**值、位置、来源等级**，以及**同一参数名在别处还说过什么**。

- **定位符必须是能被打开的坐标**：`L118`（第 118 行）、`key:train.learning_rate`（YAML 键路径）、`row3`（表格第 3 行）。**不用页码**——页码随排版变化，行号和键路径不会。
- **同一参数名不同作用域不合并**：`train.batch_size: 32` 与 `infer.batch_size: 64` 各自成立。合并会造出一个不存在的矛盾。
- **散文里的多实例不判冲突**：一句话写"XL/2 用 8 卡，B/4 用 4 卡"，是一个参数两个实例，记为 `prose_multi_value` 并进追问清单，而不是判它自相矛盾。
- **只有硬来源能定冲突**：配置、日志、代码是运行的本身；论文是对运行的描述。两个硬来源不一致 = 运行自相矛盾（阻断）；硬来源与散文不一致 = 可能是散文在描述另一次实验（重要，需追问）。

### 第二步：双向对齐（同一套机制回答两个问题）

| 方向 | 问的问题 | 答不上来意味着 |
|---|---|---|
| 前向 | 正文这个数在台账里吗 | 要么抄错，要么凭空写的 |
| 后向 | 台账这行在正文里吗 | 读者照文中步骤复现时会缺这个设置 |

前向不能只做"值是否存在于材料"，那样会把注释里的 `betas=(0.9, 0.999)` 判成凭空数值。所以每个数字落到七类之一：

| 判定 | 含义 | 严重度 |
|---|---|---|
| `traced` | 值对上台账，且这段点名了该参数 | — |
| `mismatch` | **点名了参数，但值不是台账里的那个** | 重要 |
| `invented` | 材料里根本没有这个值 | 阻断 |
| `in_material` | 材料里有这个数，但没有一行把它记为某参数的值 | 重要 |
| `value_only` | 值对得上某行，可那段没点名该参数 | 次要 |
| `ambiguous` | 一个值能对上多个参数，那段没说清是哪个 | 次要 |
| `ignored` | 按显式规则不计（年份、图表号、指标名后缀、模型名 `XL/2`、相对提升、**边界条件**） | 不计 |

其中 `mismatch` 是最值钱的一条：`learning rate of 0.001` 对上台账的 `lr0: 0.01`，直接给出两处位置。它比 `ambiguous` 有用得多——`ambiguous` 只说"不确定"，`mismatch` 说"这句话点的是这个名字，但记的是另一个数"。

**边界条件不算参数值**：`fails when the batch is smaller than 8` 里的 8 是方法的适用边界，不是某个设置的值。它既不该被要求溯源，也不能被当成凭空数值——所以单列 `ignored` 并写明理由，让它可见但不计错。

### 第三步：门禁与缺口（没检查 ≠ 通过）

门禁四态而不是三态，是因为三态会逼出一个安静的谎：跑不了的检查会被算成 pass，总体状态比证据好看。所以：

- `not_checked` 单独计数，**永远不计为 pass**；只要有 `not_checked`，总体状态就是 `incomplete`。
- 状态词只有四种：`complete` / `partial` / `blocked` / `incomplete`。`partial` 必须列出缺什么，否则门禁直接判 fail。
- 台账为空时，5 项行级检查报 `not_checked`，而不是"没有问题的 pass"。

`gaps.md` 里每条缺口都带两句：**缺了会怎样**（具体到读者复现时会踩哪一步）和**要问作者什么**（一天内能回答的一句话）。不写"受限于数据质量"这类套话——`boilerplate_absent` 会把它挑出来。

## 运行

```bash
# 1) 先扫材料，看读到什么、漏了什么（不写结论）
python scripts/run_case.py --case /input --lexicon assets/lexicon.json \
    --schema assets/schema.json --out /app/work/round1 --stage scan

# 2) 证据先行起草（v2）：读 prompts/writing-guide.md 与 /app/work/round1/candidates.json，
#    从台账写七节（步骤/设置/参数/数据/对照/复现/限制），每个数字带来源，保存 draft.md

# 3) 对齐并出门禁
python scripts/run_case.py --case /input --lexicon assets/lexicon.json \
    --schema assets/schema.json --out /app/work/round1 --stage finish \
    --draft /app/work/draft.md

# 4) 按缺口回改（v2 核心回路）：读 /app/work/round1/gaps.md，先改 blocking（编造数值/硬冲突），
#    再 major（数值不符/材料参数漏写），最后 warn；改完 draft2 再 finish：
python scripts/run_case.py --case /input --lexicon assets/lexicon.json \
    --schema assets/schema.json --out /app/work/round2 --stage finish \
    --draft /app/work/draft2.md

# 5) 记返修轮次数字（增益证据）：
python scripts/revision_log.py --before /app/work/round1/result.json \
    --after /app/work/round2/result.json --out /app/output/revision_delta.json
#   输出 invented / mismatch / not_written / blocking 的前后差值；
#   最终 methods.md 与 revision_delta.json 一并放进 /app/output/。

# 改过稿之后只重跑门禁
python scripts/run_case.py --case /input --lexicon assets/lexicon.json \
    --schema assets/schema.json --out /app/output --stage recheck

# 自测（不需要任何材料，76 项断言）
python assets/tests/run_selftest.py
```

只依赖 Python 标准库；有 `pdftotext`、`pymupdf`、`pypdf` 时自动优先用它们读 PDF，没有会退到内置解码并在 `uncertainty` 里标明编码可能不可靠。

## 交付前自检

1. `python assets/tests/run_selftest.py` 全绿（任何一项失败都不算完成）。
2. 同一输入连跑两次，`result.json`、`parameter_ledger.csv`、`gaps.md`、`validation.json` 的 sha256 必须完全一致（不写时间戳、不用随机 id、不依赖字典顺序）。
3. 五类异常各跑一次，都必须给出诚实的空结果或降级说明，而不是崩或被当成通过：
   空目录 / 只有不可读 PDF / 无正文草稿 / `output_contract` 含未知字段 / 值为空或分类值。
4. 台账里每一行的定位符都能在当前材料里解析到（`locator_resolves`），引文逐字（`quote_verbatim`）。
5. 阻断级缺口为 0 才可以在正文里把 `status` 写成 `complete`。

## 已知边界（不能做的四件事）

1. **不验证实验是否真跑过**：它只回答"这个数有没有出处"，不回答"这个实验是否真的发生过"。材料本身若作假，台账照样成立。
2. **不判断哪个值对**：冲突时两值并列给出位置，由作者决定。工具不做平均、不取最新、不猜。
3. **不改写已有正文**：`finish` 阶段 `methods.md` 保留原稿逐字，只追加出处对照，作者复核时能逐句对照。**起草阶段**（Agent 依据 `prompts/writing-guide.md` 从台账写 methods）则按证据先行生成，不是改原文。
4. **不覆盖散文里的参数名缺失**：一句话没点名参数时，工具只能报 `ambiguous`，不会替作者认定它是哪个参数。这种模糊是材料本身的模糊，工具不该替它下结论。

## 一条必须守住的输入规则：草稿不是材料

待检的草稿如果放在材料目录里，必须先把它排除在材料读取之外；本 Skill 自己的
输出（`result.json`、`methods.md`、`ledger.json` 等）同样排除。否则稿子里的
`0.001` 会被当成"材料里有这个数"给它自己做一次出处，报告就会和自己的草稿
互相印证，而不是核对作者真正提供的证据——这是循环溯源，比漏报更危险。
排除按**精确相对路径**：一个真叫 `methods.md` 的原始材料不会被按文件名误删。

## 目录

```
05-params-provenance-v2/
├── SKILL.md
├── prompts/
│   └── writing-guide.md 证据先行写作：七节写法 + 每个数字带来源
├── scripts/
│   ├── run_case.py      入口：scan / auto / finish / recheck
│   ├── materials.py     材料探测与读取（yaml/csv/代码/日志/表格/PDF/docx）
│   ├── numbers.py       数值规范化（1e-4 = 1×10⁻⁴ = 0.0001；单位族换算）
│   ├── params.py        参数候选抽取（按材料种类分路）
│   ├── ledger.py        台账构建与冲突判定
│   ├── align.py         双向对齐与七类判定
│   ├── gaps.py          缺口与追问清单
│   ├── validate.py      四态门禁（24 项）
│   ├── contract.py      output_contract 四形状解析
│   ├── revision_log.py  回改前后质量账（返修轮次数字）
│   └── emit.py          产物组装与写出（字节确定）
├── assets/
│   ├── lexicon.json     45 个参数名 + 别名 + 家族 + 七要素归属
│   ├── schema.json      来源分级、台账状态、冲突规则、定位符约定、门禁清单
│   ├── examples/        标注 example:true 的最小样例（material/ 与 deliverables/ 分离）
│   └── tests/run_selftest.py
├── references/
│   ├── elements.md      七要素判据
│   ├── source-grades.md 来源分级与冲突规则
│   ├── alignment-rules.md 七类判定与忽略规则
│   ├── failure-modes.md 九类失败模式与本 Skill 的覆盖边界
│   ├── evidence.md      A/B 对照 + 回改回路（可复算，不是自述）
│   ├── evidence-data/   A/B 固定材料与两份草稿
│   └── output-contract.md 输出字段与状态机
├── requirements.txt
└── GITHUB_URL.txt
```

### assets/examples/ 是什么

一份标注 `"example": true` 的**形状示例**：用最小材料（`material/` 下一份 `config.yaml` +
一段散文 README）演示输入输出长什么样，`deliverables/` 下放四段式草稿和示意 `result.json`。
它不是平台固定案例的答案，`result.json` 同样带 `example` 标记。示例稿件照
`references/elements.md` 的七要素写，是门禁的正面样本；只有"能 pass"和"能 fail"
两侧都有实例，门禁才算被测试过。

示例的产物只保留 `result.json` 一份；`methods.md`、`parameter_ledger.csv` 等
在运行时生成，不随包分发。`case.json` 用 `material_dirs: ["material"]` 把材料
限定在 `material/` 子目录，`deliverables/` 里的草稿与示例产物**不会**被读进台账——
这是对"草稿不是材料"这一输入规则的落实，避免示例在重跑时自我印证。
