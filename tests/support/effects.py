"""Record ordered effects and inject one failure at a named boundary."""

import hashlib
from collections import deque
from collections.abc import Callable
from collections.abc import Iterable
from dataclasses import dataclass
from dataclasses import fields
from dataclasses import is_dataclass
from datetime import UTC
from datetime import date
from datetime import datetime
from datetime import tzinfo
from enum import Enum
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from typing import Literal
from typing import Self
from typing import TypedDict

import pytest
from huggingface_hub import CommitOperationAdd
from huggingface_hub import CommitOperationDelete
from pydantic import BaseModel
from spotipy.exceptions import SpotifyException

from spotify_manager.routines.analyse_library import LibrarySyncError
from spotify_manager.routines.upload_library_files import LibraryFilesUploadError


type Json = None | bool | int | float | str | list[Json] | dict[str, Json]
type Phase = Literal["before", "after"]


class Event(TypedDict):
    """One ordered observation; value contains copied JSON-compatible data."""

    operation: str
    phase: str
    value: Json


type TraceAssertion = Callable[[str, list[Event]], None]


class FixedDatetime(datetime):
    """Clock replacement using the fixture's fixed UTC instant."""

    @classmethod
    def now(cls, tz: tzinfo | None = None) -> Self:
        """Return the fixture instant in the requested timezone.

        Args:
            tz: Target timezone, or None for a naive result.

        Returns:
            The fixed instant with the requested timezone representation.
        """
        value = cls(2026, 9, 24, 12, 0, 0, tzinfo=UTC)
        return value.astimezone(tz) if tz else value.replace(tzinfo=None)


class EffectInterruptedError(RuntimeError):
    """Signal the configured interruption before or after an accepted effect."""


@dataclass(frozen=True)
class Fault:
    """Select one effect boundary to interrupt.

    Args:
        operation: Recorded operation name.
        phase: Whether acceptance precedes the interruption.
        occurrence: One-based invocation number for that operation.
    """

    operation: str
    phase: Phase
    occurrence: int = 1


RECORDED_ERRORS = (
    EffectInterruptedError,
    LibrarySyncError,
    LibraryFilesUploadError,
    OSError,
    SpotifyException,
)


def _encode_sequence(values: Iterable[object], root: Path) -> list[Json]:
    result = []
    for value in values:
        result.append(encode_value(value, root))
    return result


def _encode_mapping(values: dict[object, object], root: Path) -> dict[str, Json]:
    result = {}
    for key, value in values.items():
        result[str(key)] = encode_value(value, root)
    return result


def _upload_contents(operation: CommitOperationAdd) -> bytes:
    source = operation.path_or_fileobj
    if isinstance(source, bytes):
        return source
    if isinstance(source, (str, Path)):
        return Path(source).read_bytes()
    raise TypeError("Trace uploads must use explicit bytes or paths")


def _encode_model(value: object, root: Path) -> Json:
    """Copy supported models and upload metadata into stable trace values.

    Args:
        value: Upload, callback, namespace, or dataclass instance.
        root: Scenario directory normalized in paths.

    Returns:
        JSON-compatible fields, content hashes, or a callback marker.

    Raises:
        TypeError: The object has no explicit trace representation.
        OSError: An upload source cannot be read.
    """
    if isinstance(value, CommitOperationAdd):
        digest = hashlib.sha256(_upload_contents(value)).hexdigest()
        return {"add": value.path_in_repo, "sha256": digest}
    if isinstance(value, CommitOperationDelete):
        return {"delete": value.path_in_repo}
    if callable(value):
        return "<callback>"
    if isinstance(value, SimpleNamespace):
        return encode_value(vars(value), root)
    if not is_dataclass(value) or isinstance(value, type):
        raise TypeError(f"Add an explicit trace codec for {type(value).__name__}")
    result = {}
    for field in fields(value):
        if field.repr:
            result[field.name] = encode_value(getattr(value, field.name), root)
    return result


def _encode_collection(value: object, root: Path) -> Json:
    if isinstance(value, dict):
        return _encode_mapping(value, root)
    if isinstance(value, (list, tuple, deque)):
        return _encode_sequence(value, root)
    if isinstance(value, (set, frozenset)):
        return _encode_sequence(sorted(value), root)
    return _encode_model(value, root)


def encode_value(value: object, root: Path) -> Json:
    """Copy a supported observation, normalizing only temporary paths.

    Args:
        value: Scalar, collection, model, callback, or upload operation.
        root: Temporary scenario directory to represent as <TMP>.

    Returns:
        An independent JSON-compatible value.

    Raises:
        TypeError: The value requires an explicit codec.
        OSError: An upload's source file cannot be read.
    """
    if isinstance(value, Enum):
        return encode_value(value.value, root)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, (str, Path)):
        return str(value).replace(str(root), "<TMP>")
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, BaseModel):
        return encode_value(value.model_dump(mode="json"), root)
    return _encode_collection(value, root)


def _record_error(trace: Trace, operation: str, error: BaseException) -> None:
    trace.record(
        operation, "error", {"type": type(error).__name__, "message": str(error)}
    )


def _observe[**P, R](
    trace: Trace,
    operation: str,
    function: Callable[P, R],
    *args: P.args,
    **kwargs: P.kwargs,
) -> R:
    """Record acceptance separately from invocation and injected failures.

    Args:
        trace: Recorder owning the observations and one-shot fault.
        operation: Effect name and occurrence-counter key.
        function: Existing fake or persistence operation.
        args: Original positional arguments.
        kwargs: Original keyword arguments.

    Returns:
        The unmodified result of the observed operation.

    Raises:
        EffectInterruptedError: The selected boundary is interrupted.
        LibrarySyncError: Library analysis fails.
        LibraryFilesUploadError: Mirror publication fails.
        OSError: Persistence or transport fails.
        SpotifyException: The Spotify operation fails.
    """
    occurrence = trace.counts.get(operation, 0) + 1
    trace.counts[operation] = occurrence
    trace.record(operation, "call", {"args": args, "kwargs": kwargs})
    trace.inject(operation, "before", occurrence)
    try:
        result = function(*args, **kwargs)
    except RECORDED_ERRORS as error:
        _record_error(trace, operation, error)
        raise
    trace.record(operation, "accepted", result)
    trace.inject(operation, "after", occurrence)
    return result


def _choose[R](
    remaining: deque[R],
    operation: str,
    *args: object,
    **kwargs: object,
) -> R:
    if not remaining:
        raise AssertionError(f"Unexpected extra prompt: {operation}")
    return remaining.popleft()


class Trace:
    """Own copied observations and one optional interruption.

    Args:
        root: Temporary scenario directory.
        fault: Optional one-shot effect boundary to interrupt.
    """

    def __init__(self, root: Path, fault: Fault | None = None) -> None:
        """Initialize the recording state.

        Args:
            root: Temporary directory normalized in observations.
            fault: Optional interruption to apply.
        """
        self.root = root
        self.events: list[Event] = []
        self.fault = fault
        self.fired = False
        self.counts: dict[str, int] = {}

    def record(self, operation: str, phase: str, value: object = None) -> None:
        """Append an observation without retaining mutable references.

        Args:
            operation: Effect or observation name.
            phase: Invocation, acceptance, result, or snapshot phase.
            value: Supported value to copy.

        Raises:
            TypeError: The value has no explicit codec.
            OSError: An upload source cannot be read.
        """
        copied = encode_value(value, self.root)
        self.events.append({"operation": operation, "phase": phase, "value": copied})

    def inject(self, operation: str, phase: Phase, occurrence: int) -> None:
        """Raise the configured interruption exactly once.

        Args:
            operation: Current effect name.
            phase: Current boundary relative to acceptance.
            occurrence: One-based invocation number.

        Raises:
            EffectInterruptedError: This is the selected boundary.
        """
        if self.fired or self.fault != Fault(operation, phase, occurrence):
            return
        self.fired = True
        self.record(operation, "interrupted", phase)
        raise EffectInterruptedError(f"{operation}: {phase} acceptance")

    def wrap[**P, R](self, operation: str, function: Callable[P, R]) -> Callable[P, R]:
        """Bind recording around an existing function without a closure.

        Args:
            operation: Name used in the trace.
            function: Existing fake or persistence function.

        Returns:
            A callable preserving the function's parameters and return type.
        """
        return partial(_observe, self, operation, function)

    def watch(
        self,
        patch: pytest.MonkeyPatch,
        target: object,
        name: str,
        operation: str,
    ) -> None:
        """Replace a callable attribute with its observed counterpart.

        Args:
            patch: Fixture that restores the attribute after the test.
            target: Object or module exposing the callable.
            name: Existing attribute name.
            operation: Name used in the trace.

        Raises:
            AttributeError: The target lacks the attribute.
            TypeError: The attribute is not callable.
        """
        function = getattr(target, name)
        if not callable(function):
            raise TypeError(f"{name} is not callable")
        patch.setattr(target, name, self.wrap(operation, function))

    def choices[R](self, operation: str, *answers: R) -> Callable[..., R]:
        """Build a strict, ordered answer source for prompts.

        Args:
            operation: Prompt name used in the trace.
            answers: Answers to consume in order.

        Returns:
            A recorded callable that rejects extra prompts.
        """
        choose = partial(_choose, deque(answers), operation)
        return self.wrap(operation, choose)

    def invoke(self, routine: Callable[[], object]) -> None:
        """Record a routine's result or an expected operational failure.

        Args:
            routine: Fully bound scenario invocation.

        Raises:
            AssertionError: A fixture assertion fails.
            TypeError: A fixture or codec is invalid.
            AttributeError: A fixture is incomplete.
        """
        try:
            result = routine()
        except RECORDED_ERRORS as error:
            _record_error(self, "run", error)
            return
        self.record("run", "result", result)


class Responses:
    """Consume scripted read responses and retain request arguments.

    Args:
        responses: Return values or exceptions in invocation order.
    """

    def __init__(self, *responses: object) -> None:
        """Initialize the script.

        Args:
            responses: Ordered values or exceptions to consume.
        """
        self.remaining = deque(responses)
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def __call__(self, *args: object, **kwargs: object) -> object:
        """Consume one response, retaining the request for assertions.

        Args:
            args: Positional request arguments.
            kwargs: Named request arguments.

        Returns:
            The next scripted response.

        Raises:
            AssertionError: The script is exhausted.
            BaseException: A scripted exception is raised as supplied.
        """
        self.calls.append((args, kwargs))
        if not self.remaining:
            raise AssertionError(
                "Unexpected request after scripted responses exhausted"
            )
        response = self.remaining.popleft()
        if isinstance(response, Exception):
            raise response
        return response
