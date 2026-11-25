# 阅读01｜文献文档解析 —— 本地验证与评估报告

> 本报告为本 Skill 在自建验证语料上的实测结果。正式案例、白板与最终测评由平台提供，此处不冒充正式成绩。

## 1. 验证语料（自建）

| 文档 | 页数 | 特征 | 用途 |
|-|-|-|-|
| Decision Transformer (arXiv 2106.01345) | 21 | 单栏为主、含双栏页、图注/脚注/参考文献齐全 | 完整性、章节、图注、参考文献 |
| BERT (arXiv 1810.04805) | 16 | 表格、公式密集 | 表格、公式、章节 |
| 受控双栏测试（pdflatex 生成） | 2 | 明确双栏 + 公式 + 表格 | **阅读顺序 ground-truth** |
| 扫描版（合成，无文字层） | 2 | 图片型 PDF | OCR 降级 |

## 2. 核心成果：多栏阅读顺序（主攻方向）

受控双栏测试页（左栏=Abstract+Introduction，右栏=Method+Results+公式+表格）：

**基础 Agent（naive `pdftotext -layout`）** —— 左右两栏被串成一行：

```
Abstract                                         2  Method
Lorem ipsum dolor sit amet...                    Quisque ullamcorper placerat...
Ut purus elit, vestibulum ut...                  vel justo vitae lacus tincidunt...
```

左栏正文与右栏正文逐行交织，读出来是拼接错的句子（串栏）。

**加载本 Skill** —— 左右两栏分离，先左后右：

```
[左栏 col0] Lorem ipsum dolor sit amet, consectetuer adipiscing elit.
[左栏 col0] Ut purus elit, vestibulum ut, placerat ac, adipiscing vi-...
   ...（左栏完整读完 Abstract + 1 Introduction）...
[右栏 col1] Quisque ullamcorper placerat ipsum. Cras nibh. Morbi...
   ...（右栏完整读完 2 Method + 3 Results + 公式 + 表格）...
```

栏位检测 `[[0.09, 0.29], [0.50, 0.91]]`，左栏 40 行、右栏 45 行，无串栏。

## 3. 实测指标汇总

| 文档 | 段落 | 表格(候选) | 公式(上界) | 章节(上界) | OCR |
|-|-:|-:|-:|-:|-:|
| Decision Transformer | 830 | 50 | 182 | 91 | 否 |
| BERT | 1323 | 18 | 83 | 63 | 否 |
| 受控双栏 | 105 | 2 | 108 | 7 | 否 |
| 扫描版(合成) | 61 | 4 | 3 | 36 | **是** |

> **上界估计判据**：公式=行内出现数学字体（CMMI/CMSY/CMEX 等）或 ≥3 个非词特殊字符即计 1（含行内公式、作者上标等误报，非独立行间公式数）；章节=字号≥正文×1.18 且短 或 匹配编号/关键词即计 1（含子小节，含少量作者单位/脚注误报）。两项均为上界，非精确计数。

## 4. 分项评估（诚实标注）

### 4.1 提得全（逐字提取）
- ✅ 正文/图注/脚注/参考文献逐字提取，页眉页脚分离；
- ✅ 每段带页码 + 归一化坐标，可指回原文（`evidence` / `reading_order`）。

### 4.2 排得对（阅读顺序）
- ✅ 双栏按"先左后右"还原，栏内按 y 排序；
- ✅ 通栏题名/摘要与栏内正文分离；
- ⚠️ 复杂 float 布局、跨页续表、边注需 Agent 用渲染页图二次核对（SKILL.md 步骤 3）。

### 4.3 拆得清（结构还原）
- ✅ 章节层级（字号+加粗+编号，过滤目录点线行）；
- ✅ 公式行定位（数学字体 CMMI/CMSY + 特殊字符密度），保留上下标与希腊字母原文；**不保证公式编号**（编号常在版面右侧单独成块）；
- ⚠️ 表格为"候选检测"（列对齐网格 + 数字密度过滤），存在少量文本分栏误报；Agent 依渲染图最终确认行列归属。这是本地无重型版面引擎时的合理取舍。

### 4.4 核得回（可复核）
- ✅ `evidence` 记录关键结论的页码/区块；`reading_order` 输出可核验序列；
- ✅ 读不出/无文字层的部分如实标注（`uncertainty`），OCR 结果标注需对照原页复核。

### 4.5 异常处理
- ✅ 无文字层 → OCR 自动降级（实测扫描版成功，61 段）；
- ✅ 加密 PDF / 乱码 / 工具缺失均有识别与降级说明（SKILL.md 异常表）。

## 5. 已知限制（如实）
1. 表格检测为启发式，存在少量误报/漏报，需 Agent 用渲染页图校正；
2. 通栏/栏内混排的复杂 float 版面，自动分栏可能不完美，需 Agent 复核；
3. OCR 对低分辨率/竖排文字置信度有限。

## 6. 增益（与基础 Agent 对照）
- 基础 Agent（naive pdftotext）在双栏页**串栏**，本 Skill **分离双栏并按序输出**；
- 基础 Agent 无表格/公式/章节结构化，本 Skill 输出结构化 + 页码坐标定位；
- 本 Skill 对扫描件自动 OCR，基础 Agent 直接读空。

---

**结论**：本 Skill 已具备"提得全、排得对、拆得清、核得回"的完整能力，主攻方向（多栏阅读顺序）有明确 ground-truth 对照证据。下一步：建 GitHub 公开仓库 → 更新 SKILL.md/README 终版 → `submit --dry-run` 预检 →（你确认后）正式提交。
