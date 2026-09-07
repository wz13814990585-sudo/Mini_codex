"""Deterministic validation for static HTML with inline JavaScript."""

from __future__ import annotations

from collections import Counter
from html.parser import HTMLParser
import json
from pathlib import Path
import shutil
import tempfile

from ..agent.sandbox import (
    SandboxLimits,
    SandboxRunner,
)

from .base import BaseTool
from .paths import resolve_workspace_path
from .results import ToolResult


class _StaticWebParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags = Counter()
        self.data_row_count = 0
        self.data_col_count = 0
        self.inline_scripts: list[dict] = []
        self._script: dict | None = None

    def handle_starttag(self, tag, attrs):
        lowered = tag.lower()
        self.tags[lowered] += 1
        attributes = {
            str(name).lower(): value
            for name, value in attrs
        }
        self.data_row_count += int(
            "data-row" in attributes
        )
        self.data_col_count += int(
            "data-col" in attributes
        )

        if lowered == "script" and not attributes.get("src"):
            self._script = {
                "attributes": attributes,
                "parts": [],
            }

    def handle_data(self, data):
        if self._script is not None:
            self._script["parts"].append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "script" and self._script is not None:
            self.inline_scripts.append(
                {
                    "attributes": self._script["attributes"],
                    "content": "".join(self._script["parts"]),
                }
            )
            self._script = None


class ValidateStaticWebTool(BaseTool):
    name = "validate_static_web"

    description = (
        "Deterministically validate one static HTML file. It parses "
        "HTML, extracts inline script blocks internally, checks "
        "JavaScript syntax with Node when available, and reports "
        "structured element/data-marker counts. This is targeted "
        "acceptance evidence and does not replace full regression "
        "tests. Use optional minimum counts only when the task "
        "explicitly requires those static HTML attributes/elements."
    )

    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Workspace-relative HTML file path.",
            },
            "min_button_count": {
                "type": "integer",
                "minimum": 0,
                "description": "Required static <button> count.",
            },
            "min_data_row_count": {
                "type": "integer",
                "minimum": 0,
                "description": (
                    "Required count of static elements with data-row."
                ),
            },
            "min_data_col_count": {
                "type": "integer",
                "minimum": 0,
                "description": (
                    "Required count of static elements with data-col."
                ),
            },
            "require_inline_script": {
                "type": "boolean",
                "description": (
                    "Fail when no inline script exists. Defaults false."
                ),
            },
        },
        "required": ["path"],
    }

    def __init__(
        self,
        workspace: str | Path = ".",
        timeout: int = 30,
        sandbox: SandboxRunner | None = None,
        node_executable: str | None = None,
    ):
        self.workspace = Path(workspace).resolve()
        self.timeout = max(1, int(timeout))
        self.sandbox = sandbox or SandboxRunner(
            workspace=self.workspace,
            limits=SandboxLimits(
                timeout_seconds=self.timeout,
            ),
        )
        self.node_executable = (
            node_executable
            if node_executable is not None
            else shutil.which("node")
        )

    def execute(
        self,
        path: str,
        min_button_count: int = 0,
        min_data_row_count: int = 0,
        min_data_col_count: int = 0,
        require_inline_script: bool = False,
    ) -> ToolResult:
        target = resolve_workspace_path(
            self.workspace,
            path,
        )

        minimums = {
            "button_count": max(0, int(min_button_count)),
            "data_row_count": max(0, int(min_data_row_count)),
            "data_col_count": max(0, int(min_data_col_count)),
        }
        errors: list[str] = []

        if not target.exists() or not target.is_file():
            return self._result(
                path=path,
                outcome="failed",
                html_parse="failed",
                script_syntax="not_checked",
                errors=[f"HTML file not found: {path}"],
            )

        try:
            source = target.read_text(encoding="utf-8")
        except Exception as error:
            return self._result(
                path=path,
                outcome="failed",
                html_parse="failed",
                script_syntax="not_checked",
                errors=[
                    f"Could not read HTML: {type(error).__name__}: {error}"
                ],
            )

        parser = _StaticWebParser()

        try:
            parser.feed(source)
            parser.close()
            html_parse = "passed"
        except Exception as error:
            html_parse = "failed"
            errors.append(
                f"HTML parse failed: {type(error).__name__}: {error}"
            )

        if parser.tags["html"] == 0 or parser.tags["body"] == 0:
            html_parse = "failed"
            errors.append(
                "Document must contain <html> and <body> elements."
            )

        counts = {
            "button_count": parser.tags["button"],
            "data_row_count": parser.data_row_count,
            "data_col_count": parser.data_col_count,
            "data_row_marker_count": source.count("data-row"),
            "data_col_marker_count": source.count("data-col"),
        }

        for name, minimum in minimums.items():
            if counts[name] < minimum:
                errors.append(
                    f"{name}={counts[name]} is below required {minimum}."
                )

        if require_inline_script and not parser.inline_scripts:
            errors.append("At least one inline <script> block is required.")

        script_syntax = self._validate_scripts(
            parser.inline_scripts,
            errors,
        )

        if errors:
            outcome = "failed"
        elif script_syntax == "unavailable":
            outcome = "inconclusive"
        else:
            outcome = "passed"

        return self._result(
            path=path,
            outcome=outcome,
            html_parse=html_parse,
            script_syntax=script_syntax,
            inline_script_count=len(parser.inline_scripts),
            counts=counts,
            errors=errors,
        )

    def _validate_scripts(
        self,
        scripts: list[dict],
        errors: list[str],
    ) -> str:
        if not scripts:
            return "not_applicable"

        if not self.node_executable:
            errors.append(
                "Node.js is unavailable; inline JavaScript syntax "
                "could not be checked."
            )
            return "unavailable"

        temp_dir = Path(self.sandbox.temp_dir)
        temp_dir.mkdir(parents=True, exist_ok=True)

        for index, script in enumerate(scripts, start=1):
            script_type = str(
                script["attributes"].get("type", "")
                or ""
            ).lower()
            suffix = ".mjs" if script_type == "module" else ".js"
            temp_path: Path | None = None

            try:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    suffix=suffix,
                    prefix="static-web-",
                    dir=temp_dir,
                    delete=False,
                ) as handle:
                    handle.write(script["content"])
                    temp_path = Path(handle.name)

                result = self.sandbox.run_argv(
                    [
                        self.node_executable,
                        "--check",
                        str(temp_path),
                    ],
                    timeout_seconds=self.timeout,
                )

                if (
                    not result.started
                    or result.timed_out
                    or result.exit_code != 0
                ):
                    detail = (
                        result.stderr.strip()
                        or result.error
                        or "Node syntax check failed."
                    )
                    errors.append(
                        f"Inline script {index}: {detail}"
                    )
                    return "failed"
            finally:
                if temp_path is not None:
                    temp_path.unlink(missing_ok=True)

        return "passed"

    @staticmethod
    def _result(
        *,
        path: str,
        outcome: str,
        html_parse: str,
        script_syntax: str,
        inline_script_count: int = 0,
        counts: dict | None = None,
        errors: list[str],
    ) -> ToolResult:
        metrics = {
            "button_count": 0,
            "data_row_count": 0,
            "data_col_count": 0,
            "data_row_marker_count": 0,
            "data_col_marker_count": 0,
        }
        metrics.update(counts or {})
        data = {
            "path": path,
            "outcome": outcome,
            "html_parse": html_parse,
            "script_syntax": script_syntax,
            "inline_script_count": inline_script_count,
            **metrics,
            "errors": errors,
            "validation_succeeded": outcome == "passed",
        }
        summary = (
            f"Static web validation {outcome} for {path}: "
            f"HTML={html_parse}, JavaScript={script_syntax}, "
            f"inline_scripts={inline_script_count}, "
            f"buttons={metrics['button_count']}, "
            f"data-row={metrics['data_row_count']}, "
            f"data-col={metrics['data_col_count']}."
        )
        return ToolResult(
            success=True,
            summary=summary,
            data=data,
            llm_content=json.dumps(
                data,
                ensure_ascii=False,
                indent=2,
            ),
        )
