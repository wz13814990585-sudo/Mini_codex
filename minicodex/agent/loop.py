"""Agent execution loop."""

import json

from minicodex.agent.context import compact_messages
from minicodex.agent.progress import ValidationStatus
from minicodex.agent.state import StepStatus


INCOMPLETE_PLAN_REMINDER = (
    "The implementation plan is not finished. "
    "Continue working on the current plan step. "
    "Call complete_plan_step only after that step "
    "is actually done. Do not give a final answer yet."
)


def run_agent_loop(agent, user_input: str) -> str:
    """Execute the LLM/tool loop for an initialized agent task."""

    messages = [
        {
            "role": "user",
            "content": user_input,
        }
    ]

    for agent_step in range(agent.max_steps):
        print(
            f"\n[Agent Step "
            f"{agent_step + 1}/{agent.max_steps}]"
        )

        current_plan_step = None

        if agent.active_plan:
            current_plan_step = (
                agent.active_plan.start_current_step()
            )

            if current_plan_step:
                print(
                    f"\n[Current Plan Step] "
                    f"{current_plan_step.id}. "
                    f"{current_plan_step.description}"
                )
                print(
                    f"[Step Failures] "
                    f"{current_plan_step.attempts}/"
                    f"{agent.max_step_attempts}"
                )

                if (
                    current_plan_step.attempts
                    >= agent.max_step_attempts
                ):
                    reason = (
                        f"Plan step "
                        f"{current_plan_step.id} "
                        f"has exceeded its attempt budget. "
                        f"Current step: "
                        f"{current_plan_step.description}"
                    )

                    (
                        recovery_message,
                        should_continue,
                    ) = agent.recovery.recover(
                        reason=reason,
                        replan_callback=agent.replan,
                    )

                    print("\n[Step Recovery]")
                    print(recovery_message)

                    if not should_continue:
                        return (
                            "Agent stopped because the "
                            "current plan step could not "
                            "be recovered."
                        )

                    current_plan_step.reset_attempts()

                    messages.append(
                        {
                            "role": "user",
                            "content": recovery_message,
                        }
                    )

                    if agent.active_plan:
                        current_plan_step = (
                            agent.active_plan.start_current_step()
                        )

        remaining_agent_steps = (
            agent.max_steps - agent_step
        )

        compact_messages(messages)

        system_prompt = agent._build_system_prompt(
            user_input=user_input,
            plan=agent.active_plan,
            current_step=current_plan_step,
            remaining_agent_steps=remaining_agent_steps,
        )

        llm_messages = [
            {
                "role": "system",
                "content": system_prompt,
            }
        ] + messages

        build_turn = getattr(
            agent,
            "_build_turn_context",
            None,
        )
        if callable(build_turn):
            llm_messages.append(
                {
                    "role": "user",
                    "content": build_turn(
                        plan=agent.active_plan,
                        current_step=current_plan_step,
                        remaining_agent_steps=remaining_agent_steps,
                    ),
                }
            )

        response = agent.llm.chat(
            messages=llm_messages,
            tools=agent.registry.get_schemas(),
        )

        if not response.tool_calls:
            content = response.content or ""

            if tests_passed_after_edit(agent):
                return content or summarize_agent_stop(
                    agent,
                    "Task validated: tests passed "
                    "after a successful edit.",
                )

            if (
                agent.active_plan
                and not agent.active_plan.is_completed()
            ):
                print(
                    "\n[Warning] "
                    "LLM returned final answer before "
                    "all plan steps were completed."
                )

                remaining_budget = (
                    agent.max_steps - agent_step - 1
                )

                if remaining_budget > 0:
                    messages.append(
                        {
                            "role": "assistant",
                            "content": (
                                content
                                or "Stopped before the "
                                "plan was complete."
                            ),
                        }
                    )
                    messages.append(
                        {
                            "role": "user",
                            "content": INCOMPLETE_PLAN_REMINDER,
                        }
                    )
                    continue

                return summarize_agent_stop(
                    agent,
                    "Agent stopped with unfinished "
                    "plan steps.",
                    content,
                )

            return content

        # assistant tool call 要保存进历史
        messages.append(
            response.model_dump(exclude_none=True)
        )

        restart_agent_loop = False
        early_stop = None

        for tool_index, tool_call in enumerate(response.tool_calls):
            tool_name = tool_call.function.name

            try:
                arguments = json.loads(
                    tool_call.function.arguments
                )
            except Exception as e:
                if current_plan_step:
                    current_plan_step.increment_attempt()

                result = (
                    "Tool argument parsing failed: "
                    f"{type(e).__name__}: {e}"
                )

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result,
                    }
                )
                continue

            print(f"\n[Tool] {tool_name}")
            print(f"[Arguments] {arguments}")

            allowed, duplicate_reason = (
                agent.progress.check_duplicate_tool_call(
                    tool_name,
                    arguments,
                )
            )

            if not allowed:
                if current_plan_step:
                    current_plan_step.increment_attempt()

                result = (
                    "Tool call blocked because "
                    "it appears to repeat an "
                    "already-attempted action. "
                    f"{duplicate_reason}"
                )
                print("\n[Duplicate Tool Blocked]")
            else:
                try:
                    result = agent.registry.execute(
                        tool_name,
                        arguments,
                    )
                except Exception as e:
                    if current_plan_step:
                        current_plan_step.increment_attempt()

                    result = (
                        "Tool execution failed: "
                        f"{type(e).__name__}: {e}"
                    )

            print(f"\n[Observation]\n{result}")

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": str(result),
                }
            )

            agent.progress.record_action(tool_name)

            if tool_name in {
                "patch_file",
                "write_file",
            }:
                if "successfully" in str(result).lower():
                    agent.progress.record_successful_edit()
                    print("\n[Edit Applied]")

            if tool_name == "complete_plan_step":
                if agent.active_plan:
                    current_plan_step = (
                        agent.active_plan.get_current_step()
                    )
                continue

            if looks_like_pytest(tool_name, arguments):
                early_stop, restart_agent_loop = (
                    apply_validation(
                        agent,
                        str(result),
                        messages,
                        full_suite=is_full_test_run(
                            tool_name,
                            arguments,
                        ),
                    )
                )

                if early_stop or restart_agent_loop:
                    append_skipped_tool_results(
                        messages,
                        response.tool_calls[tool_index + 1:],
                        "validation changed loop control flow",
                    )
                    break

            if (
                agent._step_likely_requires_edit(
                    current_plan_step
                )
                and agent.progress.is_action_stalled()
            ):
                reason = (
                    "The agent has repeatedly "
                    "inspected or validated code "
                    "without making a meaningful edit."
                )

                (
                    recovery_message,
                    should_continue,
                ) = agent.recovery.recover(
                    reason=reason,
                    replan_callback=agent.replan,
                )

                print("\n[Progress Recovery]")
                print(recovery_message)

                if not should_continue:
                    append_skipped_tool_results(
                        messages,
                        response.tool_calls[tool_index + 1:],
                        "progress recovery stopped execution",
                    )
                    return (
                        "Agent stopped because "
                        "meaningful progress could "
                        "not be made."
                    )

                messages.append(
                    {
                        "role": "user",
                        "content": recovery_message,
                    }
                )

                restart_agent_loop = True
                append_skipped_tool_results(
                    messages,
                    response.tool_calls[tool_index + 1:],
                    "progress recovery restarted the loop",
                )
                break

        if early_stop:
            return early_stop

        if restart_agent_loop:
            continue

        if tests_passed_after_edit(agent):
            return summarize_agent_stop(
                agent,
                "Task validated: the full test suite passed "
                "after the latest successful edit.",
            )

    return summarize_agent_stop(
        agent,
        "Agent stopped because the maximum "
        "number of agent steps was reached.",
    )


def looks_like_pytest(tool_name: str, arguments: dict) -> bool:
    if tool_name == "run_tests":
        return True

    if tool_name != "run_command":
        return False

    command = str(arguments.get("command", "")).lower()
    return "pytest" in command


def tests_passed_after_edit(agent) -> bool:
    progress = getattr(agent, "progress", None)
    if progress is None:
        return False

    return bool(getattr(progress, "has_validated_edit", False))


def is_full_test_run(tool_name: str, arguments: dict) -> bool:
    if tool_name != "run_tests":
        return False

    path = str(arguments.get("path", ".")).strip()
    return path in {"", ".", "./"}


def append_skipped_tool_results(
    messages: list,
    tool_calls,
    reason: str,
) -> None:
    for tool_call in tool_calls:
        messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": f"Tool call skipped because {reason}.",
            }
        )


def apply_validation(
    agent,
    result: str,
    messages: list,
    full_suite: bool = False,
) -> tuple[str | None, bool]:
    validation = agent.progress.track_validation(result)

    if validation.message:
        print("\n[Validation Progress]")
        print(validation.message)

    if validation.meaningful_progress:
        agent.recovery.mark_progress()
        print("\n[Meaningful Progress Detected]")

    if (
        validation.status == ValidationStatus.PASSED
        and full_suite
    ):
        agent.progress.mark_edit_validated()

    if not validation.stalled:
        return None, False

    reason = (
        "Validation is repeatedly failing "
        "without meaningful improvement. "
        f"{validation.message}"
    )

    recovery_message, should_continue = agent.recovery.recover(
        reason=reason,
        replan_callback=agent.replan,
    )

    print("\n[Validation Recovery]")
    print(recovery_message)

    if not should_continue:
        return (
            "Agent stopped because "
            "validation remained stalled."
        ), False

    messages.append(
        {
            "role": "user",
            "content": recovery_message,
        }
    )

    return None, True


def summarize_agent_stop(
    agent,
    reason: str,
    last_text: str = "",
) -> str:
    lines = [reason]

    plan = getattr(agent, "active_plan", None)

    if plan:
        completed = [
            step
            for step in plan.all_steps()
            if step.status == StepStatus.COMPLETED
        ]
        remaining = [
            step
            for step in plan.all_steps()
            if step.status
            in {
                StepStatus.PENDING,
                StepStatus.IN_PROGRESS,
            }
        ]

        lines.append(
            f"Plan progress: {len(completed)} completed, "
            f"{len(remaining)} remaining."
        )

        if remaining:
            lines.append(
                "Next unfinished step: "
                f"{remaining[0].id}. "
                f"{remaining[0].description}"
            )

        if plan.is_completed():
            lines.append("All plan steps are marked complete.")

    failed = getattr(
        agent.progress,
        "last_validation_failed_count",
        None,
    )

    if failed == 0:
        lines.append("Last validation: tests passed.")
    elif failed is not None:
        lines.append(
            f"Last validation: {failed} failed."
        )

    if last_text:
        lines.append(last_text)

    return "\n".join(lines)
