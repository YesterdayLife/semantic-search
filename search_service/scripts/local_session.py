"""Start and stop only the local processes this session recorded.

Qdrant, MySQL, and every other process are left untouched. On Windows, a
recorded process is started in its own process group and stopped with
CTRL_BREAK. The controller ignores that signal so the stop request does not
terminate the controller. The raw exit code is preserved. A stop requested
through this module is classified as an intentional shutdown. On Windows,
CTRL_BREAK is observed as exit code 1 even when the process log has no
traceback. An exit that nobody requested, and that is not zero, remains an
application failure.
"""

from __future__ import annotations

import ctypes
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

CREATE_NEW_PROCESS_GROUP = 0x00000200


@dataclass
class ManagedProcess:
    proc: subprocess.Popen
    log_path: Path
    requested_stop: bool = False


def classify_exit(code: int | None, requested_stop: bool) -> str:
    """Keep the raw code separate from this label. Do not rewrite the code."""
    if requested_stop:
        return "intentional_shutdown"
    if code == 0:
        return "clean_exit"
    return "application_failure"


def start(args: list[str], cwd: Path, log_path: Path) -> ManagedProcess:
    """Start one localhost process and remember its pid."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.open("ab")
    flags = CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    proc = subprocess.Popen(
        args,
        cwd=str(cwd),
        stdout=log,
        stderr=subprocess.STDOUT,
        creationflags=flags,
    )
    log.close()
    return ManagedProcess(proc, log_path)


def stop(managed: ManagedProcess, timeout: float = 15) -> dict:
    """Stop one recorded process. Other pids are not signaled."""
    managed.requested_stop = True
    _signal_recorded_process(managed.proc)
    try:
        code = managed.proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        managed.proc.kill()
        code = managed.proc.wait(timeout=5)
    return {
        "pid": managed.proc.pid,
        "exit_code": code,
        "classification": classify_exit(code, True),
        "log_path": str(managed.log_path),
    }


def wait_for_exit(managed: ManagedProcess, timeout: float = 15) -> dict:
    """Observe a process that was not asked to stop."""
    try:
        code = managed.proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        code = None
    return {
        "pid": managed.proc.pid,
        "exit_code": code,
        "classification": classify_exit(code, managed.requested_stop),
        "log_path": str(managed.log_path),
    }


def _signal_recorded_process(proc: subprocess.Popen) -> None:
    if os.name != "nt":
        proc.send_signal(signal.SIGINT)
        return
    signal.signal(signal.SIGBREAK, signal.SIG_IGN)
    try:
        os.kill(proc.pid, signal.CTRL_BREAK_EVENT)
    except OSError as exc:
        if getattr(exc, "winerror", None) != 87:
            raise
        _break_attached_console(proc.pid)


def _break_attached_console(pid: int) -> None:
    """Signal a recorded console from a later process. Other pids are not attached."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.FreeConsole()
    if not kernel32.AttachConsole(pid):
        raise OSError(ctypes.get_last_error(), f"AttachConsole failed for {pid}")
    kernel32.SetConsoleCtrlHandler(None, True)
    if not kernel32.GenerateConsoleCtrlEvent(1, 0):
        error = ctypes.get_last_error()
        kernel32.FreeConsole()
        raise OSError(error, f"CTRL_BREAK failed for {pid}")
    time.sleep(0.2)
    kernel32.FreeConsole()


def describe(managed: ManagedProcess) -> dict:
    return {"pid": managed.proc.pid, "command": managed.proc.args, "log_path": str(managed.log_path)}


def _demo() -> int:
    """Manual helper. Not used by search requests."""
    if len(sys.argv) < 2:
        print("usage: python -m scripts.local_session start|stop")
        return 2
    print("Use start() and stop() from the verification session.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_demo())
