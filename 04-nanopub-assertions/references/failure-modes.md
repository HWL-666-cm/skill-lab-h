# 五类失败模式与对应检查

下面每类都配真实公开案例，并指明是哪个检查代码拦它。写 draft 前读一遍，可以避开大部分返工。

## 一、断言过宽：主体限定被吃掉

真实误抽案例（食品与生物医学知识图谱的公开分析）：

| 抽出来的 | 原文实际说的 | 错在哪 |
|---|---|---|
| Vitamin D causes 某疾病 | Vitamin D **deficiency** 导致该病 | 丢了 deficiency，意思反了 |
| Carbohydrates treat 心肌病 | 建议**低碳水饮食**治疗心肌病 | 极性反转：减少摄入才有效 |
| Fatty acid causes 内皮功能障碍 | 脂肪酸**升高**与内皮功能障碍共同促成脓毒症 | 丢 increased，还把共现写成因果 |

共同根因是把长名词短语截成中心词，把 deficiency / increased / reduced 这类修饰当初噪音扔了。

**对应检查**：`polarity_dropped`、`scope_dropped`、`subject_not_in_evidence`。

**处理**：主体写完整名词短语，不截断到中心词；证据里有极性词时，断言必须带同族极性词，或写进 `qualifiers.polarity`。

## 二、关系方向错：主宾互换

关系抽取里的 role reversal：实体认对了、关系类型也认对了，就是主宾颠倒。在断言上，"A 抑制 B"和"B 抑制 A"是两个相反结论。

公开的临床知识图谱工作用一串类型签名规则纠正这类错误，例如：

```
Gene    -> CAUSED_BY_MUTATION -> Disease   应反转为  Disease -> CAUSED_BY_MUTATION -> Gene
Drug    -> TREATED_WITH       -> Disease   应反转为  Disease -> TREATED_WITH -> Drug
Procedure -> TREATED_WITH     -> Disease   应重定型为  Disease -> MONITORED_WITH -> Procedure
```

最后一条是另一类错误：诊断手段被当成治疗手段。方向对，但关系类型错。

**对应检查**：`direction_error`、`type_mismatch`、`unknown_predicate`。

**处理**：见 `references/relation-lexicon.md` 的"方向错的三种处理"，依次试反转、换逆关系、降级为 ASSOCIATED_WITH。

## 三、共现当因果

真实案例：`fatty acid causes 内皮功能障碍`，原文只是说脂肪酸升高与内皮功能障碍共同促成脓毒症，两者同句出现而已。

公开的关系抽取错误分析把这类归为 contextual co-occurrence：实体在同一句共现，句子里的关系动词实际作用于别的实体。

另外两类同源错误：surface trigger ambiguity（有因果词但作用对象是另一个实体）、long-range compositional（跨小句的长程关系推错）。

**对应检查**：`no_trigger`、`trigger_not_in_evidence`。

**处理**：断言必须能指认证据句里的关系动词，且该动词的句法主语、宾语与断言一致。指认不出来就降级为 `ASSOCIATED_WITH` + `relation_type: inferred`，`confidence_basis` 写"仅共现"。

## 四、不确定性混进句子

`probably`、`may`、`suggest`、`we present`、`results indicate`、`可能`、`提示` 都不是断言的一部分。它们分别属于"我对真值的置信"和"我是怎么发现的"，应写进 `confidence_basis` 与 `provenance`。

**但不要连适用范围一起删。** `in mice`、`at 20 °C`、`given a fixed threshold` 是断言成立的条件，删掉就变成过宽断言。分界线见 `references/aida-rules.md`。

**对应检查**：`aida_fail`（内部再分 `hedge_*`、`discovery_process`、`past_tense`）。

**处理**：删置信词与发现过程，把信息搬到 `confidence_basis` / `provenance`；保留范围词并在 `qualifiers.scope` 登记。

## 五、结构无效与来源链断

公开的结构诊断表列了四类症状：

| 症状 | 根因 | 修法 |
|---|---|---|
| missing assertion | assertion 图缺失或为空 | 补三元组 |
| head does not reference part | head 没链到三个图 | 三个都要链 |
| not a valid nanopub | 图没有命名 | 每个 `{ }` 前加图 URI |
| empty provenance | 没有 `prov:` 语句 | 写明来源 |

最阴的是**空 assertion 图**：TriG 语法完全合法，但不是一个合法 nanopublication。只做语法解析发现不了，必须单独查"三图非空 + head 三链接"。

**对应检查**：`empty_assertion`、`empty_provenance`、`head_link_missing`、`missing_graph`。

**处理**：`validate.py` 自带结构自检，不需要 rdflib。要更严格的语法确认，可在有 rdflib 的环境里额外解析一次。

## 六、整段粘贴

把一段话塞进一个断言字段是最省事也最没价值的做法，题面明确点名反对。

**对应检查**：`paragraph_pasted`（与某段落规范化后重合 ≥85% 且长度 >120 字符）；同时 `aida_fail` 会因 `multi_sentence` 报错。

**处理**：按命题边界拆开，一条一个可判断真假的陈述。

## 七、证据漂移

`quote` 声称来自论文，实际是模型复述的版本。这是最难被人工发现、也最伤"可核验性"的错误，因为读起来完全通顺。

**对应检查**：`evidence_drift`（规范化后在全篇文本里找不到）。

**处理**：从 `parsed.json` 或 `candidates.json` 整句复制，不手打、不缩写、不合并。注意 PDF 里的连字（ﬁ ﬂ）、软连字符、弯引号会被规范化展开，所以 `fixed` 能匹配原文的 `ﬁxed`，但词序或词形一改就匹配不上。

## 判失败的轻重

- `failed`：证据对不上、主体不在证据里、方向错、结构无效、整段粘贴。这些会让结论失效，必须修。
- `warning`：类型未定、范围丢失、极性丢失、数字不一致。结论方向没错但可能变宽，应修，来不及修要在 `uncertainty` 里写明。

修不动时保留条目并标 `failed`，不要为了好看删掉它。删掉会让"覆盖了多少结论"这个指标失真。
