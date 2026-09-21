"""Balanced semantic-routing corpus for offline stub and optional live evals."""

from dataclasses import dataclass

from ..agent.routing import ExecutionMode, TaskIntent


@dataclass(frozen=True)
class RoutingCase:
    case_id: str
    prompt: str
    intent: TaskIntent
    mode: ExecutionMode
    needs_plan: bool


ROUTING_CASES = (
    RoutingCase("en_how", "Tell me how to fix foo.py", TaskIntent.INFORMATIONAL, ExecutionMode.FAST, False),
    RoutingCase("en_inspect", "Inspect foo.py and explain the bug", TaskIntent.INSPECT_ONLY, ExecutionMode.FAST, False),
    RoutingCase("en_modify", "Inspect foo.py and fix it", TaskIntent.MODIFY, ExecutionMode.FAST, False),
    RoutingCase("en_no_edit", "Review foo.py but do not modify anything", TaskIntent.INSPECT_ONLY, ExecutionMode.FAST, False),
    RoutingCase("en_game", "Create a Snake game", TaskIntent.MODIFY, ExecutionMode.FAST, False),
    RoutingCase("tiny_arch_word", "Refactor the architecture paragraph in README.md", TaskIntent.MODIFY, ExecutionMode.FAST, False),
    RoutingCase("complex_plain", "Move task state into domain packages and update every consumer safely", TaskIntent.MODIFY, ExecutionMode.COMPLEX, True),
    RoutingCase("complex_named", "Refactor orchestration, recovery, and validation architecture", TaskIntent.MODIFY, ExecutionMode.COMPLEX, True),
    RoutingCase("zh_info", "告诉我怎么修复 foo.py，不要改代码", TaskIntent.INSPECT_ONLY, ExecutionMode.FAST, False),
    RoutingCase("zh_inspect", "检查登录模块并解释错误，不要修改", TaskIntent.INSPECT_ONLY, ExecutionMode.STANDARD, False),
    RoutingCase("zh_modify", "修复登录并添加回归测试", TaskIntent.MODIFY, ExecutionMode.STANDARD, True),
    RoutingCase("mixed", "检查 auth.py, then fix the error and add tests", TaskIntent.MODIFY, ExecutionMode.STANDARD, True),
)
