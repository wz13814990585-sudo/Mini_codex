# MiniCodex 本地 Web 工作台

**简体中文** · [English](ui.en.md)

Web 工作台是 MiniCodex Runtime 之上的薄界面层。它不重新实现规划、工具调用、安全、验证或完成判定；同一个 `build_agent()` 组合根仍然负责真正的代码任务。

> `minicodex ui` 从 `v0.3.0` 起随 wheel 一同发布。

## 启动

```bash
python -m pip install -e ".[test]"
minicodex ui --workspace /path/to/project
```

默认地址是 `http://127.0.0.1:8765/`，并自动打开浏览器：

```bash
minicodex ui --workspace /path/to/project --port 9000
minicodex ui --workspace /path/to/project --port 0 --no-browser
```

`--port 0` 让操作系统选择空闲端口。没有 API Key 时仍可打开并浏览工作区，但提交任务前必须配置 `MINICODEX_API_KEY` 或 `DEEPSEEK_API_KEY`。

## 界面区域

| 区域 | 数据来源 | 功能 |
| --- | --- | --- |
| 文件树 | 受工作区约束的只读文件 API | 搜索和选择文本文件；默认排除生成目录与凭证文件 |
| Code / Changes | 文件 API / `GitRepositoryInspector` | 查看源码或当前文件的 Git Diff |
| Agent Chat | UI 任务会话 | 提交自然语言任务并保留本次进程中的消息 |
| 任务阶段 | `TaskState` | 展示 Inspect、Act、Validate、Done 及阻塞 / 失败状态 |
| 运行活动 | `TraceRecorder` | 显示模型、工具、安全、编辑与验证事件，不提供任意 shell 输入 |
| Accept / Reject | checkpoint 生命周期 | 保留修改，或安全撤销当前任务的 Agent 编辑 |

界面右上角可在中文和英文之间切换。切换只影响 UI 文案，不改变发送给模型的任务文本。

## 任务与审查流程

1. 在 Agent Chat 中描述代码目标。
2. UI 创建一个新的 `MiniCodexAgent`，并通过 `AsyncAgentRunner` 后台执行。
3. 页面轮询权威 `TaskState` 和结构化 Trace；Agent 仍按 CLI 相同的策略编辑和验证。
4. 如果任务产生密封 checkpoint，完成后进入 `pending` 审查状态，并阻止开始下一任务。
5. **Accept** 保留物理工作区中的修改；**Reject** 调用 `undo_task()` 逆序恢复本次 checkpoint。

Reject 不运行 `git reset`，也不会还原任务开始前已存在的其他未提交修改。如果文件在 checkpoint 之后被 IDE 或用户再次改动，回滚会报告冲突并拒绝覆盖。

停止按钮使用协作式取消：在模型调用和工具执行边界生效。已经发出的同步模型请求不能由 Python 线程强制终止，但返回后不会继续下一步。

## 本地安全边界

- 服务仅允许绑定 `127.0.0.1`、`localhost` 或 `::1`。
- 所有变更型 API 都要求页面启动时生成的随机会话令牌。
- HTTP Host 必须是本地回环名称，并设置 CSP、frame、MIME 和 Referrer 安全头。
- 文件路径统一通过工作区边界解析；符号链接不会进入树。
- `.env`、常见凭证文件、私钥、二进制文件和超过 2 MiB 的文件不能预览。
- 前端只显示经过 Trace 脱敏层的结构化事件；API Key 不会写入页面配置。

本地 UI 不是远程多人服务，不应通过反向代理或端口转发暴露到网络。它也不是容器沙箱；实际命令安全仍由现有 `SafetyToolExecutor` 与 `SandboxRunner` 负责。

## 当前范围

- 一次只运行一个 Agent 任务。
- 审查粒度是整个任务，不是每条命令。
- 终端是只读活动流，不是交互式 shell。
- 消息、运行中状态和 Reject checkpoint 都是进程内状态；关闭服务后不能恢复未完成任务。
- Diff 基于当前 Git 工作树；任务开始前已存在且被 Agent 修改的文件仍可能包含混合差异，应人工审查。

架构边界见[架构说明](architecture.md)，验证与完成规则见[验证核心 V2](validation-core-v2.md)。
