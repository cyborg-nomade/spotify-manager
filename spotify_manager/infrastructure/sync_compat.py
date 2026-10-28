"""Preserve legacy I/O results and process control at Python boundaries."""

import asyncio
from collections.abc import Awaitable
from collections.abc import Coroutine
from dataclasses import dataclass
from types import TracebackType
from typing import Literal

from spotify_manager.infrastructure.spotify_async.blocking import finish_blocking


@dataclass
class LegacyControlError(RuntimeError):
    """Carry a worker's original process-control exception back to its caller.

    Args:
        control: Original synchronous operator or SDK process-control exception.
    """

    control: KeyboardInterrupt | SystemExit


class LegacyControl:
    """Keep a worker-local control exception from terminating the async event loop."""

    def __enter__(self) -> None:
        """Enter the concrete synchronous I/O call's exception boundary."""

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        """Transfer only original process control; retain all ordinary SDK errors.

        Args:
            kind: Original failure type.
            error: Original failure object.
            traceback: Original failure traceback.

        Returns:
            False for the original ordinary failure or a successful call.

        Raises:
            LegacyControlError: The worker received an original control exception.
        """
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise LegacyControlError(error) from error
        return False


async def finish_legacy[T](task: asyncio.Task[T]) -> T:
    """Finish concrete I/O before restoring its caller's original process control.

    Args:
        task: Already bounded SDK, operator or persistence call.

    Returns:
        Original synchronous call result.

    Raises:
        KeyboardInterrupt: The caller's synchronous I/O operation interrupted itself.
        SystemExit: The caller's synchronous I/O operation requested an exit.
    """
    try:
        return await finish_blocking(task)
    except LegacyControlError as error:
        raise error.control from None
    except asyncio.CancelledError:
        _close_unstarted(task.result())
        raise


def _close_unstarted(value: object) -> None:
    if isinstance(value, Coroutine):
        value.close()


async def legacy_result[T](value: T | Awaitable[T]) -> T:
    """Accept synchronous or already async implementations of a legacy I/O resource.

    Args:
        value: Result returned by the explicitly called resource method.

    Returns:
        Original completed resource result.
    """
    if isinstance(value, Awaitable):
        return await value
    return value
