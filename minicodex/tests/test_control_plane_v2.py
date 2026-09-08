from types import SimpleNamespace

from ..agent.agent import MiniCodexAgent
from ..agent.action_controller import ActionController
from ..agent.task_state import TaskState
from ..agent.execution_mode import ExecutionMode
from ..agent.execution_policy import policy_for
from ..agent.finalization import FinalizationController
from ..agent.long_term_memory import LongTermMemoryStore
from ..agent.long_term_memory_runtime import attach_long_term_memory
from ..tools.registry import ToolRegistry


def state(edit=0, validation=0):
    return TaskState(
        edit_revision=edit,
        completed_plan_steps=(),
        validation_revision=validation,
        plan_revision=0,
        rollback_revision=0,
    )


def test_action_controller_blocks_reconnaissance_but_allows_validation():
    controller = ActionController()
    policy = policy_for(ExecutionMode.FAST)
    controller.reset(state())
    for _ in range(policy.max_inspection_calls):
        controller.observe_action("search_code", state())

    assert controller.restriction_reason("search_code", {}, policy)
    assert controller.restriction_reason("validate_static_web", {}, policy) is None

    controller.observe_action("write_file", state(edit=1))
    assert controller.action_required is False
    assert controller.consecutive_inspections == 0


def test_finalization_blocks_pointless_search_only_when_active():
    controller = FinalizationController()
    policy = policy_for(ExecutionMode.FAST)

    assert controller.enter_if_needed(3, policy) is False
    assert controller.restriction_reason("search_code") is None
    assert controller.enter_if_needed(2, policy) is True
    assert controller.restriction_reason("search_code")
    assert controller.restriction_reason("validate_static_web") is None


def test_fast_repo_map_is_revision_cached_and_invalidated_after_edit():
    repo_map = SimpleNamespace(calls=0)

    def build():
        repo_map.calls += 1
        return f"map-{repo_map.calls}"

    repo_map.build = build
    agent = MiniCodexAgent(
        llm=None,
        registry=ToolRegistry(),
        planner=None,
        repo_map=repo_map,
    )
    agent.execution_policy = policy_for(ExecutionMode.FAST)

    agent._refresh_repo_map(force=True)
    agent._refresh_repo_map()
    assert repo_map.calls == 1

    agent.validation_pipeline.record_edit()
    agent._refresh_repo_map()
    agent._refresh_repo_map()
    assert repo_map.calls == 2


def test_fast_long_term_memory_retrieval_is_disabled(tmp_path):
    class FakeAgent:
        def __init__(self):
            self._retrieved_long_term_memory = []
            self.retrieve_policy = policy_for(ExecutionMode.FAST)

        def resolve_execution_policy(self, user_input):
            return self.retrieve_policy

        def _build_turn_context(self, *args, **kwargs):
            return "context"

        def run(self, user_input, use_planning=None):
            return "Done."

    class SpyStore(LongTermMemoryStore):
        def __init__(self, path):
            super().__init__(path=path, repository_key="repo")
            self.retrieve_calls = 0

        def retrieve(self, *args, **kwargs):
            self.retrieve_calls += 1
            return super().retrieve(*args, **kwargs)

    agent = FakeAgent()
    store = SpyStore(tmp_path / "memory.json")
    attach_long_term_memory(agent, store=store)

    assert agent.run("Create try_code/hello.html") == "Done."
    assert store.retrieve_calls == 0


def test_complex_long_term_memory_retrieval_remains_enabled(tmp_path):
    class FakeAgent:
        def __init__(self):
            self._retrieved_long_term_memory = []

        def resolve_execution_policy(self, user_input):
            return policy_for(ExecutionMode.COMPLEX)

        def _build_turn_context(self, *args, **kwargs):
            return "context"

        def run(self, user_input, use_planning=None):
            return "Done."

    class SpyStore(LongTermMemoryStore):
        def __init__(self, path):
            super().__init__(path=path, repository_key="repo")
            self.retrieve_calls = 0

        def retrieve(self, *args, **kwargs):
            self.retrieve_calls += 1
            return []

    agent = FakeAgent()
    store = SpyStore(tmp_path / "memory.json")
    attach_long_term_memory(agent, store=store)

    assert agent.run("Refactor async runtime architecture") == "Done."
    assert store.retrieve_calls == 1


def test_fast_system_prompt_is_compact():
    agent = MiniCodexAgent(
        llm=None,
        registry=ToolRegistry(),
        planner=None,
        repo_map=None,
    )
    agent.execution_policy = policy_for(ExecutionMode.FAST)

    prompt = agent._build_system_prompt()

    assert "FAST mode" in prompt
    assert len(prompt) < 1000
