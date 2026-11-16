"""Recorded-process shutdown stays separate from an application crash."""

from __future__ import annotations

import subprocess
import sys
import time

from scripts.local_session import classify_exit, start, stop, wait_for_exit


def test_requested_stop_is_intentional_even_when_the_exit_code_is_nonzero():
    assert classify_exit(0, True) == "intentional_shutdown"
    assert classify_exit(1, True) == "intentional_shutdown"
    assert classify_exit(1, False) == "application_failure"
    assert classify_exit(0, False) == "clean_exit"


def test_graceful_stop_signals_only_the_recorded_pid(tmp_path):
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        ready = tmp_path / "ready"
        managed = start(
            [
                sys.executable,
                "-c",
                "import signal, sys, time\n"
                "from pathlib import Path\n"
                "signal.signal(signal.SIGBREAK, lambda *_: sys.exit(0))\n"
                "Path(sys.argv[1]).write_text('ready', encoding='utf-8')\n"
                "time.sleep(30)\n",
                str(ready),
            ],
            tmp_path,
            tmp_path / "child.log",
        )
        deadline = time.perf_counter() + 5
        while not ready.exists() and time.perf_counter() < deadline:
            time.sleep(0.05)
        result = stop(managed, timeout=5)
        assert result["pid"] == managed.proc.pid
        assert result["exit_code"] in {0, 1}
        assert result["classification"] == "intentional_shutdown"
        assert (tmp_path / "child.log").read_text(encoding="utf-8") == ""
        assert other.poll() is None
    finally:
        if other.poll() is None:
            other.kill()
            other.wait(timeout=5)


def test_unrequested_nonzero_exit_remains_a_failure(tmp_path):
    managed = start([sys.executable, "-c", "import sys; sys.exit(3)"], tmp_path, tmp_path / "crash.log")
    result = wait_for_exit(managed, timeout=5)
    assert result["exit_code"] == 3
    assert result["classification"] == "application_failure"
