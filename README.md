# MiniCodex

MiniCodex 是一个面向本地代码仓库的轻量级自主编码代理。它基于 DeepSeek（或兼容 OpenAI Chat Completions 的 API）理解任务，并通过受控的文件、搜索、执行、测试与验证工具完成代码修改。

核心理念：**模型负责语义理解与策略判断；确定性 Harness 负责事实、权限、安全、执行、验证、恢复与完成判定。**

> 当前版本为早期开发版（`0.1.0`）。运行代理前，请先提交或备份工作区中的重要改动。

## 主要能力

- 按任务语义区分信息咨询、只读检查与代码修改
- 自动选择 `FAST` / `STANDARD` / `COMPLEX` 执行模式，必要时可升级
- 浏览仓库、读取文件、搜索代码与 Python 符号
- 创建文件，应用精确补丁，替换行区间或 Python 符号
- 执行命令、运行测试，并按改动范围选择验证方式
- 识别 Python 项目的缺失依赖，并通过受控工具安装
- 验证静态 Web 页面；安装 Playwright 后可做基础浏览器交互验证
- 用 checkpoint、重试与 rollback 处理失败修改，并避免覆盖外部并发改动
- 保存运行 trace、reducer 事件与高价值长期经验，便于复盘决策过程

## 工作流程

```text
用户任务
   ↓
语义路由与需求提取
   ↓
检查仓库 → 规划（按需）→ 修改
   ↓
针对性验证 → 回归验证 → 修复 / 恢复
   ↓
确定性完成检查 → 任务报告
```

模型不能只靠回复「已完成」结束修改任务。MiniCodex 必须观察到实际改动并拿到相应验证证据，或者确认用户要求的状态本来就已经满足。

运行时只有一个控制面事实源：`TaskRuntime.state`。文件与工具结果先规范化为事件，再由 reducer 更新状态；上下文、完成判定与最终报告都读取同一状态。计划只是执行辅助，模型不需要手动维护计划步骤；当用户要求与当前版本验证已满足时，遗留的计划记账不会阻止结束。

```text
工具 / 工作区事实 → RuntimeEvent → TaskState → 上下文 → 模型动作
                         ↑                    ↓
                         └──── 安全执行与验证 ────┘
```

## 环境要求

- Python 3.11 或更高版本
- DeepSeek API Key，或兼容 OpenAI Chat Completions 的模型服务
- Git（推荐，用于工作区状态检查与差异查看）

## 快速开始

### 1. 创建虚拟环境

```bash
python3.11 -m venv .venv
source .venv/bin/activate
```

Windows PowerShell：

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
```

### 2. 安装 MiniCodex

普通安装：

```bash
python -m pip install -e .
```

若还需要跑测试：

```bash
python -m pip install -e ".[test]"
```

### 3. 配置模型

在项目根目录创建 `.env`：

```dotenv
DEEPSEEK_API_KEY=your_api_key_here
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
```

也可为控制面与语义回归判断指定独立模型；未配置时会复用主模型：

```dotenv
DEEPSEEK_CONTROL_MODEL=deepseek-chat
DEEPSEEK_JUDGE_MODEL=deepseek-chat
```

请勿把真实 API Key 提交到 Git。项目已忽略 `.env`。

### 4. 启动交互式 CLI

```bash
python -m minicodex.main --output normal
```

安装后也可直接运行：

```bash
minicodex
```

默认工作区是启动时的当前目录，也可显式指定：

```bash
minicodex --workspace /path/to/project --output verbose
# 或
python -m minicodex.main --workspace ../another-project
```

启动后输入自然语言任务，例如：

```text
You > 检查登录接口的异常处理，只分析问题，不要修改代码
You > 给用户注册接口增加邮箱格式校验，并运行相关测试
You > 在 try_code 中创建一个可以直接打开运行的贪吃蛇页面
```

输入 `exit` 或 `quit` 退出。

## 输出级别

通过 `--output` 控制终端信息量：

| 级别 | 用途 |
| --- | --- |
| `normal` | 只显示面向用户的主要结果 |
| `verbose` | 额外显示执行与阶段信息 |
| `debug` | 额外显示内部结果标识、trace 摘要与长期记忆统计 |

```bash
python -m minicodex.main --output debug
```

## 可选：浏览器验证

默认的静态 Web 验证可检查 HTML 结构、内联语法与静态要求，但无法证明点击、键盘操作或游戏状态是否真正正常。若需要真实浏览器验证，请安装 Playwright：

```bash
python -m pip install playwright
playwright install chromium
```

Playwright 可用时，MiniCodex 会自动注册浏览器验证工具。缺少它时，交互运行时证明会保持为未解决的 required check，不能被静态 HTML 验证替代，也不会错误完成。

## 安全与执行边界

- CLI 可针对任意选定的本地目录；文件访问、Git 检查、sandbox、索引与 checkpoint 都受该工作区边界约束
- 只读任务不会获得编辑或依赖安装能力
- 文件修改、命令执行与包安装都会经过权限与安全策略检查
- 命令在带有超时、输出大小、文件大小、CPU 与内存限制的 sandbox 中运行
- rollback 只恢复代理自身 checkpoint 覆盖的内容；若检测到 checkpoint 之后的外部修改，会拒绝覆盖
- 自动安装目前面向 Python 包，不代表代理可以绕过网络、系统权限或项目安全策略

## 运行产物

MiniCodex 会在**选定工作区**的 `.minicodex/` 下保存运行时数据。该目录会被 RepoMap 与索引忽略，不会作为项目源码或编辑目标：

```text
.minicodex/
├── memory/long_term.json   # 跨任务经验记录
├── traces/latest.jsonl     # 最近一次运行的结构化 trace
└── sandbox/                # sandbox 运行数据
```

这些文件是本地运行产物，默认不会提交到 Git。长期记忆只是辅助缓存，物理工作区始终是事实来源；进程重启后不会假装恢复一个未完成任务。

## 项目结构

```text
minicodex/
├── main.py                 # CLI 与依赖组装入口
├── llm/                    # 模型客户端与响应类型
├── prompts/                # 系统提示词
├── agent/
│   ├── agent.py            # MiniCodexAgent 门面与组合根
│   ├── orchestration/      # 主循环、工具批次、完成报告
│   ├── routing/            # 意图、模式与执行策略
│   ├── planning/           # 需求、计划与重规划
│   ├── validation/         # 验证、测试定位与回归策略
│   ├── editing/            # 编辑恢复、checkpoint 与 rollback
│   ├── safety/             # 权限、安全执行与 sandbox
│   ├── runtime/            # 工具执行、异步任务与取消
│   ├── context/            # 仓库地图、符号索引与上下文预算
│   ├── memory/             # 工作记忆与长期记忆
│   ├── progress/           # 进度与停滞控制
│   └── observability/      # trace、指标、脱敏与输出级别
├── tools/                  # 暴露给模型的受控工具
├── evaluation/             # 行为与可靠性评估数据
└── tests/                  # 单元、集成与 benchmark 测试
```

更完整的设计说明见 [docs/architecture.md](docs/architecture.md)。

## 开发与测试

运行全部测试：

```bash
python -m pytest -q
```

运行单个测试文件：

```bash
python -m pytest -q minicodex/tests/test_task_router.py
```

检查所有 Python 文件能否编译：

```bash
python -m compileall -q minicodex
```

开发时请保持以下架构边界：

- `utils` 不依赖 agent 领域模块
- `tools` 不依赖 orchestration
- orchestration 负责协调领域 API，而不是复制领域规则
- 控制器通过事件更新 `TaskRuntime`，不得在每轮重新拼装另一份任务真相
- 每个核心概念只有一个 canonical import path，不添加旧模块兼容包装层
- 模型负责语义判断；安全、预算、权限、验证证据与完成条件保持确定性

## 验证契约与当前限制

每个需求先产生独立 `ValidationCheck`（必须证明什么），再映射为 typed `VerificationSpec`（文件、测试、命令、HTTP、浏览器或语义断言），最后由 `ValidatorResolver` 选择已注册的 validator（如何证明）。没有可用工具或可靠目标时，检查仍是 required，任务会报告阻断，而不会悄悄删掉。语义验证是只读、无工具的受限评估；精确文字要求会优先走确定性内容证明。

HarnessBench 是确定性的 CI 安全工具序列测试。`RealVibeBench` 是 provider-neutral、必须显式传入模型工厂的真实模型入口；CI 不调用它，也不调用任何付费 API。

### 当前限制

- CLI 目前仍是单进程交互式会话；任务中断后不会续跑
- 进行中的任务状态与 checkpoint 只存在于当前进程内，进程崩溃后不能续跑
- 浏览器验证依赖可选的 Playwright 与本机 Chromium
- 模型服务、网络状态、第三方包源与操作系统权限仍可能导致任务失败
- 自动化验证只能降低风险，不能代替代码审查与真实环境测试

## 许可证

仓库当前未声明开源许可证。在添加许可证前，请勿默认将本项目视为可自由再分发的软件。
