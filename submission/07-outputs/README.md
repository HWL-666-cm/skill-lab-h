# 07 题 outputs 说明

本题为 Skill 创作任务。按题面要求，**outputs 目录不放预制答案或正式测试结果**。

平台运行时，Skill 会把实际产物写到 `/app/output`：

- `result.json`：含 `case_id` 与平台 `output_contract` 全部字段
- `edited_manuscript.md`：可继续编辑的修订稿
- `change_log.csv`：逐条改动与依据

本目录仅有 `GITHUB_URL.txt`（5 分附加分所需）与本说明文件。

最小调用示例见 Skill 目录内 `examples/case-example.json` 和 `examples/output-example.md`，其中明确标注为虚构示例，不是平台固定案例的答案。
