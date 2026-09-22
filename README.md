# MiniCodex

**简体中文** · [English](README.en.md)

[![CI](https://github.com/wz13814990585-sudo/Mini_codex/actions/workflows/ci.yml/badge.svg)](https://github.com/wz13814990585-sudo/Mini_codex/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB)](https://www.python.org/)
[![Release](https://img.shields.io/github/v/release/wz13814990585-sudo/Mini_codex)](https://github.com/wz13814990585-sudo/Mini_codex/releases/latest)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

MiniCodex 是一个运行在本地代码仓库上的自主编程 Agent。它使用 DeepSeek 或其他兼容 OpenAI Chat Completions 的模型理解自然语言任务，并通过受控的浏览、搜索、编辑、命令、测试和验证工具完成代码修改。

它的核心边界是：**模型负责理解与决策，确定性 Harness 负责事实、权限、安全、执行、验证、恢复和最终完成判定。** 模型不能仅靠回复“已完成”结束修改任务。

> 当前公开版本：[`v0.4.1`](https://github.com/wz13814990585-sudo/Mini_codex/releases/tag/v0.4.1)（Alpha）。请先在已提交或已备份的工作区中使用。

## 为什么是 MiniCodex

| 能力 | 实现方式 | 用户价值 |
| --- | --- | --- |
| 仓库级编码 | 仓库地图、符号索引、相关路径和测试定位 | 不只生成片段，而是在真实项目中定位并修改代码 |
| 证据驱动完成 | 类型化验证契约、验证账本、独立完成门禁 | 没有当前版本的验证证据就不会宣称成功 |
| 安全编辑 | 工作区边界、安全策略、checkpoint、并发修改检测 | 限制文件范围，并避免回滚覆盖外部修改 |
| 有界恢复 | 失败分类、重读、重试、重规划和 rollback | 遇到过期上下文或测试失败时可以有限恢复 |
| 可观测运行 | JSONL trace、Token/调用指标、结构化任务报告 | 可以复盘 Agent 为什么读取、编辑、验证或停止 |
| 可重复评估 | 30 个隔离任务、隐藏 oracle、baseline 对照、发布门禁 | 用机器可判定结果衡量正确性，而不是只看模型文案 |

## 产品流程

```text
自然语言任务
    ↓
语义路由与需求提取
    ↓
仓库检查 → 按需规划 → 受控编辑
    ↓
针对性验收 → 相关回归 → 修复 / 恢复
    ↓
确定性完成门禁 → 结构化任务报告
```

运行时只有一个控制面事实源 `TaskRuntime.state`：

```text
工作区 / 工具事实 → RuntimeEvent → TaskState → 上下文 → 模型动作
                         ↑                    ↓
                         └──── 安全执行与验证 ────┘
```

## 快速开始

### 环境要求

- Python 3.11 或更高版本
- DeepSeek API Key，或兼容 OpenAI Chat Completions 的模型服务
- Git（推荐，用于状态和差异检查）

### 1. 安装

从源码安装：

```bash
git clone https://github.com/wz13814990585-sudo/Mini_codex.git
cd Mini_codex
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Windows PowerShell：

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .
```

也可以直接安装 `v0.4.1` wheel：

```bash
python -m pip install \
  https://github.com/wz13814990585-sudo/Mini_codex/releases/download/v0.4.1/mini_codex-0.4.1-py3-none-any.whl
```

开发和测试依赖：

```bash
python -m pip install -e ".[test]"
```

### 2. 配置模型

```bash
cp .env.example .env
```

```dotenv
MINICODEX_API_KEY=your_api_key_here
MINICODEX_BASE_URL=https://api.deepseek.com
MINICODEX_MODEL=deepseek-chat
```

MiniCodex 读取启动目录中的 `.env`，也支持已有的 `DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL` 和 `DEEPSEEK_MODEL`。`--model` 与 `--base-url` 可以覆盖环境配置；API Key 只从环境变量读取，避免出现在 shell 历史中。

### 3. 检查环境

```bash
minicodex doctor
```

普通 `doctor` 不访问网络。以下命令会发送一次最小模型请求，可能产生少量费用：

```bash
minicodex doctor --connect
```

脚本或 CI 可以读取 JSON：

```bash
minicodex doctor --json
```

### 4. 启动本地 Web 工作台

```bash
minicodex ui --workspace /path/to/project
```

浏览器工作台提供文件树、代码查看、Agent 对话、实时任务阶段、Trace 活动终端、文件级 Git Diff 导航，以及任务级 Accept / Reject。v0.4.0 提供审查、自动和只读三种每任务权限模式；审查模式会在依赖安装、外部网络访问、覆盖既有用户修改等警示级操作前暂停，等待用户选择允许一次、本任务允许或拒绝，并把决策写入 Trace 审计记录。Reject 复用 Harness 的 checkpoint rollback，只撤销本次 Agent 编辑，并在检测到外部并发修改时拒绝覆盖。

UI 仅监听 `127.0.0.1`；敏感凭证文件不会进入文件树或预览 API。可用 `--port 9000` 指定端口，或用 `--no-browser` 只启动服务。`v0.4.0` wheel 已包含 UI 静态资源与启动命令。

### 5. 使用 CLI 执行任务

执行单个任务后退出：

```bash
minicodex run "修复用户注册接口的邮箱校验，并运行相关测试" \
  --workspace /path/to/project \
  --output verbose
```

启动交互式会话：

```bash
minicodex chat --workspace /path/to/project
```

不带子命令时仍进入交互模式；`--prompt` 旧入口继续兼容：

```bash
minicodex
minicodex --workspace /path/to/project --prompt "修复失败测试"
```

## CLI 参考

| 命令 | 用途 | 是否访问模型 |
| --- | --- | --- |
| `minicodex ui` | 启动本地 Web 工作台；提交任务后调用同一 Runtime | 启动时否，执行任务时是 |
| `minicodex run "任务"` | 执行一个任务并退出 | 是 |
| `minicodex chat` | 启动连续交互会话 | 是 |
| `minicodex doctor` | 检查 Python、工作区、Git 与模型配置 | 否 |
| `minicodex doctor --connect` | 额外验证真实模型连接 | 是，最小请求 |
| `minicodex --version` | 显示版本 | 否 |
| `minicodex-release-gate --summary ...` | 检查本地回归和在线 Benchmark 报告 | 默认只读取报告 |

通用选项：

- `--workspace / -w`：目标仓库，默认是当前目录
- `--output`：`normal`、`verbose` 或 `debug`
- `--model`：覆盖模型名称
- `--base-url`：覆盖兼容 API 地址
- `--api-key-env`：从指定环境变量读取密钥

## 五分钟演示

仓库包含一个刻意保留简单缺陷的计算器项目。复制后运行，避免修改原始示例：

```bash
demo_dir="$(mktemp -d)/calculator_demo"
cp -R examples/calculator_demo "$demo_dir"

minicodex run \
  "修改 src/calculator.py，让 divide(a, b) 在 b 为 0 时抛出 ValueError，并在 tests/test_calculator.py 增加回归测试，然后运行测试。" \
  --workspace "$demo_dir" \
  --output verbose

python -m pytest -q "$demo_dir/tests"
```

该流程展示仓库检查、需求拆解、代码编辑、针对性验收、相关回归和最终报告。更多说明见[计算器演示](examples/calculator_demo/README.md)。

## 支持的工作流

- 信息咨询和只读代码审查
- 通过本地 Web UI 浏览文件、查看代码和 Diff、跟踪任务并 Accept / Reject
- 在警示级操作执行前通过 Web UI 做 Human-in-the-loop 审批
- 创建、修改、修复和重构 Python / JavaScript / TypeScript / HTML 项目
- 运行命令、pytest 和项目级测试脚本
- Flask / FastAPI 服务端点验证
- 静态 Web 验证，以及可选的 Playwright 浏览器交互验证
- Python 依赖缺失检测与受控安装
- Git 状态、差异检查和任务级撤销基础设施

执行模式由 Harness 根据任务语义选择：

- `FAST`：小范围修改和最小充分验证
- `STANDARD`：仓库检查、按需计划、验收与相关回归
- `COMPLEX`：多步修改、迭代验证与更完整的回归
- `INSPECT_ONLY`：只读检查，编辑工具不可用
- `INFORMATIONAL`：直接回答，不进入代码执行循环

## 验证、安全与恢复

每个需求先变成独立的 `ValidationCheck`，再绑定文件、测试、命令、HTTP、浏览器或语义契约。`ValidatorResolver` 只根据契约和已注册能力选择验证器；`ValidationLedger` 保存带编辑版本的证据。只有当前版本的全部必需检查都被证明，`TaskCompletionPolicy` 才允许成功结束。

关键边界：

- 只读任务不会获得编辑或依赖安装能力
- 文件、命令与依赖操作都经过安全策略和工作区检查
- 命令受超时、输出、文件大小、CPU 和内存限制
- checkpoint 只覆盖 Agent 自己的编辑；发现外部并发修改时拒绝覆盖
- 静态 HTML 检查不能替代点击、键盘或运行时状态验证
- 缺少必需能力或可靠目标时，任务明确阻塞，不会伪造成功
- 测试通过、工具成功或模型声称完成，都不能单独关闭整个任务

详细设计见[架构说明](docs/architecture.md)和[验证核心 V2](docs/validation-core-v2.md)。

## 可观测性与本地数据

运行时数据按仓库隔离保存在用户目录，不会写入目标项目：

```text
~/.minicodex/workspaces/<repository-key>/
├── memory/long_term.json   # 跨任务经验
├── traces/latest.jsonl     # 最近一次结构化 trace
└── sandbox/                # 沙箱运行数据
```

`normal` 输出主要结果；`verbose` 增加执行和阶段信息；`debug` 还会显示内部结果标识、trace 摘要与长期记忆统计。长期记忆是辅助缓存，物理工作区始终是事实来源。

## 项目结构

```text
minicodex/
├── main.py                 # CLI 组合根与 Agent 构建
├── doctor.py               # 环境与模型配置诊断
├── llm/                    # Provider 配置、客户端与响应类型
├── prompts/                # 系统提示词
├── ui/                     # 本地 Web 工作台、HTTP API 与静态资源
├── agent/
│   ├── orchestration/      # 主循环、工具批次与任务报告
│   ├── routing/            # 意图、模式与执行策略
│   ├── planning/           # 需求、计划与重规划
│   ├── validation/         # 契约、证据、测试定位与完成策略
│   ├── editing/            # 编辑恢复、checkpoint 与 rollback
│   ├── safety/             # 权限、安全执行与沙箱
│   ├── runtime/            # 工具执行、进程、取消与 Git 感知
│   ├── context/            # 仓库地图、符号索引与上下文预算
│   ├── memory/             # 工作记忆与长期记忆
│   ├── progress/           # 进度与停滞控制
│   └── observability/      # trace、指标、脱敏与输出控制
├── tools/                  # 暴露给模型的受控工具
├── evaluation/             # Benchmark、oracle、报告与发布门禁
└── tests/                  # 单元、集成和行为测试
```

## 测试与评估

当前开发提交通过 **710 项确定性测试**，CI 覆盖 Python 3.11、3.12 和 3.13，并构建 wheel 后在源码目录外验证安装入口。普通测试不会访问付费模型：

```bash
python -m pytest -q
python -m compileall -q minicodex
git diff --check
```

`MiniCodex Benchmark V1 R2` 包含 30 个隔离仓库任务、Agent 工作区之外的隐藏行为 oracle、8 个 smoke 用例、baseline 对照、多次运行、失败聚类和版本化报告。在线运行必须显式提供 provider、model 和凭证。

```bash
python -m minicodex.evaluation.run_benchmark \
  --profile minicodex \
  --provider deepseek \
  --model deepseek-chat \
  --smoke
```

正式门禁默认要求当前 Git commit 上 30 个任务至少重复 3 次、任务成功率 100%，并且错误完成、越权编辑、错误文件、错误验证目标、步数耗尽和幽灵步骤均为 0。指标定义与使用方法见[Benchmark 文档](docs/benchmark-v1.md)。历史重构与实验结果见[交付报告](docs/vibecoding-refactor-report.md)。

## 开发约束

- `utils` 不依赖 Agent 领域模块
- `tools` 不依赖 orchestration
- orchestration 只协调领域 API，不复制领域规则
- 控制器通过事件更新 `TaskRuntime`，不维护第二份任务真相
- 每个核心概念只有一个 canonical import path
- 模型负责语义判断；权限、预算、安全、验证证据和完成条件保持确定性

欢迎先运行完整测试，再提交范围清晰的变更。

## 当前限制

- CLI 与 Web UI 都是单进程会话，进程崩溃后不能续跑未完成任务
- 进行中的任务状态与 checkpoint 只存在于当前进程
- 浏览器交互验证依赖可选的 Playwright 和 Chromium
- 审查模式只审批安全策略标记为 `CAUTION` 的操作；只读模式会另行阻止所有带副作用的工具，但不是内核级隔离
- 服务工具提供受限进程和回环 HTTP 验证，不是内核级容器隔离
- 模型、网络、第三方包源和操作系统权限仍可能导致失败
- 自动验证降低风险，但不能代替人工代码审查与真实部署测试

## 文档

| 文档 | 中文 | English |
| --- | --- | --- |
| 文档索引 | [中文](docs/README.md) | [English](docs/README.en.md) |
| 本地 Web 工作台 | [中文](docs/ui.md) | [English](docs/ui.en.md) |
| Human-in-the-loop | [中文](docs/human-in-the-loop.md) | [English](docs/human-in-the-loop.en.md) |
| 架构说明 | [中文](docs/architecture.md) | [English](docs/architecture.en.md) |
| 验证核心 V2 | [中文](docs/validation-core-v2.md) | [English](docs/validation-core-v2.en.md) |
| Benchmark V1 | [中文](docs/benchmark-v1.md) | [English](docs/benchmark-v1.en.md) |
| 重构交付报告 | [中文](docs/vibecoding-refactor-report.md) | [English](docs/vibecoding-refactor-report.en.md) |
| v0.4.1 Release notes | [中文](docs/releases/v0.4.1.zh-CN.md) | [English](docs/releases/v0.4.1.md) |
| v0.4.0 Release notes | [中文](docs/releases/v0.4.0.zh-CN.md) | [English](docs/releases/v0.4.0.md) |
| v0.3.0 Release notes | [中文](docs/releases/v0.3.0.zh-CN.md) | [English](docs/releases/v0.3.0.md) |
| v0.2.0 Release notes | [中文](docs/releases/v0.2.0.zh-CN.md) | [English](docs/releases/v0.2.0.md) |
| Changelog | [中文](CHANGELOG.zh-CN.md) | [English](CHANGELOG.md) |
| MIT License | [中文参考译文](LICENSE.zh-CN.md) | [English](LICENSE) |

## 许可证

MiniCodex 使用 [MIT License](LICENSE)。中文用户可阅读[非官方参考译文](LICENSE.zh-CN.md)，法律效力以英文原文为准。
