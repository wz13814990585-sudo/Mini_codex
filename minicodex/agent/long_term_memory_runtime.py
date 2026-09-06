"""Runtime integration for persistent MiniCodex memory."""

from __future__ import annotations

from types import MethodType


# =============================================================
# Attach Long-Term Memory
# =============================================================


def attach_long_term_memory(
    agent,
    *,
    store,
    retrieval_limit: int = 5,
):
    """
    Attach persistent cross-task memory without changing the
    core AgentLoop.

    Long-term memory:

        - retrieves before a task
        - injects historical experience into turn context
        - promotes compact task experience after completion

    Historical memory is advisory only.

    Current filesystem / Git / tool observations remain source
    of truth.
    """

    if getattr(
        agent,
        "_long_term_memory_attached",
        False,
    ):

        return agent

    agent.long_term_memory_store = (
        store
    )

    agent._retrieved_long_term_memory = (
        []
    )

    # =========================================================
    # Wrap Turn Context
    # =========================================================

    original_build_turn_context = (
        agent._build_turn_context
    )

    def memory_build_turn_context(
        self,
        *args,
        **kwargs,
    ):

        base_context = (
            original_build_turn_context(
                *args,
                **kwargs,
            )
        )

        retrieved = getattr(
            self,
            "_retrieved_long_term_memory",
            [],
        )

        if not (
            retrieved
        ):

            return base_context

        try:

            memory_text = (
                store.render_retrieved(
                    retrieved
                )
            )

        except Exception:

            return base_context

        if not (
            memory_text
            .strip()
        ):

            return base_context

        return (
            base_context.rstrip()
            + "\n\n"
            + memory_text
            + "\n"
        )

    agent._build_turn_context = (
        MethodType(
            memory_build_turn_context,
            agent,
        )
    )

    # =========================================================
    # Wrap Run
    # =========================================================

    original_run = (
        agent.run
    )

    def memory_run(
        self,
        user_input: str,
        use_planning: bool = True,
    ):

        # =====================================================
        # Retrieve Before Current Task
        # =====================================================

        try:

            self._retrieved_long_term_memory = (
                store.retrieve(
                    user_input,
                    limit=(
                        retrieval_limit
                    ),
                )
            )

        except Exception:

            # Memory failure must never block Agent execution.
            self._retrieved_long_term_memory = (
                []
            )

        try:

            output = (
                original_run(
                    user_input,
                    use_planning=(
                        use_planning
                    ),
                )
            )

        except Exception as e:

            try:

                record = (
                    build_task_memory_record(
                        agent=(
                            self
                        ),
                        store=(
                            store
                        ),
                        user_input=(
                            user_input
                        ),
                        output="",
                        runtime_error=(
                            f"{type(e).__name__}: "
                            f"{e}"
                        ),
                    )
                )

                if (
                    record
                    is not None
                ):

                    store.remember(
                        record
                    )

            except Exception:

                pass

            raise

        # =====================================================
        # Promote Experience
        # =====================================================

        try:

            record = (
                build_task_memory_record(
                    agent=(
                        self
                    ),
                    store=(
                        store
                    ),
                    user_input=(
                        user_input
                    ),
                    output=(
                        str(
                            output
                        )
                    ),
                    runtime_error=None,
                )
            )

            if (
                record
                is not None
            ):

                store.remember(
                    record
                )

        except Exception:

            # Long-term persistence is observability/context,
            # not task correctness. Never alter Agent result.
            pass

        return output

    agent.run = (
        MethodType(
            memory_run,
            agent,
        )
    )

    agent._long_term_memory_attached = (
        True
    )

    return agent


# =============================================================
# Build Task Experience
# =============================================================


def build_task_memory_record(
    *,
    agent,
    store,
    user_input: str,
    output: str,
    runtime_error: str | None,
):
    """
    Deterministically promote compact task experience.

    Do NOT persist:

        raw file contents
        complete tool outputs
        complete shell output
        full conversation history

    Persist only compact task-level facts.
    """

    validation_pipeline = getattr(
        agent,
        "validation_pipeline",
        None,
    )

    validation_state = getattr(
        validation_pipeline,
        "state",
        None,
    )

    has_edit = bool(
        getattr(
            validation_state,
            "has_edit",
            False,
        )
    )

    edit_revision = int(
        getattr(
            validation_state,
            "edit_revision",
            0,
        )
        or 0
    )

    acceptance_passed = bool(
        getattr(
            validation_state,
            "acceptance_passed",
            False,
        )
    )

    full_passed = bool(
        getattr(
            validation_state,
            "full_passed",
            False,
        )
    )

    # =========================================================
    # Plan State
    # =========================================================

    plan = getattr(
        agent,
        "active_plan",
        None,
    )

    if (
        plan
        is None
    ):

        plan_completed = True

    else:

        try:

            plan_completed = bool(
                plan.is_completed()
            )

        except Exception:

            plan_completed = False

    # =========================================================
    # Outcome
    # =========================================================

    if (
        runtime_error
        is not None
    ):

        outcome = (
            "error"
        )

    elif (
        has_edit
    ):

        if (
            acceptance_passed
            and full_passed
            and plan_completed
        ):

            outcome = (
                "success"
            )

        else:

            outcome = (
                "incomplete"
            )

    else:

        outcome = (
            "informational"
        )

    # =========================================================
    # Touched Files
    # =========================================================

    touched_files = ()

    git_awareness = getattr(
        agent,
        "git_awareness",
        None,
    )

    if (
        git_awareness
        is not None
    ):

        try:

            task_state = (
                git_awareness
                .task_state()
            )

            touched_files = tuple(
                task_state
                .agent_touched_files
            )

        except Exception:

            touched_files = ()

    # =========================================================
    # Compact Working-Memory Facts
    # =========================================================

    memory_lines = []

    working_summary = getattr(
        agent,
        "working_summary",
        None,
    )

    working_memory = getattr(
        working_summary,
        "memory",
        None,
    )

    entries = getattr(
        working_memory,
        "entries",
        {},
    )

    if isinstance(
        entries,
        dict,
    ):

        useful_kinds = {
            "file",
            "validation",
            "plan",
            "safety",
            "failure",
            "git",
        }

        ordered = sorted(
            entries.values(),
            key=lambda entry: (
                getattr(
                    entry,
                    "sequence",
                    0,
                )
            ),
        )

        for entry in (
            ordered
        ):

            kind = getattr(
                getattr(
                    entry,
                    "kind",
                    None,
                ),
                "value",
                "",
            )

            if (
                kind
                not in useful_kinds
            ):

                continue

            value = (
                str(
                    getattr(
                        entry,
                        "value",
                        "",
                    )
                    or ""
                )
                .strip()
            )

            if not (
                value
            ):

                continue

            memory_lines.append(
                value
            )

        memory_lines = (
            memory_lines[
                -8:
            ]
        )

    # =========================================================
    # Summary
    # =========================================================

    summary_parts = [
        (
            f"Outcome={outcome}."
        )
    ]

    if (
        has_edit
    ):

        summary_parts.append(
            (
                f"Edit revision="
                f"{edit_revision}."
            )
        )

        summary_parts.append(
            (
                "Acceptance="
                f"{acceptance_passed}; "
                "full regression="
                f"{full_passed}."
            )
        )

    if (
        plan
        is not None
    ):

        summary_parts.append(
            (
                "Plan completed="
                f"{plan_completed}."
            )
        )

    if (
        runtime_error
    ):

        summary_parts.append(
            (
                "Runtime error: "
                f"{runtime_error}"
            )
        )

    if (
        memory_lines
    ):

        summary_parts.append(
            (
                "Key facts: "
                + " | ".join(
                    memory_lines
                )
            )
        )

    elif (
        output
    ):

        # Keep only a tiny outcome hint for informational tasks.
        cleaned_output = " ".join(
            str(
                output
            )
            .split()
        )

        if (
            cleaned_output
        ):

            summary_parts.append(
                (
                    "Result: "
                    + cleaned_output[
                        :300
                    ]
                )
            )

    summary = " ".join(
        summary_parts
    )

    # =========================================================
    # Tags
    # =========================================================

    tags = []

    if (
        has_edit
    ):

        tags.append(
            "editing"
        )

    if (
        acceptance_passed
    ):

        tags.append(
            "acceptance-passed"
        )

    if (
        full_passed
    ):

        tags.append(
            "regression-passed"
        )

    if (
        touched_files
    ):

        tags.append(
            "repository-change"
        )

    if (
        runtime_error
    ):

        tags.append(
            "runtime-error"
        )

    return (
        store.create_record(
            task_prompt=(
                user_input
            ),
            outcome=(
                outcome
            ),
            summary=(
                summary
            ),
            touched_files=(
                touched_files
            ),
            tags=(
                tags
            ),
        )
    )