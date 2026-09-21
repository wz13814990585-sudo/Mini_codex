# Vibecoding 重构交付报告

| 项目 | 说明 |
| --- | --- |
| 分支 | `demo_game_try` |
| 改动前基线 | `e3510ac` |
| 最新完整回归 | **654 passed in 21.63s** |
| 离线 VibeBench | **15/15**，误完成率 **0** |
| 在线 R2 smoke | **8/8**，误完成 / 错验证目标 / 步数耗尽均为 **0** |
| 编译 / diff 检查 | `compileall`、`git diff --check` 通过 |

以上结果只证明本地自动化覆盖内的行为，**不代表**真实模型或任意仓库的生产可靠性已经得到验证。

---

## 1. 文件变更概览

### 新建

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

后续轮次还新增了：`validator_resolver.py`、`tool_result_handlers.py`、`real_vibebench.py`、`workspace.py`、`verification_spec.py`、`validate_semantic.py`、`real_repo_bench.py` 等（以当前 Git 树为准）。

### 修改

主要覆盖：`docs/architecture.md`、`agent` 编排 / 验证 / 编辑 / 安全 / 运行时、`tools`、`evaluation`、`main.py` 以及大量相关测试。完整清单见历次 Git diff。

### 删除

- `minicodex/tests/test_complete_plan_step.py`
- `minicodex/tools/planning/complete_plan_step.py`
- `minicodex/agent/validation/selector.py`（后续轮次删除，未保留第二套选择器）

删除的是过时的手动计划完成工具及旧选择器，未删除用户业务文件。旧版本可从 Git 基线恢复；没有保留旧入口兼容包装。

---

## 2. 核心架构

### 验证链路

```text
需求 → ValidationPlanner → ValidationPlan → 工具执行 → ValidationPipeline
    → ValidationLedger → RequirementEvidenceResolver → TaskCompletionPolicy
```

- Pipeline 负责结果规范化、失败身份与基线比较
- 下一步策略在 `validation/decision_policy.py`
- 工具成功、编辑成功、单个测试通过，都不等于任务完成

### ValidationPlan / ValidationLedger

- `validation/plan.py`：不可变检查，含 ID、需求 ID、purpose、目标、capability、required、strength、revision、milestone、reason
- `validation/ledger.py`：唯一验证历史存储；绿色布尔值是派生属性，不再直接写入
- 每次已记录的物理编辑会推进 revision，并默认让旧证据失效
- 同 revision、同验证 key 出现矛盾时标记不稳定；采用有界一致复验，而不是立即修复 / 回滚
- 基线保留失败身份，不能只用失败数量判断是否回归

### 需求与证据绑定

- 多需求任务通过工具 schema 的 `validation_check` 明确绑定（如 V1 / V2）
- 仅真正单一候选检查可省略绑定
- R1 PASS 不能填满 R2；编辑文件不再直接满足文件或文档需求
- 检查首次获得足够强度的确定结果后锁定目标，不能失败后偷偷改验另一个目标
- HTTP 路径、请求体、状态 / 内容断言共同参与目标身份
- 完成需要全部 required 检查的当前证明

---

## 3. 编辑与工作单元

### WorkUnit

`editing/work_unit.py` 将显式多路径目标下的相关修改聚合为轻量工作单元。

- 每次修改仍独立推进 revision
- 多文件中间态可暂缓 Python 语法检查
- 默认最多 8 次编辑，之后必须进入验证
- 里程碑只绑定 `milestone == "work_unit"` 的检查；task-level runtime / regression 不会误卡住 edit boundary
- 单文件任务不走额外事务流程

### EditIntent / 编辑后验证

`editing/edit_intent.py` 将预期路径、文本、删除文本、符号和显式允许范围与 patch / write 机制分开。Checkpoint executor 在物理成功后验证意图，并把未解决问题加入完成阻断条件。

DiffQualityGate 会检查：

- 显式范围不符、保护目录、大量删除、超大重写
- 新增重复导入 / 定义、移除断言与跳过测试
- Python 符号使用 AST 验证

合法修改测试契约需要原始用户授权；被本任务修改的单个测试不能自动作为唯一充分证明。零退出码本身不证明行为；`echo tests passed`、常量真断言、移除断言的「优化」与普通 curl 请求，都不能满足行为强度。

---

## 4. 上下文、导航与能力

### ProjectProfile / 约定

`context/workspace_session.py` 识别：

- 语言：Python / JS / TS / HTML
- 清单：pyproject / package.json
- 包管理：pip / uv / npm / pnpm / yarn
- 代表性框架、测试工具，以及 manifest 中配置的 test / lint / typecheck / build / start / dev 命令

约定来自源码样例（异步函数、返回类型标注、snake_case、pytest fixture、模块 logger、异常处理），不会把未观察到的风格声明为项目规则。

### ChangeImpact / 导航

同一文件提供有界 ChangeImpactResolver，组合目标、导入、依赖者、相关测试和邻近文件，进入 ContextBuilder 的 LOCATE → EXPAND → READ 提示。

- Python：支持绝对 / 相对导入及 src / lib 布局
- JS：支持常见相对导入
- TestIndex 支持嵌套测试目录，不再只扫固定目录
- RepoMap 不再每个 Standard 回合强制重建；SymbolIndex / TestIndex 使用修订缓存

### 工具 capability

`tools/registry.py` 提供能力及执行元数据（含 retry-safe / idempotent）。工具暴露、动作分类、检查点、编辑 / 验证事件、安全评估优先使用 capability。没有引入 MCP 或 Multi-Agent。

### ToolBatchRunner 拆分

| 模块 | 职责 |
| --- | --- |
| `tool_batch_runner.py` | 有序批次与交接（约 24 行） |
| `tool_event_adapter.py` | 工具事实到需求 / 计划 / 内存 / 验证 / 恢复事件的领域交接 |
| `tool_batch_result.py` | 结果定义 |

沿用现有消息协议关闭器，在恢复或重启前为全部已声明 `tool_call_id` 补齐响应。

---

## 5. 运行时、服务与会话

### TaskRuntime / 事件状态

- TaskState 是 frozen snapshot，生产状态变更通过 RuntimeEvent / reducer
- 已删除旧的直接写入与可变快照更新路径
- WorkUnit、编辑问题、外部工作区变化、取消和回滚通过事件同步
- 架构测试会扫描越过 reducer 的 TaskState 字段写入，并用独立解释器检查关键域导入

### Verification Ladder

`validation/ladder.py` 表达七级强度：结构 → lint / typecheck → 针对性测试 → 相关回归 → build → 运行时 → 全量回归。

- Planner 将观察到的 lint / build 命令加入 required 检查
- 交互 HTML / game 需求要求 browser runtime 强度
- RegressionPolicy 按风险 / 范围判断：FAST auth 仍需相关回归；README-only 不强制无关全量测试

### ManagedProcess / 服务验证

`runtime/managed_process.py` 复用 SandboxRunner 的环境、资源限制和临时目录。生命周期：启动独立进程组 → 轮询 ready → HTTP 断言 → 停止 / 清理。

- 有总时限、取消传播、32KB 日志与 64KB 响应上限
- 拒绝已被占用的端口；清理覆盖父进程退出后仍存活的同组子进程
- `validate_service.py` 支持 loopback HTTP、JSON 请求体、状态码及内容断言

### WorkspaceSession / 连续任务

`MiniCodexAgent` 复用 WorkspaceSession 中的 profile、约定、索引和相关文件；每次 run 重建任务需求、计划、ledger 与恢复状态。连续任务不复用上一任务的绿色证据和 blocker。

工具调用 / 上下文前检查文件指纹；外部变化使当前证据失效。验证期间若文件变化，结果标为 inconclusive，必须基于新 revision 复验。

### 安全撤销与干预

- `agent.undo_task()` 使用现有检查点反向恢复整个最近任务
- 不使用 `git reset`，不自动覆盖并发内容
- Safety 增加 AUTONOMOUS / APPROVAL / CLARIFICATION 分类及宿主 hook
- hook 不能静默覆盖硬安全拒绝（这是宿主集成接口，不是新增交互式审批 UI）

---

## 6. 评估与指标

### VibeBench / RealRepoBench

- `evaluation/vibebench.py`：确定性 HarnessBench，15 类场景；默认无付费 API 调用
- `real_vibebench.py`：要求 provider-neutral `model_factory`，CI 不调用
- `RealRepoBench`：提供明确的 Python / FastAPI / HTML / TypeScript 本地 fixture；oracle 写在 agent workspace 外的独立目录

### 真实模型 smoke 反馈闭环

30 场景在线结果曾为 26/30。四个失败中，三个来自过窄 oracle：把合法 TypeScript 当纯 JavaScript data URL 执行、DOM stub 不支持 `querySelector`、以及只接受 `addEventListener` 而拒绝 `onclick`。这些已在 `minicodex-bench-v1-r2` 修正并增加回归用例。

剩余真实误完成来自 `fix_python_sort_key`：弱验收在编辑前碰巧通过，系统忽略了 `no_edit_if_already_satisfied=false` 并直接结束。当前完成门禁已接入该策略；零编辑完成权限由用户原文确定性派生，不能由控制模型自行放宽。Requirement path 也会对齐显式目标及已有 `src/` / `lib/` 布局，避免创建重复顶层包。

修复后的 `minicodex-bench-v1-r2` 在线 smoke（DeepSeek `deepseek-chat`，temperature 0，单次运行）为 8/8。`fix_python_sort_key` 从旧结果的零编辑误完成变为一次正确 patch 后通过；`create_calculator_service` 从旧 trace 的 6 次编辑降为严格位于 `src/calculator/` 的 2 次编辑。平均每题 3.5 次 LLM 调用、7207.6 tokens、6.97 秒。原始结果位于 `benchmark_results/minicodex-bench-v1-r2/product_gate_r2_online/`。

随后在 commit `b54a61c` 上执行了完整 30 题单次在线 R2：26/30（86.67%），错误完成与越权编辑均为 0。四个失败的隐藏 oracle 实际全部通过，但完成门禁因内部验收未通过而安全停止。其中三个 Flask 场景复现为子进程 `Flask.test_client()` 的 `SIGSEGV (-11)`；另一个折扣边界场景由“越界仍返回非负值”和“越界必须抛 ValueError”两个互相矛盾的提取契约造成。运行后已改为对 Flask 使用受控回环服务探测，并增加边界异常契约一致性清理。成功用例复盘还发现旧指标会漏报“改对文件同时又改了无关文件”，现已改为逐个检查 allowed scope；JSON fragment 也改用结构化验证，Python contract 会按真实 import 锚定已有源码。原始结果位于 `benchmark_results/minicodex-bench-v1-r2/product_full_r2_online/`。

在 commit `b3d9978` 上对 6 个受影响场景做定向在线复测，结果为 2/6。该轮确认折扣边界和 Node test-script 场景已通过，同时暴露两个新的确定性边界缺陷：Harness 的 `purpose` 元数据被错误透传给不声明该参数的 `ValidateServiceTool`，使三个 Flask 场景在编辑前后被 `TypeError` 阻塞；Python contract 在“真实路径 + 幻觉路径”混合时仍保留不存在的 `calculator.js`，导致跟进场景 oracle 通过但被正确判为 wrong-file。当前已在统一工具执行边界按 backend schema 过滤内部元数据，并让 Python import 锚点清理混合幻觉路径。定向结果位于 `benchmark_results/minicodex-bench-v1-r2/product_r2_targeted_after_validation_fix/`；最新修复尚未再次调用在线模型。

### 行动效率指标

记录首次编辑时间、前置检查 / 搜索数、工具 / 模型调用、token、重复读取 / 搜索、错文件 / 错验证目标、验证 / 编辑比、无进展、耗尽、回滚、恢复和可选美元成本。

离线样本参考值（早期轮次）：15/15 成功，0 误完成；主模型 / 工具调用约 2.47 次 / 成功任务。脚本 token 为合成计数，不是模型实测。

---

## 7. 产品化与工作区可靠性

- `WorkspaceConfig` 区分 application root、target workspace、runtime / sandbox / trace root 和稳定 repository key
- `minicodex` 默认使用当前目录，`--workspace PATH` 选择任意存在目录
- CLI 注册的文件、编辑、命令、测试、Web、Git、索引、checkpoint 工具共享 selected workspace
- Planner 不会因 capability 缺失丢弃 required rung；Resolver 返回 resolved / capability-missing / target-unresolved
- `ValidationCheck.spec` 使用 typed union：文件、测试、命令、HTTP、浏览器、语义
- Browser spec 必须提供 selector、动作和 post-action assertion
- `validation.semantic` 先做确定性字面内容证明，再使用无工具、受限 JSON judge
- `.minicodex` 被 RepoMap 忽略并受 Safety 保护，不能作为普通 edit target
- 目标项目优先使用其 `.venv` / `venv`；识别 `uv.lock` / `poetry.lock`
- 验证循环在 prompt 渲染前准备当前 required check；`TARGET_UNRESOLVED` 仅允许一次限定侦察

---

## 8. 验证命令与结果演进

### 实际执行过的命令

```sh
python -m pytest -q --tb=line
python -m compileall -q minicodex
git diff --check
python -m minicodex.evaluation.vibebench
```

未调用外部付费模型。服务端口相关测试在受控本机权限下运行。

### 结果演进

| 阶段 | pytest | 备注 |
| --- | --- | --- |
| 首轮重构 | 555 passed / 12.53s | VibeBench 15/15 |
| 可靠性收尾 | 559 passed / 13.23s | 新增 Resolver / RealVibeBench / CI |
| 产品化收尾 | 566 passed / 13.17s | Workspace / typed Spec / Semantic |
| RealRepoBench 绑定 | 569 passed / 13.78s | SpecBinder / 项目执行环境 |
| 预真实测试集成 | 572 passed / 12.86s | 再绑定 / 参数校验 / 外置 oracle |
| 执行闭环 | 579 passed / 13.09s | 完成初始执行闭环 |
| 产品门禁与 R2 oracle | 654 passed / 21.63s | 离线 VibeBench 15/15 |
| Dogfood、发布门禁与完整 R2 修复 | 662 passed / 19.92s | 离线 VibeBench 15/15；Flask 服务端到端探测通过 |
| 成功用例质量口径收紧 | 665 passed / 20.11s | 逐路径 wrong-file、结构化 JSON、import 路径锚定 |
| 工具 schema 路径约束 | **666 passed / 20.70s** | 当前最新；读取与编辑路径在生成阶段即限制到当前契约范围 |
| 定向 R2 反馈修复 | **668 passed / 24.36s** | 当前最新；backend 元数据隔离、混合幻觉路径清理、服务进程竞态回收；离线 VibeBench 15/15 |

CI 只跑确定性 pytest / compileall，不调用真实模型。

---

## 9. 真实剩余边界

- 已做一次 30 题真实模型实验及一次 6 题定向复测，但最新边界修复尚未在线复测，也尚未做 3 次重复稳定性实验；未执行真实浏览器 UI 交互验收（可选 Playwright 不作为本次 CI 前提）
- 需求提取与验证目标选择仍依赖模型 / 有限启发式；显式绑定与强度是确定性门禁，但不能自动证明任意文档语义正确
- 导航有规模界限：session 扫描最多约 1500 文件，约定 / 依赖扫描最多约 80 源文件，TestIndex 最多约 2000 文件
- 外部变更检测是 stat 指纹，不是文件系统事务 / 锁；整任务撤销仅覆盖检查点化编辑
- 服务隔离继承已有进程沙箱，不是内核级文件系统 / 网络隔离；当前服务工具为有界 HTTP 生命周期
- WorkUnit 基于显式目标自动形成，不是任意自然语言语义边界的完美分组器
- 离线用例规模有限，不能仅凭数百项测试与脚本场景声称已满足所有生产环境

---

## 10. 相关文档

- 架构总览：[architecture.md](architecture.md)
- 项目使用说明：[../README.md](../README.md)
