"""Keep Rich's existing input behavior inside a bounded, interruptible I/O edge."""

import asyncio
import codecs
import io
import os
import select
import sys
from dataclasses import dataclass
from types import TracebackType
from typing import TextIO
from typing import cast

import typer
from rich.console import Console
from rich.prompt import Prompt

from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.cli_cancellation import check_cli_interruption
from spotify_manager.infrastructure.spotify_async.blocking import finish_blocking


class TerminalStream:
    """Read terminal characters without retaining an uninterruptible readline worker.

    Args:
        source: Original standard input; ownership remains with the caller.
    """

    def __init__(self, source: TextIO) -> None:
        """Duplicate the descriptor so CPython input uses this stream's readline.

        Args:
            source: Original input with its configured encoding and error policy.
        """
        self._source = source
        self._descriptor = os.dup(source.fileno())
        decoder = codecs.getincrementaldecoder(source.encoding or "utf-8")
        self._decoder = io.IncrementalNewlineDecoder(
            decoder(source.errors or "strict"), translate=True
        )
        self._pending = ""
        self._eof = False
        self.closed = False

    @property
    def encoding(self) -> str:
        """Retain the original input encoding.

        Returns:
            Original input encoding.
        """
        return self._source.encoding or "utf-8"

    @property
    def errors(self) -> str:
        """Retain the original decoder error policy.

        Returns:
            Original input error policy.
        """
        return self._source.errors or "strict"

    def fileno(self) -> int:
        """Expose the owned duplicate descriptor.

        Returns:
            This reader's descriptor.
        """
        return self._descriptor

    def isatty(self) -> bool:
        """Retain terminal detection used by Rich and the retry key reader.

        Returns:
            Whether the original source is a terminal.
        """
        return self._source.isatty()

    def readable(self) -> bool:
        """Report that the duplicated input is readable.

        Returns:
            True for this input-only stream.
        """
        return True

    def _character(self) -> str:
        while not self._pending and not self._eof:
            check_cli_interruption()
            ready, _, _ = select.select([self._descriptor], [], [], 0.1)
            if not ready:
                continue
            content = os.read(self._descriptor, 1)
            self._eof = not content
            self._pending += self._decoder.decode(content, final=self._eof)
        value, self._pending = self._pending[:1], self._pending[1:]
        return value

    def read(self, size: int = -1) -> str:
        """Read decoded characters without prefetching later prompt answers.

        Args:
            size: Maximum characters, or all remaining input for a negative size.

        Returns:
            Decoded characters through the requested size or EOF.
        """
        result = ""
        while size < 0 or len(result) < size:
            character = self._character()
            if not character:
                break
            result += character
        return result

    def readline(self, size: int = -1) -> str:
        """Read one original universal-newline-delimited answer.

        Args:
            size: Maximum characters, or an entire line for a negative size.

        Returns:
            One decoded line, retaining its terminating newline when present.
        """
        result = ""
        while size < 0 or len(result) < size:
            character = self._character()
            result += character
            if not character or character == "\n":
                break
        return result

    def close(self) -> None:
        """Release only the duplicate, preserving caller-owned standard input."""
        if not self.closed:
            os.close(self._descriptor)
        self.closed = True


@dataclass
class TerminalSession:
    """Own terminal input only at the real CLI boundary."""

    _original: TextIO | None = None
    _stream: TerminalStream | None = None

    def __enter__(self) -> None:
        """Wrap descriptor-backed input; retain memory streams used by CLI embedders."""
        if not isinstance(sys.stdin, io.TextIOBase):
            return
        source = cast(TextIO, sys.stdin)
        try:
            self._stream = TerminalStream(source)
        except OSError, ValueError, io.UnsupportedOperation:
            return
        self._original = source
        sys.stdin = cast(TextIO, self._stream)

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Restore standard input after every input worker has finished.

        Args:
            kind: Original failure type.
            error: Original failure.
            traceback: Original failure traceback.
        """
        if self._original is not None:
            sys.stdin = self._original
        if self._stream is not None:
            self._stream.close()


@dataclass(frozen=True)
class TerminalPrompt:
    """Await Rich's own formatting, validation and patched public prompt hooks.

    Args:
        source: Existing Rich prompt class supplied by the CLI adapter.
    """

    source: type[Prompt]

    async def ask(
        self,
        prompt: str,
        *,
        choices: list[str] | None = None,
        default: str | None = None,
        console: Console | None = None,
    ) -> str:
        """Await the original prompt with one bounded terminal input worker.

        Args:
            prompt: Original styled question.
            choices: Original valid responses.
            default: Original response for an empty answer, or no default.
            console: Existing console used by the command.

        Returns:
            Original validated Rich response.
        """
        check_cli_interruption()
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(
                    self.source.ask,
                    prompt,
                    choices=choices,
                    default=... if default is None else default,
                    console=console,
                )
            )
            return cast(str, await finish_blocking(task))


async def terminal_input(console: Console, prompt: str) -> str:
    """Await an unvalidated Rich input prompt.

    Args:
        console: Existing command console.
        prompt: Original styled input prompt.

    Returns:
        Original entered text.
    """
    check_cli_interruption()
    async with blocking_capacity():
        task = asyncio.create_task(asyncio.to_thread(console.input, prompt))
        return await finish_blocking(task)


async def terminal_confirm(prompt: str) -> bool:
    """Await Typer's original validation, default and abort behavior.

    Args:
        prompt: Original confirmation text.

    Returns:
        Original operator approval.
    """
    check_cli_interruption()
    async with blocking_capacity():
        task = asyncio.create_task(asyncio.to_thread(typer.confirm, prompt))
        return await finish_blocking(task)


class TerminalKey:
    """Own the existing single-key terminal retry input."""

    def read(self, timeout: float) -> str:
        """Read one key after the original polling deadline.

        Args:
            timeout: Original maximum wait in seconds.

        Returns:
            Lowercase key, or an empty string on the polling deadline.
        """
        check_cli_interruption()
        ready, _, _ = select.select([sys.stdin], [], [], timeout)
        if not ready:
            return ""
        return sys.stdin.read(1).lower()


async def terminal_key(timeout: float) -> str:
    """Await the original single-key retry input without blocking the loop.

    Args:
        timeout: Original maximum wait in seconds.

    Returns:
        Lowercase key, or an empty string on the polling deadline.
    """
    async with blocking_capacity():
        task = asyncio.create_task(asyncio.to_thread(TerminalKey().read, timeout))
        return await finish_blocking(task)
