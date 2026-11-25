---
name: 04-nanopub-assertions
description: "把科研论文段落拆成可独立判断真假的 AIDA 断言，为每条断言绑定逐字原文证据、页码与字符位置，导出机器可读的 result.json 与四图 TriG，并用校验器拦住断言过宽、关系方向错、证据漂移和结构无效。用户说\"把这篇论文的结论拆成一条条能判断真假的断言\"\"每条结论都要能点回原文那句话\"\"帮我做成 nanopublication\"\"这段 discussion 拆一下，别整段塞一个字段里\"\"导出的结构要能直接被程序读\"时使用。"
version: 1.0.0
agent_created: true
---

# Nanopublication 断言抽取与证据绑定

把论文里的一段结论拆成若干条 AIDA 断言，每条绑定逐字原文证据和位置，导出可机器读取的结构，并用校验器把"过宽、方向错、证据漂移、结构无效"拦在交付之前。

## 何时用

- 要把论文结论做成可逐条引用、可逐条核对的断言集合。
- 要交付 nanopublication 或类似的四图知识单元。
- 需要说明"这条结论出自原文哪句话、哪一页"。
- 已有摘录，但整段塞在一个字段里、无法逐条判断真假。

不适用于：只需要摘要或翻译；只需要书目信息；要直接发布到线上网络（本 Skill 不签名、不发布）。

## 核心思路

判断与机械两件事分开做：

- **判断**（拆成几条、改写成什么句子、主体宾语是谁、关系是哪个）由模型完成，脚本不猜。
- **机械**（句子在不在原文、页码对不对、主语在不在证据里、签名合不合、结构完不完整）全部由脚本判定，模型不能自证。

拆断言的产出必须过校验器才算完成。校验器不通过时，按 `repair.json` 的定位信息重写，最多两轮；两轮仍不过的断言标 `failed`，保留在结果里不删除。

## 三步流程

### 第一步：解析与候选

```bash
python scripts/run_case.py --case /input/case.json \
  --lexicon assets/relation-lexicon.json --out /app/output --stage prepare
```

产出 `parsed.json`（段落、句子、字符跨度、全篇规范化文本）和 `candidates.json`（按关系触发词和结论信号排序的候选句，含 `sid`、页码、字符跨度、AIDA 预检结果）。

`/input/case.json` 里的 PDF 路径会被自动发现。找不到 PDF、PDF 缺失、无文本引擎时返回 `status=blocked` 并写明原因，不生成空结果。

### 第二步：写 draft

从 `candidates.json` 里挑句子，按下面的结构写 `draft.json`。一条断言一个对象，不许把一段话放进一个 `text`。

```json
{
  "case_id": "ral2016",
  "source": {"doi": "10.1109/LRA.2016.2530866", "title": "...", "year": 2016},
  "assertions": [
    {
      "id": "A01",
      "text": "Given a fixed uncertainty threshold, the estimation performance is robust to changes in the bearing noise.",
      "subject": {"label": "estimation performance", "type": "MEASURE"},
      "predicate": "ASSOCIATED_WITH",
      "object": {"label": "bearing noise", "type": "MEASURE"},
      "qualifiers": {"scope": ["Given a fixed uncertainty threshold"], "polarity": null, "population": null},
      "evidence": {"quote": "Given a ﬁxed U⋆, the estimation performance is robust to the change in the bearing noise.", "page": 8, "sentence_id": "P181S02"},
      "provenance": {"source": "RAL2016"},
      "confidence_basis": "the paper states robustness only under a fixed threshold, so the scope is kept",
      "relation_type": "direct",
      "relation_evidence": {"trigger": "robust to"}
    }
  ],
  "uncertainty": ["该论文 PDF 无 DOI，来源只用文件名。"]
}
```

字段含义与取值见 `references/output-contract.md`；关系与实体类型只能取 `assets/relation-lexicon.json` 里的值。

写 draft 时守四条：

1. `evidence.quote` 从 `parsed.json` 或 `candidates.json` 里**整句复制**，不改写、不缩写、不合并。
2. `text` 里的主体和宾语都要在 `quote` 里出现。
3. `relation_evidence.trigger` 必须是 `quote` 里真实出现的那个动词或介词。
4. `text` 不能以 This/These/It/该/其 开头，不能含 we/our/本文/我们，不能含 may/might/suggest/可能/提示。

### 第三步：校验与导出

```bash
python scripts/run_case.py --case /input/case.json \
  --lexicon assets/relation-lexicon.json --out /app/output --stage finish --draft draft.json
```

产出 `result.json`、`assertions.trig`、`validation.json`、`repair.json`。退出码 0 表示全部通过。

校验不通过时读 `repair.json`：每条失败给出 `codes`、`page`、`char_span`、`sentence_id` 和改法。按改法重写 draft 后再跑一次 finish。

无模型可用时用 `--stage auto` 生成候选草稿，产出必须标明是规则候选，不可直接当交付。

## AIDA 四判据

| 判据 | 要求 | 违反的典型写法 |
|---|---|---|
| Atomic | 一句话只讲一个可判断真假的命题 | 分号连接两个命题；`and` 后接第二个谓语 |
| Independent | 脱离上下文仍能读懂 | `This suggests…`、`These two factors…`、`我们…` |
| Declarative | 完整陈述句，以句号结尾 | 疑问句、感叹句、短语片段 |
| Absolute | 只写断言核心，剥离置信度与发现过程 | `probably`、`may`、`suggest`、`we present`、`results indicate` |

**最容易做错的一条：Absolute 剥的是什么。** 三段要分开：

| 层 | 例子 | 处理 |
|---|---|---|
| 真值不确定性 | probably, may, suggest, 可能, 提示 | 剥离，写进 `confidence_basis` |
| 发现过程 | we present, this study, results indicate, 本文, 结果表明 | 剥离，写进 `provenance` |
| 断言适用范围 | given a fixed U⋆, in mice, at 20 °C, for adults, 在…条件下 | **保留**，写进 `qualifiers.scope` |

剥离适用范围会让断言变宽，是本题最常见的扣分点。校验器会拿证据所在整句去比对，即使 `quote` 被截短也能发现范围丢失。

细则、改写对照和真实误抽案例见 `references/aida-rules.md`。

## 校验器查什么

| 检查 | 判据 | 失败代码 |
|---|---|---|
| 证据逐字命中 | `quote` 规范化后能在全篇文本中找到 | `evidence_drift` |
| 证据长度 | 5–500 字符 | `quote_length` |
| 页码 | 声明页码 = 实际所在页 | `page_mismatch` |
| 主体/宾语 | 两者都在 `quote` 里出现 | `subject_not_in_evidence` / `object_not_in_evidence` |
| 关系 | 在受控词表内 | `unknown_predicate` |
| 方向 | 类型签名匹配；主宾互换能检出 | `direction_error` |
| 类型 | 主语宾语类型已标注 | `type_unresolved` |
| 触发词 | 声明的 trigger 真在 `quote` 里 | `trigger_not_in_evidence` / `no_trigger` |
| 范围与极性 | 证据有 deficiency / increase / in mice 而断言丢了 | `scope_dropped` / `polarity_dropped` |
| 数字 | 断言里的数字在证据里出现 | `number_mismatch` |
| 整段粘贴 | 断言与某段落重合度 ≥85% 且超 120 字符 | `paragraph_pasted` |
| 结构 | 每个 nanopub 四图齐全、assertion 与 provenance 非空、head 三链接 | `empty_assertion` 等 |

## 导出了什么

`result.json`：`case_id`、`status`、`assertions[]`（含 AIDA 判定、主体关系、证据、来源、置信依据、状态、问题）、`sources`、`validation`、`uncertainty`。

`assertions.trig`：一条断言一个 nanopublication，四图结构，只使用官方词表（`np:`、`npx:`、`hycl:`、`cito:`、`prov:`）。AIDA 句用 `http://purl.org/aida/` 加空格换 `+`，证据用 `cito:hasQuotedText`。草稿 IRI 是内容哈希，不是 trusty URI，未签名，不可直接发布。

### 平台输出契约（`output_contract`）

运行约定要求 `result.json` 带上案例声明的**全部 `output_contract` 字段**。这个契约在 `/input/case.json` 里，形态不固定，所以 `scripts/contract.py` 的做法是"输入宽松、输出兜底"：

1. **读名字**：接受 `{"fields": {...}}` / `{"required": [...]}` 包装、字段描述字典、纯名字列表，或能解析成上述任一形态的 JSON 字符串。
2. **能对上就复制**：声明的名字命中同义词表（如 `claims`/`statements` → `assertions`，`source_metadata` → `sources`）时，把规范字段的值原样复制过去，平台用哪种拼写都能读。
3. **能算就派生**：顶层声明 `evidence` 一类字段时，从各条断言的 `evidence` 聚合出顶层证据索引（`assertion_id`、`quote`、`page`、`char_span`、`sentence_id`），值来自源头，不另编。
4. **对不上就留空并说清**：无法映射的名字写成 `null`，同时记进 `uncertainty` 与 `contract_report.missing` —— 让缺口可见，绝不猜内容去填。

每次带契约的运行，`result.json` 多一个 `contract_report`：`declared`（声明了哪些）、`native`（原生就有）、`aliased`（复制自哪个字段）、`derived`（派生自哪个字段）、`missing`（没做出来的）。只有顶层字段名会被重映射，断言对象内部保持 `references/output-contract.md` 的规范键名。

## 最小示例

`assets/examples/case.json` 是示例输入，`pdf` 处填论文路径。对这一篇跑完三步，得到 `result.json`、`assertions.trig`、`validation.json` 三份产物。

产物示例 `assets/examples/result.json` 与 `assets/examples/validation.json` 取自一篇公开论文的两条断言，用于说明字段结构与四图形态，是接口示例，不是平台固定案例的正式结果，顶层都带 `example: true` 和 `example_note`。为让提交包只保留白名单内后缀，`assertions.trig` 不随包附带；它由 `scripts/emit.py` 在运行时写出（头部带 `# EXAMPLE-NOT-A-OFFICIAL-CASE` 注释），跑一遍示例即可生成。

## 运行环境

- Python 3.10+，脚本只用标准库。
- 读 PDF 需要一个引擎：优先 PyMuPDF（`pip install pymupdf`），否则 `pdftotext`（poppler-utils）。两者都没有时返回 `status=blocked`。
- 不联网、不写 PDF、不修改输入文件。

## 安全边界

- 写入范围限于 `--out` 指定的目录。不修改输入 PDF，不写用户目录。
- 不做任何网络请求；AIDA 句 IRI 的百分号编码在本地完成。
- 调用外部进程只有一处：`pdf_text.py` 在缺少 PyMuPDF 时执行 `pdftotext`。命令与参数以列表传入，不经 shell，路径来自 `--case` 声明的 PDF。
- `shutil.rmtree` 只作用于 `tempfile.mkdtemp` 创建的临时目录，并在 `finally` 中执行。
- 不签名、不发布、不读取环境变量或任何凭据。

## 限制

- 只处理有文本层的 PDF。扫描页返回 `ocr_required`，不猜内容。
- 证据只取正文文字，不支持表格单元格、图内标注、公式编号作为证据。
- `quote` 必须在原文连续命中；跨页或跨栏断开的句子需要分两条断言。
- 关系词表以科研通用关系为主，主题高度专门的论文需要按 `references/relation-lexicon.md` 扩展。
- 中文论文的指代与置信词判定弱于英文，中文案例需人工复核 `absolute` 判据。
- 不签名、不发布、不生成密钥。

## 自查

交付前逐条确认：

- `validation.json` 的 `status` 是 `pass`，或失败项已在 `uncertainty` 里说明。
- 每条断言都有 `evidence.quote`，且 `page` 与 `sentence_id` 非空。
- 没有任何 `text` 与原文段落重合超过 85%。
- 带条件的结论，`qualifiers.scope` 非空且出现在 `text` 里。
- `assertions.trig` 的 nanopub 数量等于断言数量。
- `result.json` 的 `status` 与 `validation.status` 一致。
- 案例带 `output_contract` 时，`contract_report.missing` 为空；若非空，缺口已写进 `uncertainty`。

## 异常处置

| 情况 | 做法 |
|---|---|
| 找不到 PDF 或无文本引擎 | 返回 `status=blocked`，写明缺什么，不产出空结果 |
| 扫描页无文本层 | 该页标 `ocr_required`，不生成断言 |
| 断言找不到支撑片段 | 标 `failed`，`confidence_basis` 写"无直接证据"，不删条目 |
| 断言与证据冲突 | 以证据为准改写断言；改不动就标 `failed` |
| 字段缺失 | 只补有证据的字段，其余留空并在 `uncertainty` 说明 |
| 校验两轮仍不过 | 保留条目、标 `failed`、写明原因，交付其余部分 |
