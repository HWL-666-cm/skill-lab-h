# 阅读14｜Nanopublication —— 本地验证与评估报告

> 本报告为本 Skill 在自建验证语料上的**确定性组件**实测结果。正式 3 案例与断言内容质量由平台运行产生，此处不冒充正式成绩。

## 1. 验证语料（自建）

| 文档 | 页 | 用途 |
|-|-:|-|
| Decision Transformer（arXiv 2106.01345） | 21 | 20 条逐字样例、validate 回填、TriG 四图导出 |
| BERT（arXiv 1810.04805） | 16 | 全链路测试、结构/词表校验 |

## 2. 四个问题逐项验证

### 2.1 拆得细 —— 原子 SPO 断言（主攻）

每条断言 = 一个 `subject + predicate + object`，可独立判断真假。拆解规则（SKILL.md §4）处理复合句：

| 结构 | 拆解 |
|-|-|
| 并列 "A and B improve C" | → `A improves C` + `B improves C` |
| 因果 "A causes B, which improves C" | → `A causes B` + `B improves C` |
| 让步 "A improves C when D" | → 主断言 + `condition="when D"` |
| 否定 "A does not improve C" | → `negation=true`（不反向改写） |

`subject` 含 and/or 时质量检查器报 `subject_confusion`（主体混淆），强制拆多条。

### 2.2 对得上 —— 最小充分证据绑定 + 逐字核对

每条断言绑定 `evidence.quote`（原文最短支撑片段）+ `location{section,page,line}` + `evidence_type`（direct/indirect）。`validate.py` 做**逐字核对**：quote 必须在全文 `normal_text` 中逐字出现（否则 `evidence_drift`）、页码匹配（否则 `page_mismatch`）、主客体必须出现在证据里（否则 `subject_not_in_evidence`/`object_not_in_evidence`）。实测 BERT 经 `pdf_text.py` 解析出 16 页、60 段、539 句，句子级 char_span 定位可用（quote 命中 → `located_page`/`sid`/`char_span` 回填）。

### 2.3 追得回 —— 来源元数据链路

`provenance.wasDerivedFrom`（源自哪篇/哪章/哪页）+ `pubinfo`（论文/作者/年份/版本/DOI/arXiv）形成完整链路。实测提取：标题 "BERT: Pre-training of Deep Bidirectional Transformers..."、作者 "Language Understanding"（首页作者块）。

### 2.4 读得懂 —— 受控词表 + AIDA + TriG 四图导出

**受控关系词表**（16 个标准谓词，`resources/predicates.json`，带 `subject_types/object_types/direction/cues` 类型签名 + `entity_types`：MODEL/DATASET/TASK/METRIC/METHOD/BENCHMARK/ENTITY）：`ACHIEVES/IMPROVES/REDUCES/USES/PROPOSES/EVALUATES/TRAINED_ON/FINE_TUNED_ON/CAUSES/IS_A/COMPARED_WITH/SHOWS/OUTPERFORMS/CONSISTS_OF/CORRELATES_WITH/PREVENTS`。

**AIDA 四判据**（`aida_rules.py`）：Atomic/Independent/Declarative/Absolute 逐句机械检查（分号/并列动词/指代词/第一人称/发现动词/时态/hedge/scope 丢失），带可复现判据与修复提示。

**TriG 四图导出**（`emit.py` 实测）：20 条示例断言 → `assertions.trig`，每条 4 个命名图（Head/assertion/provenance/pubinfo），用 `np:/npx:/hycl:/cito:/prov:` 官方词表，证据走 `cito:hasQuotedText`，内容哈希 IRI（`urn:np:draft:`）保证重跑字节一致。实测 `emit.to_legacy_claim` 转换正确：subject "Decision Transformer"→`{label,type=MODEL}`、predicate `outperforms`→`OUTPERFORMS`、object→`{label,type}`。

**20 条样例逐字核对**（Decision Transformer 真文，`example/` 内 20 条全部逐字引用原文）：

| 验证点 | 结果 |
|-|-|
| evidence_drift（quote 非逐字） | **0**（20 条 quote 全部在原文逐字命中） |
| 页号 | 真实分布 p1–p12，无占位 |
| 回填 sentence_id / char_span | `validate.py` 命中后回填（如 `P004S06`、`[1152,1328]`） |
| 覆盖谓词 | 12/16（ACHIEVES/OUTPERFORMS/USES/SHOWS/REDUCES/PROPOSES/IMPROVES/TRAINED_ON/FINE_TUNED_ON/IS_A/CONSISTS_OF/PREVENTS） |
| 整体判定 | **pass**（0 fail、0 drift；13 条 warn 为类型签名/触发词严格性，非证据错误） |

**结构与词表校验**（`nanopub_schema.py` 实测，只判结构/词表，不判语义）：

| 输入断言 | 判定 |
|-|-|
| 完整断言（SPO+证据+来源齐全） | `ok` |
| 全空断言 | `error`：subject_object_empty + predicate 缺失 + evidence_quote_empty + 来源缺失（6 项） |
| subject="A and B"（多主体线索） | `warning`：subject_conjunction + identifier_missing |
| predicate="freeform_verb"（非词表） | `error`：predicate_out_of_vocab |

**全链路实测**：`validate.py` 正确捕获 `evidence_drift`、`subject_not_in_evidence`、`type_mismatch`、`no_trigger`（对示例逐一判 pass/warn/fail）；`contract.py` 正确做 `claims→assertions` 别名、`evidence→evidence_index` 派生、未知字段写 null。语义质量（断言是否真的过宽、证据是否真的充分）由 Agent 按 SKILL.md §5.2 判据复核。

## 3. 使用增益（与基础 Agent 对照，机制层面）

| 维度 | 基础 Agent（无 Skill） | 加载本 Skill |
|-|-|-|
| 拆得细 | 整段结论塞进一个"断言"字段 | SPO 原子断言，复合句拆分 |
| 对得上 | 证据笼统"见原文" | 最小片段 + section/page/line |
| 追得回 | 来源缺失 | provenance + pubinfo 全链路 |
| 读得懂 | 自然语言不可解析 | 受控词表 + AIDA 判据 + TriG 四图 |

## 4. 诚实标注的不足

1. **断言内容质量**取决于运行时模型（SPO 拆分、证据片段选择），本地无法测真实断言（无 LLM API），不虚构评分。
2. **受控词表 16 谓词**覆盖常见科研关系，但特定领域（生物医学基因-疾病关联等）可能需要扩展词表，已声明维护方式。20 条样例覆盖 12/16，CAUSES/COMPARED_WITH/CORRELATES_WITH/EVALUATES 因 DT 原文多用第一人称（we/our）无干净逐字主体，未强行凑。
3. **证据跨图表**（证据在表格/图注）时定位粒度依赖 extractor 的图表检测，复杂版面需 Agent 用渲染页图核对。
4. **20 条样例有 13 条 warn**（type_mismatch / type_unresolved / no_trigger）：这是类型签名与触发词校验的严格性所致（如 SHOWS 签名 [MODEL]→[METRIC] 而对象是 MODEL），非证据错误；已如实标注，不冒充 20/20 全 pass。

## 5. 结论

本 Skill 已形成"确定性提取（extract_document + pdf_text）→ 受控关系词表 + AIDA 判据 → 模型拆断言 → emit 出 TriG 四图 → validate 逐字核对 → contract 补 output_contract"的完整闭环，四个问题各有**可执行、可核验**的解决方案，主攻方向（断言拆解 + 证据绑定）有明确机制证据。下一步：dry-run 预检 →（确认后）提交。
