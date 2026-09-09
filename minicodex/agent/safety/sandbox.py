"""Process-level execution sandbox for MiniCodex."""

from __future__ import annotations

from dataclasses import (
    asdict,
    dataclass,
)
from pathlib import Path
import os
import signal
import subprocess
import sys
import tempfile
import time


try:

    import resource

except ImportError:  # pragma: no cover

    resource = None


# =============================================================
# Sandbox Limits
# =============================================================


@dataclass(frozen=True)
class SandboxLimits:
    """
    Deterministic subprocess limits.

    This is process-level isolation.

    It is NOT a kernel filesystem/network sandbox.
    """

    timeout_seconds: float = 30.0

    max_output_bytes: int = (
        1_000_000
    )

    max_file_bytes: int = (
        32
        * 1024
        * 1024
    )

    max_cpu_seconds: int = 20

    # RLIMIT_AS is only enabled on Linux in this implementation.
    max_memory_bytes: int = (
        1024
        * 1024
        * 1024
    )


# =============================================================
# Sandbox Result
# =============================================================


@dataclass(frozen=True)
class SandboxResult:

    started: bool

    exit_code: int | None

    stdout: str

    stderr: str

    timed_out: bool

    output_limited: bool

    duration_seconds: float

    command: tuple[
        str,
        ...,
    ]

    shell: bool

    cwd: str

    failure_type: str | None = None

    error: str | None = None

    resource_limits_applied: bool = False

    @property
    def command_succeeded(
        self,
    ) -> bool:

        return (
            self.started
            and not self.timed_out
            and self.exit_code
            == 0
        )

    def sandbox_metadata(
        self,
    ) -> dict:

        return {
            "mode": (
                "process"
            ),
            "cwd": (
                self.cwd
            ),
            "shell": (
                self.shell
            ),
            "timed_out": (
                self.timed_out
            ),
            "output_limited": (
                self.output_limited
            ),
            "duration_seconds": (
                self.duration_seconds
            ),
            "resource_limits_applied": (
                self.resource_limits_applied
            ),
            "environment_sanitized": (
                True
            ),
            "filesystem_isolated": (
                False
            ),
            "network_isolated": (
                False
            ),
        }


# =============================================================
# Sandbox Runner
# =============================================================


class SandboxRunner:
    """
    Execute child processes through a bounded process boundary.

    Guarantees implemented here:

        - fixed workspace cwd
        - sanitized environment
        - new process session
        - timeout enforcement
        - process-group termination
        - bounded captured output
        - CPU resource limit where supported
        - output file-size limit where supported
        - Linux virtual-memory limit where supported

    Important:

        This is NOT equivalent to a container, VM, chroot,
        seccomp profile, macOS seatbelt, or Linux namespace.

    Child code may still access OS resources that the current
    operating-system user can access.

    Stage 12 Safety and Stage 17 Sandbox therefore solve
    different problems.
    """

    SAFE_ENV_KEYS = {
        "PATH",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TERM",
        "SYSTEMROOT",
        "WINDIR",
    }

    def __init__(
        self,
        *,
        workspace,
        limits: (
            SandboxLimits
            | None
        ) = None,
    ):

        self.workspace = (
            Path(
                workspace
            )
            .resolve()
        )

        self.limits = (
            limits
            or SandboxLimits()
        )

        self.runtime_root = (
            self.workspace
            / ".minicodex"
            / "sandbox"
        )

        self.home_dir = (
            self.runtime_root
            / "home"
        )

        self.temp_dir = (
            self.runtime_root
            / "tmp"
        )

    # =========================================================
    # Shell Command
    # =========================================================

    def run_shell(
        self,
        command: str,
        *,
        timeout_seconds: (
            float
            | None
        ) = None,
    ) -> SandboxResult:

        return (
            self._run(
                command=[
                    "/bin/bash",
                    "-o",
                    "pipefail",
                    "-c",
                    str(
                        command
                    ),
                ],
                shell=True,
                timeout_seconds=(
                    timeout_seconds
                ),
            )
        )

    # =========================================================
    # Direct argv
    # =========================================================

    def run_argv(
        self,
        command,
        *,
        timeout_seconds: (
            float
            | None
        ) = None,
    ) -> SandboxResult:

        normalized = tuple(
            str(
                item
            )
            for item
            in command
        )

        return (
            self._run(
                command=(
                    normalized
                ),
                shell=False,
                timeout_seconds=(
                    timeout_seconds
                ),
            )
        )

    # =========================================================
    # Execute
    # =========================================================

    def _run(
        self,
        *,
        command,
        shell: bool,
        timeout_seconds: (
            float
            | None
        ),
    ) -> SandboxResult:

        normalized_command = tuple(
            str(
                item
            )
            for item
            in command
        )

        timeout = (
            self.limits
            .timeout_seconds
            if (
                timeout_seconds
                is None
            )
            else max(
                0.05,
                float(
                    timeout_seconds
                ),
            )
        )

        started_at = (
            time.perf_counter()
        )

        # =====================================================
        # Runtime Directories
        # =====================================================

        try:

            self.home_dir.mkdir(
                parents=True,
                exist_ok=True,
            )

            self.temp_dir.mkdir(
                parents=True,
                exist_ok=True,
            )

        except Exception as e:

            return SandboxResult(
                started=False,
                exit_code=None,
                stdout="",
                stderr="",
                timed_out=False,
                output_limited=False,
                duration_seconds=(
                    time.perf_counter()
                    - started_at
                ),
                command=(
                    normalized_command
                ),
                shell=(
                    shell
                ),
                cwd=str(
                    self.workspace
                ),
                failure_type=(
                    "sandbox_setup"
                ),
                error=(
                    f"{type(e).__name__}: "
                    f"{e}"
                ),
            )

        environment = (
            self._build_environment()
        )

        preexec_fn = (
            self._build_preexec_fn()
        )

        resource_limits_applied = (
            preexec_fn
            is not None
        )

        # =====================================================
        # Use Temporary Files For Output
        #
        # Avoid subprocess.communicate() accumulating arbitrary
        # stdout/stderr into parent-process memory.
        # =====================================================

        try:

            with tempfile.TemporaryFile() as stdout_file, (
                tempfile.TemporaryFile()
            ) as stderr_file:

                try:

                    process = (
                        subprocess.Popen(
                            list(
                                normalized_command
                            ),
                            cwd=(
                                self.workspace
                            ),
                            stdout=(
                                stdout_file
                            ),
                            stderr=(
                                stderr_file
                            ),
                            env=(
                                environment
                            ),
                            start_new_session=True,
                            preexec_fn=(
                                preexec_fn
                            ),
                        )
                    )

                except Exception as e:

                    return SandboxResult(
                        started=False,
                        exit_code=None,
                        stdout="",
                        stderr="",
                        timed_out=False,
                        output_limited=False,
                        duration_seconds=(
                            time.perf_counter()
                            - started_at
                        ),
                        command=(
                            normalized_command
                        ),
                        shell=(
                            shell
                        ),
                        cwd=str(
                            self.workspace
                        ),
                        failure_type=(
                            "sandbox_start"
                        ),
                        error=(
                            f"{type(e).__name__}: "
                            f"{e}"
                        ),
                        resource_limits_applied=(
                            resource_limits_applied
                        ),
                    )

                timed_out = False

                try:

                    process.wait(
                        timeout=(
                            timeout
                        )
                    )

                except (
                    subprocess.TimeoutExpired
                ):

                    timed_out = True

                    self._terminate_process_group(
                        process
                    )

                # Ensure final process status exists.
                try:

                    exit_code = (
                        process.wait(
                            timeout=1.0
                        )
                    )

                except (
                    subprocess.TimeoutExpired
                ):

                    self._kill_process_group(
                        process
                    )

                    exit_code = (
                        process.wait()
                    )

                stdout_bytes, (
                    stdout_limited
                ) = self._read_bounded(
                    stdout_file
                )

                stderr_bytes, (
                    stderr_limited
                ) = self._read_bounded(
                    stderr_file
                )

                output_limited = (
                    stdout_limited
                    or stderr_limited
                )

                stdout = (
                    stdout_bytes
                    .decode(
                        "utf-8",
                        errors="replace",
                    )
                )

                stderr = (
                    stderr_bytes
                    .decode(
                        "utf-8",
                        errors="replace",
                    )
                )

                if (
                    stdout_limited
                ):

                    stdout += (
                        "\n[Sandbox output "
                        "truncated]\n"
                    )

                if (
                    stderr_limited
                ):

                    stderr += (
                        "\n[Sandbox output "
                        "truncated]\n"
                    )

                duration = (
                    time.perf_counter()
                    - started_at
                )

                return SandboxResult(
                    started=True,
                    exit_code=(
                        exit_code
                    ),
                    stdout=(
                        stdout
                    ),
                    stderr=(
                        stderr
                    ),
                    timed_out=(
                        timed_out
                    ),
                    output_limited=(
                        output_limited
                    ),
                    duration_seconds=(
                        duration
                    ),
                    command=(
                        normalized_command
                    ),
                    shell=(
                        shell
                    ),
                    cwd=str(
                        self.workspace
                    ),
                    failure_type=(
                        "timeout"
                        if timed_out
                        else None
                    ),
                    error=(
                        (
                            "Process exceeded "
                            f"{timeout} seconds."
                        )
                        if timed_out
                        else None
                    ),
                    resource_limits_applied=(
                        resource_limits_applied
                    ),
                )

        except Exception as e:

            return SandboxResult(
                started=False,
                exit_code=None,
                stdout="",
                stderr="",
                timed_out=False,
                output_limited=False,
                duration_seconds=(
                    time.perf_counter()
                    - started_at
                ),
                command=(
                    normalized_command
                ),
                shell=(
                    shell
                ),
                cwd=str(
                    self.workspace
                ),
                failure_type=(
                    "sandbox_runtime"
                ),
                error=(
                    f"{type(e).__name__}: "
                    f"{e}"
                ),
                resource_limits_applied=(
                    resource_limits_applied
                ),
            )

    # =========================================================
    # Environment
    # =========================================================

    def _build_environment(
        self,
    ) -> dict[str, str]:
        """
        Do not inherit arbitrary parent-process secrets.

        API keys, cloud credentials, database passwords, etc.
        therefore do not automatically enter Agent-spawned code.
        """

        environment = {}

        for key in (
            self.SAFE_ENV_KEYS
        ):

            value = (
                os.environ.get(
                    key
                )
            )

            if (
                value is not None
            ):

                environment[
                    key
                ] = value

        environment[
            "HOME"
        ] = str(
            self.home_dir
        )

        environment[
            "TMPDIR"
        ] = str(
            self.temp_dir
        )

        environment[
            "TEMP"
        ] = str(
            self.temp_dir
        )

        environment[
            "TMP"
        ] = str(
            self.temp_dir
        )

        environment[
            "PYTHONDONTWRITEBYTECODE"
        ] = "1"

        environment[
            "PYTHONUNBUFFERED"
        ] = "1"

        environment[
            "PIP_DISABLE_PIP_VERSION_CHECK"
        ] = "1"

        return environment

    # =========================================================
    # POSIX Resource Limits
    # =========================================================

    def _build_preexec_fn(
        self,
    ):

        if (
            resource
            is None
        ):

            return None

        limits = (
            self.limits
        )

        def apply_limits():

            # =================================================
            # CPU
            # =================================================

            cpu_limit = max(
                1,
                int(
                    limits
                    .max_cpu_seconds
                ),
            )

            try:

                resource.setrlimit(
                    resource.RLIMIT_CPU,
                    (
                        cpu_limit,
                        cpu_limit,
                    ),
                )

            except Exception:

                pass

            # =================================================
            # Maximum file size created by child
            # =================================================

            file_limit = max(
                1024,
                int(
                    limits
                    .max_file_bytes
                ),
            )

            try:

                resource.setrlimit(
                    resource.RLIMIT_FSIZE,
                    (
                        file_limit,
                        file_limit,
                    ),
                )

            except Exception:

                pass

            # =================================================
            # Address-space limit
            #
            # RLIMIT_AS behaves poorly for many macOS runtimes,
            # so apply it only on Linux.
            # =================================================

            if (
                sys.platform
                .startswith(
                    "linux"
                )
            ):

                memory_limit = max(
                    64
                    * 1024
                    * 1024,
                    int(
                        limits
                        .max_memory_bytes
                    ),
                )

                try:

                    resource.setrlimit(
                        resource.RLIMIT_AS,
                        (
                            memory_limit,
                            memory_limit,
                        ),
                    )

                except Exception:

                    pass

        return apply_limits

    # =========================================================
    # Bounded Output
    # =========================================================

    def _read_bounded(
        self,
        file_object,
    ) -> tuple[
        bytes,
        bool,
    ]:

        limit = max(
            1,
            int(
                self.limits
                .max_output_bytes
            ),
        )

        file_object.flush()

        file_object.seek(
            0,
            os.SEEK_END,
        )

        total_size = (
            file_object.tell()
        )

        limited = (
            total_size
            > limit
        )

        file_object.seek(
            0
        )

        content = (
            file_object.read(
                limit
            )
        )

        return (
            content,
            limited,
        )

    # =========================================================
    # Graceful Process-Group Termination
    # =========================================================

    @staticmethod
    def _terminate_process_group(
        process,
    ) -> None:

        if (
            process.poll()
            is not None
        ):

            return

        try:

            os.killpg(
                process.pid,
                signal.SIGTERM,
            )

        except (
            ProcessLookupError,
            PermissionError,
            OSError,
        ):

            try:

                process.terminate()

            except Exception:

                pass

    # =========================================================
    # Hard Process-Group Kill
    # =========================================================

    @staticmethod
    def _kill_process_group(
        process,
    ) -> None:

        if (
            process.poll()
            is not None
        ):

            return

        try:

            os.killpg(
                process.pid,
                signal.SIGKILL,
            )

        except (
            ProcessLookupError,
            PermissionError,
            OSError,
        ):

            try:

                process.kill()

            except Exception:

                pass
