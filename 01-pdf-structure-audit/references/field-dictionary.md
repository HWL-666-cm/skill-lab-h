# 字段字典

`document.json` 的每一个字段：含义、取值、证据要求。写这份字典的目的是让下游（或评审）
不用读代码就知道"这个值凭什么可信"。

通用约定：

- **`bbox`** 一律 `[x0, y0, x1, y1]`，单位 pt，原点在页面左上角，坐标系是 PDF 的页面坐标。
  拿它去 `page.get_text("words", clip=bbox)` 能回抽原文——第六步的锚点核验就是这么做的。
- **`page`** 是**物理页码**（PDF 第几页），不是印刷页码。印刷页码单独放在 `page_label`。
- **`id`** 全局唯一、可引用：`p13para11` = 第 13 页第 11 段；`t1` = 第 1 张表；`f3` = 第 3 个公式。
- 任何"没识别出来"都用 `null` + 在 `uncertainty` 写原因，**不用空字符串假装成功**。

---

## 顶层

| 字段 | 含义 | 取值 |
|---|---|---|
| `source` | PDF 路径 | 字符串 |
| `page_count` | 页数 | 整数 |
| `status` | 文档级状态 | `ok` / `blocked`（`blocked` 时无其它字段） |
| `triage` | 分诊结果 | 见下 |
| `pages` | 每页的版式与全部段落 | 列表，见下 |
| `issues` | 解析过程中记下的可疑点 | 列表 `{type, page, para, detail}` |
| `body_font_size` | 推定的正文字号（所有"大/小"判断的基准） | 浮点，按字符数加权的众数 |
| `sections` | 章节树 | 列表，见下 |
| `front_matter` | 标题/作者/单位/摘要/关键词 | 见下 |
| `tables` | 表格 | 列表，见下 |
| `formulas` | 公式 | 列表，见下 |
| `body_paragraphs` | 正文段落流（阅读顺序） | 列表，见下 |
| `captions` | 所有题注（图+表） | `{page, para, kind, number, text, bbox}` |
| `figures` | 图片块与题注的配对 | `{page, para, kind, number, text, bbox, region, method}` |
| `references` | 参考文献条目 | `{page, para, text, bbox, doi, year}` |
| `footnotes` | 脚注（标位置，不硬拼进正文） | `{page, para, text}` |
| `anchors` | 锚点核验汇总 | `{total_units, passed, failed, pass_rate, by_kind}` |
| `meta` | 运行元信息（同 `run_meta.json`） | 见 `run_meta.json` |

## `triage`（分诊）

| 字段 | 含义 |
|---|---|
| `pages[]` | 每页 `{page, route, chars, garbled_ratio, images, drawings, fonts_total, fonts_missing_tounicode, rotation, flags, reasons}` |
| `route_counts` | `{"text": n, "ocr": m}` |
| `password_required` / `opened` | 是否有打开密码 / 空密码是否成功 |
| `needs_ocr_pages` | 无可用文字层、需要 OCR 的页号列表——**这是 partial 的直接原因** |
| `low_text_pages` | 字数偏少但仍有文字层的页（可能是整页图或纯公式页） |

`route=ocr` 的四种触发（`reasons` 里会写是哪种）：

| reason | 含义 | 为什么不能硬走文本层 |
|---|---|---|
| `no_text_layer_with_images` | 一个字都没有、但有整页图 | 扫描件，文本层不存在 |
| `very_little_text_but_many_drawings` | 几乎没字、矢量图元很多 | 文字被转曲（轮廓化），只有形状没有字符 |
| `garbled_ratio=…` | 私用区/替换符/`(cid:N)` 占比 > 3% | ToUnicode 坏了，抽出来是乱码，看着像字其实无意义 |
| `low_text`（flag） | 字数 < 120 但有文字 | 仍走文本，只是记一条警告 |

## `pages[]`

| 字段 | 含义 |
|---|---|
| `no` / `width` / `height` / `rotation` | 页号、页面尺寸、旋转角 |
| `layout.mode` | `1col` / `2col` / `3col` / `unknown`（OCR 页） |
| `layout.splits` | 栏缝 x 坐标列表（1 栏为空） |
| `layout.gutter` | 每道栏缝的 `[左栏右边缘中位数, 右栏左边缘]` |
| `layout.content` | 正文区 `[x0,y0,x1,y1]` |
| `paras` | 该页**全部**段落（含页眉、题注、表单元格——它们靠 `role` 区分，不删除） |
| `route` | `text` / `ocr` |
| `line_count` | 该页行数（切段前的原始行） |

## `pages[].paras[]` 与 `body_paragraphs[]`（同构）

| 字段 | 含义 | 证据 |
|---|---|---|
| `id` | `p{页}para{k}` | — |
| `page` | 物理页码 | — |
| `zone` / `col` | 所属通栏带 / 栏序（阅读顺序的依据） | 由 `layout.splits` 推出 |
| `block` | 来源文本块 id | PyMuPDF block |
| `bbox` | 段落外接框 | 可直接回抽原文 |
| `lines` | 构成该段的行 id 列表 | 逐行可查 |
| `text` | 段落文本（已归一化 NBSP/连字/软连字符） | 与 `text_raw` 逐字对照 |
| `text_raw` | 未归一化原文 | 逐字比对的基准 |
| `size` / `bold` / `math` | 主字号 / 是否含粗体 / 是否含数学字形 | 用于标题与公式判定 |
| `role` | 见下表 | 判据见 `layout-rules.md` |
| `section` | 所属章节 id | 与 `sections[].id` 对应 |
| `text_joined` | 若与上一段是同一段被排版切断，这里是拼接后的完整文本（`¶`） | 两条独立记录都保留，页码各自可核 |

`role` 取值：`title` / `title_continuation` / `authors` / `affiliation` / `meta` / `abstract` /
`keywords` / `heading` / `body` / `caption` / `table_cell` / `formula` / `reference` /
`footnote` / `header` / `footer` / `page_number` / `fragment` / `empty`。

> `fragment` 是"长度 < 3 或纯数字/纯符号"的碎片（如正文里的上标 `2`）。它不删，标出来，
> 因为删了就说不清"这里原来有东西"。

## `sections[]`（章节树）

| 字段 | 含义 |
|---|---|
| `id` | `sec{k}` |
| `title` | 完整标题文本（含编号，如 `2.1 Forecast variable`） |
| `level` | 层级（1 起）；`null` 表示"是标题但没编号，层级按字号排名推定" |
| `number` | 编号字符串（`2.1`），无编号为 `null` |
| `page` / `para` | 标题所在页码与段落 id |
| `children` | 子章节（递归） |

## `front_matter`

| 字段 | 含义 | 缺失时 |
|---|---|---|
| `title` | 标题（首页同字号连续块合并后的结果，跨行已拼接） | `null` + `uncertainty` 说明"首页无大于正文的标题块" |
| `authors` | 作者行原文 | `null` + 说明"可能只有一人或与单位同段" |
| `affiliations` | 单位行列表 | `[]` |
| `abstract` | 摘要正文（去掉 `Abstract.` 标签本身） | `null` + 说明 |
| `keywords` | 关键词 | `null` |
| `method` | 每项用了哪条判据（`merged_title_block_by_font_size` / `explicit_label` / `inferred_leading_block` …） | — |
| `*_para` | 对应段落的 id，便于回查 | — |
| `uncertainty` | 前言区的不确定项 | — |

## `tables[]`

| 字段 | 含义 |
|---|---|
| `id` / `page` / `pages` | 表 id、起始页、涉及页（跨页续表会有多页） |
| `caption` / `caption_number` / `caption_para` | 题注原文、编号、题注段落 id |
| `method` | `word_grid`（自建词坐标网格）/ `find_tables_lines`（有线表格） |
| `region` | 检测到的表格区域 bbox（**未经裁剪**，用于复核"是不是整片区域都算进来了"） |
| `bbox` | 实际单元格覆盖的 bbox |
| `bands` | 列带 `[[x0,x1], …]`，即每一列的水平范围 |
| `rows` / `cols` | 行数 / 列数 |
| `row_bboxes` | 每行的 `[y0,y1]` |
| `matrix` | 二维文本矩阵（`matrix[行][列]`），合并单元格只在左上角有值 |
| `cells` | `{"行,列": {row, col, colspan, bbox, text}}`，带单元格级 bbox |
| `header_rows` | 表头行数（`0` 表示首行就是数据，输出 Markdown 时留空表头） |
| `status` | `structured`（通过校验）/ `detected_unstructured`（只标了区域） |
| `reject_reasons` | 未通过校验的具体原因（列数、非空率、像散文…） |
| `continued` | 是否由跨页续表合并而来 |

**`status=detected_unstructured` 的表不能当数据用**：它的 `matrix` 可能缺列或串行，
正确用法是"按 `region` 页码人工/OCR 复核"。

## `formulas[]`

| 字段 | 含义 |
|---|---|
| `id` / `page` / `bbox` | 公式 id、页码、区域 |
| `number` | 右缘编号（`(3)` → `3`），无编号为 `null` |
| `text_raw` | 原始提取串（保真，可能是乱序的） |
| `text_scripted` | 还原上下标后的串（`x^{2}`、`w_{i}`），用于继续处理 |
| `has_superscript` / `has_subscript` | 是否检出上下标 |
| `math_fonts` | 命中的数学字体名（CM*、Symbol、STIX…） |
| `line_count` | 该公式由几行拼成 |
| `status` | `ok` / `unnumbered`（无编号但有主体）/ `number_only`（只定位到编号） |
| `image` | 区域截图相对路径（`formulas/f3.png`），供人工核对符号 |

## `figures[]`

| 字段 | 含义 |
|---|---|
| `page` / `para` / `kind` / `number` / `text` | 题注所在页、段落 id、`figure`/`table`、编号、题注原文 |
| `bbox` | 题注 bbox |
| `region` | 推定属于该图的图像区域 bbox（题注上方图片块；退化为"上一段正文底 → 题注顶"） |
| `method` | `image_block_above_caption` / `gap_between_text_and_caption` |

> 只做**位置**配对，不做图像内容识别。`region` 是"这张图大概在哪"，不是"这张图是什么"。

## `result.json`（平台契约件）

| 字段 | 含义 |
|---|---|
| `case_id` | 来自 `case.json`；没有则用文件名 |
| `status` | `ok` / `partial` / `needs_review` / `blocked` |
| `source` | `{file, sha256_16, page_count, engine}` |
| `document` | 标题/作者/单位/摘要/关键词/章节/表格/图片/公式/参考文献（汇总视图） |
| `body_paragraphs` | 正文段（带 `id/page/section/bbox/text/continued_from`） |
| `evidence` | `anchors`（通过率）、`page_map`（每页路由与版式）、以及各产物的相对路径 |
| `coverage` | 13 项覆盖清单，每项 `{key, label, present, count, note}` |
| `sources` | 来源清单：PDF + "结构由本机提取、无外部服务、无人工补写" |
| `uncertainty` | 不确定项（含覆盖缺失、表格未结构化、公式只定位到编号、契约字段无法对应） |
| `changes` | 变更记录：做了什么处理（隔离页眉、重排顺序、重建表格、还原上下标、锚点核验） |
| `stats` | 各类计数 |
| `output_contract` | 按 `case.json` 的字段名逐个填；填不出写 `null` 并在 `uncertainty` 记原因 |
| `handover` | 仅 `partial`/`needs_review`：要人看哪里、建议怎么处理 |
