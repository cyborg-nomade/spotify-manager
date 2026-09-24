"""Ordered, immutable observations and one-shot faults around existing fakes."""

import hashlib
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import fields
from dataclasses import is_dataclass
from datetime import UTC
from datetime import date
from datetime import datetime
from datetime import tzinfo
from enum import Enum
from functools import wraps
from pathlib import Path
from types import SimpleNamespace
from typing import Literal
from typing import Self

import pytest
from huggingface_hub import CommitOperationAdd
from huggingface_hub import CommitOperationDelete
from pydantic import BaseModel


type Json = None | bool | int | float | str | list[Json] | dict[str, Json]


class FixedDatetime(datetime):
    @classmethod
    def now(cls, tz: tzinfo | None = None) -> Self:
        value = cls(2026, 9, 24, 12, 0, 0, tzinfo=UTC)
        return value.astimezone(tz) if tz else value.replace(tzinfo=None)


class EffectInterruptedError(RuntimeError):
    """A one-shot failure at an explicitly identified effect boundary."""


@dataclass(frozen=True)
class Fault:
    operation: str
    phase: Literal["before", "after"]
    occurrence: int = 1


class Trace:
    def __init__(self, root: Path, fault: Fault | None = None) -> None:
        self.root = root
        self.events: list[Json] = []
        self.fault = fault
        self.fired = False
        self.counts: dict[str, int] = {}

    def encode(self, value: object) -> Json:
        if isinstance(value, Enum):
            return self.encode(value.value)
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, (str, Path)):
            return str(value).replace(str(self.root), "<TMP>")
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, BaseModel):
            return self.encode(value.model_dump(mode="json"))
        if isinstance(value, dict):
            return {str(key): self.encode(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, deque)):
            return [self.encode(item) for item in value]
        if isinstance(value, (set, frozenset)):
            return self.encode(sorted(value))
        if isinstance(value, CommitOperationAdd):
            source = value.path_or_fileobj
            if isinstance(source, bytes):
                contents = source
            elif isinstance(source, (str, Path)):
                contents = Path(source).read_bytes()
            else:
                raise TypeError("Trace uploads must use explicit bytes or paths")
            return {
                "add": value.path_in_repo,
                "sha256": hashlib.sha256(contents).hexdigest(),
            }
        if isinstance(value, CommitOperationDelete):
            return {"delete": value.path_in_repo}
        if callable(value):
            return "<callback>"
        if is_dataclass(value) and not isinstance(value, type):
            return {
                field.name: self.encode(getattr(value, field.name))
                for field in fields(value)
                if field.repr
            }
        if isinstance(value, SimpleNamespace):
            return self.encode(vars(value))
        raise TypeError(f"Add an explicit trace codec for {type(value).__name__}")

    def record(self, operation: str, phase: str, value: object = None) -> None:
        self.events.append(
            {"operation": operation, "phase": phase, "value": self.encode(value)}
        )

    def inject(
        self, operation: str, phase: Literal["before", "after"], occurrence: int
    ) -> None:
        if self.fault == Fault(operation, phase, occurrence) and not self.fired:
            self.fired = True
            self.record(operation, "interrupted", phase)
            raise EffectInterruptedError(f"{operation}: {phase} acceptance")

    def wrap[**P, R](self, operation: str, function: Callable[P, R]) -> Callable[P, R]:
        @wraps(function)
        def observed(*args: P.args, **kwargs: P.kwargs) -> R:
            occurrence = self.counts.get(operation, 0) + 1
            self.counts[operation] = occurrence
            self.record(operation, "call", {"args": args, "kwargs": kwargs})
            self.inject(operation, "before", occurrence)
            try:
                result = function(*args, **kwargs)
            except Exception as error:
                self.record(
                    operation,
                    "error",
                    {"type": type(error).__name__, "message": str(error)},
                )
                raise
            self.record(operation, "accepted", result)
            self.inject(operation, "after", occurrence)
            return result

        return observed

    def watch(
        self, patch: pytest.MonkeyPatch, target: object, name: str, operation: str
    ) -> None:
        patch.setattr(target, name, self.wrap(operation, getattr(target, name)))

    def choices(self, operation: str, *answers: object) -> Callable[..., object]:
        remaining = deque(answers)

        def choose(*args: object, **kwargs: object) -> object:
            if not remaining:
                raise AssertionError(f"Unexpected extra prompt: {operation}")
            return remaining.popleft()

        return self.wrap(operation, choose)

    def invoke(self, routine: Callable[[], object]) -> None:
        try:
            result = routine()
        except AssertionError, TypeError, AttributeError:
            raise
        except Exception as error:
            # Freeze existing error translation, including swallowed/wrapped faults.
            self.record(
                "run", "error", {"type": type(error).__name__, "message": str(error)}
            )
        else:
            self.record("run", "result", result)


class Responses:
    """Strict scripted read responses; pages are supplied at the adapter boundary."""

    def __init__(self, *responses: object) -> None:
        self.remaining = deque(responses)
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def __call__(self, *args: object, **kwargs: object) -> object:
        self.calls.append((args, kwargs))
        if not self.remaining:
            raise AssertionError(
                "Unexpected request after scripted responses exhausted"
            )
        response = self.remaining.popleft()
        if isinstance(response, Exception):
            raise response
        return response
