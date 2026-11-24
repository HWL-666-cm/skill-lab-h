# Agent 侧操作流程（怎么调、怎么读、怎么写结论）

这份文件是给**调用这个 Skill 的 Agent** 看的。它不讲实现原理（那是 `references/` 的事），
只讲"拿到一个 PDF 之后按什么顺序做、看到什么算成功、失败了怎么交代"。

---

## 0 先判断该不该用本 Skill

| 输入情况 | 动作 |
|---|---|
| `/input` 里有 PDF，任务要求阅读/提取/结构化/翻译/问答 | 用本 Skill，走第 1 步 |
| 任务是"回答某个具体问题"，但需要引用原文位置 | 用本 Skill 先拿结构，再基于 `body_paragraphs` 回答，答案里带 `[p.N]` |
| 输入是图片（jpg/png）、或要求理解图表科学含义 | 不走本 Skill（只做结构元素识别，不做内容理解） |
| 输入已经是 markdown/txt | 不必用本 Skill |

## 1 一条命令跑完（不要手工拼步骤）

```bash
python scripts/run_case.py --input /input --output /app/output
```

它会：找 PDF → 分诊 → 版面 → 结构 → 表格 → 公式 → 锚点 → 按 `output_contract` 组装 `result.json`。

**为什么不让 Agent 自己分步调脚本**：单次运行预算 64 次模型请求 / 900 秒。
分步调要把中间 JSON 传进上下文，既烧 token 又容易传错文件；一条命令内部完成全部六步，
Agent 只需要读最后的汇总行。

打印出来的汇总长这样，先读这一段再决定下一步：

```json
{"status": "ok", "pages": 14, "counts": {"paragraphs": 144, "sections": 7, "tables": 2,
 "formulas": 12, "references": 19, "captions": 5}, "anchor_pass_rate": 0.9929,
 "coverage_missing": ["keywords"], "uncertainty": 2}
```

## 2 按 status 分流（这是最重要的一步）

| status | 含义 | Agent 接下来做什么 |
|---|---|---|
| `ok` | 结构完整、锚点 ≥ 0.90 | 直接用 `output_contract` 里的内容作答；答案里保留页码引用 |
| `partial` | 有页走 OCR / 有表未结构化 / 锚点 0.60–0.90 | **可以用**，但必须把 `uncertainty` 里的条目原样写进回答的"边界说明" |
| `needs_review` | 锚点 < 0.60，定位不可靠 | 不要拿它的页码/坐标当依据；改为"整体内容可用、逐句定位不可用"，并指向 `handover` |
| `blocked` | 打不开 / 没 PDF / 缺依赖 | 直接说明原因，**不要尝试自己从文件头猜内容** |

**不许把 `partial` 说成"完整解析"**。`handover.needs_human` 为真时，回答里要有一句
"以下部分需要人工确认：…"。

## 3 怎么读产物（按需要读，别整份塞进上下文）

| 想知道 | 读哪里 | 提示 |
|---|---|---|
| 全文/某节文字 | `document.md`（人读版）或 `result.json.output_contract` 里对应字段 | 正文段落前有 `[p.N]`，`¶` 表示与上段是同一段被排版切断 |
| 章节层级 | `document.json.sections`（树） | 每个节点有 `page`/`para`，可回查 |
| 表格数据 | `document.json.tables[].matrix` 或 `tables/t*.md` | **`status != "structured"` 的表不能用**，只能按 `region` 页码人工看 |
| 公式 | `formulas.md` + `formulas/*.png` | `text_scripted` 是还原上下标后的版本；符号核对看 PNG |
| 某段凭什么这么说 | `anchors.json` + 段落 `bbox` | 拿 `bbox` 回原 PDF 可逐字比对 |
| 这份文档哪里不可靠 | `audit.json.issues` + `result.json.uncertainty` | 逐条带页码/字段 |
| 版式判断依据 | `run_meta.json.layout_summary`、`document.json.pages[].layout` | `1col/2col/3col` 与栏缝坐标 |

## 4 回答问题的写法（关键：结论必须能回到位置）

回答里引用原文时，用统一格式，不要只给"文章说"：

```
…低能见度过程被定义为能见度 < 1000 m 且 ww 在 40–49（第 3 页，第 2.1 节）[p.3]
```

- 每个实质结论后面跟 `[p.N]`；跨页的给区间 `[p.3–4]`。
- 引用表格时写 `表 t1（第 3 页）`，并且只在 `status=structured` 时引用具体数值。
- 引用公式时写 `公式 f5（编号 3，第 4 页）`，符号以 `formulas/f5.png` 为准。
- **原文没写**就写"原文未报告"，不要用常识补；**读不出**就写"该处未能可靠提取（第 N 页）"。
- 中英混排时不要翻译`bbox`/页码这类定位信息。

## 5 失败了怎么交代（不是重试，是说明）

| 现象 | 回答里必须包含 |
|---|---|
| `status=blocked`，原因是有密码 | "该 PDF 有打开密码，无法解析；需要提供密码或解密后的版本" |
| `status=partial`，`needs_ocr_pages=[3,4]` | "第 3–4 页无文字层（扫描页），本次结果不含这两页正文；需要 OCR 才能继续" |
| 表格 `detected_unstructured` | "第 N 页的表检出了区域但未能还原行列，已记录区域坐标；该表数值未纳入结论" |
| 锚点 < 0.90 | "本次解析的定位可靠性偏低（通过率 X），引用页码前建议人工抽查" |
| `coverage` 有 `present=false` | 逐项说明是"原文确实没有"还是"未能识别"——两者必须区分 |

## 6 预算纪律

- 一次解析只调一次 `run_case.py`；不要为了"保险"重跑多遍（结果确定，重跑不改变结论）。
- 不要读 `document.json` 全文进上下文——它含每个字符的坐标，通常几百 KB。
  需要正文就取 `document.md` 或 `output_contract` 的字段；需要某节就按 `sections[].page` 定位。
- 已知需要 OCR 的页（`triage.needs_ocr_pages` 非空）时，不要反复重试文本提取。

## 7 交付前自检（30 秒）

1. `result.json` 里有 `case_id` 吗？`output_contract` 的字段是否都出现了（值可为 `null`，但字段要在）？
2. `status` 与 `uncertainty` 是否一致（`partial` 就必须有说明）？
3. 回答里每个结论都有 `[p.N]` 吗？
4. 有没有把 `detected_unstructured` 的表当成数据引用？
5. 有没有把"原文未报告"写成具体数值？
