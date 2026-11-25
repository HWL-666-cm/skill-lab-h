# 文献总结与结构化笔记 Skill（structured-notes-v2）

阅读10｜文献总结与结构化笔记的参赛作品。核心思路：**按论文自身章节树生成字段化、带证据标记与原文锚点的可检索笔记**，而不是一段压缩后的通读摘要。

## 一句话方案

把一篇论文整理成三类可复用结构，四件事有确定性支撑：

1. **对得上**：笔记骨架 = 论文自身章节树（`3 → 3.1 → 3.1.1`），逐章提炼，不套通用模板；
2. **留得住**：论文卡片字段化（研究问题/数据/方法/方法前提/发现/关键数值/局限/未报告）+ 证据五标记；
3. **找得回**：每条笔记带 `§章节 / 页码 / 段落 / 图表 / 公式` 稳定锚点；
4. **用得上**：字段化 JSON（论文卡片 + 章节笔记 + 知识点条目），可检索、可跨论文比较。

## 文件结构

```
SKILL.md                     # Skill 本体（流程/字段/证据标记/锚点/输出/异常）
README.md                    # 本说明
GITHUB_URL.txt               # 提交用 GitHub 链接
scripts/extract_document.py  # 结构化解析：章节层级 + 段落 + 图表 + 阅读顺序（确定性）
scripts/build_skeleton.py    # 笔记骨架：章节树 + 论文卡片空字段 + 锚点（确定性）
scripts/run.py               # 评测环境入口
example/demo_result.json     # 最小调用示例（标为示例）
```

## 调用方式

```bash
python3 scripts/extract_document.py <paper.pdf> /app/work/extracted.json --workdir /app/work/ext
python3 scripts/build_skeleton.py /app/work/extracted.json /app/work/skeleton.json
# Agent 依据 SKILL.md 填论文卡片 / 章节笔记 / 知识点条目，写 result.json
```

## 依赖与限制

- 运行时镜像预装 poppler-utils + python3（仅标准库）+ 可选 tesseract（OCR）。
- 章节树由确定性脚本生成，标题/脚注/表格行偶有噪声，Agent 依渲染页图校正。
- 笔记内容（论文卡片/章节总结/知识点）由运行时模型生成，本 Skill 负责"结构 + 锚点 + 证据标记约束"。
