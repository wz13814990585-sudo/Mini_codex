from ..agent.edit_failure import EditFailureType
from ..agent.edit_retry import EditRetryPolicy
from ..agent.tool_executor import PreparedToolCall, ToolExecutor
from ..tools.results import ToolResult


class RaisingRegistry:
    def __init__(self, error):
        self.error = error

    def execute(self, name, arguments):
        raise self.error


def test_edit_exception_is_exported_as_typed_failure():
    executor = ToolExecutor(RaisingRegistry(ValueError("Requested line range 9-10 exceeds file length 3.")))

    result = executor.execute_prepared(
        PreparedToolCall("replace_lines", {"path": "app.py"})
    ).result

    assert result.data["failure_type"] == EditFailureType.INVALID_RANGE.value
    assert result.data["reason_code"] == "invalid_range"


def test_symbol_not_found_recovery_allows_one_symbol_search():
    policy = EditRetryPolicy()
    message = policy.observe(
        "replace_symbol",
        {"symbol": "missing"},
        ToolResult(
            success=False,
            summary="not found",
            data={
                "symbol": "missing",
                "edit_failure_type": EditFailureType.SYMBOL_NOT_FOUND.value,
            },
        ),
    )

    assert "search_symbol" in message
    assert policy.restriction_reason("search_symbol", {"query": "missing"}) is None
    assert policy.restriction_reason("read_file", {"path": "app.py"}) is not None
