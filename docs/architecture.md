# MiniCodex Vibecoding 架构说明

MiniCodex 遵循同一条控制面边界：**语义理解与策略判断属于有界 LLM 调用；事实状态、安全、执行、策略、恢复与完成判定属于确定性 Harness。**

需求—证据重构及其验证结果见 [交付报告](vibecoding-refactor-report.md)。可复用的 `WorkspaceSession` 保存有界的项目知识；每次请求都会获得全新的任务局部运行时、需求、验证账本、恢复与计划状态。

任务开始时，`TaskRouter` 发起一次无状态的控制模型调用，返回严格的 `RoutingDecision`：`TaskIntent`、`ExecutionMode`、独立的 `needs_plan`、置信度，以及有界的调试原因。只发送当前原始任务文本。响应对 schema 做校验；畸形 / 提供商 / 超时失败时，使用同一套保守的确定性回退。路径提取保持结构化，并按工作区规范化。旧的关键词复杂度打分器与意图分类器**不是**生产路由路径。

`ExecutionPolicy` 把语义模式翻译成固定的步数、重试、工具、验证、恢复与上下文上限。模型不能自行选择资源。运行时作用域可单调升级：FAST → STANDARD → COMPLEX，且不会重置已消耗预算。直接执行可在新事实证明需要协调时激活一次计划；重规划尝试单独受限。

只读检查请求看不到编辑或依赖安装能力。信息咨询请求通常看不到工具。模型散文不能完成修改任务：任务必须完成编辑并验证，或验证所请求状态本来就已经存在。

## 状态、事件、进度与阶段

`TaskRuntime` 持有一次运行的冻结权威快照 `TaskState`。文件系统内容与规范化后的工具结果是事实输入；控制器是缓存或专项组件，不是互相竞争的编排状态。重要变更会变成显式 `RuntimeEvent`，由纯函数 `reduce_task_state` 消费：

```text
工作区 / 工具事实 → RuntimeEvent → reducer → 当前 TaskState
                                             ↓
                                      ContextBuilder
                                             ↓
                                        模型决策
```

状态包含：运行 ID、意图、模式、阶段、预算、目标、需求、编辑 / 验证 / 回滚 / 计划修订、当前证据、进度压力、恢复级别、阻断原因与结果。状态转换可独立测试。`task_progress_state()` 直接返回该状态，不会通过轮询控制器重新拼装真相。

`AgentPhase` 共七个状态：`INSPECTING`、`ACTING`、`VALIDATING`、`FIXING`、`FINALIZING`、`DONE`、`BLOCKED`。`ActionController` 消费强制的 `ProgressSignal`，不会从任意状态变化推断进度。读取是观察；编辑与已完成的计划准则会推进进度；验证无变化不推进；失败数改善会推进；从通过变失败视为回退；回滚本身不是正向推进。`ValidationFingerprint` 只比较同一组稳定的 purpose / scope / 规范化目标 / validator 序列，并包含失败身份，而不只是失败数量。同一修订下的矛盾结果会变成不稳定证据。

## 运行时职责

共享流程如下：

1. 根据当前状态与证据评估是否可完成。
2. 应用有界的模式、计划、阶段与预算策略。
3. `TurnBuilder` 把系统文本委托给 `PromptBuilder`，把阶段相关任务上下文委托给 `ContextBuilder`，把 schema 委托给 `ToolSchemaProvider`。
4. `ToolCallRunner` 负责单次调用的准备 → 限制 → 修订感知的重复检查 → 安全执行。
5. `ToolBatchRunner` 负责完整、有序的提供商批次，并为每个已声明调用发出恰好一个工具结果（包括控制转换前被跳过的调用）。
6. `PlanOrchestrator` 负责步骤尝试、局部恢复与重规划转换。
7. `ValidationPlanner` 创建独立的需求检查。`ValidationPipeline` 规范化执行事实；`ValidationLedger` 持有带修订的历史、目标绑定、基线与不稳定性。`RequirementEvidenceResolver` 从充分的当前证明推导满意度。`ValidationDecisionPolicy` 负责下一步动作决策；`ProgressController` 只描述可比较趋势。
8. 紧凑、无状态的 `SemanticRegressionJudge` 仅在真正模糊的跨修订回归时运行。其建议不能编辑、回滚、绕过安全或完成任务。
9. 确定性恢复允许有界、实质不同的修复；之后 `RollbackCoordinator` 才可恢复无冲突的 checkpoint。
10. `CompletionHandler` 是唯一的终止所有者。`TaskReportBuilder` 立即渲染最终编码报告，不再额外调用模型。

常见产品流程：

- `MODIFY + FAST`：最小检查 → 编辑 → 成比例验收 → 完成
- `MODIFY + STANDARD`：可选短计划 → 编辑 → 验收 → 相关回归 → 完成
- `MODIFY + COMPLEX`：可选计划 → 迭代编辑 → 验收 → 全量回归 → 完成
- `INSPECT_ONLY`：检查 → 报告，零编辑
- `INFORMATIONAL`：直接回答

计划包含结果描述、预期目标、依赖、验收准则、状态与证据。证据会自动对账准则。手动计划完成工具已移除。当显式需求与成比例的当前修订验证已满足时，仅剩记账意义的步骤会被 superseded，不能让代理一直活着。

## 编辑、恢复与安全

`EditStrategyHint` 建议：新文件用 `write_file`，小范围精确改动用 `patch_file`，已知 Python 符号用 `replace_symbol`，已知行区间用 `replace_lines`。它只是建议，从不自动编辑。`EditRetryPolicy` 先做局部恢复：过期 / 范围 / 歧义编辑会重读目标；缺失符号会做一次符号搜索；测试失败聚焦失败测试或 traceback 路径；依赖失败检查清单文件。

所有变更仍经过 `SafetyToolExecutor`、无编辑权限守卫、工作区 / 受保护路径规则、反测试作弊检查，以及 checkpoint 捕获 / 密封。Checkpoint 执行会检测并发改动；回滚拒绝覆盖 checkpoint 之后的外部编辑。回滚会创建新的单调修订，使验证 / 计划证据与仓库缓存失效，并重新同步任务局部记忆。仅失败数升高本身不会触发回滚。稳定的 `EditFailureType` 与 `ReasonCode` 驱动控制逻辑；面向用户的文案不参与控制。

## 验证目标选择

`ValidationSelector` 推荐一个成比例的验证器。静态 HTML 使用 `validate_static_web`，证明结构、内联语法与配置的静态要求——不证明点击、键盘、玩法或运行时状态。可选的 `validate_browser_app` 用 Playwright 做页面加载、控制台错误、选择器、文本、点击、按键，以及基础 DOM / 文本变化。仅在 Playwright 可用时注册；静态验证仍是回退方案。

带修订缓存、基于 AST 的 `TestIndex` 把被导入 / 引用的 Python 源模块映射到测试。`TestTargetResolver` 按精确 basename、导入匹配、同包测试、更广测试目录排序。只有真正聚焦的候选才标为验收；包级 / 宽范围候选仍是回归。源模块绝不会当作 pytest 验收目标。`run_tests` 从失败 node ID 与 traceback / 错误位置发出保守的仓库相对 `failure_paths`，以及有界失败指纹。回归基线证据区分：预先存在、持续存在、已解决、新引入。工具执行失败与超时是不确定的环境证据，不是自动代码失败。

`RelevantPathResolver` 从请求目标、已编辑路径、失败测试、traceback、验证目标、过期编辑、计划准则、符号搜索恢复，以及显式依赖解析证据推导范围。它不会把每个清单文件都塞进无关任务。

## 上下文、记忆、能力与体验

`ContextBuilder` 是唯一的上下文路径。内容随阶段变化：检查阶段看目标 / 仓库片段；行动阶段看编辑提示与精确当前状态；验证阶段看变更目标与推荐验证器；修复阶段看最新失败路径；收尾阶段只看缺失证据。较旧的工具载荷会压缩为短事实。需要精确代码时从工作区重新读取。

`TaskRequirements` 保存可独立证明的用户结果及其当前证据。多目标 / 需协调的任务可做一次无状态需求调用；明显的 FAST 任务可跳过。绿色验证不能在显式请求结果仍未证明时结束任务。

工作记忆条目带有路径与修订。编辑某路径会先移除该路径的旧观察，再记录新修订。记忆是缓存；工作区仍是权威来源。

任务控制状态与 checkpoint 是任务局部、进程内的。MiniCodex 不宣称进程崩溃后可续跑进行中任务。重启后的进程必须检查物理工作区并建立新的验证；不能复用崩溃前的验证或回滚状态。

`ToolRegistry` 暴露与后端无关的 `ToolMetadata`：能力、风险、副作用类别、只读状态、超时类别与后端。支持如 `filesystem.read`、`filesystem.write`、`code.search`、`code.edit`、`process.run`、`test.run`、`validation.static_web`、`validation.browser`、`dependency.install`、`git.inspect` 等轻量能力，并为内置工具提供确定性的名称默认值。这是未来本地 / 远程后端的接缝；MCP 联网尚未实现。

CLI 级别为 `normal`、`verbose`、`debug`。`normal` 隐藏 Harness / 提供商噪声与内部枚举。`verbose` 保留执行 / 阶段诊断。`debug` 还会暴露结果 token 与任务后的 trace 摘要。`normal` 最终报告只包含变更文件与验证结果。

## 包职责划分

| 包 | 职责 |
| --- | --- |
| `agent/` | 仅 `MiniCodexAgent` 门面、中心 `TaskState`、共享 reason code 与包导出 |
| `agent/context/` | 上下文预算与压缩，以及导航用的仓库地图与符号上下文 |
| `agent/orchestration/` | 循环控制、提供商回合、工具批次、计划与验证协调、完成处理与任务报告 |
| `agent/routing/` | 语义路由 schema / 提示 / 回退、任务意图、执行模式与确定性执行策略 |
| `agent/progress/` | 进度信号、动作压力与收尾控制 |
| `agent/planning/` | 任务需求、计划、规划 / 重规划、计划质量与步骤证据 |
| `agent/validation/` | 证据规范化、验证选择、测试索引与目标、相关路径、回归策略与完成策略 |
| `agent/editing/` | 编辑策略 / 重试、checkpoint、已验证执行、回滚与回滚协调 |
| `agent/dependency/` | 感知清单的依赖解析策略 |
| `agent/memory/` | 任务局部工作记忆与持久记忆集成 |
| `agent/safety/` | 权限策略、失败即关闭的执行与进程沙箱 |
| `agent/runtime/` | 工具执行、取消、异步任务机制与 Git 工作树感知 |
| `agent/observability/` | 执行 / token 指标、结构化 trace 事件与适配器、输出级别选择 |
| `tools/` | 模型可调用能力，按 `filesystem`、`search`、`editing`、`execution`、`validation`、`planning` 与只读 `git` 分组；仅核心类型留在浅层的 `base.py`、`registry.py`、`results.py` |
| `utils/` | 仅领域无关辅助，包括工作区路径解析 |

## 依赖规则与规范导入

依赖方向是刻意的：`utils` 不依赖 agent 领域；tools 不依赖 orchestration；领域包避免导入 `MiniCodexAgent` 门面；orchestration 协调领域 API；`agent.py` 作为组合根。包 `__init__.py` 暴露有意设计的稳定 API。少数导入为惰性加载，仅用于防止包初始化循环，同时保持规范类 / 枚举的身份。每个概念只有一个规范模块路径；源码树中没有旧模块包装或兼容导入路径。

`ExecutionMetrics` 与确定性评估 Harness 会区分主代理、路由、需求与语义裁判的调用 / token / 延迟。也会记录模式升级、晚期规划、修复、验证 / 不稳定复验、被阻止的过早回滚、结果、误完成、错误编辑、工具计数、重规划、回滚、动作压力与预算耗尽。提示词版本与配置的模型名可观测。评估包同时包含 30 任务端到端目录，以及平衡的中英 / 混合路由语料。
