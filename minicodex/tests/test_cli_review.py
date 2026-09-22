"""Offline tests for the CLI-first review and rollback path."""

from types import SimpleNamespace

from ..agent.editing.checkpoint import CheckpointManager
from ..agent.editing.rollback import RollbackEngine
from ..cli_review import checkpoint_diff, review_task


def _edited_agent(workspace):
    manager = CheckpointManager(workspace)
    checkpoint = manager.capture(path="index.html", edit_revision=1)
    (workspace / "index.html").write_text("<h1>Game</h1>\n", encoding="utf-8")
    manager.seal(checkpoint.checkpoint_id)
    rollback = RollbackEngine(workspace=workspace, checkpoint_manager=manager)
    return SimpleNamespace(checkpoint_manager=manager, undo_task=rollback.undo_task)


def test_cli_review_accept_keeps_checkpointed_new_file(tmp_path):
    agent = _edited_agent(tmp_path)
    output = []
    assert "+++ b/index.html" in checkpoint_diff(agent, tmp_path)
    assert review_task(agent, tmp_path, input_fn=lambda _: "accept", print_fn=output.append) == "accepted"
    assert (tmp_path / "index.html").read_text(encoding="utf-8") == "<h1>Game</h1>\n"


def test_cli_review_reject_restores_only_agent_edit(tmp_path):
    (tmp_path / "user.txt").write_text("keep", encoding="utf-8")
    agent = _edited_agent(tmp_path)
    assert review_task(agent, tmp_path, input_fn=lambda _: "reject", print_fn=lambda _: None) == "rejected"
    assert not (tmp_path / "index.html").exists()
    assert (tmp_path / "user.txt").read_text(encoding="utf-8") == "keep"


def test_cli_review_refuses_concurrent_change_without_overwriting(tmp_path):
    agent = _edited_agent(tmp_path)
    (tmp_path / "index.html").write_text("external edit\n", encoding="utf-8")
    assert review_task(agent, tmp_path, input_fn=lambda _: "reject", print_fn=lambda _: None) == "conflict"
    assert (tmp_path / "index.html").read_text(encoding="utf-8") == "external edit\n"


def test_cli_review_interrupted_keeps_files_untouched(tmp_path):
    agent = _edited_agent(tmp_path)

    def interrupted(_prompt):
        raise EOFError

    assert review_task(agent, tmp_path, input_fn=interrupted, print_fn=lambda _: None) == "pending"
    assert (tmp_path / "index.html").read_text(encoding="utf-8") == "<h1>Game</h1>\n"
