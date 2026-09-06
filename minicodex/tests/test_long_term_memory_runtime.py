from types import (
    SimpleNamespace,
)

from ..agent.long_term_memory import (
    LongTermMemoryStore,
)
from ..agent.long_term_memory_runtime import (
    attach_long_term_memory,
)
from ..agent.working_memory import (
    MemoryKind,
)
from ..agent.working_summary import (
    WorkingSummary,
)


# =============================================================
# Fake Git Awareness
# =============================================================


class FakeGitAwareness:

    def __init__(
        self,
        touched_files=(),
    ):

        self.touched_files = tuple(
            touched_files
        )

    def task_state(
        self,
    ):

        return SimpleNamespace(
            agent_touched_files=(
                self.touched_files
            )
        )


# =============================================================
# Fake Agent
# =============================================================


class FakeAgent:

    def __init__(
        self,
        workspace,
        *,
        touched_files=(),
    ):

        self.workspace = (
            workspace
        )

        self.validation_pipeline = (
            SimpleNamespace(
                state=(
                    SimpleNamespace(
                        edit_revision=0,
                        has_edit=False,
                        acceptance_passed=False,
                        full_passed=False,
                    )
                )
            )
        )

        self.active_plan = None

        self.working_summary = (
            WorkingSummary()
        )

        self.git_awareness = (
            FakeGitAwareness(
                touched_files=(
                    touched_files
                )
            )
        )

        self.last_context = None

    def _build_turn_context(
        self,
        *args,
        **kwargs,
    ):

        return (
            "CURRENT TASK CONTEXT"
        )

    def run(
        self,
        user_input,
        use_planning=True,
    ):

        self.last_context = (
            self._build_turn_context()
        )

        return (
            "Done."
        )


# =============================================================
# Historical Memory Injection
# =============================================================


def test_relevant_long_term_memory_is_injected(
    tmp_path,
):

    store = (
        LongTermMemoryStore(
            path=(
                tmp_path
                / "memory.json"
            ),
            repository_key="demo",
        )
    )

    store.remember(
        store.create_record(
            task_prompt=(
                "Fix parser validation bug"
            ),
            outcome=(
                "success"
            ),
            summary=(
                "Previous parser fix "
                "passed acceptance tests."
            ),
            touched_files=(
                "parser.py",
            ),
        )
    )

    agent = (
        FakeAgent(
            tmp_path
        )
    )

    attach_long_term_memory(
        agent,
        store=(
            store
        ),
    )

    agent.run(
        (
            "Fix another parser "
            "validation issue"
        )
    )

    assert (
        "CURRENT TASK CONTEXT"
        in agent.last_context
    )

    assert (
        "Relevant long-term memory"
        in agent.last_context
    )

    assert (
        "parser.py"
        in agent.last_context
    )

    assert (
        "historical only"
        in agent.last_context
    )


# =============================================================
# Irrelevant Memory Is Not Injected
# =============================================================


def test_irrelevant_long_term_memory_not_injected(
    tmp_path,
):

    store = (
        LongTermMemoryStore(
            path=(
                tmp_path
                / "memory.json"
            ),
            repository_key="demo",
        )
    )

    store.remember(
        store.create_record(
            task_prompt=(
                "Fix database connection"
            ),
            outcome="success",
            summary=(
                "Database fixed."
            ),
        )
    )

    agent = (
        FakeAgent(
            tmp_path
        )
    )

    attach_long_term_memory(
        agent,
        store=(
            store
        ),
    )

    agent.run(
        "Change CSS color"
    )

    assert (
        agent.last_context
        == "CURRENT TASK CONTEXT"
    )


# =============================================================
# Successful Editing Task Is Persisted
# =============================================================


def test_successful_task_is_promoted_to_long_term_memory(
    tmp_path,
):

    store = (
        LongTermMemoryStore(
            path=(
                tmp_path
                / "memory.json"
            ),
            repository_key="demo",
        )
    )

    agent = (
        FakeAgent(
            tmp_path,
            touched_files=(
                "app.py",
            ),
        )
    )

    agent.validation_pipeline.state = (
        SimpleNamespace(
            edit_revision=2,
            has_edit=True,
            acceptance_passed=True,
            full_passed=True,
        )
    )

    agent.working_summary.memory.upsert(
        key=(
            "file:app.py:edit"
        ),
        kind=(
            MemoryKind.FILE
        ),
        value=(
            "Latest successful edit "
            "changed app.py."
        ),
        source_tool=(
            "replace_symbol"
        ),
        path=(
            "app.py"
        ),
        revision=2,
    )

    attach_long_term_memory(
        agent,
        store=(
            store
        ),
    )

    result = (
        agent.run(
            "Fix app parser"
        )
    )

    assert (
        result
        == "Done."
    )

    assert (
        len(
            store.records
        )
        == 1
    )

    record = (
        store.records[
            0
        ]
    )

    assert (
        record.outcome
        == "success"
    )

    assert (
        "app.py"
        in record.touched_files
    )

    assert (
        "Acceptance=True"
        in record.summary
    )


# =============================================================
# Incomplete Editing Task Is Still Remembered
# =============================================================


def test_incomplete_task_is_remembered(
    tmp_path,
):

    store = (
        LongTermMemoryStore(
            path=(
                tmp_path
                / "memory.json"
            ),
            repository_key="demo",
        )
    )

    agent = (
        FakeAgent(
            tmp_path,
            touched_files=(
                "broken.py",
            ),
        )
    )

    agent.validation_pipeline.state = (
        SimpleNamespace(
            edit_revision=1,
            has_edit=True,
            acceptance_passed=False,
            full_passed=False,
        )
    )

    attach_long_term_memory(
        agent,
        store=(
            store
        ),
    )

    agent.run(
        "Fix broken parser"
    )

    assert (
        len(
            store.records
        )
        == 1
    )

    assert (
        store.records[
            0
        ].outcome
        == "incomplete"
    )


# =============================================================
# Informational Task Is Remembered
# =============================================================


def test_read_only_task_is_informational_memory(
    tmp_path,
):

    store = (
        LongTermMemoryStore(
            path=(
                tmp_path
                / "memory.json"
            ),
            repository_key="demo",
        )
    )

    agent = (
        FakeAgent(
            tmp_path
        )
    )

    attach_long_term_memory(
        agent,
        store=(
            store
        ),
    )

    agent.run(
        (
            "Explain repository "
            "architecture"
        )
    )

    assert (
        store.records[
            0
        ].outcome
        == "informational"
    )


# =============================================================
# Memory Failure Does Not Break Agent
# =============================================================


def test_memory_persistence_failure_does_not_break_agent(
    tmp_path,
):

    class BrokenStore:

        def retrieve(
            self,
            query,
            limit=5,
        ):

            raise RuntimeError(
                "retrieve failed"
            )

        def render_retrieved(
            self,
            retrieved,
        ):

            raise RuntimeError(
                "render failed"
            )

        def create_record(
            self,
            **kwargs,
        ):

            raise RuntimeError(
                "create failed"
            )

        def remember(
            self,
            record,
        ):

            raise RuntimeError(
                "write failed"
            )

    agent = (
        FakeAgent(
            tmp_path
        )
    )

    attach_long_term_memory(
        agent,
        store=(
            BrokenStore()
        ),
    )

    result = (
        agent.run(
            "Normal task"
        )
    )

    assert (
        result
        == "Done."
    )