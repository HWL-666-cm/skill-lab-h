# Nanopublication 断言抽取 Skill（nanopub-assertions-v2）

阅读14｜Nanopublication 的参赛作品。核心思路：**把论文结论拆成原子 subject-predicate-object 断言，每条绑定最小证据片段与来源元数据，导出 TriG 四图，并用受控关系词表 + AIDA 判据 + 逐字校验保证可机器解析、可回原文**。

## 一句话方案

四件事有确定性支撑：

1. **拆得细**：一段结论 → 若干 SPO 原子断言，复合句按并列/因果/让步拆解，AIDA 四判据把关；
2. **对得上**：每条断言绑定最小充分证据片段，`validate.py` 逐字核对 quote 在原文出现 + 页码匹配 + 主客体在证据内；
3. **追得回**：`provenance` + `pubinfo`（论文/作者/年份/版本/DOI/arXiv）+ TriG 的 `prov:wasDerivedFrom` 完整链路；
4. **读得懂**：受控关系词表（16 谓词 + 类型签名）+ 字段化 JSON + `assertions.trig` 四图（Head/Assertion/Provenance/PubInfo，官方词表 np/npx/hycl/cito/prov）。

## 文件结构

```
SKILL.md                        # Skill 本体（拆解规则/证据绑定/校验/输出/异常）
README.md                       # 本说明
GITHUB_URL.txt                  # 提交用 GitHub 链接
resources/predicates.json       # 受控关系词表（16 谓词 + 类型签名 + entity_types）
assets/relation-lexicon.json    # v1 生物医学词表（领域扩展参考）
references/output-contract.md   # 字段字典与导出结构
references/aida-rules.md        # AIDA 四判据细则与改写对照
references/failure-modes.md     # 失效模式
scripts/extract_document.py     # 结构化解析：章节/段落/标题/作者（确定性）
scripts/pdf_text.py             # 句子级解析：char_span + normal_text（供逐字核对）
scripts/aida_rules.py           # AIDA 四判据机械检查
scripts/nanopub_schema.py       # 结构与词表校验（确定性）
scripts/validate.py             # 逐条断言校验（AIDA/quote/entities/relation/trigger/scope/paste/confidence）
scripts/emit.py                 # 四图 TriG 渲染 + to_legacy_claim 转换
scripts/contract.py             # output_contract 顶层字段补齐
scripts/run.py                  # 编排入口：extract →（填断言）→ emit → validate → contract
example/demo_result.json        # 20 条断言示例（标为示例）
```

## 调用方式（两阶段）

```bash
python3 scripts/run.py          # 阶段 A：提取 + 骨架（status=partial）
# Agent 依据 SKILL.md 拆断言，写入 /app/work/nanopubs.json
python3 scripts/run.py          # 阶段 B：emit 出 assertions.trig + validate + 出 result.json
```

## 受控关系词表（读得懂的关键）

`predicate` 必须取自 `resources/predicates.json` 的 `relations` 键（16 个），杜绝自由发挥：

`ACHIEVES / IMPROVES / REDUCES / USES / PROPOSES / EVALUATES / TRAINED_ON / FINE_TUNED_ON / CAUSES / IS_A / COMPARED_WITH / SHOWS / OUTPERFORMS / CONSISTS_OF / CORRELATES_WITH / PREVENTS`

每个谓词带 `subject_types/object_types`（类型签名，方向错误即报 `direction_error`）+ `cues`（触发词）+ `verb`（AIDA 句合成）。实体类型：`MODEL/DATASET/TASK/METRIC/METHOD/BENCHMARK/ENTITY`。

## 依赖与限制

- 运行时镜像预装 poppler-utils + python3（仅标准库）+ 可选 tesseract。
- 断言内容（SPO 拆分、证据片段选择）由运行时模型生成，本 Skill 负责"受控词表 + AIDA 判据 + 逐字校验 + 四图渲染"把关。
- 结构/词表校验为确定性规则；语义质量（断言是否真的过宽、证据是否真的充分）由 Agent 判据复核，脚本不冒充语义判断。
