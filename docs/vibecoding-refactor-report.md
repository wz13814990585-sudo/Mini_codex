# Vibecoding 重构交付报告

分支：`demo_game_try`。改动前基线：`e3510ac`。本次修改未提交、未推送。

最终完整回归：**555 passed in 12.53s**；编译检查、diff 空白检查通过。
离线 VibeBench：**15/15**，误完成率 **0**。
这些结果证明本地自动化覆盖内的行为，不代表真实模型或任意仓库的生产可靠性已经得到验证。

## 1. 新建文件

- [docs/vibecoding-refactor-report.md](../docs/vibecoding-refactor-report.md)
- [minicodex/agent/context/workspace_session.py](../minicodex/agent/context/workspace_session.py)
- [minicodex/agent/editing/edit_intent.py](../minicodex/agent/editing/edit_intent.py)
- [minicodex/agent/editing/work_unit.py](../minicodex/agent/editing/work_unit.py)
- [minicodex/agent/orchestration/tool_batch_result.py](../minicodex/agent/orchestration/tool_batch_result.py)
- [minicodex/agent/orchestration/tool_event_adapter.py](../minicodex/agent/orchestration/tool_event_adapter.py)
- [minicodex/agent/runtime/managed_process.py](../minicodex/agent/runtime/managed_process.py)
- [minicodex/agent/validation/decision_policy.py](../minicodex/agent/validation/decision_policy.py)
- [minicodex/agent/validation/evidence.py](../minicodex/agent/validation/evidence.py)
- [minicodex/agent/validation/ladder.py](../minicodex/agent/validation/ladder.py)
- [minicodex/agent/validation/ledger.py](../minicodex/agent/validation/ledger.py)
- [minicodex/agent/validation/plan.py](../minicodex/agent/validation/plan.py)
- [minicodex/evaluation/vibebench.py](../minicodex/evaluation/vibebench.py)
- [minicodex/tests/evidence_fixtures.py](../minicodex/tests/evidence_fixtures.py)
- [minicodex/tests/test_vibecoding_runtime.py](../minicodex/tests/test_vibecoding_runtime.py)
- [minicodex/tools/validation/validate_service.py](../minicodex/tools/validation/validate_service.py)

## 2. 修改文件

- [docs/architecture.md](../docs/architecture.md)
- [minicodex/agent/agent.py](../minicodex/agent/agent.py)
- [minicodex/agent/context/symbol_index.py](../minicodex/agent/context/symbol_index.py)
- [minicodex/agent/editing/checkpoint.py](../minicodex/agent/editing/checkpoint.py)
- [minicodex/agent/editing/checkpoint_executor.py](../minicodex/agent/editing/checkpoint_executor.py)
- [minicodex/agent/editing/edit_verifier.py](../minicodex/agent/editing/edit_verifier.py)
- [minicodex/agent/editing/rollback.py](../minicodex/agent/editing/rollback.py)
- [minicodex/agent/editing/rollback_coordinator.py](../minicodex/agent/editing/rollback_coordinator.py)
- [minicodex/agent/memory/working_memory.py](../minicodex/agent/memory/working_memory.py)
- [minicodex/agent/memory/working_summary.py](../minicodex/agent/memory/working_summary.py)
- [minicodex/agent/observability/metrics.py](../minicodex/agent/observability/metrics.py)
- [minicodex/agent/observability/trace_runtime.py](../minicodex/agent/observability/trace_runtime.py)
- [minicodex/agent/orchestration/__init__.py](../minicodex/agent/orchestration/__init__.py)
- [minicodex/agent/orchestration/context_builder.py](../minicodex/agent/orchestration/context_builder.py)
- [minicodex/agent/orchestration/loop.py](../minicodex/agent/orchestration/loop.py)
- [minicodex/agent/orchestration/orchestration_transitions.py](../minicodex/agent/orchestration/orchestration_transitions.py)
- [minicodex/agent/orchestration/tool_batch.py](../minicodex/agent/orchestration/tool_batch.py)
- [minicodex/agent/orchestration/tool_batch_runner.py](../minicodex/agent/orchestration/tool_batch_runner.py)
- [minicodex/agent/orchestration/tool_call_runner.py](../minicodex/agent/orchestration/tool_call_runner.py)
- [minicodex/agent/orchestration/tool_schema_provider.py](../minicodex/agent/orchestration/tool_schema_provider.py)
- [minicodex/agent/orchestration/validation_orchestrator.py](../minicodex/agent/orchestration/validation_orchestrator.py)
- [minicodex/agent/planning/requirements.py](../minicodex/agent/planning/requirements.py)
- [minicodex/agent/progress/action_controller.py](../minicodex/agent/progress/action_controller.py)
- [minicodex/agent/routing/execution_policy.py](../minicodex/agent/routing/execution_policy.py)
- [minicodex/agent/routing/task_router.py](../minicodex/agent/routing/task_router.py)
- [minicodex/agent/runtime/async_runtime.py](../minicodex/agent/runtime/async_runtime.py)
- [minicodex/agent/runtime/execution_control.py](../minicodex/agent/runtime/execution_control.py)
- [minicodex/agent/runtime/task_control.py](../minicodex/agent/runtime/task_control.py)
- [minicodex/agent/safety/safety.py](../minicodex/agent/safety/safety.py)
- [minicodex/agent/safety/safety_executor.py](../minicodex/agent/safety/safety_executor.py)
- [minicodex/agent/task_state.py](../minicodex/agent/task_state.py)
- [minicodex/agent/validation/__init__.py](../minicodex/agent/validation/__init__.py)
- [minicodex/agent/validation/completion_policy.py](../minicodex/agent/validation/completion_policy.py)
- [minicodex/agent/validation/pipeline.py](../minicodex/agent/validation/pipeline.py)
- [minicodex/agent/validation/regression_policy.py](../minicodex/agent/validation/regression_policy.py)
- [minicodex/agent/validation/selector.py](../minicodex/agent/validation/selector.py)
- [minicodex/agent/validation/test_index.py](../minicodex/agent/validation/test_index.py)
- [minicodex/evaluation/harness.py](../minicodex/evaluation/harness.py)
- [minicodex/evaluation/models.py](../minicodex/evaluation/models.py)
- [minicodex/main.py](../minicodex/main.py)
- [minicodex/tests/benchmarks/test_fast_task_execution.py](../minicodex/tests/benchmarks/test_fast_task_execution.py)
- [minicodex/tests/test_canonical_architecture.py](../minicodex/tests/test_canonical_architecture.py)
- [minicodex/tests/test_completion_policy.py](../minicodex/tests/test_completion_policy.py)
- [minicodex/tests/test_execution_and_regression_policy.py](../minicodex/tests/test_execution_and_regression_policy.py)
- [minicodex/tests/test_fast_mode_integration.py](../minicodex/tests/test_fast_mode_integration.py)
- [minicodex/tests/test_plan_progress.py](../minicodex/tests/test_plan_progress.py)
- [minicodex/tests/test_plan_quality_and_reconciliation.py](../minicodex/tests/test_plan_quality_and_reconciliation.py)
- [minicodex/tests/test_reliability_control_components.py](../minicodex/tests/test_reliability_control_components.py)
- [minicodex/tests/test_runtime_state_reducer.py](../minicodex/tests/test_runtime_state_reducer.py)
- [minicodex/tests/test_semantic_control_plane.py](../minicodex/tests/test_semantic_control_plane.py)
- [minicodex/tests/test_validate_static_web.py](../minicodex/tests/test_validate_static_web.py)
- [minicodex/tests/test_validation_integration.py](../minicodex/tests/test_validation_integration.py)
- [minicodex/tests/test_validation_pipeline.py](../minicodex/tests/test_validation_pipeline.py)
- [minicodex/tests/test_working_summary.py](../minicodex/tests/test_working_summary.py)
- [minicodex/tests/unit/orchestration/test_phase_context.py](../minicodex/tests/unit/orchestration/test_phase_context.py)
- [minicodex/tests/unit/progress/test_phase_policy.py](../minicodex/tests/unit/progress/test_phase_policy.py)
- [minicodex/tools/execution/run_command.py](../minicodex/tools/execution/run_command.py)
- [minicodex/tools/planning/__init__.py](../minicodex/tools/planning/__init__.py)
- [minicodex/tools/registry.py](../minicodex/tools/registry.py)
- [minicodex/tools/validation/validate_browser_app.py](../minicodex/tools/validation/validate_browser_app.py)
- [minicodex/tools/validation/validate_static_web.py](../minicodex/tools/validation/validate_static_web.py)

## 3. 删除文件

- `minicodex/tests/test_complete_plan_step.py`
- `minicodex/tools/planning/complete_plan_step.py`

删除的是过时的手动计划完成工具及其包装测试，未删除用户业务文件。
旧版本可从上述 Git 基线恢复；没有保留旧入口兼容包装。

## 4. 验证架构

需求 → ValidationPlanner → ValidationPlan → 工具执行 → ValidationPipeline
→ ValidationLedger → RequirementEvidenceResolver → TaskCompletionPolicy。

Pipeline 保留结果规范化、失败身份/基线比较；下一步策略迁至
`validation/decision_policy.py`。工具成功、编辑成功、单个测试通过都不等于任务完成。

## 5. ValidationPlan / ValidationLedger

`validation/plan.py` 的不可变检查包含 ID、需求 ID、purpose、目标、
capability、required、strength、revision、milestone、reason。
`validation/ledger.py` 是唯一验证历史存储；绿色布尔值为派生属性，不再直接写入。

每次已记录物理编辑推进 revision，默认让旧证据全部失效。
同 revision、同验证 key 出现矛盾时标记不稳定；采用有界一致复验，
而不是立即修复/回滚。基线保留失败身份，不能仅用失败数量判断是否回归。

## 6. 需求与证据绑定

多需求任务通过工具 schema 的 `validation_check` 明确绑定 V1/V2 等。
仅真正单一候选检查可省略绑定。R1 PASS 不能填满 R2；
编辑文件不再直接满足文件或文档需求。

检查首次获得足够强度的确定结果后锁定目标，不能失败后偷偷改验另一个目标。
HTTP 路径、请求体、状态/内容断言共同参与目标身份，
因此同一个 /login 的无效密码和有效密码可以分别证明。

完成需要全部 required 检查的当前证明。语义需求有独立分类，
但任意自然语言与断言之间的语义充分性仍有边界，见第 23 项。

## 7. WorkUnit

`editing/work_unit.py` 将显式多路径目标下的相关修改聚合为轻量工作单元。
每次修改仍独立推进 revision；多文件中间态可暂缓 Python 语法检查。
默认最多 8 次编辑，之后必须进入验证；里程碑会检查已改 Python 文件，
确定的验证结果关闭单元。单文件任务不采用额外事务流程。

## 8. EditIntent / PostEditVerification

`editing/edit_intent.py` 将预期路径、文本、删除文本、符号和显式允许范围
与 patch/write 机制分开。Checkpoint executor 在物理成功后验证意图，
并把未解决问题加入完成阻断条件。

DiffQualityGate 检查显式范围不符、保护目录、大量删除、
超大重写、新增重复导入/定义、移除断言与跳过测试。
Python 符号使用 AST 验证。合法修改测试契约需要原始用户授权；
被本任务修改的单个测试不能自动作为唯一充分证明。

零退出码本身不证明行为；`echo tests passed`、常量真断言、
移除断言的 Python 优化模式和普通 curl 请求不能满足行为强度。

## 9. ProjectProfile / CodebaseConventions

`context/workspace_session.py` 识别 Python/JS/TS/HTML、
pyproject/package.json、pip/uv/npm/pnpm/yarn、代表性框架、
测试工具及 manifest 中配置的 test/lint/typecheck/build/start/dev 命令。
容忍不完整的 package.json。

约定来自源码样例：异步函数、返回类型标注、snake_case、
pytest fixture、模块 logger、异常处理。不会把未观察到的风格声明为项目规则。

## 10. ChangeImpact / 导航

同一文件提供有界 ChangeImpactResolver，组合目标、导入、
依赖者、相关测试和邻近文件，进入 ContextBuilder 的 LOCATE → EXPAND → READ 提示。
Python 支持绝对/相对导入及 src/lib 布局；JS 支持常见相对导入。

TestIndex 不再只扫描 MiniCodex 和根 tests 两个目录，支持嵌套测试目录。
RepoMap 不再每个 Standard 回合强制重建；SymbolIndex/TestIndex 使用修订缓存。

## 11. 工具 capability 迁移

`tools/registry.py` 提供能力及执行元数据，包括 retry-safe/idempotent。
工具暴露、动作分类、检查点、编辑/验证事件、安全评估优先使用 capability；
不同名称的同能力适配器走同一规范化路径。

没有引入 MCP 或 Multi-Agent。具体参数解析、replan 和安装依赖等特殊操作
仍保留必要的工具专属逻辑，不宣称所有工具名称分支已消失。

## 12. ToolBatchRunner 拆分

`tool_batch_runner.py` 缩为 24 行，负责有序批次和交接；
`tool_event_adapter.py` 处理工具事实到需求/计划/内存/验证/恢复事件的领域交接；
`tool_batch_result.py` 定义结果。
沿用现有消息协议关闭器，恢复或重启前为全部已声明 tool_call_id 补齐响应。

## 13. TaskRuntime / 事件状态

TaskState 是 frozen snapshot，生产状态变更通过 RuntimeEvent/reducer。
删除旧直接写入和可变快照更新路径。WorkUnit、编辑问题、外部工作区变化、
取消和回滚通过事件同步。架构测试扫描越过 reducer 的 TaskState 字段写入，
另用独立解释器检查关键域导入，防止同进程测试掩盖循环依赖。

## 14. Verification Ladder

`validation/ladder.py` 表达结构、lint/typecheck、针对性测试、
相关回归、build、运行时、全量回归七级强度。
Planner 将观察到的 lint/build 命令加入 required 检查。
交互 HTML/game 需求要求 browser runtime 强度；
RegressionPolicy 根据风险/范围判断，FAST auth 仍需要相关回归，
README-only 不强制无关全量测试。

回归范围由现有 RegressionPolicy/Selector 配合计划决定，不仅取决于模式。

## 15. ManagedProcess

`runtime/managed_process.py` 复用 SandboxRunner 的环境、资源限制和临时目录。
生命周期：启动独立进程组 → 轮询 ready → HTTP 断言 → 停止/清理。
有总时限、取消传播、32KB 日志与 64KB 响应上限；拒绝已被占用的端口。
清理覆盖父进程退出后仍存活的同组子进程。

`validate_service.py` 注册为真实工具，支持 loopback HTTP、
JSON 请求体、状态码及内容断言，401 等响应可正常验证。
禁止重定向离开服务；环境/启动失败不等同于代码失败。
测试实际启动服务并验证成功、超时、取消、子进程清理和端口拒绝。

## 16. WorkspaceSession / 连续任务

MiniCodexAgent 复用 WorkspaceSession 中的 profile、约定、
索引和相关文件；每次 run 重建任务需求、计划、ledger 与恢复状态。
连续任务测试确认不复用上一任务的绿色证据和 blocker。

工具调用/上下文前检查文件指纹，外部变化使当前证据失效。
会执行进程的验证完成后也重新检查；若验证期间文件变化，
结果标为 inconclusive，必须基于新 revision 复验。

## 17. 安全撤销与干预

`agent.undo_task()` 使用现有检查点反向恢复整个最近任务。
先验证完整链及当前文件；任务前已有修改会被保留。
并发修改、两次 agent 编辑间插入的用户修改、被裁剪的历史都会阻止不安全撤销。
不使用 git reset，不自动覆盖并发内容。

Safety 增加 AUTONOMOUS / APPROVAL / CLARIFICATION 分类及宿主 hook。
普通操作继续自动执行；hook 不能静默覆盖硬安全拒绝。
此处是宿主集成接口，不是新增交互式审批 UI。

## 18. VibeBench

`evaluation/vibebench.py` 使用唯一 EvaluationHarness。
脚本只替换模型，真实编辑、命令、pytest、HTTP 服务和完成门禁都执行。

15 类场景：tiny edit、already satisfied、create、unknown repository、
local repair、multi-file requirements、local bug、small feature、Python CLI、
refactor、API service、HTML page、dependency constraint、failing test、follow-up。
可注入 model_factory 选择真实模型，默认无付费 API 调用。

## 19. 行动效率指标

记录首次编辑时间/前置检查搜索数、工具/模型调用、token、
重复读取/搜索、错文件/错验证目标、验证/编辑比、无进展、
耗尽、回滚、恢复和可选美元成本。

最终离线样本：15/15 成功，0 误完成；主模型/工具调用均为 2.47 次/成功任务，
控制模型调用 0；成功用时中位数 0.0535 秒、首次编辑中位数 0.00744 秒。
错文件、错目标、重复工具、耗尽、回滚率均为 0。

脚本 token 为合成计数，不是模型实测；美元成本为 null，不伪造价格。
当前恢复成功指标统计恢复控制路径，普通 fail→local repair 不一定计入该计数；
该样本的 recovery_success_rate 为 0，不能解释成 local_repair 场景失败。

## 20. 测试新增/迁移

`test_vibecoding_runtime.py` 覆盖需求隔离/目标锁定/强度/陈旧证据、
flaky、反作弊、WorkUnit、profile、嵌套索引、意图/diff、
能力别名、冻结状态、风险、撤销、服务、session 和 15 场景端到端。
`test_canonical_architecture.py` 增加状态写入、唯一实现路径、
领域依赖及 fresh-interpreter 导入断言。

旧验证测试改为真实记录 evidence；旧状态测试改为发出事件。
保留原有 baseline/failure identity、恢复、工具批次协议等回归测试。

## 21. 实际执行的验证命令

以下在仓库实际 Python 环境运行；socket 测试经授权在沙箱外运行。
未调用外部付费模型。

```sh
python -m pytest -q minicodex/tests/test_vibecoding_runtime.py minicodex/tests/test_runtime_state_reducer.py minicodex/tests/test_working_summary.py --tb=short
python -m pytest -q minicodex/tests/test_vibecoding_runtime.py minicodex/tests/test_canonical_architecture.py minicodex/tests/unit/validation/test_test_index.py --tb=short
python -m pytest -q --tb=line
python -m compileall -q minicodex
git diff --check
python -m minicodex.evaluation.vibebench | tail -75
python -m minicodex.evaluation.vibebench | python -c 'import json,sys; report=json.load(sys.stdin); print(json.dumps({key: value for key, value in report.items() if key != "results"}, indent=2))'
rg -n 'complete_plan_step|class ValidationState|compatibility shim' minicodex/agent minicodex/tools minicodex/main.py
```

另外执行过验证工具、安全/检查点及其他受影响域的定向测试。
上述 stale-reference 搜索生产路径无匹配；测试中保留“旧模块不存在”的否定断言。

## 22. 最终结果

| 检查 | 结果 |
| --- | --- |
| 完整 pytest | 555 passed in 12.53s |
| VibeBench | 15 passed / 0 failed |
| compileall | exit 0 |
| git diff --check | exit 0 |
| 独立导入/状态架构测试 | 包含于通过的完整测试 |
| 生产旧接口搜索 | 无匹配 |

没有将环境失败隐藏为通过。没有提交或推送这些改动。

## 23. 真实剩余边界

- 未做真实模型成功率/成本实验，也未执行真实浏览器 UI 交互验收。
  Browser 工具测试有替身；实际运行需要现有可选 Playwright 后端。
- 需求提取和验证目标选择仍依赖模型/有限启发式。显式绑定和强度是确定性门禁，
  但不能自动证明任意文档语义正确，或证明任意用户提供的测试没有遗漏/弱化。
- 导航有明确规模界限：session 扫描最多 1500 文件、约定/依赖扫描最多 80 源文件，
  TestIndex 最多遍历 2000 文件。没有完整 JS/TS 类型级调用图；
  超出有界扫描的并发文件变化也不能由该指纹保证发现。
- 外部变更检测是 stat 指纹而非文件系统事务/锁；不能保证检查与完成之间绝无竞争。
  整任务撤销仅覆盖检查点化编辑；任意子进程副作用不承诺可撤销。
- 服务隔离继承已有进程沙箱，不是内核级文件系统/网络隔离。
  进程组清理面向 POSIX；端口启动前检查不是无竞态的 OS socket 所有权证明。
  当前服务工具为有界 HTTP 生命周期，不提供常驻 daemon 或自动前端浏览器生命周期编排。
- WorkUnit 基于当前显式目标自动形成，不是任意自然语言语义边界的完美分组器。
  显式范围检查不能替代对“哪些关联文件允许修改”的语义判断。
- 具体 validator 参数、少量控制操作仍存在名称相关逻辑；
  ToolEventAdapter 保留领域协调，未再创建第二套执行 Harness。
- 离线用例规模较小，不能仅凭 555 项测试与 15 个脚本场景声称已经满足所有生产环境。

## 第二轮可靠性收尾（当前 HEAD）

1. 已在当前 `demo_game_try` 工作树检查 HEAD（`e96f772`），未基于旧报告假设实现。
2. 新增 `validator_resolver.py`、`tool_result_handlers.py`、`real_vibebench.py` 与 CI workflow。
3. 修改需求、验证、会话、编排、能力元数据及其测试；具体清单以本次 Git diff 为准。
4. 删除过时的 `validation/selector.py`，没有保留第二套选择器。
5. `TaskRequirement` 统一为 description/category/kind/paths/observable；提取 schema 与提示词要求相同字段。
6. `ValidationPlanner` 将 Ladder 的可执行 rung 物化为带 capability、强度、里程碑、observable 的检查；无关 README 不加回归。
7. `ValidatorResolver` 以缺失检查和 registry capability 选择工具/精确参数；服务命令仅在 profile 提供带 `{port}` 的安全模板时解析。
8. `ValidationDecisionPolicy` 先返回下一条未证明的 required check；旧全量枚举只保留给无计划的窄兼容路径。
9. `ValidationLedger` 保持证据真相；TaskState 的 validation 字段仅由验证事件投影。
10. WorkUnit 仅在其 milestone checks 都有当前 revision 证明时完成，语法检查不会提前关闭行为工作单元。
11. Edit/validation 的领域反应已移至独立 result handlers；adapter 只保留批次协议和事件转接。
12. 内建工具声明 capability；registry 的 legacy 标签仅位于第三方/旧测试工具边界，编排读取 capability 而非该映射。
13. WorkspaceSession 对 agent-owned dirty path 增量刷新，未变化回合按周期抽样外部变更，避免每次 context 全量扫描。
14. ContextBuilder 仅提示当前 phase 的下一动作、WorkUnit、失败或缺失 check，并将历史记忆限制为 advisory 短片段。
15. `vibebench.py` 归类为 deterministic HarnessBench；`real_vibebench.py` 要求 provider-neutral `model_factory`，CI 不调用它。
16. 新增 GitHub Actions：安装测试依赖、pytest、compileall，且不调用实时模型。
17. 新增/更新测试覆盖 schema、semantic docs、ladder materialization、resolver、missing check、WorkUnit、增量 session 与 opt-in RealVibeBench。
18. 实际执行：`python -m pytest -q --tb=line`、`python -m compileall -q minicodex`、`git diff --check`。
19. 最终结果：**559 passed in 13.23s**（服务端口测试以受控本机权限运行）；compileall 和 diff 空白检查通过。
20. 剩余限制：没有在 CI/本次交付中运行付费真实模型；无法从安全 profile 命令推导服务启动 argv 时，resolver 会拒绝编造参数并保留该检查待模型提供精确调用。
