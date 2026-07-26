"""Shared subprocess cleanup helpers for the e2e server fixtures.

Windows teardown is the hard part: ``npm.cmd run dev`` launches vite as a
grandchild, and if the intermediate wrapper exits early, ``taskkill /T``
can no longer discover the orphaned ``node.exe`` — which then squats on
the dev-server port and breaks every later e2e run (``--strictPort``
binds fail silently against the stale instance). ``kill_port_listener``
is the belt-and-braces cleanup that frees the port regardless of process
ancestry.
"""

from __future__ import annotations

import subprocess
import sys


def kill_process_tree(proc: subprocess.Popen[bytes]) -> None:
    """Terminate a subprocess and its children (vite spawns node children).

    On Windows, ``proc.terminate()`` only kills the immediate process
    (e.g. the ``cmd.exe`` wrapper that launched ``npm``); ``taskkill /T
    /F`` kills the whole tree. On non-Windows we fall back to SIGTERM +
    SIGKILL.
    """
    if proc.poll() is not None:
        return
    pid = proc.pid
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        try:
            proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                pass
    else:
        proc.terminate()
        try:
            proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                pass


def kill_port_listener(port: int) -> None:
    """Force-kill whatever process is still LISTENING on *port* (win32).

    Catches orphaned dev servers that survived :func:`kill_process_tree`
    because their parent wrapper already exited. No-op when the port is
    free or on non-Windows platforms (where the process-group kill above
    suffices).
    """
    if sys.platform != "win32":
        return
    result = subprocess.run(
        ["netstat", "-ano", "-p", "TCP"],
        capture_output=True,
        text=True,
        check=False,
    )
    needle = f":{port}"
    for line in result.stdout.splitlines():
        parts = line.split()
        # TCP  127.0.0.1:5173  0.0.0.0:0  LISTENING  <pid>
        if (
            len(parts) >= 5
            and parts[0] == "TCP"
            and parts[1].endswith(needle)
            and parts[3] == "LISTENING"
        ):
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", parts[4]],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
