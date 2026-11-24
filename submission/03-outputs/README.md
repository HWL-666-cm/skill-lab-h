# 03 题运行时输出目录说明

本题是 Skill 创作任务，**只提交 Skill 及其必要资源，不提交答案、白板或正式测试结果**。
本目录刻意不放任何 `result.json` / 笔记样例答案文件——平台会用固定 3 个案例现场运行 Skill 生成结果。

## 运行时产物写到哪里

平台运行合同规定最终产物在 `/app/output`，Skill 会写：

| 文件 | 作用 |
|---|---|
| `/app/output/result.json` | 主结果，含 case_id、paper_card、section_outline、claim_notes、source_map、uncertainties、limitations、audit 等全部 `output_contract` 字段 |
| `/app/output/notes.csv` | 逐条笔记可核对表（id / field / value / page / section / quote / 锚点判定），便于人工复核 |

中间产物写在 `/app/work`：`extracted.json`（PDF 抽取）、`notes.json`（结构化笔记）、`anchor_audit.json`（锚点核验）、`task_items.json`（任务项清单）。

## 自查命令（与当前提交脚本参数一致）

```bash
python3 /skills/weekly-skill/scripts/run_selftest.py
```

5 条合成用例应全 PASS。若 FAIL，说明锚点核验脚本损坏，先修脚本再跑案例。
