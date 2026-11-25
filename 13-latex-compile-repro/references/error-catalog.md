# LaTeX 错误分类表

分类的目的不是"把错误归堆"，而是决定**谁能修**：脚本可确定性修复的走自动，涉及领域判断的必须交人工。词表源头在 `assets/lexicon.json`，本文件解释每一类为什么这么分。

| 类别 | 典型日志 | 根因 | 自动可修 | 处理原则 |
|---|---|---|---|---|
| 引擎与编码 | `LaTeX Error: Unicode character β`、`inputenc Error` | 非 ASCII/CJK 字符用 pdflatex 编译 | 是 | 切 xelatex/lualatex；或显式 `\DeclareUnicodeCharacter`。切换写入 manifest |
| 宏包与加载顺序 | `File 'x.sty' not found`、`Option clash for package biblatex` | 缺包、重复加载、选项冲突 | 部分 | 白名单内标准宏包可自动补；第三方包需确认来源。选项冲突要合并 `\usepackage`，不能删报错的那一行 |
| 引用与参考文献 | `Citation 'k' undefined`、`Reference 'r' undefined`、`No file main.bbl` | 未收敛、键不存在、文献后端错配 | 部分 | 前两种先看是不是中间态；最后一轮仍存在才补键/补 `\label`。补键涉及内容判断，标人工 |
| 数学公式 | `Missing $ inserted`、`Extra } or forgotten $` | 数学定界符不匹配 | 否 | 符号含义与编号属于作者意图，只给位置和候选修复 |
| 表格与溢出 | `Overfull \hbox (Npt too wide)`、`Misplaced \noalign` | 列宽超出、列数与 `&`/`\multicolumn` 不符 | 部分是 | 用 `tabularx`/`p{}`/调 `\tabcolsep`/统一字号；不用 `\resizebox` 硬缩放；不改表格数值 |
| 模板与必填项 | `File 'x.cls' not found`、`Emergency stop` | 模板类缺失、致命错误 | 否 | 补真实 `.cls` 或换可用文档类；致命错误看前一条 `!` 行才是真根因 |
| 陈旧辅助文件 | `\abx@aux@refcontext` undefined、`Undefined control sequence` 且源码无此宏 | `.aux/.bbl/.bcf` 残留自上一次构建 | 是 | 清理 `.aux/.bbl/.bcf/.blg/.out/.toc/.lof/.lot` 后从头全量重编 |
| 字体 | `Font ... not found` | 字体未安装或名称不匹配 | 否 | 记录所需字体及版本，建议安装或改用已有字体 |

## 日志格式兼容

必须同时支持两种错误行格式：

```
! LaTeX Error: File `foo.sty' not found.        ← 传统格式
./main.tex:8: LaTeX Error: Unicode character β  ← -file-line-error 格式
```

开发期真实踩过：只匹配带 `!` 前缀的格式时，含 Unicode 的稿子被判成"未分类错误"，自动修复完全没触发。词表里两种都收。

## 多遍收敛：哪些警告不是错误

`latex → bibtex → latex → latex`（natbib）或 `latex → biber → latex`（biblatex）中，前几轮出现这些是**正常中间态**：

- `No file main.bbl.`
- `Citation 'xxx' undefined`
- `Reference 'yyy' undefined`
- `There were undefined references`

判据：**编译最终成功时，台账只保留最后一轮仍可见的问题**；编译失败时保留所有观察，因为早期报错才是真根因。这样既满足"不只看第一条错误"，又不会把已经自愈的警告当缺陷去修。

## 行号提取

TeX 的行号分散在几种格式里，提取器按优先级找：

1. `./main.tex:12: ...`（`-file-line-error`）
2. `l.12 \some command`
3. `at lines 12--14`
4. `on input line 12`

第 4 种常被 TeX 折行成 `on input line` 在行尾、数字在**下一行**，需要跨行取。引用未定义的行号就是这么丢过一次。
