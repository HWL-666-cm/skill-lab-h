---
name: nanopub-assertions-v2
description: Nanopublication 结构化抽取 Skill。把论文结论拆成原子断言（subject-predicate-object），为每条绑定最小证据片段与原文位置，补全来源元数据，并用受控关系词表与结构与词表校验保证可机器解析。
---

# Nanopublication 断言抽取（nanopub-assertions-v2）

## 1. 用途与触发条件

**用途**：把科研论文中的关键结论拆成**可独立判断真假的原子断言**（Nanopublication），每条断言绑定最小证据片段与来源元数据，输出可被下游程序直接解析的结构化结果。

**适用任务**：论文断言抽取、知识单元构建、证据绑定、来源回溯、结构化导出（供知识图谱/数据库/推理系统消费）。

**触发条件**：任务要求从科研材料抽取"断言/结论/知识三元组"，且要求证据可回原文、来源可追溯、结果可机器解析。

**不适用**：纯翻译（translation-audit-v2）、纯总结笔记（structured-notes-v2）、不需要原子化拆分的整段摘要。

## 2. 四个核心问题与解决方案（必读）

| 问题 | 解决方案（可执行、可核验） |
|-|-|
| **拆得细** | 一段结论拆成若干 `subject-predicate-object` 原子断言；复合句按并列/因果/让步拆解，限定条件写进 `condition`，否定写 `negation`，拒绝把整段塞进一个字段。 |
| **对得上** | 每条断言绑定**最小充分证据片段**（`evidence.quote` + 原文位置 `section/page/line`），区分 `direct`（直接证据）与 `indirect`（间接推论）。 |
| **追得回** | `provenance.wasDerivedFrom`（源自哪篇/哪章/哪页）+ `pubinfo`（论文/作者/年份/版本/标识符 DOI/arXiv）形成完整链路，他人据此回到原文。 |
| **读得懂** | 字段化 JSON + **受控关系词表**（`predicate` 必须取自 `resources/predicates.json` 的 16 个标准谓词），下游程序无需人工清洗即可解析。 |

## 3. 工作流程（两阶段，预算友好）

### 阶段一：确定性准备（0 次模型请求）

```bash
python3 scripts/run.py
```

`run.py` 一次跑两条提取线：`extract_document.py`（章节/标题/作者，供 pubinfo 与证据定位）+ `pdf_text.py`（句子级 char_span 与 normal_text，供 validate 逐字核对）。产出骨架 `result.json`（status=partial，附章节、受控词表、空模板），并提示写入 `/app/work/nanopubs.json`。

### 阶段二：模型拆断言（预算内）

1. **读骨架 + 受控词表**：`predicate` 只能从 `resources/predicates.json` 的 `relations` 键选（16 个：`ACHIEVES/IMPROVES/REDUCES/USES/PROPOSES/EVALUATES/TRAINED_ON/FINE_TUNED_ON/CAUSES/IS_A/COMPARED_WITH/SHOWS/OUTPERFORMS/CONSISTS_OF/CORRELATES_WITH/PREVENTS`）。
2. **逐段拆断言（分批，每批 3–5 段）**：按 §4 拆解规则生成 `subject-predicate-object`，每条绑定证据（quote 逐字复制自原文，供 `validate` 的 `evidence_drift` 核对）。
3. **写断言**：按 §6 嵌套字段写 `/app/work/nanopubs.json`（每条一个对象，`assertion/evidence/provenance/pubinfo/confidence`）。
4. **重跑 run.py 完成 emit + validate（0 次请求）**：
   ```bash
   python3 scripts/run.py
   ```
   此时 run.py 检测到 nanopubs.json，执行：`emit.to_legacy_claim`（嵌套→四图）→ `emit.build_trig`（出 `/app/output/assertions.trig`）→ `validate.validate`（逐条 AIDA/quote/entities/relation/trigger/scope/paste/confidence 校验，出 `validation.json`）→ `emit.build_result`（顶层 `assertions[]`）→ `contract.apply`（补 output_contract）。返回每条的 pass/warn/fail 与修复提示。
5. **带违规修正**：按 `validation.json` 的 `fix` 修正 `error` 级断言，重写 nanopubs.json，重跑 run.py；仍失败写 `uncertainty`，不硬造证据。

### 模型请求预算（64 次上限）

| 阶段 | 请求数 |
|-|-:|
| 读骨架 + 确定抽取范围 | 1 |
| 逐段拆断言（每批 3–5 段） | ≤ 35 |
| 带违规修正 | ≤ 5 |
| **合计** | **≤ 41**，留 ≥23 次余量 |

超长兜底：先交已拆的前 N 段 + `status=partial`，未拆段号写入 `uncertainty`；`assertions` 为空或 `assertions.trig` 为空时绝不写 `success`。

## 4. 断言拆解规则（拆得细）

一条 nanopub 断言必须满足"**单一、可独立判断真假**"：

1. **一个 subject、一个 predicate、一个 object**；`subject` 含并列连词（and/or）时必须拆成多条（防止主体混淆）；
2. **复合句拆解**：
   - 并列 "A and B improve C" → `A improves C` + `B improves C`；
   - 因果 "A causes B, which improves C" → `A causes B` + `B improves C`；
   - 让步/限定 "A improves C when D" → 主断言 `A improves C`，`condition="when D"`；
3. **否定**："A does not improve C" → `negation=true`（不得反向写成"A worsens C"）；
4. **模态**：`fact`（实验证实）/`claim`（作者主张）/`hypothesis`（假设）分开记录；
5. **数值断言**：object 保留数值+单位+基线+条件（如 `80.5 GLUE score (baseline GPT, on GLUE)`），不写"显著提升"这类无锚点的模糊表述。

## 5. 证据绑定与校验（对得上 / 质量检查方向）

**证据最小充分性**：`evidence.quote` 取原文中**能支撑该断言的最短片段**（一句，非整段）；`location` 给出 `section/page/line`；`evidence_type` 区分 `direct`（原文直接陈述）与 `indirect`（需推理）。

### 5.1 结构与词表校验（脚本，可复现）

`nanopub_schema.py` **只做结构与词表校验，不做语义判断**：

| 检查项 | 判定规则（可复现） |
|-|-|
| 字段缺失 | subject/object/predicate/quote 为空，或 location 无 page/section |
| 主体混淆线索 | subject 含 and/or 并列连词（warning，需复核） |
| 词表越界 | predicate 不在受控词表 |
| 来源缺失 | paper/year/identifier 缺一项以上 |

### 5.2 语义质量判据（Agent 复核）

语义质量需理解内容，脚本无法代判，由 Agent 按下列**可复现判据**复核：

| 语义检查 | 可复现判据 |
|-|-|
| 断言过宽 | 拆完的断言必须能答全三问：谁（subject）？做了什么（predicate）？结果/对象（object）？答不完整 → 继续拆。subject 或 object 标签 > 80 字符视为可能未拆净，需再拆 |
| 证据不足 | quote 必须逐字来自原文，且**无需额外推理**即可支撑该断言；若需推理才能从 quote 得出断言 → `evidence_type="indirect"`，`confidence.level` 降为 medium/low |

**通过标准**：结构校验无 error + 语义判据全部满足。

## 6. Nanopub 结构（四图，读得懂）

```json
{
  "id": "np-1",
  "assertion": {"subject":"BERT LARGE","predicate":"achieves","object":"80.5 GLUE score",
                "condition":"on GLUE benchmark","negation":false,"modality":"fact"},
  "evidence": {"quote":"BERT LARGE obtains a score of 80.5 on GLUE",
               "location":{"section":"4.1","page":5,"line":12},
               "evidence_type":"direct","supports":true},
  "provenance": {"wasDerivedFrom":{"paper":"BERT: Pre-training of...","section":"4.1","page":5},
                 "method":"text-extraction"},
  "pubinfo": {"paper":"BERT: Pre-training of...","authors":["Jacob Devlin","..."],
              "year":2019,"version":"v2","identifier":"arXiv:1810.04805"},
  "confidence": {"basis":"直接证据","level":"high"}
}
```

四图对应：`assertion`（主断言 SPO）+ `provenance`（断言来源：wasDerivedFrom）+ `pubinfo`（发布信息：作者/年份/版本/标识符）+ `head`（id 链接各图）。

## 7. 输出格式（三份产物）

`run.py` 阶段 B 产出三份：`/app/output/result.json`（主结果，**顶层 `assertions[]`**）、`/app/output/assertions.trig`（四图 RDF）、`/app/output/validation.json`（逐条检查）。字段字典见 `references/output-contract.md`。

```json
{
  "case_id": "来自 case.json",
  "status": "pass | partial | fail | blocked",
  "task": "nanopublication-assertion-extraction",
  "input": {"file":"","pages":0,"paragraphs":0,"sentences":0},
  "assertions": [
    { "id":"A01", "text":"BERT LARGE achieves 80.5 GLUE score.",
      "aida": {"atomic":true,"independent":true,"declarative":true,"absolute":true},
      "subject":{"label":"BERT LARGE","type":"MODEL"}, "predicate":"ACHIEVES",
      "object":{"label":"80.5 GLUE score","type":"METRIC"},
      "evidence":{"quote":"...","page":5,"sentence_id":"P023S01","char_span":[0,10]},
      "confidence_basis":"直接引文","relation_type":"direct","status":"verified" }
  ],
  "sources": [{"name":"","iri":"","doi":"","title":"","year":0}],
  "validation": {"status":"","counts":{"pass":0,"warn":0,"fail":0},"structure":{"n_nanopubs":0}},
  "uncertainty": [],
  "contract_report": {"declared":[],"native":[],"aliased":{},"derived":{},"missing":[]}
}
```

`output_contract` 声明的字段由 `contract.py` 在顶层补齐（同义词别名 / 证据索引派生 / 无法映射写 null）。**不变量：`assertions` 为空或 `assertions.trig` 为空时，`status` 绝不写 `pass`。**

## 8. 异常处理

| 情况 | 识别 | 处理 |
|-|-|-|
| 无文字层/扫描件 | `pdffonts` 无字体 | `extract_document.py` 自动 OCR；断言标注"OCR 可能错字，需对照页图复核" |
| 断言找不到支撑片段 | 结构校验 `evidence_quote_empty` | 该断言 `status=partial`，写 `uncertainty`，不硬造证据 |
| 断言与证据冲突 | 证据片段不支持断言 | 标记 `supports=false` + `confidence.level=low`，写冲突 |
| 证据跨图表 | 证据在表格/图注 | 定位 `location` 写图表编号（`Fig.3`/`Table 2`） |
| 字段缺失 | 来源元数据不全 | 写"未报告"，不补造；结构与词表校验报 warning |

## 9. 最小调用示例

完整示例见 `example/` 两个文件：`nanopubs.json`（Agent 填写的嵌套输入，20 条）+ `demo_result.json`（run.py 阶段 B 的输出，顶层 `assertions[]` + 填好的 `answer`）。20 条断言全部**逐字引用** Decision Transformer 原文（页号真实，`sentence_id`/`char_span` 由 validate 回填），覆盖 12 个受控谓词。

输入（`nanopubs.json` 一条）：
```json
{"id":"A01",
 "assertion":{"subject":"Decision Transformer","predicate":"outperforms",
              "object":"state-of-the-art model-free offline RL baselines","negation":false},
 "evidence":{"quote":"Despite its simplicity, Decision Transformer matches or exceeds the performance of state-of-the-art model-free offline RL baselines...",
             "location":{"page":1,"line":null},"evidence_type":"direct"},
 "pubinfo":{"paper":"Decision Transformer: Reinforcement Learning via Sequence Modeling","year":2021,"identifier":"arXiv:2106.01345"}}
```

> `example/` 为示意输出，标为示例；正式案例断言由平台实际运行产生。
