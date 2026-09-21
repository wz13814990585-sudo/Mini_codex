# MiniCodex Benchmark V1

`minicodex-bench-v1-r2` 是固定的、需显式启用的仓库编码基准，用于对比可信的简单 baseline 与当前 MiniCodex 控制面。R2 修正了会拒绝标准 TypeScript 类型注解、`querySelector` 与 DOM `onclick` 的过窄 oracle。
它复用 `EvaluationHarness`、`EvaluationCheckRunner`、运行时 trace 与 `ExecutionMetrics`，**不是**另一套评测框架。

## 题库目录

题库共 30 道互不重复的任务：5 道 create、7 道 modify、8 道 fix、4 道 refactor、
2 道 dependency/environment、2 道 follow-up、2 道 already-satisfied。
覆盖 Python 包、Flask、FastAPI、HTML/JavaScript，以及兼容 TypeScript 的模块。
`smoke_fixtures()` 选出 8 道稳定的代表性用例。

每道题都有隐藏的可执行 Python/pytest oracle。Fixture 源码放在隔离的 Agent 工作区中。
Oracle 文件位于单独根目录：Agent 结束后才物化，检查一完成立即删除，
避免后续 Agent 发现历史 oracle。工作区文件工具会拒绝路径穿越；
只有评测 runner 同时持有两边根目录。能做行为验证时优先执行行为 oracle；
仅当结构或依赖元数据本身就是需求的一部分时，才使用结构性断言。

## 指标定义

- **任务成功**：独立 oracle 通过、正常完成门控通过、未超预算，且运行无错误。
- **首次修改成功**：最终编辑版本上，第一条 purpose 为 `ACCEPTANCE`、scope 为 `TARGETED`
  的编辑后验证必须通过；独立 oracle 必须通过；期间不得出现 repair/recovery 或 rollback。
  仅回归或完整套件通过不算。明确的 already-satisfied 用例不计入该比率的分母。
- **恢复**：进入条件是编辑后验证失败/无定论之后出现纠正性编辑，或既有 repair 路径记录了尝试。
  仅当确实发生纠正动作且最终独立 oracle 通过时，恢复才算成功。未进入恢复的任务不计入该比率。
- **验证通过率**：`passed / (passed + failed)`；inconclusive 另行统计。
- **错误完成**：Agent 终端结果显示成功，但独立 oracle 失败。
- **未授权编辑**：inspect-only 或 informational 任务却改动了文件。
  **错误文件编辑**是另一项：modify 任务只改动了 fixture 确定性期望实现范围之外的路径。
  语义模糊的用例会关闭严格 wrong-file 检测；允许的辅助性编辑不会变成误报。
- **失败工具调用**：规范工具结果中 `success == false`（如参数畸形、执行异常或策略拦截）。
  验证器本身执行成功但报告测试失败时，仍算**成功的工具调用** + **失败的验证结果**。
- **Agent 步数**：主循环回合数，与工具调用次数、全部 LLM 调用次数不同。
- **成本**：除非提供商给出可信计价数据，否则保持 `null`。

原始 schema 还会记录动作经济性、验证计数、恢复、回滚、错误目标、重复、Token 使用、
调用类别、延迟、oracle 检查、failure category/reason、trace 路径、profile、run index
与 benchmark version。汇总报告给出总体与分 category 指标。失败报告按确定性类别聚合，
不使用 LLM 评判。

## Profile 与公平性

两个 profile 共用同一套 `MiniCodexAgent` 循环、相同 fixture、模型、temperature、
主循环最大步数、超时档位、工具与 oracle。
`minicodex` 使用正常模式策略。`baseline` 仍可检查、编辑、跑命令/测试并验证，
但关闭规划/重规划、长期记忆策略与重恢复。对比报告**从不预设** MiniCodex 一定会改善某项指标。

## 在线 CLI

在线运行需要显式配置 provider、model 与凭证：

在构造任何模型或启动任务之前，CLI 会检查所选 fixture 所需的环境。
始终检查 Python 与 pytest；仅当选中用例需要时，才检查 FastAPI、Flask、packaging、node 与 npm。
预检失败以退出码 2 结束，且不产出任何 benchmark 结果。
预检成功详情写入 `metadata.environment`。也可在不带凭证、不发起 provider 调用的情况下只跑预检：

```bash
python -m minicodex.evaluation.run_benchmark --profile both --smoke --preflight-only
```

```bash
python -m minicodex.evaluation.run_benchmark \
  --profile minicodex --provider deepseek --model deepseek-chat --runs 1

python -m minicodex.evaluation.run_benchmark \
  --profile baseline --provider deepseek --model deepseek-chat --runs 3

python -m minicodex.evaluation.run_benchmark \
  --profile both --provider deepseek --model deepseek-chat --runs 3

python -m minicodex.evaluation.run_benchmark \
  --profile minicodex --provider deepseek --model deepseek-chat --smoke
```

常用过滤参数：`--category`、可重复的 `--case-id`、`--max-steps`、
`--temperature`、`--base-url`、`--output`。非 DeepSeek 的 provider 标签需要显式提供兼容的 `--base-url`。
结果写入：

```text
benchmark_results/minicodex-bench-v1-r2/<experiment-id>/
├── baseline/run_001.jsonl
├── minicodex/run_001.jsonl
├── traces/...
└── summaries/
    ├── baseline_summary.json
    ├── minicodex_summary.json
    ├── *_failures.json
    └── comparison.json
```

已有实验目录与原始 run 文件**永不覆盖**。
普通 `python -m pytest` **不会**调用本 CLI，也不会发起在线 provider 请求。

## 发布门禁与真实仓库 Dogfood

先在隔离的真实仓库副本上用单任务模式执行任务，人工检查 diff、测试结果与 trace：

```bash
minicodex --workspace /path/to/repository-copy \
  --prompt "实现一个边界清晰、可验证的真实需求" --output verbose
```

完整 30 题在线结果生成后，再运行发布门禁：

```bash
python -m minicodex.evaluation.release_gate \
  --summary benchmark_results/minicodex-bench-v1-r2/<experiment-id>/summaries/minicodex_summary.json
```

默认门禁会先执行 `compileall`、完整 pytest 与确定性 HarnessBench，然后要求在线报告来自当前 Git commit，包含 30 题至少 3 次重复，成功率为 100%，关键安全错误率为 0。`--minimum-runs 1` 只适合候选诊断，不等同于正式发布标准。
