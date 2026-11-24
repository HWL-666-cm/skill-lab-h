# 字段字典（result.json 与中间产物）

## 1. `pdf_paragraphs.py` 输出

```json
{
  "source": "路径",
  "page_count": 14,
  "extraction": "pymupdf-block",
  "running_headers_removed": 2,
  "paragraphs": [
    {"pid": 8, "page": 1, "section": "1 Introduction", "kind": "para",
     "text": "……", "continued_from": null}
  ],
  "issues": [{"pid": 12, "type": "paragraph_continuation", "detail": "……"}]
}
```

| 字段 | 含义 | 是否待译 |
|---|---|---|
| `pid` | 全局段落号，从 1 递增，**对齐的唯一基准** | — |
| `page` | PDF 物理页码（1 起） | — |
| `section` | 所在章节标题（最近一个 heading） | — |
| `kind` | `para`/`heading`/`caption`/`formula`/`fragment`/`meta`/`reference` | 见下 |
| `text` | 段落文本（已合并硬换行与断词连字符） | — |
| `continued_from` | 若疑似续接上一段，记录上一段 pid | — |

`kind` 处置口径：

| kind | 含义 | 译不译 |
|---|---|---|
| `para` | 正文段落 | **译** |
| `heading` | 章节标题 | 译（术语要一致） |
| `caption` | 图表题注 | 按任务要求，通常译 |
| `formula` | 公式或公式碎片 | 不译；公式内可译文字单列 |
| `fragment` | 表格行/版式碎片 | 不译（除非任务点名要译表） |
| `meta` | 期刊名/DOI/作者/收稿日期/版权 | 不译 |
| `reference` | 参考文献条目 | 不译 |

`issues` 类型：`paragraph_continuation`（疑似续段）、`low_text_page`（可能扫描页需 OCR）。

## 2. `term_extract.py` 输出（术语表）

```json
{
  "schema_version": "1.0",
  "stats": {"body_paragraphs": 100, "candidates_raw": 14,
            "candidates_merged": 12, "abbreviation_definitions": 14},
  "concepts": [
    {"concept_id": "C04", "source": "capacity-reducing low-visibility procedure",
     "abbr": "lvp", "target": "低能见度程序", "aliases_allowed": ["low-visibility procedure"],
     "forbidden": ["低能见度流程"], "evidence": "abbreviation-definition",
     "occurrences": [{"pid": 8, "page": 1, "section": "1 Introduction"}], "locked": true}
  ]
}
```

| 字段 | 含义 |
|---|---|
| `source` | 原文术语（canonical 形式） |
| `abbr` | 缩写（可空） |
| `target` | 中文译名（**Agent 填**；空 = 未锁定） |
| `aliases_allowed` | 原文侧合法变体（单复数、长形式），匹配时也算命中 |
| `forbidden` | 译文侧禁用译名，出现即报 `forbidden_term_used` |
| `evidence` | 抽取依据：`abbreviation-definition` / `high-frequency-phrase(n)` |
| `occurrences` | 术语在原文出现的段（pid/page/section），供逐段核对 |

## 3. `translation_audit.py` 输出（审计报告）

```json
{
  "verdict": "needs_revision",
  "counts": {"body_paragraphs": 103, "translated_paragraphs": 3,
             "glossary_concepts": 12, "errors": 12, "warnings": 3, "issues_total": 15},
  "issues": [
    {"id": "I006", "type": "term_missing_in_translation", "severity": "error",
     "pid": 8, "detail": "C04「…」应在 pid 8 出现，译文未使用锁定译名「低能见度程序」。",
     "evidence": "target=低能见度程序;source_hit=1"}
  ],
  "coverage": {"missing_pids": [], "orphan_pids": [], "empty_pids": []}
}
```

`verdict`：有 `error` → `needs_revision`；只有 `warning` → `needs_review`；都没有 → `ok`。

问题类型全表：

| type | 级别 | 含义 | 对应四问 |
|---|---|---|---|
| `missing_paragraph` | error | 原文正文段无译文 | 段落全 |
| `orphan_paragraph` | error | 译文段号原文不存在 | 段落全 |
| `empty_translation` | error | 译文为空 | 段落全 |
| `term_missing_in_translation` | error | 该段原文含术语，译文未用锁定译名 | 术语稳 |
| `forbidden_term_used` | error | 译文用了禁用别名 | 术语稳 |
| `term_overused` | warning | 译文用了该术语但原文该段没检出，可能串位 | 术语稳 |
| `number_lost` | error | 阿拉伯数字未保留 | 关系准 |
| `unit_lost` | warning | 单位符号未保留 | 关系准 |
| `cite_year_lost` | warning | 引用年份未保留 | 可核验 |
| `bracket_cite_lost` | warning | `[n]` 引用编号未保留 | 可核验 |
| `fig_tab_ref_lost` | warning | 图表编号未保留 | 可核验 |
| `negation_lost` | warning | 原文有否定、译文无否定词 | 关系准 |
| `glossary_unlocked` | warning | 术语未定译名，未纳入检查 | 术语稳 |

## 4. `make_result.py` 输出（平台结果）

| 字段 | 含义 |
|---|---|
| `case_id` | 案例标识（来自 `--case-id`） |
| `status` | `ok` / `partial` / `failed`（缺段或有硬错误即 `partial`） |
| `translation` | 段落级对照：`pid/page/section/source/target/status` |
| `glossary` | 术语表（含 occurrences） |
| `audit_report` | 审计报告原样（verdict/counts/issues/coverage） |
| `source_map` | 每段的 pid/page/section 定位 |
| `task_coverage` | 段数总计/已译/术语数/已锁术语数 |
| `uncertainties` | 警告项 + 未锁术语（需人工确认） |
| `limitations` | 能力边界（脚本不能判译文质量等） |
| `change_log` | 缺段与硬错误的处理记录 |
| `output_contract_alignment` | 契约字段映射结果与缺失的必需字段 |

同目录产物：`bilingual.md`（段落级双语对照）、`glossary.csv`（Excel 可打开）。
