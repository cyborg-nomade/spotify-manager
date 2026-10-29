"""Protect Rich input semantics, event-loop responsiveness and terminal ownership."""

import asyncio
import io
import os
from typing import TextIO
from typing import cast

import pytest
from rich.console import Console
from rich.prompt import Prompt

from spotify_manager.infrastructure.cli_cancellation import CliCancellation
from spotify_manager.infrastructure.cli_cancellation import CliInterruptedError
from spotify_manager.interfaces.cli.terminal import TerminalPrompt
from spotify_manager.interfaces.cli.terminal import TerminalStream


@pytest.mark.parametrize(
    "answer,expected", [("k\n", "k"), ("\n", "r"), ("x\nk\n", "k")]
)
async def test_rich_validation_and_default_are_preserved(
    monkeypatch: pytest.MonkeyPatch, answer: str, expected: str
) -> None:
    """Keep Rich's original validation loop and empty-answer default.

    Args:
        monkeypatch: Scoped memory input substitution.
        answer: Original terminal input, including invalid answers.
        expected: Original validated action.
    """
    output = io.StringIO()
    monkeypatch.setattr("sys.stdin", io.StringIO(answer))
    result = await TerminalPrompt(Prompt).ask(
        "Action", choices=["r", "k"], default="r", console=Console(file=output)
    )
    assert result == expected
    assert "Action" in output.getvalue()
    assert ("Please select" in output.getvalue()) == answer.startswith("x")


async def test_waiting_for_an_answer_leaves_the_loop_responsive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Run another task before releasing a real pipe-backed input worker.

    Args:
        monkeypatch: Scoped standard input substitution.
    """
    reading, writing = os.pipe()
    with os.fdopen(reading) as source, CliCancellation() as cancellation:
        stream = TerminalStream(source)
        monkeypatch.setattr("sys.stdin", cast(TextIO, stream))
        task = asyncio.create_task(TerminalPrompt(Prompt).ask("Action", default="r"))
        try:
            await asyncio.sleep(0)
            assert not task.done()
            os.write(writing, b"k\n")
            assert await task == "k"
        finally:
            cancellation.request()
            os.close(writing)
            stream.close()
        assert not source.closed


async def test_interruption_releases_a_waiting_terminal_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stop waiting for input without leaving executor shutdown blocked.

    Args:
        monkeypatch: Scoped standard input substitution.
    """
    reading, writing = os.pipe()
    with os.fdopen(reading) as source, CliCancellation() as cancellation:
        stream = TerminalStream(source)
        monkeypatch.setattr("sys.stdin", cast(TextIO, stream))
        task = asyncio.create_task(TerminalPrompt(Prompt).ask("Action"))
        try:
            await asyncio.sleep(0)
            cancellation.request()
            await _expect_interrupted(task)
        finally:
            os.close(writing)
            stream.close()


async def _expect_interrupted(task: asyncio.Task[str]) -> None:
    with pytest.raises(CliInterruptedError):
        await task


def test_terminal_decoder_preserves_unicode_and_line_boundaries() -> None:
    """Decode multibyte input and universal newlines without consuming later answers."""
    reading, writing = os.pipe()
    os.write(writing, "café\r\nnext\n".encode())
    os.close(writing)
    with os.fdopen(reading, encoding="utf-8") as source:
        stream = TerminalStream(source)
        try:
            assert stream.readline() == "café\n"
            assert stream.read(1) == "n"
            assert stream.readline() == "ext\n"
            assert stream.readline() == ""
            assert stream.read(0) == ""
        finally:
            stream.close()
            stream.close()
        assert not source.closed
