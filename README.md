# Bohrium Campus Challenge · CUGB 分站赛 第一期

本仓库收录参加「玻尔产品周赛 · 中国地质大学（北京）分站赛 · 第一期」的参赛 Skill。
本期主题：**AI 文献阅读与学术写作**。

每个题目一个子目录，目录内为该题可被 Agent 调用的 Skill（`SKILL.md` + 脚本 + 资源）。

## 赛题清单

| # | 题目 | challenge id | 目录 |
|---|---|---|---|
| 01 | 文献文档解析 | `product-arena-08-3027d350` | `01-literature-parsing/` |
| 02 | 文献翻译 | `product-arena-01-5a9928c1` | `02-literature-translation/` |
| 03 | 文献总结与结构化笔记 | `product-arena-06-6d8cf72b` | `03-summarization-notes/` |
| 04 | Nanopublication | `product-arena-09-0e8befd4` | `04-nanopublication/` |
| 05 | 文献知识图谱构建 | `product-arena-10-760d1a0b` | `05-knowledge-graph/` |
| 06 | 学术语言润色 | `product-arena-02-7051d92d` | `06-academic-polishing/` |
| 07 | 参考文献与引用管理 | `product-arena-03-429cc14d` | `07-citation-management/` |
| 08 | 引言与相关工作写作 | `product-arena-04-4b82ad21` | `08-intro-related-work/` |
| 09 | 方法与实验章节写作 | `product-arena-05-64faa4a2` | `09-methods-experiments/` |
| 10 | LaTeX 写作与编译 | `product-arena-07-865de7e4` | `10-latex-writing/` |

## 目录约定

每个题目目录下至少包含：

```
<NN>-<slug>/
├── SKILL.md              # 必需：YAML frontmatter（name / description）+ 完整说明
├── scripts/              # 实际依赖的脚本
├── resources/            # 词表、模板、配置等
├── examples/             # 最小调用示例（标明为示例，不是正式结果）
└── GITHUB_URL.txt        # 提交用：第一行本仓库该题目录的公开链接
```

## Skill 编写要求（平台评分口径）

- `SKILL.md` 需有合法的 `name` / `description` YAML frontmatter
- 写清：用途、适用条件、调用方式、输入输出、异常处理、限制
- 不提交预制答案，平台用固定案例实际运行 Skill
- 输出结构化结果，保留证据定位（页码 / 段落 / 字段）与不确定项标注
- 资源限制：最多 50 个 UTF-8 文本文件，单文件 ≤ 500KB，总计 ≤ 2MB

## 提交

每题通过 Playground CLI 提交，并在提交目录根路径放置 `GITHUB_URL.txt`：

```
playground submit --challenge-id <ID> --skill <目录> --trace <原生会话日志>
```

## 许可

本仓库内容仅用于赛事提交与学习交流。引用请注明来源。
