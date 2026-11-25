---
name: latex-compile-repro
description: 当用户要求编译 LaTeX 项目、定位和修复 LaTeX 编译错误、排查引用或文献未定义、处理宏包冲突与 Unicode/中文编译失败、修复宽表溢出、把稿件迁入模板并保持可编译、说明 TeX 版本与字体依赖、或让他人按记录复现同一份 LaTeX 产物时使用。对 .tex 工程做真实多遍编译、按文件行号定位根因、在副本上做确定性修复、输出可编辑源码与可核验的构建清单。
---

# LaTeX 编译错误定位与可重复构建

## 适用范围

处理**已有 LaTeX 工程**的编译与修复：主文件/子文件、`.bib`、模板类、公式、表格、交叉引用、参考文献和字体依赖。输出的是**可继续编辑的源码**，不是 PDF、截图或片段。

不适用：从零代写论文内容、替换作者的数值或公式含义、在没有 TeX 引擎的机器上声称编译成功。

## 核心工作流

```
识别工程结构 → 真实多遍编译 → 全量日志分类 → 副本修复 → 重编收敛 → 独立目录复现 → 源码正确性审计
```

1. **识别工程**：读 `.tex` 主文件（含 `\documentclass`）、子文件、`.bib`、`.cls/.sty`、字体，判断引擎与文献后端。
2. **真实编译**：在隔离工作目录编译，捕获**全部轮次**的完整日志；不只看第一条错误。
3. **错误分类**：每条给 `文件:行号 → 根因 → 修复 → 复验`，类别见 `references/error-catalog.md`。
4. **副本修复**：只在 staging 副本上改，保留原始文件与 diff。
5. **重编收敛**：修复后重新编译，直到通过或确认需要人工判断。
6. **独立复现**：换一个干净目录，只拿最终源码按构建清单重编，比对源码哈希、退出码和诊断。
7. **正确性审计**（编译通过后）：对最终源码做引用/交叉引用/版式检查，抓"编译干净但产物错"的问题，见 `references/correctness-audit.md`。

## 调用方式

在本 Skill 目录执行（`<skill-dir>` = 本目录）：

```bash
python <skill-dir>/scripts/run_case.py \
  --case <case.json 或工程目录> \
  --out <输出目录> \
  --lexicon <skill-dir>/assets/lexicon.json \
  --schema <skill-dir>/assets/schema.json
```

常用选项：

| 选项 | 作用 |
|---|---|
| `--engine pdflatex\|xelatex\|lualatex` | 覆盖自动推断的引擎 |
| `--strategy latexmk\|sequence` | 强制编译器策略；默认自动，latexmk 运行时损坏会自动降级 |
| `--stage profile\|build\|reproduce\|full` | 只跑某一阶段，默认 full |
| `--deterministic` | 固定 `SOURCE_DATE_EPOCH`，使 PDF 字节也可复现（会固定 `\today`） |
| `--max-rounds N` / `--timeout N` | 修复轮数上限 / 单次编译超时秒数 |

单独使用某个脚本时，先读它的 `--help`。脚本之间只通过 JSON 文件交换数据。

## 输出

`<out>/` 下：

| 文件 | 内容 |
|---|---|
| `result.json` | `case_id`、`status`、全部 `output_contract` 字段、来源、不确定性、改动记录 |
| `source/` | 可编辑源码（`.tex/.bib/.cls/...`），已应用自动修复 |
| `error_ledger.json` | 每条错误的位置、类别、根因、修复、复验 |
| `changes.md` | 修复台账：已应用 vs 待人工确认 |
| `build_manifest.json` | 发行版、引擎、命令、轮次、源码哈希、依赖版本 |
| `reproduce.json` | 独立复现比对结果 |
| `audit.json` | 源码级正确性审计：引用/交叉引用/版式（只报告不改写） |
| `validation.json` | 门禁检查结果 |

`status` 三态：`complete`（编译通过、无未解决阻断项、复现通过）、`partial`（有未解决警告或复现差异）、`blocked`（无源码或环境不可用）。

## 关键规则（为什么这样定）

- **只在最后一轮之后判断引用/文献警告**。`Citation undefined`、`No file main.bbl` 是 `latex → bibtex → latex → latex` 的正常中间态；把它们当错误会去修一个已经自愈的问题。
- **不靠 `\resizebox` 硬缩放宽表**。社区共识是用 `tabularx` 的 `X` 列、`p{}` 定宽列、减小 `\tabcolsep` 或统一字号；硬缩放会让字号和线宽不一致。
- **biblatex 与 natbib/BibTeX 不混用**。检测到哪一个就只用哪一套命令，混用会产生 `Option clash`。
- **自动修复只覆盖确定性动作**：清理陈旧辅助文件、切换到 Unicode 引擎、补白名单内的标准宏包。数值、公式语义、引用键、模板必填项一律标 `applied: false` 交人工判断——猜错比不改更糟。
- **复现不等于 PDF 字节一致**。pdfTeX 默认把编译时间写进 PDF，两次正确编译天然不同；默认比对源码哈希、退出码和诊断，只有 `--deterministic` 才要求 PDF 字节一致。
- **不把 PDF/PNG 放进交付目录**。评测器对 Skill 资源有白名单后缀限制，运行时产物只在 manifest 里记哈希。

## 异常处理

| 情况 | 行为 |
|---|---|
| 没有 `.tex` 且 case 未内联源码 | 写 `status: blocked`，不编造源码 |
| latexmk 存在但运行时损坏（Perl/路径/locale 错） | 自动降级到显式编译序列，在 manifest 里记录原因 |
| bibtex/biber 在含非 ASCII 路径下失败 | 改用相对文件名、在 build 目录运行 |
| 宏包/字体确实缺失 | 明确写出缺什么、建议安装方式；不伪造环境 |
| 引用的 `output_contract` 字段无对应产物 | 置 `null` 并写入 `contract_report.missing`，不编造值 |
| 权限不足、超时 | 记录原始错误，标 `partial` 或 `blocked` |

## 资源与版本

- 依赖：Python 3（标准库即可）＋ 本机 TeX Live（pdflatex/xelatex/latexmk/bibtex/biber）。无第三方 Python 包。
- 引擎版本、发行版、宏包与字体信息由 `build_manifest.json` 在运行时记录，不在文档里写死。
- Skill 资源：UTF-8 文本，单文件 < 500KB，总数 < 50，总计 < 2MB，无符号链接。

## 示例与自测

- `assets/examples/`：一组最小可编译工程（好稿、坏稿），`result.json` 带 `example: true`，**不是正式案例答案**。
- `assets/tests/run_selftest.py`：冷启动自测 20 项，覆盖多遍收敛、引擎切换、行号定位、honesty、确定性和源码正确性审计。运行：

```bash
python <skill-dir>/assets/tests/run_selftest.py
```

更细的错误分类、修复策略和复现判据见 `references/` 目录。
