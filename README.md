# MiniCodex

MiniCodex 是一个面向本地代码仓库的轻量级自主编码代理。它使用 DeepSeek（或兼容 OpenAI Chat Completions API 的服务）理解任务，并通过受控的文件、搜索、执行、测试和验证工具完成代码修改。

项目的核心原则是：**让模型负责语义理解和策略，让确定性的 Harness 负责事实、权限、安全、执行、验证、恢复与完成判定。**

> 当前版本为早期开发版（`0.1.0`）。运行代理前，建议先提交或备份工作区中的重要改动。

## 主要能力

- 根据任务语义区分信息咨询、只读检查和代码修改任务。
- 自动选择 `FAST`、`STANDARD` 或 `COMPLEX` 执行模式，并在必要时升级模式。
- 浏览仓库、读取文件、搜索代码和 Python 符号。
- 创建文件，应用精确补丁，替换行区间或 Python 符号。
- 执行命令、运行测试，并按改动范围选择验证方式。
- 为 Python 项目识别缺失依赖，并通过受控工具安装包。
- 验证静态 Web 页面；安装 Playwright 后可执行基础浏览器交互验证。
- 使用 checkpoint、重试和 rollback 处理失败修改，同时避免覆盖外部并发改动。
- 保存运行 trace 和长期任务经验，便于定位代理为何作出某个决定。

## 工作流程

```text
用户任务
   ↓
语义路由与需求提取
   ↓
检查仓库 → 规划（按需）→ 修改
   ↓
针对性验证 → 回归验证 → 修复/恢复
   ↓
确定性完成检查 → 任务报告
```

模型不能仅通过回复“已完成”结束修改任务。MiniCodex 必须观察到实际改动并取得相应的验证证据，或者验证用户要求的状态本来就已经存在。

## 环境要求

- Python 3.11 或更高版本
- DeepSeek API Key，或兼容 OpenAI Chat Completions API 的模型服务
- Git（推荐，用于工作区状态检查和差异查看）

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

如果还需要运行测试：

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

还可以为控制面和语义回归判断指定独立模型；未配置时会复用主模型：

```dotenv
DEEPSEEK_CONTROL_MODEL=deepseek-chat
DEEPSEEK_JUDGE_MODEL=deepseek-chat
```

不要将真实 API Key 提交到 Git。项目已忽略 `.env` 文件。

### 4. 启动交互式 CLI

```bash
python -m minicodex.main --output normal
```

也可以在安装后直接运行：

```bash
minicodex
```

启动后输入自然语言任务，例如：

```text
You > 检查登录接口的异常处理，只分析问题，不要修改代码
You > 给用户注册接口增加邮箱格式校验，并运行相关测试
You > 在 try_code 中创建一个可以直接打开运行的贪吃蛇页面
```

输入 `exit` 或 `quit` 退出。

## 输出级别

通过模块启动时，可以使用 `--output` 控制终端信息量：

| 级别 | 用途 |
| --- | --- |
| `normal` | 只显示面向用户的主要结果 |
| `verbose` | 额外显示执行和阶段信息 |
| `debug` | 额外显示内部结果标识、trace 摘要和长期记忆统计 |

示例：

```bash
python -m minicodex.main --output debug
```

## 可选：浏览器验证

默认的静态 Web 验证可以检查 HTML 结构、内联语法和静态要求，但不能证明点击、键盘操作或游戏状态确实正常。需要真实浏览器验证时，安装 Playwright：

```bash
python -m pip install playwright
playwright install chromium
```

Playwright 可用时，MiniCodex 会自动注册浏览器验证工具；不可用时会继续使用静态验证。

## 安全与执行边界

- 当前 CLI 的工作区固定为本项目根目录，文件访问会经过路径规范化和工作区边界检查。
- 只读任务不会获得编辑或依赖安装能力。
- 文件修改、命令执行和包安装都会经过权限与安全策略检查。
- 命令在带有超时、输出大小、文件大小、CPU 和内存限制的 sandbox 中运行。
- rollback 只恢复代理自身 checkpoint 覆盖的内容；如果检测到 checkpoint 之后的外部修改，会拒绝覆盖。
- 自动安装功能目前面向 Python 包，并不代表代理可以绕过网络、系统权限或项目安全策略。

## 运行产物

MiniCodex 会在项目根目录的 `.minicodex/` 下保存运行时数据：

```text
.minicodex/
├── memory/long_term.json   # 跨任务经验记录
├── traces/latest.jsonl     # 最近一次运行的结构化 trace
└── sandbox/                # sandbox 运行数据
```

这些文件是本地运行产物，默认不会提交到 Git。长期记忆是辅助缓存，物理工作区始终是事实来源；进程重启后不会假装恢复一个未完成任务。

## 项目结构

```text
minicodex/
├── main.py                 # CLI 与依赖组装入口
├── llm/                    # 模型客户端和响应类型
├── prompts/                # 系统提示词
├── agent/
│   ├── agent.py            # MiniCodexAgent 门面与组合根
│   ├── orchestration/      # 主循环、工具批次、完成报告
│   ├── routing/            # 意图、模式和执行策略
│   ├── planning/           # 需求、计划和重规划
│   ├── validation/         # 验证、测试定位和回归策略
│   ├── editing/            # 编辑恢复、checkpoint 和 rollback
│   ├── safety/             # 权限、安全执行和 sandbox
│   ├── runtime/            # 工具执行、异步任务和取消
│   ├── context/            # 仓库地图、符号索引和上下文预算
│   ├── memory/             # 工作记忆和长期记忆
│   ├── progress/           # 进度与停滞控制
│   └── observability/      # trace、指标、脱敏和输出级别
├── tools/                  # 暴露给模型的受控工具
├── evaluation/             # 行为与可靠性评估数据
└── tests/                  # 单元、集成和 benchmark 测试
```

更完整的设计说明参见 [docs/architecture.md](docs/architecture.md)。

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

开发时应保持以下架构边界：

- `utils` 不依赖 agent 领域模块。
- `tools` 不依赖 orchestration。
- orchestration 负责协调领域 API，而不是复制领域规则。
- 每个核心概念只有一个 canonical import path，不添加旧模块兼容包装层。
- 模型负责语义判断；安全、预算、权限、验证证据与完成条件保持确定性。

## 当前限制

- CLI 目前是单进程交互式会话，工作区固定为 MiniCodex 自身仓库。
- 进行中的任务状态和 checkpoint 只存在于当前进程内，进程崩溃后不能续跑。
- 浏览器验证依赖可选的 Playwright 和本机 Chromium。
- 模型服务、网络状态、第三方包源和操作系统权限仍可能导致任务失败。
- 自动化验证只能降低风险，不能代替代码审查和真实环境测试。

## License

仓库当前未声明开源许可证。在添加许可证前，请勿默认将本项目视为可自由再分发的软件。
