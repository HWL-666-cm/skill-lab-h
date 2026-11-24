---
name: pdf-structure-audit
description: 把科研 PDF 解析成"能继续处理、也能回查"的结构化文档：正文按正确阅读顺序（双栏/三栏/跨栏/跨页不串栏）、章节树、表格单元格矩阵、公式与编号、图表题注、参考文献、页眉页脚脚注分离，并给出每一条结果的页码与 bbox 依据，最后用 bbox 回抽原文做锚点自检。当用户要求读取/解析/提取科研论文 PDF、需要处理双栏串栏、表格错列、公式上下标失真、扫描版无文字层，或需要"每段能指回原文页码"的解析结果时使用。适用于英文与中文期刊论文、arXiv 预印本、报告类 PDF。
---

# 科研 PDF 结构解析（pdf-structure-audit）

## 这个 Skill 解决什么

用户给一份 PDF，要的通常不是"一段看起来像全文的字符串"，而是下面四件事同时成立：

| 要求 | 具体含义 | 本 Skill 的交付物 |
|---|---|---|
| 提得全 | 正文、题注、脚注、参考文献逐字提取，页眉页脚不混进正文 | `document.md` / `body_paragraphs` / `references` / `coverage` 逐项打勾 |
| 排得对 | 双栏/多栏/跨栏/跨页按原版面顺序，不串栏、不把相邻段拼成一句 | `sections` + 段落序列 + `reading_order_metrics` 的回跳计数 |
| 拆得清 | 章节层级、表格行列与单元格归属、公式上下标与编号 | `sections` 树 / `tables[].matrix`+`cells` / `formulas[]` |
| 核得回 | 每段文字、每张表能指回页码与区块，读不出的如实标注 | 每个单元带 `page`+`bbox`，`anchors.json` 的通过率与失败清单 |

一句话：**不做"猜"，只做"有坐标证据的判定"**。判不出来就写进 `uncertainty`，不补、不编。

## 什么时候该用

- 用户让你读论文 PDF 并回答/提取/整理（尤其双栏、含表格、含公式、含扫描页）。
- 用户抱怨"复制出来是乱的""两栏串在一起""表格变成一坨""公式乱码"。
- 用户需要把论文拆成可检索的结构（章节 → 段落 → 表格 → 公式），或需要"每句话来自第几页"。
- 输入是扫描件或图片型 PDF，需要判断"能不能读、读到什么程度"。

不适合：纯图片/插画解析、手写稿识别、需要理解图表科学含义的任务（本 Skill 只做结构元素识别）。

## 怎么调用

最小一步（推荐，什么参数都不用想）：

```bash
python scripts/run_case.py --input /input --output /app/output
```

它会自己找 `/input/case.json` 里指向的 PDF（键名不敏感：`files`/`materials`/`pdf`/`attachments`…都能认，
找不到就递归扫 `/input` 下第一个 PDF），跑完六步，把 `result.json` 按 `output_contract` 字段名写好。

指定文件时：

```bash
python scripts/run_case.py --pdf paper.pdf --case case.json --output out/
```

跑自检（不写文件、只看结果对不对）：

```bash
python scripts/run_selftest.py            # 合成件 7 个 + 单元断言 5 条，逐条 PASS/FAIL
python scripts/run_selftest.py --keep ./tmp_selftest   # 保留生成的 PDF 与产物，便于人工核对
```

## 输入 / 输出

**输入**：一个 PDF 文件（可选 `case.json`，提供 `case_id` 与 `output_contract`）。
PDF 必须是真文件——**不读预抽取文本层之外的任何"提示"**，也不依据文件名/领域标签补造内容。

**输出**（全部落在 `--output` 目录）：

| 文件 | 内容 | 给谁看 |
|---|---|---|
| `result.json` | 平台契约件：`case_id`、`status`、`output_contract`（按字段名填）、`sources`、`uncertainty`、`changes`、`stats` | 平台/评审 |
| `document.json` | 全量机读结构：`pages`（含每页版式与全部段落）、`sections`、`tables`（含 `cells` 级 bbox）、`formulas`、`figures`、`references`、`front_matter`、`triage`、`anchors`、`issues` | 下游程序 |
| `document.md` | 人读版：标题/作者/摘要 → 结构目录 → 正文（带 `[p.N]` 页码、`¶` 续段标记）→ 表格 → 公式 → 参考文献 → 页眉页脚 → 未确定项 | 人 |
| `tables/t*.md` | 每张表一份 Markdown（表头行、合并单元格说明、未校验原因） | 人/程序 |
| `formulas.md` + `formulas/*.png` | 公式的原始串、还原上下标后的串、所在页码，附区域截图供人工核对 | 人 |
| `anchors.json` | 逐单元锚点核验结果（`coverage`、阈值、是否通过、失败原因） | 评审 |
| `audit.json` | 自检汇总：覆盖清单、锚点统计、问题列表、分诊结果 | 评审 |
| `run_meta.json` | 页数、耗时、版式分布、锚点通过率、覆盖缺失项 | 运行记录 |

字段级说明见 `references/field-dictionary.md`。

## 六步流水线（脚本对应关系）

| 步 | 做什么 | 脚本 |
|---|---|---|
| 1 分诊 | 逐页判断文字层可信否：字数、乱码占比、字体 ToUnicode、是否有图、是否转曲 → `route: text/ocr` | `scripts/pdfcore.py: triage_document` |
| 2 版面 | 用窄正文行的左边缘聚类 + 交叉率判栏（1/2/3 栏），通栏行作**分区边界**再在带内按栏排序 | `scripts/layout.py` |
| 3 结构 | 字号/加粗/编号正则 → 章节树；跨页同位重复 → 页眉页脚；题注编号+分隔符 → 题注；参考文献区隔离 | `scripts/structure.py` |
| 4 表格 | 题注定区域 → 横线收紧边界 → 词坐标投影切列重构网格 → 一致性校验 → 跨页续表合并 | `scripts/tables.py` |
| 5 公式 | 数学字体/字形 + 右缘编号配对 → 上下标按字号与基线还原为 `^{}`/`_{}` → 区域截图 | `scripts/formulas.py` |
| 6 锚点 | 按 bbox 回原 PDF 取字，逐单元比对覆盖率，输出通过率与失败清单（**不静默修补**） | `scripts/anchors.py` |

编排与产物落盘：`scripts/build.py`；契约装配：`scripts/make_result.py`；平台入口：`scripts/run_case.py`。

## 状态怎么给（不许粉饰）

| status | 什么时候 |
|---|---|
| `ok` | 锚点通过率 ≥ 0.90、没有整页不可读、表格全部结构化 |
| `partial` | 有页走了 OCR，或有表格只标了区域没结构化，或锚点 0.60–0.90 |
| `needs_review` | 锚点 < 0.60（定位不可靠），必须人工核对 |
| `blocked` | PDF 打不开（有密码且空密码失败）、输入里没有 PDF、缺依赖 |

`partial` / `needs_review` 会额外写 `handover`（要人看哪里、建议怎么处理）。
不确定项一律进 `uncertainty`，逐条带页码或字段名。

## 依赖

- Python 3.10+，**PyMuPDF ≥ 1.23**（唯一硬依赖，`pip install -r requirements.txt`，实测 1.28.2）。不依赖 pdfplumber / 任何联网服务。版本下限的理由写在 `requirements.txt` 注释里。
- 可选：`Pillow`（只在导出公式区域 PNG 时用到，缺失则跳过截图并在 `uncertainty` 记一条）。
- 版式规则、判据与阈值为什么这么定：`references/layout-rules.md`。
- 已知边界与诚实降级口径：`references/failure-modes.md`。
- 真实论文上的实测指标（只登记题录，不含原文）：`references/benchmark.md`。
- Agent 侧操作流程（怎么调、怎么读结果、怎么写结论）：`prompts/extraction-workflow.md`。
- 最小调用示例：`examples/`。

## 扫描页与平台工具怎么协同

本 Skill 不内置 OCR 引擎，但也不会把扫描页当"读过了"。分诊判定某页无可用文字层时：

1. 该页渲成 `pages/pNN.png`（150 dpi）落在输出目录，**产物可核验，不是一句口头说明**；
2. 正文里不产出这一页的内容（几何推断在无字页上等于编造），`status` 降为 `partial`；
3. `uncertainty` 写明图片路径与"未回填前不要当成已读"。

若运行环境带平台 OCR 工具（本题 `resources` 声明了 `ocr-tool`），由 Agent 对 `pages/*.png` 识别，把结果按本 Skill 的段落 id 回填后再出 `document.md`。接口名与参数以平台当次注入为准，**脚本不硬编码调用**——猜接口名会在换环境时直接崩。同理，若 `scientific-python` 里没有 PyMuPDF，用平台的 `pdf-text-tool` 先取行级文本，本 Skill 的版面/结构/表格/锚点规则仍适用（输入只需行级 bbox 与字体信息）。

## 自检方法（交结果前 30 秒能做完）

1. `run_meta.json` 的 `anchor_pass_rate` ≥ 0.95？低于 0.90 就去 `anchors.json.failures` 看是哪些单元、为什么。
2. `coverage` 里有没有 `present=false` 的项？有就必须在 `uncertainty` 里解释（原文确实没有 ≠ 没识别出来）。
3. `tables[].status` 是否全为 `structured`？`detected_unstructured` 的表不能当数据用。
4. `document.md` 随机抽 3 段，对着 PDF 同页扫一眼：有没有串栏、有没有把页眉读进正文。
5. `status` 与上面四项是否一致？不一致就改 `status`，别改证据。
