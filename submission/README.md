# 玻尔产品周赛·地大分站赛第一期 —— 提交包（第 06 / 03 / 07 / 02 题）

本题为 Skill 创作任务，**只提交 Skill 及其必要资源**，不提交答案、白板或正式测试结果。
本文件夹汇总四题的提交材料，每题的 Skill 目录均远低于平台资源上限
（50 个 UTF-8 文本文件 / 单文件 500 KB / 总计 2 MB）。

---

## 第 06 题：学术语言润色

### 目录结构与用途

| 路径 | 作用 | 对应提交参数 |
|---|---|---|
| `06-academic-polishing/` | Skill 本体 15 个文件：入口 `SKILL.md`，以及提示词、规则词表、审计脚本、示例、自测用例 | `--skill` |
| `06-academic-polishing/scripts/` | 4 个实际依赖脚本：限定强度审计、术语审计、契约对齐、自测 | — |
| `06-academic-polishing/prompts/`、`references/` | pass1 编辑 / pass2 复核提示词、输出契约、评分表、词表、语域规则 | — |
| `06-academic-polishing/examples/`、`tests/` | 一组标注为示例的输入输出、6 条合成回归用例 | — |
| `06-academic-polishing/GITHUB_URL.txt` | 公开仓库对应目录链接 | — |
| `06-outputs/` | 只放说明，**没有任何答案文件** | `--outputs` |

题面 ID：`product-arena-02-7051d92d`（写作02｜学术语言润色）。

```bash
playground submit \
  --challenge-id product-arena-02-7051d92d \
  --skill    "D:/桌面/bohrium-cugb-p1/submission/06-academic-polishing" \
  --outputs  "D:/桌面/bohrium-cugb-p1/submission/06-outputs" \
  --trace    "D:/桌面/bohrium-cugb-p1/_trace/06_trace_extended.jsonl" \
  --dry-run
```

> 第 06 题已于 2026-11-24 07:11 UTC 正式提交，attempt 103624，状态 submitted / scoring_state queued。

---

## 第 03 题：文献总结与结构化笔记

### 目录结构与用途

| 路径 | 作用 | 对应提交参数 |
|---|---|---|
| `03-structured-notes/` | Skill 本体 12 个文件（含 `GITHUB_URL.txt`）：入口 `SKILL.md`、提示词、字段字典、锚点规则、4 个脚本、示例、5 条自测用例 | `--skill` |
| `03-structured-notes/SKILL.md` | 平台入口；说明四问（对得上/留得住/找得回/用得上）如何落地 | — |
| `03-structured-notes/scripts/pdf_extract.py` | PDF→带物理页码文本 + 论文本身章节骨架 + 乱码/图片页标记 | — |
| `03-structured-notes/scripts/anchor_audit.py` | 核心创新：逐条核验 claim 的页码/quote/数值是否真指向原文 | — |
| `03-structured-notes/scripts/make_result.py` | 组装 `result.json`，对齐平台 `output_contract` | — |
| `03-structured-notes/scripts/run_selftest.py` | 5 条合成用例，验证核验脚本能抓错且不误报 | — |
| `03-outputs/` | 只放说明，**没有任何答案文件**；说明运行时产物位置 | `--outputs` |
| `03-outputs/GITHUB_URL.txt` | 公开仓库对应目录链接 | — |

题面 ID：`product-arena-06-6d8cf72b`（阅读10｜文献总结与结构化笔记；平台占位名与实际题号不一致，以 ID 为准）。

```bash
playground submit \
  --challenge-id product-arena-06-6d8cf72b \
  --skill    "D:/桌面/bohrium-cugb-p1/submission/03-structured-notes" \
  --outputs  "D:/桌面/bohrium-cugb-p1/submission/03-outputs" \
  --trace    "<本题真实 Agent 会话日志 jsonl 的绝对路径>" \
  --dry-run
```

> 第 03 题尚未提交。`--trace` 必须取自本题相关对话，不能伪造或复用 06 的 trace。

---

## 第 01 题：文献文档解析

### 目录结构与用途

| 路径 | 作用 | 对应提交参数 |
|---|---|---|
| `01-pdf-structure-audit/` | Skill 本体 29 文件（含 `GITHUB_URL.txt`）：入口 `SKILL.md`、11 个脚本、`requirements.txt`、工作流提示词、4 份参考（字段字典/版式判据/异常分支/实测基准）、示例、7 条合成自测 | `--skill` |
| `01-pdf-structure-audit/SKILL.md` | 平台入口；把题面"提得全/排得对/拆得清/核得回"翻成四类可验收交付物 | — |
| `01-pdf-structure-audit/scripts/pdfcore.py` | 底座：文本归一化（NBSP/连字/软连字符）、乱码占比、ToUnicode 检测、页级 line 模型（含跨栏合行切段）、逐页分诊 | — |
| `01-pdf-structure-audit/scripts/layout.py` | 分栏（窄行聚类 + 交叉率 + 邻栏中位栏缝）与阅读顺序（通栏行作分区边界） | — |
| `01-pdf-structure-audit/scripts/structure.py` | 章节树、页眉页脚隔离、题注判据、前言区、参考文献区、续段判定 | — |
| `01-pdf-structure-audit/scripts/tables.py` | 题注定位 → 横线收紧边界 → 词坐标重建网格 → 一致性校验 → 跨页续表合并 | — |
| `01-pdf-structure-audit/scripts/formulas.py` | 数学字体/字形 + 右缘编号配对 → 上下标还原 → 区域截图 | — |
| `01-pdf-structure-audit/scripts/anchors.py` | 核心：bbox 回抽原文、逐单元覆盖率、按类型阈值判定，不静默修补 | — |
| `01-pdf-structure-audit/scripts/build.py` | 六步编排 + 产物落盘（document.json/md、tables/、formulas.md、audit/anchors/run_meta） | — |
| `01-pdf-structure-audit/scripts/make_result.py` | 组装 `result.json`，按 `output_contract` 字段名逐个填，填不出写 null + 原因 | — |
| `01-pdf-structure-audit/scripts/run_case.py` | 平台入口：读 `/input` 找 PDF，异常一律落 `status=blocked` 的结构化结果 | — |
| `01-pdf-structure-audit/scripts/run_selftest.py` | 7 个合成件 + 5 条单元断言；本地实跑 12/12 通过 | — |
| `01-outputs/` | 只放说明，**没有任何答案文件** | `--outputs` |
| `01-outputs/GITHUB_URL.txt` | 公开仓库对应目录链接 | — |

题面 ID：`product-arena-08-3027d350`（阅读01｜文献文档解析；平台占位名与实际题号不一致，以 ID 为准）。

```bash
playground submit \
  --challenge-id product-arena-08-3027d350 \
  --skill    "D:/桌面/bohrium-cugb-p1/01-pdf-structure-audit" \
  --outputs  "D:/桌面/bohrium-cugb-p1/submission/01-outputs" \
  --trace    "_trace/01_trace.jsonl" \
  --dry-run
```

> 第 01 题尚未提交。trace 已备好在 `_trace/01_trace.jsonl`（48 条、valid=true，8 类 PII 残留全 0；论文题名保留为公开题录信息）。
> 明细见 `01-提交清单.md`。

---

## 第 07 题：参考文献与引用管理

### 目录结构与用途

| 路径 | 作用 | 对应提交参数 |
|---|---|---|
| `07-structured-citation/` | Skill 本体 12 个文件（含 `GITHUB_URL.txt`）：入口 `SKILL.md`、提示词、字段字典、去重/格式判据、评分自查表、3 个脚本、示例、13 条自测 | `--skill` |
| `07-structured-citation/SKILL.md` | 平台入口；主线"编得顺"双向编号一致性，第二层"收得净"可解释去重与字段核验 | — |
| `07-structured-citation/scripts/citation_audit.py` | 核心审计：悬空/未用、编号重排、逐条回链、同 DOI 分级去重、预印本/DOI/访问日期核验 | — |
| `07-structured-citation/scripts/make_result.py` | 组装 `result.json`，对齐 `output_contract`，输出可编辑稿与 change_log | — |
| `07-structured-citation/scripts/run_selftest.py` | 13 条合成用例；本地实跑 13/13 通过 | — |
| `07-outputs/` | 只放说明，**没有任何答案文件** | `--outputs` |
| `07-outputs/GITHUB_URL.txt` | 公开仓库对应目录链接 | — |

题面 ID：`product-arena-03-429cc14d`（写作04｜参考文献与引用管理；平台占位名与实际题号不一致，以 ID 为准）。

```bash
playground submit \
  --challenge-id product-arena-03-429cc14d \
  --skill    "D:/桌面/bohrium-cugb-p1/submission/07-structured-citation" \
  --outputs  "D:/桌面/bohrium-cugb-p1/submission/07-outputs" \
  --trace    "<本题真实 Agent 会话日志 jsonl 的绝对路径>" \
  --dry-run
```

> 第 07 题尚未提交。trace 必须取本题相关对话并脱敏，不能复用 06 或 03 的 trace。trace 已备好在 `_trace/07_trace.jsonl`（40 条、valid=true）。

---

## 第 02 题：文献翻译

### 目录结构与用途

| 路径 | 作用 | 对应提交参数 |
|---|---|---|
| `02-translation-audit/` | Skill 本体 14 个文件（含 `GITHUB_URL.txt`）：入口 `SKILL.md`、工作流提示词、字段字典、翻译保真规则、评分自查、4 个脚本、示例、13 条自测 | `--skill` |
| `02-translation-audit/SKILL.md` | 平台入口；说明"脚本负责锁和查、Agent 负责译"的分工与六步流程 | — |
| `02-translation-audit/scripts/pdf_paragraphs.py` | PDF→段落级结构：双栏按 x0/y0 排阅读顺序、页眉页脚自适应剔除、跨页续段标记、公式/表行/参考文献/元数据分类 | — |
| `02-translation-audit/scripts/term_extract.py` | 术语候选抽取：缩写定义（含小写 lvp）、高频名词短语；单复数与同缩写合并；只给候选与位置，不定译名 | — |
| `02-translation-audit/scripts/translation_audit.py` | 核心审计：段号覆盖、术语漂移/禁用别名、数字单位引用否定守恒；支持 `--scope` 局部审计 | — |
| `02-translation-audit/scripts/make_result.py` | 组装 `result.json` 对齐 `output_contract`，并产出 `bilingual.md` + `glossary.csv` | — |
| `02-translation-audit/scripts/run_selftest.py` | 13 条合成用例；本地实跑 13/13 通过 | — |
| `02-outputs/` | 只放说明，**没有任何答案文件** | `--outputs` |
| `02-outputs/GITHUB_URL.txt` | 公开仓库对应目录链接 | — |

题面 ID：`product-arena-01-5a9928c1`（阅读03｜文献翻译；平台占位名与实际题号不一致，以 ID 为准）。

```bash
playground submit \
  --challenge-id product-arena-01-5a9928c1 \
  --skill    "D:/桌面/bohrium-cugb-p1/submission/02-translation-audit" \
  --outputs  "D:/桌面/bohrium-cugb-p1/submission/02-outputs" \
  --trace    "<本题真实 Agent 会话日志 jsonl 的绝对路径>" \
  --dry-run
```

> 第 02 题尚未提交。验证用的海雾论文原文全程本地处理，未上传、未进包。
> trace 已备好在 `_trace/02_trace.jsonl`（76 条、valid=true，8 类 PII 残留全 0）。

---

## 运行时路径（供核对，不需要手工创建）

- 输入：`/input/case.json` 与同目录 `task.md`；若给 PDF，读取实际 PDF 而非标签推断内容。
- 工作区：`/app/work`；最终产物：`/app/output/result.json` + 可编辑产物，必须含 `case_id` 和 `output_contract` 全部字段，并标注 `status` / `sources` / `uncertainty` / 变更记录。
- 安装位置：平台把 Skill 装到 `/skills/weekly-skill`，不要依赖本机绝对路径。
- 预算：64 次模型请求 / 900 秒 / 单次 16384 token；先存诚实的部分结果再增量改进。

## 明确不在本包内的内容

| 内容 | 位置 | 不进包的原因 |
|---|---|---|
| A/B 验证记录、论文抽取结果与可行性判断 | `../_validation/` | 含本地研究材料，题面不要求提交自造测评结果；论文原文全程未上传 |
| 旧版回滚备份 | `../_backup/` | 本地版本管理 |
| 会话轨迹 | `../_trace/` | 提交时单独用 `--trace` 指定，不进 Skill 包 |
| CLI 调试产物与压缩包 | `../_submit/`、`../playground-arm.zip` | 本地调试，与 Skill 无关 |

## 公开仓库状态

- 06：`GITHUB_URL.txt` 指向 https://github.com/HWL-666-cm/skill-lab-h/tree/main/06-academic-polishing
- 03：`GITHUB_URL.txt` 指向 https://github.com/HWL-666-cm/skill-lab-h/tree/main/03-structured-notes
- 07：`GITHUB_URL.txt` 指向 https://github.com/HWL-666-cm/skill-lab-h/tree/main/07-structured-citation
- 02：`GITHUB_URL.txt` 指向 https://github.com/HWL-666-cm/skill-lab-h/tree/main/02-translation-audit

提交前需用**未登录** GitHub 的浏览器窗口打开一次链接确认可见。
