"""Verify real terminal interruption drains input workers and restores stdin."""

import os
import pty
import select
import signal
import subprocess
import sys
from time import monotonic


PROMPT_PROGRAM = """
import sys
from rich.prompt import Prompt
from spotify_manager.bootstrap.execution import run_cli
from spotify_manager.interfaces.cli.terminal import TerminalPrompt

try:
    run_cli(TerminalPrompt(Prompt).ask("Action", choices=["r", "k"], default="r"))
except KeyboardInterrupt:
    print("STOPPED", sys.stdin.closed, flush=True)
"""


def _read_until(descriptor: int, marker: bytes) -> bytes:
    output = bytearray()
    deadline = monotonic() + 10
    while marker not in output:
        remaining = deadline - monotonic()
        assert remaining > 0, output.decode(errors="replace")
        ready, _, _ = select.select([descriptor], [], [], remaining)
        assert ready, output.decode(errors="replace")
        output.extend(os.read(descriptor, 4096))
    return bytes(output)


def test_sigint_exits_a_real_prompt_without_closing_caller_stdin() -> None:
    """Interrupt only after the prompt is visible, then require clean process exit."""
    parent, child = pty.openpty()
    process = subprocess.Popen(
        [sys.executable, "-c", PROMPT_PROGRAM],
        stdin=child,
        stdout=child,
        stderr=child,
        start_new_session=True,
    )
    os.close(child)
    try:
        _read_until(parent, b"Action")
        process.send_signal(signal.SIGINT)
        _read_until(parent, b"STOPPED False")
        assert process.wait(timeout=10) == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        os.close(parent)
