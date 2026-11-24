# 玻尔产品周赛·地大分站赛第一期 —— 提交包（第 06 题 + 第 03 题）

本题为 Skill 创作任务，**只提交 Skill 及其必要资源**，不提交答案、白板或正式测试结果。
本文件夹汇总两题的提交材料，每题的 Skill 目录均远低于平台资源上限
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

提交前需用**未登录** GitHub 的浏览器窗口打开一次链接确认可见。
