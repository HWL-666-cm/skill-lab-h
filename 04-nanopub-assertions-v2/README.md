# Nanopublication 断言抽取 Skill（nanopub-assertions-v2）

阅读14｜Nanopublication 的参赛作品。核心思路：**把论文结论拆成原子 subject-predicate-object 断言，每条绑定最小证据片段与来源元数据，用受控关系词表与确定性质量检查保证可机器解析**。

## 一句话方案

四件事有确定性支撑：

1. **拆得细**：一段结论 → 若干 SPO 原子断言，复合句按并列/因果/让步拆解，限定条件写 `condition`；
2. **对得上**：每条断言绑定最小充分证据片段（`quote` + `section/page/line`），区分直接证据/间接推论；
3. **追得回**：`provenance` + `pubinfo`（论文/作者/年份/版本/DOI/arXiv）形成完整来源链路；
4. **读得懂**：受控关系词表（16 个标准谓词）+ 字段化 JSON，下游程序直接解析。

## 文件结构

```
SKILL.md                        # Skill 本体（拆解规则/证据绑定/质量检查/输出/异常）
README.md                       # 本说明
GITHUB_URL.txt                  # 提交用 GitHub 链接
resources/predicates.json       # 受控关系词表（16 个标准谓词）
scripts/extract_document.py     # 结构化解析：章节/段落/标题/作者（确定性）
scripts/nanopub_schema.py       # Nanopub 结构 + 确定性质量检查（确定性）
scripts/run.py                  # 评测环境入口
example/demo_result.json        # 最小调用示例（标为示例）
```

## 调用方式

```bash
python3 scripts/extract_document.py <paper.pdf> /app/work/extracted.json --workdir /app/work/ext
# Agent 依据 SKILL.md 拆断言、绑证据、填来源，写出 nanopubs.json
python3 scripts/nanopub_schema.py /app/work/nanopubs.json   # 质量检查
```

## 受控关系词表（读得懂的关键）

`predicate` 必须取自 `resources/predicates.json` 的 16 个标准谓词，杜绝自由发挥：

`achieves / improves / reduces / uses / proposes / evaluates / trained_on / fine_tuned_on / causes / is_a / compared_with / shows / outperforms / consists_of / correlates_with / prevents`

每个谓词带 `type`（标准名）+ `label`（中文）+ `verbs`（自然语言动词映射），下游程序可直接映射到 RDF/知识图谱。

## 依赖与限制

- 运行时镜像预装 poppler-utils + python3（仅标准库）+ 可选 tesseract。
- 断言内容（SPO 拆分、证据片段选择）由运行时模型生成，本 Skill 负责"受控词表约束 + 质量检查把关"。
- 质量检查为确定性规则（断言过宽/证据不足/关系类型错误/主体混淆/来源缺失），可复现。
