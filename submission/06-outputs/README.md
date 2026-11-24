# outputs 目录：不提交预制答案

按题面「交付要求」：

> 参赛者只提交 Skill 及其必要资源；平台统一使用本题固定的 3 个案例运行 Skill。
> **Do not submit prepared answers or formal test outputs.**

本目录只放说明，**刻意不放任何答案文件**。评测时平台把 `06-academic-polishing/` 安装到
`/skills/weekly-skill`，在 3 个固定案例上各跑 3 次（加载 Skill / 不加载 Skill 两条件对照）。
`result.json`、`polished.md`、`changes.csv` 等产物由 Skill 在运行时写入 `/app/output`，
不是本包内的静态文件。

## 自查命令（接口已与当前脚本对齐）

```bash
# 1) 校验脚本本身能抓错、且不误报（6 条用例）
python ../06-academic-polishing/scripts/run_selftest.py --verbose

# 2) 人工走一遍接口（示例输入见 06-academic-polishing/examples/case-example.json）
python ../06-academic-polishing/scripts/hedge_audit.py \
  --original orig.txt --revised revised.txt --out audit.json

python ../06-academic-polishing/scripts/term_audit.py \
  --input orig.txt --out glossary.json
python ../06-academic-polishing/scripts/term_audit.py \
  --input revised.txt --glossary glossary.json --out drift.json

python ../06-academic-polishing/scripts/make_result.py \
  --case-id <CASE_ID> --case-json /input/case.json \
  --revised /app/work/revised.txt \
  --changes /app/work/changes.json \
  --audit /app/work/facts_after.json \
  --terms /app/work/terms_after.json \
  --task-items /app/work/task_items.json \
  --out /app/output/result.json
```

字段口径见 `../06-academic-polishing/references/output-contract.md`；
对照实验设计与自评表见 `../06-academic-polishing/references/eval-rubric.md`。

公开仓库：https://github.com/HWL-666-cm/skill-lab-h
