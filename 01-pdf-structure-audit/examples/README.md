# 最小调用示例

> **这是示例，不是正式案例结果。** 输入是用 `tests/make_cases.py` 现场合成的 3 页双栏 PDF
> （内容为占位文字，不是任何真实论文），case_id 故意写成 `EXAMPLE-NOT-A-OFFICIAL-CASE`。
> 这里放它的目的只有一个：让人一眼看清"输入长什么样、命令怎么写、输出有哪些文件"。

## 1 输入

```
examples/in/
├── case.json        # case_id + 文件清单 + output_contract（字段名由平台给，这里照抄一份）
└── two_column.pdf   # 3 页、通栏标题+摘要、正文两栏（合成件）
```

`case.json` 里的 `output_contract` 是**字段名清单**，本 Skill 会按这些名字逐个填：

```json
{
 "case_id": "EXAMPLE-NOT-A-OFFICIAL-CASE",
 "files": ["two_column.pdf"],
 "output_contract": {
  "reading_result": "按原版面顺序的正文（Markdown）",
  "sections": "章节树",
  "tables": "表格的行列与单元格",
  "evidence": "页码与区块定位",
  "uncertainty": "未报告与不确定项"
 }
}
```

## 2 调用

```bash
python scripts/run_case.py --input examples/in --output examples/sample_output
```

（等价写法：`--pdf examples/in/two_column.pdf --case examples/in/case.json`。全部参数见 `--help`。）

## 3 输出

```
examples/sample_output/
├── result.json        # 平台契约件：case_id / status / output_contract / sources / uncertainty / changes
├── document.json      # 全量机读结构（段落带 bbox、章节树、表格 cells、公式…）
├── document.md        # 人读版：标题→摘要→结构目录→正文([p.N])→表格→公式→参考文献→未确定项
├── tables/            # 每张表一份 Markdown（本示例无表）
├── formulas.md        # 公式清单（本示例无公式）
├── anchors.json       # 逐单元锚点核验
├── audit.json         # 覆盖清单 + 锚点统计 + 问题列表 + 分诊
└── run_meta.json      # 页数/耗时/版式分布/锚点通过率/覆盖缺失
```

命令行会先打一行汇总，**先读这一行**决定下一步（`ok` 可直接用，`partial` 必须把
`uncertainty` 带进结论，`needs_review` 不能拿它的页码当依据）：

```json
{"status": "ok", "pages": 3, "counts": {"paragraphs": 24, "sections": 3, "tables": 0,
 "formulas": 0, "references": 0, "captions": 0}, "anchor_pass_rate": 1.0,
 "coverage_missing": ["tables", "figures", "formulas", "references", "keywords", "footnotes"]}
```

`coverage_missing` 里那些项之所以缺失，是因为这份合成件**本来就没有**表格/公式/参考文献——
这正是"缺失 ≠ 没识别出来"的例子：`uncertainty` 里会逐条写明"原文可能确实没有，或未能识别，需人工确认"。

## 4 示意输出（节选，均为示例）

`document.md` 开头：

```markdown
# A Two Column Paper About Visibility Nowcasting

- 源文件：`two_column.pdf`（3 页）
- 作者：C. Writer, D. Writer
- 版式：2col 3 页
- 解析耗时：0.11s；锚点通过率：1.0

> 段落前的 `[p.N]` 是**物理页码**，用于回查原文；`¶` 表示该段与上一段是同一段被排版切断。

## 结构目录
- 1 Introduction（第 1 页）
- 2 Results（第 2 页）
- 3 Results（第 3 页）

## 正文
### 1 Introduction
[p.1] Visibility forecasting at airports is a hard problem because low-visibility events are rare, …
```

`result.json` 关键字段：

```json
{
 "case_id": "EXAMPLE-NOT-A-OFFICIAL-CASE",
 "status": "ok",
 "document": {"title": "A Two Column Paper About Visibility Nowcasting",
              "authors": "C. Writer, D. Writer", "sections": ["…"], "tables": []},
 "body_paragraphs": [{"id": "p1para6", "page": 1, "section": "sec1",
                      "bbox": [51.7, 306.5, 290.7, 364.9],
                      "text": "The predictor set matters more than the learning algorithm …",
                      "continued_from": null}],
 "evidence": {"anchors": {"total_units": 30, "passed": 30, "failed": 0, "pass_rate": 1.0},
              "markdown_file": "document.md", "tables_dir": "tables/"},
 "coverage": [{"key": "title", "label": "标题", "present": true, "count": 1}, "…"],
 "sources": [{"kind": "pdf", "file": "two_column.pdf", "pages": 3}, "…"],
 "uncertainty": ["覆盖项缺失：单位（affiliations）——原文可能确实没有，或未能识别，需人工确认",
                 "覆盖项缺失：关键词（keywords）——原文可能确实没有，或未能识别，需人工确认"],
 "changes": [{"type": "header_footer_isolated", "detail": "…隔离页眉页脚 0 处，未删除，保留在 paras 中可查"},
             {"type": "reading_order", "detail": "按栏缝 + 通栏分区重排：…"}, "…"]
}
```

## 5 换成你自己的 PDF

```bash
python scripts/run_case.py --pdf /path/to/paper.pdf --output out/
```

没有 `case.json` 也能跑：`case_id` 取文件名，`output_contract` 给一份自描述结构
（`document` / `body_paragraphs` / `evidence` / `coverage`）。有 `case.json` 就严格按它的字段名填。
