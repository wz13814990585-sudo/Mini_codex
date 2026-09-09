"""Select the system prompt for the active execution policy."""

from ..routing import ExecutionMode
from ...prompts.system import (
    build_fast_system_prompt,
    build_standard_system_prompt,
    build_system_prompt,
)


class PromptBuilder:
    def build(self, agent, **kwargs) -> str:
        del kwargs
        policy = getattr(agent, "execution_policy", None)
        if policy is not None and policy.compact_context:
            return build_fast_system_prompt()
        if policy is not None and policy.mode == ExecutionMode.STANDARD:
            return build_standard_system_prompt()
        return build_system_prompt()
