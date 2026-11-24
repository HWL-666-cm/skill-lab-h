# 翻译工作流（Agent 执行顺序）

本文件是 `SKILL.md` 的执行细化。**顺序不可跳**：先结构、再术语、再翻译、再审计。

## 第 0 步：识别输入与边界

1. 读 `/input/case.json` 与 `task.md`，确认：源语言、目标语言、要译的范围（全文/指定段落区间）、
   是否要求双语对照、是否有指定术语表或样式规范。
2. 判断输入类型：
   - `pdf` → 走 `scripts/pdf_paragraphs.py`
   - `txt/md` → 按空行切段，人工补 pid
   - 已在对话里粘贴的片段 → 按语义段切，自建 pid
3. 输入里如果**没有可读文本层**（`pdf_paragraphs.py` 报 `low_text_page`），
   明确写"该页需 OCR，本轮未处理"，不要凭版式猜内容。

## 第 1 步：段落重建（脚本）

```bash
python3 scripts/pdf_paragraphs.py --pdf <原文> --out /app/work/paras.json
```

读输出的 `kinds` 分布，确认：
- `para` 是待译正文段；
- `meta`（期刊名/DOI/作者/收稿日期）、`formula`、`fragment`、`caption`、`reference` **不译**；
- `heading` 视任务要求决定是否译（通常译，术语也要一致）；
- `issues` 里的 `paragraph_continuation` 需要人工判断两段是否该合并。

**为什么先做这步**：不先固定段号，后面所有对齐与核验都失去基准。

## 第 2 步：术语表（脚本抽候选 → Agent 定译名 → 锁定）

```bash
python3 scripts/term_extract.py --paras /app/work/paras.json --out /app/work/glossary.json
```

然后 Agent 必须逐条审核 `concepts`，做三件事：

1. **收紧全称**：抽取可能把修饰语带进来（实测 `atmospheric high-resolution` 应只是 `high-resolution`）。
2. **剔除误收**：少数短语会带上动词（如 `choose Relative Humidity`），应删掉或改正。
3. **填 `target`**：给出唯一中文译名；把**容易混淆但必须避免的译法**写进 `forbidden`
   （例如 `lead time` → `预报时效`，禁用 `领先时间`）。
4. 全部填完把 `locked` 置 `true`。

**为什么必须锁定**：术语表的全部价值在于"被真正执行"。不锁定就是写在提示里的建议，
基础 Agent 的术语漂移正是这么来的。

## 第 3 步：分段翻译（Agent）

按 `para` 的 pid 顺序译，遵守：

- 每段译文对照原文，**保留**：数字、单位符号（`h/d/km/%/UTC` 等按原文写）、
  引用标记（`(Author, 2019)` / `Author et al. (2019)` / `[n]`）、公式与图表编号（`Eq. (1)`、`Fig. 2`、`Table 1`）。
- 术语必须用锁定译名，不得使用 `forbidden` 里的词。
- 限定强度不得升级：`may/suggest/indicate` 不能译成"证明/表明必然"；
  `not/unresolved/without` 等否定必须保留。
- 原文疑似有技术错误时，**按原文译**并在 `uncertainties` 里单列，不要悄悄"纠正"。
- 译不准或原文残缺时，译文中标注 `【待核】`，并写进不确定性清单，不要含糊带过。

译文格式两种都支持（审计脚本都能读）：

```json
{"paragraphs": [{"pid": 8, "target": "……"}]}
```

```markdown
[P8] ……
[P13] ……
```

## 第 4 步：审计（脚本）

```bash
python3 scripts/translation_audit.py \
  --paras /app/work/paras.json \
  --glossary /app/work/glossary.json \
  --translation /app/work/translation.json \
  --scope 8,13,16 \
  --out /app/work/audit.json
```

- **分块/局部翻译时必须给 `--scope`**，否则未译段会被正确报成漏段。
- 看 `verdict`：`ok` / `needs_review`（只有警告）/ `needs_revision`（有硬错误）。
- `error` 必须修；`warning` 逐条判断是真问题还是可接受（例如中文译名后接英文缩写导致的 unit_lost）。

## 第 5 步：修 → 重审（最多两轮）

只修有证据的问题，不为"读起来更好"反复重译。两轮后仍有争议，
保留问题并写进 `uncertainties`，标注需人工确认，不要无限打磨。

## 第 6 步：组装结果与产物

```bash
python3 scripts/make_result.py --case-id <case_id> --case-json /input/case.json \
  --paras /app/work/paras.json --glossary /app/work/glossary.json \
  --translation /app/work/translation.json --audit /app/work/audit.json \
  --out /app/output/result.json
```

产出 `result.json` + `bilingual.md`（段落级对照）+ `glossary.csv`（可继续维护）。
`status` 必须诚实：缺段或有硬错误就是 `partial`，不要写 `ok`。
