# 示例输出（示意，不是正式案例结果）

> 本文件是格式示意，用一段虚构原文演示 `bilingual.md` 与 `result.json` 长什么样。
> **不是平台案例结果，不能当答案提交。**

## 1. bilingual.md 片段

```markdown
# 双语对照（段落级）

来源：example.pdf

## P3 · p1 · 1 Introduction

**原文**：Visibility forecasts are generated with two approaches (Author et al., 2020).

**译文**：能见度预报由两种方法生成（Author et al., 2020）。
```

## 2. glossary.csv 片段

```csv
concept_id,source,abbr,target,forbidden,occurrence_pids
C01,visibility forecast,,能见度预报,可见度预报,3
```

## 3. result.json 关键字段（截断）

```json
{
  "case_id": "example-001",
  "status": "ok",
  "translation": [
    {"pid": 3, "page": 1, "section": "1 Introduction",
     "source": "Visibility forecasts are generated with two approaches (Author et al., 2020).",
     "target": "能见度预报由两种方法生成（Author et al., 2020）。",
     "status": "translated"}
  ],
  "glossary": [
    {"concept_id": "C01", "source": "visibility forecast", "target": "能见度预报",
     "forbidden": ["可见度预报"], "occurrences": [{"pid": 3, "page": 1}]}
  ],
  "audit_report": {
    "verdict": "ok",
    "counts": {"body_paragraphs": 1, "translated_paragraphs": 1,
               "glossary_concepts": 1, "errors": 0, "warnings": 0}
  },
  "task_coverage": {"paragraphs_total": 1, "paragraphs_translated": 1,
                    "glossary_terms": 1, "glossary_locked": 1},
  "output_contract_alignment": {"contract_fields": [], "filled_from_aliases": {}, "missing_required": []}
}
```

## 4. 审计报告里 error / warning 的样子

```json
{
  "verdict": "needs_revision",
  "issues": [
    {"id": "I001", "type": "missing_paragraph", "severity": "error",
     "detail": "原文 1 个正文段没有译文（漏段）：pid [13]", "evidence": "missing_count=1"},
    {"id": "I006", "type": "forbidden_term_used", "severity": "error", "pid": 8,
     "detail": "C04 译文使用了禁用别名「低能见度流程」，应为「低能见度程序」。",
     "evidence": "forbidden=低能见度流程"},
    {"id": "I013", "type": "unit_lost", "severity": "warning", "pid": 8,
     "detail": "pid 8 单位符号未保留：['d', 'h']", "evidence": "d,h"}
  ]
}
```
