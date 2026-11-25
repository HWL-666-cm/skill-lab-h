# 验证清单

## 每次开发后必跑

```bash
python <skill-dir>/assets/tests/run_selftest.py
```

16 项覆盖：好稿完整链路、多遍中间态过滤、引擎自动切换、行号定位、honesty、blocked、确定性、脚本语法。

## 10 项门禁（`assets/schema.json`）

| 检查 | 严重度 | 判定 |
|---|---|---|
| `has_case_id` | fail | case_id 非空 |
| `has_sources` | fail | 列出实际读取的输入 |
| `has_artifacts` | fail | 可编辑源码文件真实存在 |
| `has_build_manifest` | fail | 引擎、发行版、命令、轮次、源码哈希齐全 |
| `has_error_ledger` | fail | 每条含 location/root_cause/fix/reverify |
| `has_changes` | warn | 有改动记录；干净构建可无改动 |
| `has_uncertainty` | warn | 有未解决项时必须写明 |
| `compiled` | fail | 最终编译收敛 |
| `reproduced` | warn | 独立复现 verdict 为 verified/partial |
| `no_fabrication` | fail | 状态与证据一致 |

## 交付前人工核对

- [ ] `SKILL.md` 根目录存在，frontmatter 的 `name`/`description` 合法且含触发词
- [ ] 交付目录内没有 `.pdf/.png/.trig/.log/.jsonl` 等白名单外后缀
- [ ] `assets/examples/result.json` 带 `example: true` / `example_note`（不是正式答案）
- [ ] trace 是真实会话抽取，valid
- [ ] dry-run bundle 的 `outputs/SKILL.md` 与 `results/SKILL.md` 都在
- [ ] 没有把开发缓存目录（`_dev/`、临时工程）打进提交包

## 已知平台侧风险（来自讨论区）

同题有用户报告三次恒 0 或 `evaluation_error`（`JudgeUnavailable`），但也有人拿 63–76 分，说明题目本身可做。可控因素只有提交结构、轨迹真实性和不交预制答案；若出现恒 0，先查这三项，再找负责人，不要在内容上无限改。
