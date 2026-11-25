# 科研文献翻译 Skill（translation-audit-v2）

阅读03｜文献翻译的参赛作品。核心思路：**术语表驱动 + 代码级强制执行的文献翻译流程**——术语一致性不是"写在提示里"，而是"翻译后用代码校验并强制回填"。

## 一句话方案

把一篇英文科研论文翻译成**段落级双语对照**结果，四件事由确定性代码保证：

1. **术语稳**：抽取候选术语 → Agent 确认译名 → 翻译后逐段校验 + 强制回填禁用译名；
2. **段落全**：多栏阅读顺序 + 行距/缩进聚段，跨页跨栏不漏段、段号一一对应；
3. **关系准**：数字+单位、文献引用、URL/DOI、公式编号翻译前用占位符保护；
4. **可核验**：每段译文带 `id/page/column/section` 定位 + 译法依据。

## 文件结构

```
SKILL.md                        # Skill 本体（用途/流程/术语表格式/占位符规则/输出/异常）
README.md                       # 本说明
GITHUB_URL.txt                  # 提交用 GitHub 链接
scripts/extract_document.py     # 结构化解析 + 多栏阅读顺序 + 行→段落聚合（确定性）
scripts/prepare_translation.py  # 候选术语抽取 + 占位符保护 + 段落级翻译任务（确定性）
scripts/validate_translation.py # 译文核验 + 术语强制回填（确定性）
scripts/run.py                  # 评测环境入口（读 case.json/task.md → 跑解析 → 写 result.json 草稿）
example/demo_result.json        # 最小调用示例（标为示例）
```

## 调用方式

```bash
# 1. 结构化解析 + 段落聚合
python3 scripts/extract_document.py <paper.pdf> /app/work/extracted.json --workdir /app/work/ext
# 2. 生成翻译任务（候选术语表 + 占位符保护）
python3 scripts/prepare_translation.py /app/work/extracted.json /app/work/translation_job.json
# （Agent 依据 SKILL.md 确认术语表并逐批翻译，写出 translations.json）
# 3. 核验 + 强制回填
python3 scripts/validate_translation.py /app/work/translation_job.json /app/work/translations.json /app/work/termbase.json
```

## 依赖与版本

- 运行时镜像已预装：poppler-utils（`pdfinfo/pdftohtml/pdftotext/pdffonts/pdftoppm`）、`python3`、可选 `tesseract`（OCR）。
- 脚本仅依赖 Python 标准库（`json/re/subprocess/collections`），无第三方包。
- 扫描件自动 OCR 降级；公式/表格为图片时 Agent 用渲染页图判读。

## 限制

- 作者-年份式行内引用 `(Zhu et al., 2015)` 若在提取阶段丢失（部分 PDF 排版），需对照渲染页图补回；
- 复合单位（`m/s` 等）按首个单位保护，剩余符号由"数字单位必须与原文一致"的翻译指令兜底；
- 译文语言质量取决于运行时的 DeepSeek 模型，本 Skill 负责"约束与核验"，不负责模型本身的流畅度。
