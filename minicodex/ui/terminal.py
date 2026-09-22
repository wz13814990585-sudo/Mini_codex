"""One opt-in, local PTY session for the MiniCodex workspace UI.

This is a real user shell, not an Agent tool. It deliberately does not claim
to enforce the Agent's file/command safety policy; the UI must label it clearly.
"""

from __future__ import annotations

from collections import deque
import codecs
import os
from pathlib import Path
import secrets
import signal
import struct
import subprocess
import threading

try:  # POSIX only; the rest of the UI remains importable on Windows.
    import fcntl
    import pty
    import termios
except ImportError:  # pragma: no cover - exercised on POSIX CI
    fcntl = pty = termios = None


class TerminalError(ValueError):
    """A user-visible terminal lifecycle or input error."""


class WorkspaceTerminal:
    """Bounded PTY output, serialized input, and owned process-group cleanup."""

    _MAX_CHUNKS = 512
    _MAX_INPUT_BYTES = 8192

    def __init__(self, workspace: str | Path, *, shell: str | None = None) -> None:
        self.workspace = Path(workspace).resolve()
        self.shell = shell or os.environ.get("SHELL") or "/bin/sh"
        self._lock = threading.RLock()
        self._write_lock = threading.Lock()
        self._chunks: deque[tuple[int, str]] = deque(maxlen=self._MAX_CHUNKS)
        self._sequence = 0
        self._session_id = ""
        self._pid: int | None = None
        self._process: subprocess.Popen[bytes] | None = None
        self._fd: int | None = None
        self._reader_thread: threading.Thread | None = None
        self._running = False
        self._exit_code: int | None = None

    @property
    def running(self) -> bool:
        with self._lock:
            return self._running

    def start(self, *, cols: int = 80, rows: int = 24) -> dict:
        if pty is None:
            raise TerminalError("Interactive terminal requires a POSIX host.")
        cols, rows = self._dimensions(cols, rows)
        shell = Path(self.shell)
        if not shell.is_absolute() or not shell.is_file() or not os.access(shell, os.X_OK):
            raise TerminalError("Configured shell is not an executable absolute path.")
        with self._lock:
            if self._running:
                return self.snapshot()
            env = os.environ.copy()
            env.update({"TERM": "xterm-256color", "COLORTERM": "truecolor"})
            fd, slave = pty.openpty()
            try:
                process = subprocess.Popen(
                    [str(shell), "-i"],
                    stdin=slave, stdout=slave, stderr=slave,
                    cwd=self.workspace, env=env,
                    start_new_session=True, close_fds=True,
                )
            except BaseException:
                os.close(fd)
                raise
            finally:
                os.close(slave)
            pid = process.pid
            self._pid = pid
            self._process = process
            self._fd = fd
            self._session_id = secrets.token_urlsafe(12)
            self._sequence = 0
            self._chunks.clear()
            self._exit_code = None
            self._running = True
            self._set_size(fd, pid, cols, rows)
            self._reader_thread = threading.Thread(
                target=self._read_output, args=(process, fd), daemon=True,
                name=f"MiniCodex-PTY-{pid}",
            )
            self._reader_thread.start()
            return self.snapshot()

    def snapshot(self, *, after: int = 0) -> dict:
        with self._lock:
            oldest = self._chunks[0][0] if self._chunks else self._sequence + 1
            reset = after < oldest - 1
            chunks = [
                {"sequence": sequence, "data": data}
                for sequence, data in self._chunks
                if reset or sequence > after
            ]
            return {
                "session_id": self._session_id,
                "running": self._running,
                "exit_code": self._exit_code,
                "sequence": self._sequence,
                "reset": reset,
                "chunks": chunks,
            }

    def write(self, data: str) -> None:
        if not isinstance(data, str):
            raise TerminalError("Terminal input must be text.")
        encoded = data.encode("utf-8")
        if len(encoded) > self._MAX_INPUT_BYTES:
            raise TerminalError("Terminal input is too large.")
        with self._write_lock:
            with self._lock:
                if not self._running or self._fd is None:
                    raise TerminalError("Terminal is not running.")
                fd = self._fd
            offset = 0
            try:
                while offset < len(encoded):
                    offset += os.write(fd, encoded[offset:])
            except OSError as exc:
                raise TerminalError("Terminal input failed; restart the session.") from exc

    def resize(self, *, cols: int, rows: int) -> dict:
        cols, rows = self._dimensions(cols, rows)
        with self._lock:
            if not self._running or self._fd is None or self._pid is None:
                raise TerminalError("Terminal is not running.")
            self._set_size(self._fd, self._pid, cols, rows)
            return self.snapshot(after=self._sequence)

    def stop(self) -> dict:
        with self._lock:
            pid = self._pid
            reader = self._reader_thread
            if not self._running or pid is None:
                return self.snapshot(after=self._sequence)
        self._signal_group(pid, signal.SIGHUP)
        if reader is not None:
            reader.join(timeout=0.75)
            if reader.is_alive():
                self._signal_group(pid, signal.SIGTERM)
                reader.join(timeout=0.75)
            if reader.is_alive():
                self._signal_group(pid, signal.SIGKILL)
                reader.join(timeout=1)
        return self.snapshot(after=self._sequence)

    @staticmethod
    def _dimensions(cols: int, rows: int) -> tuple[int, int]:
        if type(cols) is not int or type(rows) is not int or not 20 <= cols <= 300 or not 5 <= rows <= 120:
            raise TerminalError("Terminal size is outside the supported range.")
        return cols, rows

    @staticmethod
    def _set_size(fd: int, pid: int, cols: int, rows: int) -> None:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        WorkspaceTerminal._signal_group(pid, signal.SIGWINCH)

    @staticmethod
    def _signal_group(pid: int, sig: int) -> None:
        try:
            os.killpg(pid, sig)
        except ProcessLookupError:
            pass

    def _read_output(self, process: subprocess.Popen[bytes], fd: int) -> None:
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        try:
            while True:
                try:
                    chunk = os.read(fd, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                data = decoder.decode(chunk)
                if data:
                    with self._lock:
                        self._sequence += 1
                        self._chunks.append((self._sequence, data))
            tail = decoder.decode(b"", final=True)
            if tail:
                with self._lock:
                    self._sequence += 1
                    self._chunks.append((self._sequence, tail))
        finally:
            try:
                os.close(fd)
            except OSError:
                pass
            exit_code = process.wait()
            with self._lock:
                if self._process is process:
                    self._fd = None
                    self._running = False
                    self._exit_code = exit_code
