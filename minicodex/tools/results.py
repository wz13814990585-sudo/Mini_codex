from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolResult:
    success: bool
    summary: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    llm_content: str | None = None

    def to_llm_text(self) -> str:
        parts = [self.summary]

        if self.llm_content:
            parts.append(self.llm_content)

        if self.error:
            parts.append(f"Error: {self.error}")

        return "\n\n".join(parts)


