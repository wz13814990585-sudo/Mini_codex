from ..agent.long_term_memory import (
    LongTermMemoryStore,
)


# =============================================================
# Create + Persist
# =============================================================


def test_long_term_memory_persists(
    tmp_path,
):

    path = (
        tmp_path
        / "memory.json"
    )

    store = (
        LongTermMemoryStore(
            path=path,
            repository_key="demo",
        )
    )

    record = (
        store.create_record(
            task_prompt=(
                "Fix parser error"
            ),
            outcome=(
                "success"
            ),
            summary=(
                "Parser fix passed tests."
            ),
            touched_files=(
                "parser.py",
            ),
            tags=(
                "editing",
            ),
        )
    )

    store.remember(
        record
    )

    assert (
        path.exists()
        is True
    )

    reloaded = (
        LongTermMemoryStore(
            path=path,
            repository_key="demo",
        )
    )

    assert (
        len(
            reloaded.records
        )
        == 1
    )

    assert (
        reloaded.records[
            0
        ].task_prompt
        == "Fix parser error"
    )


# =============================================================
# Relevant Retrieval
# =============================================================


def test_retrieve_relevant_memory(
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

    parser_record = (
        store.create_record(
            task_prompt=(
                "Fix parser validation bug"
            ),
            outcome="success",
            summary=(
                "Updated parser.py and "
                "acceptance tests passed."
            ),
            touched_files=(
                "parser.py",
            ),
        )
    )

    docs_record = (
        store.create_record(
            task_prompt=(
                "Update README documentation"
            ),
            outcome="success",
            summary=(
                "Updated README."
            ),
            touched_files=(
                "README.md",
            ),
        )
    )

    store.remember(
        parser_record
    )

    store.remember(
        docs_record
    )

    results = (
        store.retrieve(
            (
                "There is another "
                "parser validation problem"
            )
        )
    )

    assert (
        results
    )

    assert (
        results[
            0
        ].record.task_prompt
        == "Fix parser validation bug"
    )


# =============================================================
# Irrelevant Memory Is Not Injected
# =============================================================


def test_irrelevant_memory_not_retrieved(
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
                "Database connection fixed."
            ),
        )
    )

    results = (
        store.retrieve(
            "Change CSS button color"
        )
    )

    assert (
        results
        == []
    )


# =============================================================
# Same Task Replaces Old Memory
# =============================================================


def test_same_task_replaces_previous_memory(
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

    first = (
        store.create_record(
            task_prompt=(
                "Fix parser"
            ),
            outcome=(
                "incomplete"
            ),
            summary=(
                "First attempt failed."
            ),
        )
    )

    second = (
        store.create_record(
            task_prompt=(
                "Fix parser"
            ),
            outcome=(
                "success"
            ),
            summary=(
                "Second attempt passed."
            ),
        )
    )

    store.remember(
        first
    )

    store.remember(
        second
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
        == "success"
    )


# =============================================================
# Bounded Store
# =============================================================


def test_long_term_memory_is_bounded(
    tmp_path,
):

    store = (
        LongTermMemoryStore(
            path=(
                tmp_path
                / "memory.json"
            ),
            repository_key="demo",
            max_records=3,
        )
    )

    for index in range(
        5
    ):

        store.remember(
            store.create_record(
                task_prompt=(
                    f"Task {index}"
                ),
                outcome="success",
                summary=(
                    f"Completed {index}"
                ),
            )
        )

    assert (
        len(
            store.records
        )
        == 3
    )

    prompts = [
        record.task_prompt
        for record
        in store.records
    ]

    assert (
        "Task 0"
        not in prompts
    )

    assert (
        "Task 4"
        in prompts
    )


# =============================================================
# Repository Separation
# =============================================================


def test_repository_key_filters_memory(
    tmp_path,
):

    path = (
        tmp_path
        / "memory.json"
    )

    store_a = (
        LongTermMemoryStore(
            path=path,
            repository_key="repo-a",
        )
    )

    store_a.remember(
        store_a.create_record(
            task_prompt=(
                "Fix parser"
            ),
            outcome="success",
            summary="Done.",
        )
    )

    store_b = (
        LongTermMemoryStore(
            path=path,
            repository_key="repo-b",
        )
    )

    results = (
        store_b.retrieve(
            "Fix parser"
        )
    )

    assert (
        results
        == []
    )


# =============================================================
# Render
# =============================================================


def test_render_retrieved_warns_historical_only(
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
                "Fix parser bug"
            ),
            outcome="success",
            summary=(
                "parser.py passed tests."
            ),
            touched_files=(
                "parser.py",
            ),
        )
    )

    retrieved = (
        store.retrieve(
            "parser bug"
        )
    )

    rendered = (
        store.render_retrieved(
            retrieved
        )
    )

    assert (
        "historical only"
        in rendered
    )

    assert (
        "verify current"
        in rendered
    )

    assert (
        "parser.py"
        in rendered
    )