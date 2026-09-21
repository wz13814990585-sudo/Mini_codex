from dataclasses import (
    dataclass,
    field,
)

from .working_memory import (
    WorkingMemory,
)


@dataclass
class WorkingSummary:
    """
    Compact task-level factual execution history.

    Summary responsibility:

        preserve recent factual execution events

    Working-memory responsibility:

        preserve latest-known structured task state

    Both are task-local and reset for every new user task.
    """

    max_items: int = 30

    items: list[str] = field(
        default_factory=list
    )

    memory: WorkingMemory = field(
        default_factory=WorkingMemory,
        repr=False,
    )

    # =========================================================
    # Reset
    # =========================================================

    def reset(
        self,
    ) -> None:

        self.items.clear()

        self.memory.reset()

    # =========================================================
    # Add Fact
    # =========================================================

    def add(
        self,
        text: str,
    ) -> None:

        normalized = (
            str(
                text
            )
            .strip()
        )

        if not normalized:

            return

        # Avoid exact duplicate facts.
        if (
            normalized
            in self.items
        ):

            return

        self.items.append(
            normalized
        )

        # Keep summary bounded.
        if (
            len(
                self.items
            )
            > self.max_items
        ):

            overflow = (
                len(
                    self.items
                )
                - self.max_items
            )

            del self.items[
                :overflow
            ]

    def advance_revision(self, revision: int) -> None:
        """Drop stale active validation/failure prose after a physical mutation."""
        self.items[:] = [
            item for item in self.items
            if not any(marker in item.casefold() for marker in (
                "validation failed", "tests failed", "still failing", "inconclusive validation",
                "验证失败", "测试失败", "仍然失败", "验证结果不确定", "验证尚无定论",
            ))
        ]
        self.memory.invalidate_validation_before(revision)

    def render_relevant(
        self,
        target_paths: tuple[str, ...] = (),
        *,
        max_items: int = 10,
    ) -> str:
        """Render recent actionable facts, prioritizing explicit targets."""

        targets = tuple(str(path).casefold() for path in target_paths if path)
        ranked: list[tuple[int, int, str]] = []
        for index, item in enumerate(self.items):
            lowered = item.casefold()
            score = 0
            if any(target in lowered for target in targets):
                score += 4
            if any(word in lowered for word in (
                "failed", "modified", "validation", "blocked", "stale", "installed",
                "失败", "已修改", "验证", "阻塞", "过期", "已安装", "修改",
            )):
                score += 2
            if index >= max(0, len(self.items) - max_items):
                score += 1
            ranked.append((score, index, item))
        selected = sorted(ranked, key=lambda value: (value[0], value[1]), reverse=True)
        selected = sorted(selected[:max(1, int(max_items))], key=lambda value: value[1])
        return "\n".join(f"- {item}" for _, _, item in selected)

    # =========================================================
    # Record Tool Result
    # =========================================================

    def record_tool_result(
        self,
        tool_name: str,
        arguments: dict,
        result,
        revision: int | None = None,
    ) -> None:

        if not isinstance(
            arguments,
            dict,
        ):

            arguments = {}

        # =====================================================
        # Structured working memory
        #
        # Memory is a cache, not source of truth.
        #
        # A memory-recording failure must never break the Agent
        # execution path.
        # =====================================================

        try:

            self.memory.record_tool_result(
                tool_name=(
                    tool_name
                ),
                arguments=(
                    arguments
                ),
                result=(
                    result
                ),
                revision=revision,
            )

        except Exception:

            pass

        path = (
            str(
                arguments.get(
                    "path",
                    "",
                )
                or ""
            )
            .strip()
        )

        # =====================================================
        # Read File
        # =====================================================

        if (
            tool_name
            == "read_file"
        ):

            if result.success:

                if path:

                    self.add(
                        f"已检查文件：{path}。"
                    )

                else:

                    self.add(
                        "已成功检查文件。"
                    )

            else:

                self.add(
                    self._failure_fact(
                        tool_name,
                        path,
                        result,
                    )
                )

            return

        # =====================================================
        # Search Code
        # =====================================================

        if (
            tool_name
            == "search_code"
        ):

            query = (
                str(
                    arguments.get(
                        "query",
                        "",
                    )
                    or ""
                )
                .strip()
            )

            if result.success:

                if query:

                    self.add(
                        f"已搜索项目代码：{query}。"
                    )

            else:

                self.add(
                    self._failure_fact(
                        tool_name,
                        query,
                        result,
                    )
                )

            return

        # =====================================================
        # Search Symbol
        # =====================================================

        if (
            tool_name
            == "search_symbol"
        ):

            query = (
                str(
                    arguments.get(
                        "query",
                        arguments.get(
                            "name",
                            "",
                        ),
                    )
                    or ""
                )
                .strip()
            )

            if result.success:

                if query:

                    self.add(
                        f"已搜索项目符号：{query}。"
                    )

            else:

                self.add(
                    self._failure_fact(
                        tool_name,
                        query,
                        result,
                    )
                )

            return

        # =====================================================
        # Edit Tools
        # =====================================================

        if (
            tool_name
            in {
                "write_file",
                "patch_file",
                "replace_lines",
                "replace_symbol",
            }
        ):

            if result.success:

                if path:
                    self.items[:] = [item for item in self.items if path not in item]

                if path:

                    self.add(
                        f"已成功修改文件：{path}。"
                    )

                else:

                    self.add(
                        "已成功修改项目文件。"
                    )

            else:

                self.add(
                    self._failure_fact(
                        tool_name,
                        path,
                        result,
                    )
                )

            return

        # =====================================================
        # Dependency Installation
        # =====================================================

        if tool_name == "install_python_package":
            package = str(
                arguments.get("package", "")
                or ""
            ).strip()
            import_name = str(
                arguments.get("import_name", "")
                or ""
            ).strip()

            if result.success:
                action = (
                    "已可用"
                    if result.data.get("already_available")
                    else "已安装并通过导入验证"
                )
                self.add(
                    f"Python 依赖 {package}（{import_name}）"
                    f"{action}。"
                )
            else:
                self.add(
                    self._failure_fact(
                        tool_name,
                        package,
                        result,
                    )
                )

            return

        if tool_name in {"validate_static_web", "validate_browser_app"}:
            outcome = str(
                result.data.get("outcome", "inconclusive")
            )
            self.add(
                f"路径 {path or '未知路径'} 的 Web 验证结果为 "
                f"{outcome}。"
            )
            return

        # =====================================================
        # Tests
        # =====================================================

        if (
            tool_name
            == "run_tests"
        ):

            if not result.success:

                self.add(
                    self._failure_fact(
                        tool_name,
                        path,
                        result,
                    )
                )

                return

            tests_passed = (
                result.data.get(
                    "tests_passed"
                )
            )

            passed = (
                self._safe_int(
                    result.data.get(
                        "passed",
                        0,
                    )
                )
            )

            failed = (
                self._safe_int(
                    result.data.get(
                        "failed",
                        0,
                    )
                )
            )

            errors = (
                self._safe_int(
                    result.data.get(
                        "errors",
                        0,
                    )
                )
            )

            if (
                tests_passed
                is True
            ):

                self.add(
                    f"验证通过：{passed} 个测试通过，"
                    "0 个失败。"
                )

            elif (
                failed
                + errors
                > 0
            ):

                self.add(
                    f"验证仍失败：{passed} 通过，"
                    f"{failed} 失败，"
                    f"{errors} 错误。"
                )

            else:

                self.add(
                    "已运行验证，但尚无明确的通过/失败结果。"
                )

            return

        # =====================================================
        # Run Command
        # =====================================================

        if (
            tool_name
            == "run_command"
        ):

            command = (
                str(
                    arguments.get(
                        "command",
                        "",
                    )
                    or ""
                )
                .strip()
            )

            command_succeeded = (
                result.data.get(
                    "command_succeeded"
                )
            )

            if (
                result.success
                and command_succeeded
                is True
            ):

                self.add(
                    f"命令成功：{command}。"
                )

            elif (
                result.success
                and command_succeeded
                is False
            ):

                self.add(
                    f"命令未成功完成：{command}。"
                )

            else:

                self.add(
                    self._failure_fact(
                        tool_name,
                        command,
                        result,
                    )
                )

            return

        # =====================================================
        # Complete Plan Step
        # =====================================================

        if (
            tool_name
            == "plan_step_completed"
        ):

            if (
                result.data.get(
                    "completed"
                )
            ):

                step_id = (
                    result.data.get(
                        "step_id"
                    )
                )

                description = (
                    result.data.get(
                        "step_description"
                    )
                )

                self.add(
                    f"已完成计划步骤 {step_id}："
                    f"{description}。"
                )

            return

        # =====================================================
        # Replan
        # =====================================================

        if (
            tool_name
            == "replan"
        ):

            if (
                result.data.get(
                    "replanned"
                )
            ):

                reason = (
                    str(
                        result.data.get(
                            "reason",
                            "",
                        )
                        or ""
                    )
                    .strip()
                )

                if reason:

                    self.add(
                        f"实现计划已修订。原因：{reason}"
                    )

                else:

                    self.add(
                        "实现计划已修订。"
                    )

            return

        # =====================================================
        # Git Status
        # =====================================================

        if (
            tool_name
            == "git_status"
        ):

            if result.success:

                self.add(
                    "Git 仓库状态已刷新。"
                )

            else:

                self.add(
                    self._failure_fact(
                        tool_name,
                        path,
                        result,
                    )
                )

            return

        # =====================================================
        # Git Diff
        # =====================================================

        if (
            tool_name
            == "git_diff"
        ):

            if result.success:

                if path:

                    self.add(
                        f"已检查 Git 差异：{path}。"
                    )

                else:

                    self.add(
                        "已检查当前 Git 差异。"
                    )

            else:

                self.add(
                    self._failure_fact(
                        tool_name,
                        path,
                        result,
                    )
                )

            return

        # =====================================================
        # Generic Failure
        # =====================================================

        if not result.success:

            self.add(
                self._failure_fact(
                    tool_name,
                    path,
                    result,
                )
            )

    # =========================================================
    # Render
    # =========================================================

    def render(
        self,
    ) -> str:

        if (
            not self.items
            and len(
                self.memory
            )
            == 0
        ):

            # Preserve the established empty-summary result.
            return (
                "尚未记录重要的执行事实。"
            )

        sections = []

        # =====================================================
        # Current-state memory
        # =====================================================

        if (
            len(
                self.memory
            )
            > 0
        ):

            sections.append(
                (
                    "结构化工作记忆"
                    "（最新已知任务状态）：\n"
                    f"{self.memory.render()}"
                )
            )

        # =====================================================
        # Recent history
        # =====================================================

        if self.items:

            recent_items = (
                self.items[
                    -10:
                ]
            )

            sections.append(
                (
                    "近期执行事实：\n"
                    + "\n".join(
                        f"- {item}"
                        for item
                        in recent_items
                    )
                )
            )

        return "\n\n".join(
            sections
        )

    # =========================================================
    # Failure Helper
    # =========================================================

    def _failure_fact(
        self,
        tool_name: str,
        target: str,
        result,
    ) -> str:

        target_text = (
            f" ({target})"
            if target
            else ""
        )

        error = (
            str(
                getattr(
                    result,
                    "error",
                    "",
                )
                or ""
            )
            .strip()
        )

        if error:

            return (
                f"{tool_name}"
                f"{target_text} 失败："
                f"{error}"
            )

        return (
            f"{tool_name}"
            f"{target_text} 失败。"
        )

    # =========================================================
    # Safe Int
    # =========================================================

    @staticmethod
    def _safe_int(
        value,
    ) -> int:

        try:

            return int(
                value
                or 0
            )

        except (
            TypeError,
            ValueError,
        ):

            return 0
