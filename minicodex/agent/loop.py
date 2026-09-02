"""Agent execution loop."""

import json


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
                current_plan_step.increment_attempt()

                print(
                    f"\n[Current Plan Step] "
                    f"{current_plan_step.id}. "
                    f"{current_plan_step.description}"
                )
                print(
                    f"[Step Attempt] "
                    f"{current_plan_step.attempts}/"
                    f"{agent.max_step_attempts}"
                )

                if (
                    current_plan_step.attempts
                    > agent.max_step_attempts
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

                    messages.append(
                        {
                            "role": "user",
                            "content": recovery_message,
                        }
                    )
                    continue

        system_prompt = agent._build_system_prompt(
            user_input=user_input,
            plan=agent.active_plan,
            current_step=current_plan_step,
        )

        llm_messages = [
            {
                "role": "system",
                "content": system_prompt,
            }
        ] + messages

        response = agent.llm.chat(
            messages=llm_messages,
            tools=agent.registry.get_schemas(),
        )

        if not response.tool_calls:
            if (
                agent.active_plan
                and not agent.active_plan.is_completed()
            ):
                print(
                    "\n[Warning] "
                    "LLM returned final answer before "
                    "all plan steps were completed."
                )

            return response.content or ""

        # assistant tool call 要保存进历史
        messages.append(
            response.model_dump(exclude_none=True)
        )

        restart_agent_loop = False

        for tool_call in response.tool_calls:
            tool_name = tool_call.function.name

            try:
                arguments = json.loads(
                    tool_call.function.arguments
                )
            except Exception as e:
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
                    agent.recovery.mark_progress()

            if tool_name == "run_tests":
                (
                    validation_ok,
                    validation_message,
                ) = agent.progress.track_validation(
                    str(result)
                )

                if validation_message:
                    print("\n[Validation Progress]")
                    print(validation_message)

                if validation_ok and validation_message:
                    agent.recovery.mark_progress()

                if not validation_ok:
                    reason = (
                        "Validation is repeatedly "
                        "failing without meaningful "
                        "improvement. "
                        f"{validation_message}"
                    )

                    (
                        recovery_message,
                        should_continue,
                    ) = agent.recovery.recover(
                        reason=reason,
                        replan_callback=agent.replan,
                    )

                    print("\n[Validation Recovery]")
                    print(recovery_message)

                    if not should_continue:
                        return (
                            "Agent stopped because "
                            "validation remained stalled."
                        )

                    messages.append(
                        {
                            "role": "user",
                            "content": recovery_message,
                        }
                    )

                    restart_agent_loop = True
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
                break

        if restart_agent_loop:
            continue

    return (
        "Agent stopped because the maximum "
        "number of agent steps was reached."
    )
