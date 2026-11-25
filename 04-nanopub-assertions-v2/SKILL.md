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
python3 scripts/extract_document.py <paper.pdf> /app/work/extracted.json --workdir /app/work/ext
```

产出章节/段落（带 `id/page/column/section`）、标题/作者（供 `pubinfo` 与证据定位）。

### 阶段二：模型拆断言（预算内）

1. **读骨架 + 受控词表**：`predicate` 只能从 `resources/predicates.json` 的 16 个谓词中选择（`achieves/improves/reduces/uses/proposes/evaluates/trained_on/fine_tuned_on/causes/is_a/compared_with/shows/outperforms/consists_of/correlates_with/prevents`）。
2. **逐段拆断言（分批，每批 3–5 段）**：按 §4 拆解规则生成 `subject-predicate-object`，每条绑定证据。
3. **结构与词表校验（0 次请求）**：把断言写成 `nanopubs.json`，运行：
   ```bash
   python3 scripts/nanopub_schema.py /app/work/nanopubs.json
   ```
   校验器确定性检查：字段缺失、词表越界、主体混淆线索、来源缺失（§5.1）。
4. **带违规修正**：对 `error` 级断言，把具体违规回传模型修正一次；仍失败写入 `uncertainty`。
5. **去重与归并**：同一 subject-predicate-object 的重复断言合并，冲突断言都保留并标注冲突。

### 模型请求预算（64 次上限）

| 阶段 | 请求数 |
|-|-:|
| 读骨架 + 确定抽取范围 | 1 |
| 逐段拆断言（每批 3–5 段，约 100 段 → 20–33 批） | ≤ 35 |
| 带违规修正 | ≤ 5 |
| **合计** | **≤ 41**，留 ≥23 次余量 |

超长兜底：先交已拆的前 N 段 + `status=partial`，未拆段号写入 `uncertainty`，不留空断言冒充完整。

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

## 7. 输出格式（/app/output/result.json）

```json
{
  "case_id": "来自 case.json",
  "answer": { "output_contract 声明的每个字段": "真实断言结果" },
  "structured": {
    "nanopubs": [ { "id":"","assertion":{},"evidence":{},"provenance":{},"pubinfo":{},"confidence":{} } ],
    "validation_summary": {"total":0,"ok":0,"error":0,"warning":0},
    "predicates": [{"type":"achieves","label":"达到/取得","verbs":["achieve"]}],
    "document": {"title":"","page_count":0,"ocr_used":false}
  },
  "evidence": [{"item":"断言","value":"依据","source":"§/页/行"}],
  "status": "success | partial | failed | refused | unable_to_judge",
  "status_detail": "一句话",
  "uncertainty": [{"item":"","reason":""}],
  "warnings": [],
  "changes": [{"time":"","action":"","detail":""}]
}
```

## 8. 异常处理

| 情况 | 识别 | 处理 |
|-|-|-|
| 无文字层/扫描件 | `pdffonts` 无字体 | `extract_document.py` 自动 OCR；断言标注"OCR 可能错字，需对照页图复核" |
| 断言找不到支撑片段 | 结构校验 `evidence_quote_empty` | 该断言 `status=partial`，写 `uncertainty`，不硬造证据 |
| 断言与证据冲突 | 证据片段不支持断言 | 标记 `supports=false` + `confidence.level=low`，写冲突 |
| 证据跨图表 | 证据在表格/图注 | 定位 `location` 写图表编号（`Fig.3`/`Table 2`） |
| 字段缺失 | 来源元数据不全 | 写"未报告"，不补造；结构与词表校验报 warning |

## 9. 最小调用示例

输入：BERT 论文第 5 页一句 "BERT LARGE obtains a score of 80.5 on GLUE, outperforming GPT."

拆解（示意，标为示例）：
```json
{"id":"np-1","assertion":{"subject":"BERT LARGE","predicate":"achieves","object":"80.5 GLUE score","condition":"on GLUE"},
 "evidence":{"quote":"BERT LARGE obtains a score of 80.5 on GLUE","location":{"section":"4.1","page":5,"line":12},"evidence_type":"direct"},
 "pubinfo":{"paper":"BERT: Pre-training of...","authors":["Devlin et al."],"year":2019,"identifier":"arXiv:1810.04805"}}
{"id":"np-2","assertion":{"subject":"BERT LARGE","predicate":"outperforms","object":"GPT","condition":"on GLUE"},
 "evidence":{"quote":"...outperforming GPT","location":{"section":"4.1","page":5,"line":12},"evidence_type":"direct"},
 "pubinfo":{}}
```

> 以上为示意输出，标为示例；正式案例断言由平台实际运行产生。
