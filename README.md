# Bohrium Campus Challenge · CUGB 分站赛 第一期

本仓库收录参加「玻尔产品周赛 · 中国地质大学（北京）分站赛 · 第一期」的参赛 Skill。
本期主题：**AI 文献阅读与学术写作**。

每个题目一个子目录，目录内为该题可被 Agent 调用的 Skill（`SKILL.md` + 脚本 + 资源）。

## 赛题清单

> **目录编号为开发顺序，与平台题号不一致**，对外沟通请以 `challenge id` 或「平台题号」列为准。

| 目录 | 平台题号 | 官方题名 | challenge id |
|---|---|---|---|
| `01-pdf-structure-audit/` | 阅读01 | 文献文档解析 | `product-arena-08-3027d350` |
| `02-translation-audit/` | 阅读03 | 文献翻译 | `product-arena-01-5a9928c1` |
| `03-structured-notes/` | 阅读10 | 文献总结与结构化笔记 | `product-arena-06-6d8cf72b` |
| `04-nanopub-assertions/` | 阅读14 | Nanopublication | `product-arena-09-0e8befd4` |
| `05-params-provenance/` | 写作09 | 方法与实验章节写作 | `product-arena-05-64faa4a2` |
| `06-academic-polishing/` | 写作02 | 学术语言润色 | `product-arena-02-7051d92d` |
| `07-citation-audit/` | 写作04 | 参考文献与引用管理 | `product-arena-03-429cc14d` |
| `08-claim-evidence-binding/` | 写作08 | 引言与相关工作写作 | `product-arena-04-4b82ad21` |
| `10-knowledge-graph/` | 阅读15 | 文献知识图谱构建 | `product-arena-10-760d1a0b` |
| `13-latex-compile-repro/` | 写作13 | LaTeX 写作与编译 | `product-arena-07-865de7e4` |

## 目录约定

每个题目目录下至少包含：

```
<NN>-<slug>/
├── SKILL.md              # 必需：YAML frontmatter（name / description）+ 完整说明
├── scripts/              # 实际依赖的脚本（含主流程入口与自测）
├── references/           # 错误分类、方法、口径、输出契约等判断依据
├── assets/               # 词表、schema、示例输入（示例均标 example: true）
├── requirements.txt      # 第三方依赖声明
└── GITHUB_URL.txt        # 提交用：本仓库该题目录的公开链接
```

## Skill 编写要求（平台评分口径）

- `SKILL.md` 需有合法的 `name` / `description` YAML frontmatter
- 写清：用途、适用条件、调用方式、输入输出、异常处理、限制
- 不提交预制答案，平台用固定案例实际运行 Skill
- 输出结构化结果，保留证据定位（页码 / 段落 / 字段 / 文件行号）与不确定项标注
- 资源限制：最多 50 个 UTF-8 文本文件，单文件 ≤ 500KB，总计 ≤ 2MB
- 提交包内只保留文本类后缀（`.md .txt .py .json .yaml .yml .toml .csv .tex .bib .svg .html .css .sh` 与 `LICENSE`），不随包附带 `.pdf` / `.png` / `.log` 等，需要时由包内脚本现场生成

## 提交

每题通过 Playground CLI 提交，`outputs` 目录根路径放置 `SKILL.md` 与 `GITHUB_URL.txt`：

```
playground submit --challenge-id <ID> --outputs <目录> --trace <原生会话日志>
```

## 进度

| 平台题号 | 目录 | 状态 |
|---|---|---|
| 阅读01 文献文档解析 | `01-pdf-structure-audit/` | 已提交（attempt 107003） |
| 阅读01 文献文档解析（v2 重做，主攻多栏阅读顺序） | `01-pdf-structure-audit-v2/` | 已提交（attempt 107223） |
| 阅读03 文献翻译 | `02-translation-audit/` | 已提交（attempt 106280） |
| 阅读03 文献翻译（v2 重做，主攻术语一致性） | `02-translation-audit-v2/` | 已提交（attempt 107344） |
| 阅读10 文献总结与结构化笔记 | `03-structured-notes/` | 已提交（attempt 106281） |
| 阅读10 文献总结与结构化笔记（v2 重做，主攻章节对齐） | `03-structured-notes-v2/` | 待提交 |
| 阅读14 Nanopublication | `04-nanopub-assertions/` | 已提交（attempt 107004） |
| 阅读14 Nanopublication（v2 重做） | `04-nanopub-assertions-v2/` | 已提交（attempt 108129） |
| 写作09 方法与实验章节写作 | `05-params-provenance/` | 已提交（attempt 107005） |
| 写作02 学术语言润色 | `06-academic-polishing/` | 已提交（attempt 106276） |
| 写作02 学术语言润色（v2 重做，主攻语域/中式英语审计） | `06-academic-polishing-v2/` | 开发中 |
| 写作04 参考文献与引用管理 | `07-citation-audit/` | 已提交（attempt 106286） |
| 写作08 引言与相关工作写作 | `08-claim-evidence-binding/` | 已提交（attempt 106837） |
| 阅读15 文献知识图谱构建 | `10-knowledge-graph/` | 已提交（attempt 107006） |
| 阅读15 文献知识图谱构建（v2 重做，主攻跨篇实体对齐 + 自动缩写识别 + 增量更新） | `10-knowledge-graph-v2/` | 开发中 |
| 写作13 LaTeX 写作与编译 | `13-latex-compile-repro/` | 已提交（attempt 106999） |

## 各题技术要点

| 目录 | 核心做法 |
|---|---|
| `01-pdf-structure-audit/` | 六步流水线（分诊→版面→结构→表格→公式→锚点），7 个合成自测件 + 两篇真实论文实测 |
| `02-translation-audit/` | 术语表约束 + 逐段回译审计，数字/公式/引用零漂移检查 |
| `03-structured-notes/` | 结构化笔记模板 + 覆盖度与出处核对 |
| `04-nanopub-assertions/` | 断言四图（Assoc/Provenance/PubInfo 等）生成与校验 |
| `05-params-provenance/` | 参数与实验设置的来源追溯，逐项绑定到原文位置 |
| `06-academic-polishing/` | 双审计脚本（语言 + 事实）+ 两份提示词 + 自测用例 |
| `07-citation-audit/` | 引用元数据逐字段核对，捕获年份/作者/标题混合幻觉 |
| `08-claim-evidence-binding/` | 断言—证据绑定，anchored/loose/overclaimed 四态判定 |
| `10-knowledge-graph/` | 文献实体与关系抽取，证据约束的图构建 |
| `13-latex-compile-repro/` | 工程画像 → 多遍真编译 → 7 类错误分类（文件:行号）→ 副本修复 → 独立目录复现 |

## 许可

本仓库内容仅用于赛事提交与学习交流。引用请注明来源。
