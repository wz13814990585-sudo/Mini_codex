from abc import ABC, abstractmethod
from typing import Any


class BaseTool(ABC):

    name: str
    description: str
    parameters: dict

    @abstractmethod
    def execute(self, **kwargs) -> Any:
        pass

    def to_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            }
        }
