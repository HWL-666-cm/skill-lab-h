# 阅读01｜文献文档解析 — Skill 交付说明

本目录是「阅读01｜文献文档解析」赛题的提交物：一个可被 Agent 调用的 **科研 PDF 结构化解析 Skill**。

## 目录结构

```
.
├── SKILL.md                 # Skill 本体（name/description YAML 元信息 + 完整流程）
├── README.md                # 本说明
├── GITHUB_URL.txt           # 作品 GitHub 公开链接（附加分，需参赛者填写）
├── scripts/
│   ├── extract_pdf.py       # 核心解析器（结构化提取 + 版面分析 + OCR 降级）
│   └── run.py               # 评测环境入口（case.json/task.md → result.json）
└── example/
    └── demo_result.json     # 最小调用示例（示意输出，已标明为示例）
```

## 依赖

- 系统工具（poppler-utils）：`pdfinfo` `pdftohtml` `pdftotext` `pdffonts` `pdftoppm`
- Python 3（仅标准库）
- 可选：`tesseract`（扫描版 PDF OCR）

评测运行环境固定镜像已预装上述依赖，无需额外安装。

## 快速开始

```bash
# 1) 直接解析一份 PDF
python3 scripts/extract_pdf.py /path/to/paper.pdf output.json --workdir /app/work

# 2) 评测环境入口（读 /input/case.json + /input/task.md，写 /app/output/result.json）
python3 scripts/run.py
```

## 输出结构（result.json）

| 字段 | 含义 |
|-|-|
| `case_id` | 案例标识（来自 case.json） |
| `answer` | 题面 `output_contract` 声明的每个字段的答案 |
| `structured` | 结构化解析结果（标题/作者/章节/**阅读顺序 reading_order**/表格/公式/图注/参考文献/脚注，均带页码+归一化坐标） |
| `evidence` | 关键结论到原文的页码/区块/字段定位 |
| `status` | success / partial / failed / refused / unable_to_judge |
| `uncertainty` | 无法判断/读不出的部分（诚实标注） |
| `changes` | 变更记录（时间戳） |

## 核心能力

- **提得全**：正文/图注/脚注/参考文献逐字提取，页眉页脚与正文分离；
- **排得对**：**竖直栏缝检测**识别双栏/多栏，按"先左栏后右栏、栏内自上而下"重建阅读顺序，输出可核验的 `reading_order`；
- **拆得清**：章节层级（字号+编号+加粗）、表格候选检测（列对齐+数字密度过滤）、公式行定位与字符保留（不保证编号）；
- **核得回**：每个段落/表格/公式带页码与归一化坐标定位；
- **异常处理**：加密 PDF、无文字层扫描件（OCR 降级）、乱码字体识别。

## 两阶段设计

确定性脚本 `scripts/extract_pdf.py` 做版面/坐标/结构重活，Agent 用渲染页图做语义核验与答题——把 64 次模型请求花在"校验与回答"，而非从零重排文字。

## 限制

- 只做结构元素识别，不理解图表/公式的科学含义；
- 复杂 float 排版、跨页大表建议配合渲染页图二次核对（SKILL.md 步骤 3）。
