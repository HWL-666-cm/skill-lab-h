# 第 02 题 outputs 目录说明

本目录对应平台的 `--outputs` 参数。

按题面要求，参赛者**只提交 Skill 及其必要资源**，平台用本题固定的 3 个案例实际运行。
所以这里**不含任何答案、译文、result.json 或预生成的正式测试结果**。

运行时由 Skill 在 `/app/output/` 下自行产出：

| 产物 | 内容 |
|---|---|
| `result.json` | 含 `case_id`、`status`、段落级 `translation`、`glossary`、`audit_report`、`source_map`、`uncertainties`、`limitations`、`change_log` |
| `bilingual.md` | 段落级双语对照（每段带 pid / 页码 / 章节） |
| `glossary.csv` | 术语表，可被 Excel 打开继续维护 |

安装与调用方式见 `SKILL.md` 与 `prompts/translation-workflow.md`。
