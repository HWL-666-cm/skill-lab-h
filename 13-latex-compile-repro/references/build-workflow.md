# 编译流程与可重复构建

## 引擎选择（按源码证据，不按文件名）

| 源码特征 | 引擎 |
|---|---|
| 含中文、希腊字母等非 ASCII 字符 | `xelatex` |
| 含 `fontspec` / `ctex` / `xeCJK` / `CJK` | `xelatex` |
| 纯 ASCII、无字体包 | `pdflatex` |
| 需要 Lua 特性 | `lualatex`（手动指定） |

判断逻辑在 `scripts/profile.py`。选错引擎会让 inputenc 错误盖住真正的 bug，所以画像必须先做。

## 文献后端（不可混用）

| 源码特征 | 后端 | 编译序列 |
|---|---|---|
| `\usepackage{biblatex}` / `\addbibresource` | biblatex | `xelatex → biber → xelatex → xelatex` |
| `\usepackage{natbib}` / `\bibliography` | natbib | `pdflatex → bibtex → pdflatex → pdflatex` |
| 都没有 | none | 单遍或多遍 pdflatex |

混用会报 `Option clash for package biblatex` 或 `\printbibliography` 未定义。脚本检测到哪一个就只用哪一套，不猜。

## latexmk 与其运行时降级

优先用 `latexmk`，因为它自己判断引用是否收敛。但"装了"不等于"能用"：Windows 中文路径下 latexmk 的 Perl 包装可能失败，报 `runscript.tlu` / `perl.exe: No such file or directory` / `Cannot write file 'D:/????/...'`，且**不会产生任何 `.log`**。

`build.py` 检测这些特征后自动降级到显式编译序列，并在 manifest 的 `latexmk_note` 里记录原因。同理，bibtex/biber 改用**在 build 目录里以裸文件名运行**，避免把含中文的绝对路径交给 Perl 层。

## 隔离目录

```
<work>/
├── src/            # 从 case 材料复制而来，修复只在这里发生
├── src_original/   # 初始快照，用于算 diff
├── build/          # 编译产物与中间文件
└── repro/          # 独立复现用的另一套 src + build
```

原始 case 文件**从不修改**。`-output-directory` 把 `.aux/.log/.pdf` 全部导到 `build/`，交付目录 `out/source/` 只放可编辑源码。

## 复现判据（分层）

| 层次 | 默认 | `--deterministic` |
|---|---|---|
| 源码 sha256 一致 | 必须 | 必须 |
| 编译退出码一致 | 必须 | 必须 |
| 错误诊断签名一致 | 必须 | 必须 |
| PDF 字节 sha256 一致 | 不要求（记差异） | 必须 |

为什么默认不要求 PDF 字节一致：pdfTeX 把编译时间写进 PDF，同一份源码两次编译天然不同；除非固定 `SOURCE_DATE_EPOCH`。固定时间戳的代价是 `\today` 不再是真实日期，所以做成可选开关。

复现时逐轮保存 `.log` 快照——TeX 每轮覆盖 `main.log`，只在最后读一次会丢掉中间状态，导致复现台账和原台账口径不一致。

## 可移植性

`result.json` 和 `build_manifest.json` 不含开发机绝对路径：

- `project_profile.root` → `<case_root>`
- `main_tex` → 相对 case 根的路径
- 命令里的 `-output-directory=...` → `-output-directory=<build>`
- `repro_dir` → `repro`

因此同一 case 在不同机器/不同临时目录下运行，结构化产物字节一致（PDF 哈希与耗时字段除外）。
