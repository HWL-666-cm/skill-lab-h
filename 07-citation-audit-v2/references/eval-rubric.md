# 评分点对照与交付自查表

## 一、评分点 → 本 Skill 的对应机制

| 评分维度 | 分值 | 本 Skill 的机制 |
|---|---|---|
| 实际效果·任务完成度 | 15 | 覆盖五类动作 + 一个可编辑产物：引用定位（claim_recall）、编号重排、去重、格式转换（render）、来源核验；`task_coverage` 六键逐项标 done/pending |
| 实际效果·结果正确性 | 15 | 所有判定带 `evidence`（行号/字段值/编号）；每条引用落到真实条目，`match_basis`（编号/键）+ `confidence` |
| 实际效果·结果完整性 | 5 | 逐条 `source_map`（句/行号/条目/依据/置信度）+ `fact_map`；遗漏项列进 limitations |
| 实际效果·可核验性 | 5 | 原稿快照、文献库快照、逐条 `source_map`、`change_log`、审计报告五件套 |
| 使用增益·质量 | 15 | A/B 对照：同稿件同库，裸 Agent 10 处返工 / 本 Skill 1 处警告，机器可复算（`references/evidence.md`） |
| 使用增益·效率 | 5 | 脚本一次跑完双向核验 + 重排 + 去重 + 渲染，无需逐条人眼对照 |
| 使用增益·可验证性 | 5 | 审计 JSON + 自测 18 条 + 确定性哈希（evidence-data 附 sha256） |
| 创新增益 | 15 | 双向闭包核验、按首次出现重排且排除悬空号、强弱分级去重且冲突不合并、论断句规则召回、GB/T 7714/APA 渲染 |
| 可靠体验 | 10 | 三种库形态、异常输入不崩、NFKC 规范化、警告与硬错误分级、64 请求预算账 |
| 生态贡献 | 10 | 字段字典、判据说明、18 条自测、示例、A/B 证据、限制清单 |

## 二、交付前自查（每条都要真的做）

- [ ] `python3 scripts/run_selftest.py` 输出 `18/18 passed`
- [ ] 审计报告的 `inputs.citation_style` 与实际稿件一致
- [ ] `numbering.proposed` 不含悬空引用编号
- [ ] `duplicate_decisions` 里没有任何 `merge` 是建立在冲突元数据上的
- [ ] 修订稿与原文都能在 `/app/output` 找到，改动逐条进 `change_log`
- [ ] `result.json` 的 `case_id` 来自输入，不自己编
- [ ] `status` 只依据修订稿复核结果；原稿问题在 `issues_found_in_input`
- [ ] 所有 warning 都出现在 `uncertainties`，没有被悄悄丢弃
- [ ] `bibliography` 字段与输入文献库条目数一致（合并/删除时说明原因）
- [ ] `source_map` 逐条可回溯（每条引用有句子/行号/条目 key/匹配依据/confidence）
- [ ] 提交目录根有 `GITHUB_URL.txt`，outputs 目录只有说明、无预制答案

## 三、常见失败模式（评审时最容易扣分的做法）

1. 把引用从段末挪走就算"挂得对"，但正文论断本身没有来源支撑。
2. 用 `\cite{}` 的稿子去检查顺序编码制编号——两者不同制式，不要混判。
3. 同 DOI 两条直接合并，丢掉了其中一条独有的卷期页字段。
4. 缺字段时凭常识补一个"看起来对"的年份或卷号。
5. 说"已通过 DOI 官网核验"——Skill 离线，没做就是没做。
6. `status` 统计原稿错误数，修订稿已修干净仍报 partial——这是 v1 的 bug，v2 已修。
7. 把"解析文献库"当成"格式转换"——解析是 BibTeX/RIS → 内部字段，转换是内部字段 → GB/T 7714/APA 渲染，v2 用 `render.py` 补上转换一侧。
