# 玻尔产品周赛·地大分站赛第一期 —— 第 06 题提交包

## 1. 这个文件夹是什么

本题是 Skill 创作任务，**只提交 Skill 及其必要资源**，不提交答案、白板或正式测试结果。
本文件夹把提交所需的材料集中在一处，共 17 个文件、约 82 KB，低于平台资源上限
（50 个 UTF-8 文本文件 / 单文件 500 KB / 总计 2 MB）。

## 2. 目录结构与用途

| 路径 | 作用 | 对应提交参数 |
|---|---|---|
| `06-academic-polishing/` | Skill 本体 15 个文件：入口 `SKILL.md`，以及提示词、规则词表、审计脚本、示例、自测用例 | `--skill` |
| `06-academic-polishing/SKILL.md` | 平台入口，运行合同要求位于 `/app/submission/SKILL.md`，安装后为 `/skills/weekly-skill/SKILL.md` | — |
| `06-academic-polishing/scripts/` | 4 个实际依赖脚本：限定强度审计、术语审计、契约对齐、自测 | — |
| `06-academic-polishing/prompts/`、`references/` | pass1 编辑 / pass2 复核提示词、输出契约、评分表、词表、语域规则 | — |
| `06-academic-polishing/examples/`、`tests/` | 一组标注为示例的输入输出、6 条合成回归用例 | — |
| `06-academic-polishing/GITHUB_URL.txt` | 公开仓库对应目录链接 | — |
| `06-outputs/` | 只放说明，**没有任何答案文件**；说明运行时产物写在 `/app/output` | `--outputs` |
| `06-outputs/README.md` | 自查命令与运行接口说明，命令与当前脚本参数一致 | — |

## 3. 提交命令模板

题面 ID：`product-arena-02-7051d92d`（写作02｜学术语言润色）。

```bash
playground submit \
  --challenge-id product-arena-02-7051d92d \
  --skill    "D:/桌面/bohrium-cugb-p1/submission/06-academic-polishing" \
  --outputs  "D:/桌面/bohrium-cugb-p1/submission/06-outputs" \
  --trace    "<真实 Agent 会话日志 jsonl 的绝对路径>" \
  --dry-run
```

`--trace` 必须是真实会话轨迹，CLI 会校验且题面要求原生轨迹由平台记录。
**本包不包含 trace 文件**：尚未确定使用哪一份真实会话日志，不能伪造，需先确认再填。

## 4. 运行时路径（供核对，不需要手工创建）

- 输入：`/input/case.json` 与同目录 `task.md`；若给 PDF，读取实际 PDF 而非标签推断内容。
- 工作区：`/app/work`；最终产物：`/app/output/result.json` 及可编辑稿，必须含
  `case_id` 和 `output_contract` 全部字段，并标注 `status`、`sources`、`uncertainty`、`change_records`。
- 安装位置：平台把 Skill 装到 `/skills/weekly-skill`，不要依赖本机绝对路径。
- 预算：64 次模型请求 / 900 秒 / 单次 16384 token；先存诚实的部分结果再增量改进。

## 5. 明确不在本包内的内容

| 内容 | 位置 | 不进包的原因 |
|---|---|---|
| A/B 验证记录与四问评估 | `../_validation/` | 含本地研究材料，题面不要求提交白板或自造测评结果 |
| 旧版回滚备份 | `../_backup/` | 只是本地版本管理 |
| CLI 调试产物 | `../_submit/dry2.json`、`dry2.err` | 本地调试记录 |
| 平台 CLI 压缩包 | `../playground-arm.zip` | 与 Skill 无关 |

## 6. 公开仓库状态

`GITHUB_URL.txt` 指向 https://github.com/HWL-666-cm/skill-lab-h/tree/main/06-academic-polishing 。
本地已完成修复，但仓库当前仍是修复前的 v1.1；如需评审看到本版本，需要先推送更新。
