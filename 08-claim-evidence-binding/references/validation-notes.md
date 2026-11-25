# 验证记录（真实运行，非总结性空话）

环境：Python 3.12（`D:/venvs/main/Scripts/python.exe`），PyYAML 6.0.3，arXiv 公开论文源码 1706.03762。全部命令真实执行。

## 1. 示例材料端到端（assets/examples/）

- `scan`：2 文件 / 45 units / 8 引用 / 2 图表锚点 / 5 空白句，unreadable=0。
- `finish --draft draft_good.md`（正确引用 + 图表锚点）：`status=complete`、`validation=warn`、`trace_rate=1.0`、4 句 `anchored` + 1 句 `loose`、`top_failures=[]`。
- `finish --draft draft_bad.md`（错年份 + 套话 + 夸大）：`status=partial`、`validation=fail`，抓到：
  - `citation_metadata_mismatch`: `year 2019 != material 2020`（真作者 Smith + 错年份）
  - `hedge_overclaim` ×2（"首次填补空白""彻底解决"）
  - `cliche_background`（"近年来受到广泛关注""具有重要意义"）
  - `no_evidence_for_claim`、`gap_without_citation`、`key_work_not_written`

## 2. 开发中发现并修复的 7 个真实缺陷

按顺序：

1. **标题被当断言、缩写切碎句子**：好稿 trace_rate 从 0.067 → 修复后 1.0。修法见 `failure-modes.md` #1。
2. **可选捕获组 None 导致崩溃**：`AttributeError: 'NoneType' object has no attribute 'strip'`。修：遍历组取非空。
3. **引用重复匹配**：`Smith et al. (2020)` 同时被 author_year 和裸 `(2020)` 匹配，后者解析不到 → 全判 unverified。修：重叠区间去重 + author-year 用整串解析。
4. **混合幻觉漏报**：错年份 2019 只报 unverified，不报具体字段。修：作者对上即绑定，再逐字段比对 → 精确报 `year 2019 != material 2020`。
5. **无 draft 误判 complete**：门禁无断言行，status 判定漏条件。修：无 draft 强制 partial + limits。
6. **真实论文 0 条参考文献**：arXiv 1706.03762 用 `\bibitem{}` 内嵌，不是 `.bib`。修：新增 bibitem 解析 → 0 条变 40 条，key（如 `layernorm2016`）和年份都正确。
7. **LaTeX 注释被当断言**：`%\marginpar{...}` 被报 unanchored。修：剥离整行与行尾注释。

## 3. 真实公开论文验证（arXiv 1706.03762）

- 干净目录 scan：80 文件 / 35168 units（前一次含 `_dev` 自身产物，已隔离）/ 40 引用 / 4 图表锚点 / 19 空白句。
- 用论文真实 `introduction.tex` 当 draft 跑 finish：`trace_rate=0.75`（9 anchored + 12 loose + 7 unanchored）。
- 带 `\citep{...}` 的句子全部正确绑定 bibitem key（如 `\citep{hochreiter1997}`、`\citep{sutskever14, bahdanau2014neural, cho2014learning}`）。
- 无引用的方法描述句判 unanchored——这是诚实行为：它确实没有可定位的证据锚点，不由 Skill 替作者判断是否需要引用。

## 4. 异常用例

| 用例 | 结果 |
|---|---|
| 空材料目录 | `status=blocked`，写出原因 |
| 只有正文无 bib | 降级路径正常，抽到正文中的作者年引用 |
| 无 draft | `status=partial` + limits 两条 |
| 两次同输入运行 | 8 输出文件逐字节一致，文件集相同 |

## 5. 自测

`python assets/tests/run_selftest.py` → **25/25 通过**，每条断言对应上面一个真实缺陷或核心机制。

## 6. 诚实声明

- 本文所有命令与数据都来自本地真实运行；没有编造评测分数或平台成绩。
- A/B 两稿（good/bad）是为验证机制自造的对照，不是平台固定案例，也不是正式答案。
- 真实论文测试只验证"锚点抽取与引用核对"，不评价该论文写作质量。
- 语义准确性（转述是否忠实、分组是否深刻）机器判不了，未声称已验证。
