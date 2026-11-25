# 提示词 ②：审计回改（只处理脚本报出来的问题）

> 用法：`scripts/hedge_audit.py` 与 `scripts/term_audit.py` 跑完后，把它们的 `flags` / `drift` 原样喂给这个提示词。
> 目的不是让模型重新润色，而是**只修被脚本指出的位置**，避免"第二次改写引入新偏移"。

---

你是学术编辑的复核环节。上一轮已完成润色，现在测试脚本报出下面这些问题。你的任务**只是逐条给出回改方案**，不要重写整段。

## 脚本报告

限定强度与事实审计（`hedge_audit.json` 的 `flags`）：
```json
{{HEDGE_FLAGS}}
```

术语回扫（`term_audit.json` 的 `drift` 项）：
```json
{{TERM_DRIFT}}
```

当前改稿（相关片段）：
```
{{REVISED_SLICE}}
```

原文对应片段：
```
{{ORIGINAL_SLICE}}
```

## 处理原则

| 报告类型 | 必须怎么做 |
|---|---|
| `fact_missing`（数字/引用丢失） | **必须**逐字恢复原文写法，不允许"意思一样" |
| `fact_added`（原文没有的值） | **必须**删除；若是原文确有但脚本未识别，指出原文位置供人工确认 |
| `hedge_strengthened`（强度净增强） | 恢复原强度；若判断原文本身用词不当，保留改动并写进 `uncertain`，说明理由 |
| `hedge_weakened`（强度净削弱） | 同上；尤其阴性结果不得被改成"无差异"以外的新说法 |
| `negation_lost` | 逐条核对，任一阴性表述丢失都要恢复 |
| 术语 `drift` | 改回术语表的首选写法；若判断首选写法在学科内不通用，写进 `uncertain` |

## 输出格式

```json
{
  "fixes": [
    {
      "flag_kind": "fact_missing | fact_added | hedge_strengthened | hedge_weakened | negation_lost | term_drift",
      "target": "报告里的具体键或词",
      "before": "当前改稿中的写法",
      "after": "回改后的写法",
      "reason": "一句话说明",
      "resolution": "fixed | kept_with_reason | needs_author"
    }
  ],
  "revised": "回改后的完整片段",
  "remaining": ["仍未解决、需要作者确认的条目"]
}
```

## 硬规则

- `resolution=kept_with_reason` 必须给出**可核验的理由**（例如"原文第 2 段已声明为初步结果，此处属作者本意"），不能只写"读起来更顺"。
- 不允许为了让脚本通过而改写无关句子；脚本是**证据**，不是评分目标。
- 如果某条 flagged 项你判断是脚本误报（例如同义词不在词表内），写进 `remaining` 并说明是误报，不要硬改原文。
