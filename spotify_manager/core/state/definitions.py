"""Named namespace definitions and the retained external Python hook adapter."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from typing import Protocol


type StateFactory = Callable[[], dict[str, Any]]
type StateValidator = Callable[[object], dict[str, Any]]


class StateDefinition(Protocol):
    """Construct and validate the persisted format of one routine namespace."""

    def default(self) -> dict[str, Any]:
        """Construct a fresh missing-namespace value.

        Returns:
            Complete default JSON value.
        """
        ...

    def validate(self, raw: object) -> dict[str, Any]:
        """Validate and normalize one namespace value.

        Args:
            raw: Untrusted persisted or edited JSON value.

        Returns:
            Complete validated namespace.
        """
        ...


@dataclass(frozen=True)
class CompatibilityDefinition:
    """Adapt retained caller-provided Python hooks once at the service edge.

    Args:
        factory: Existing external missing-namespace hook.
        validator: Existing external validation hook.
    """

    factory: StateFactory
    validator: StateValidator

    def default(self) -> dict[str, Any]:
        """Construct the external caller's original default.

        Returns:
            Original default value.
        """
        return self.factory()

    def validate(self, raw: object) -> dict[str, Any]:
        """Apply the external caller's original validation hook.

        Args:
            raw: Untrusted value.

        Returns:
            Original normalized value.
        """
        return self.validator(raw)


def state_definition(
    source: StateFactory | StateDefinition, validator: StateValidator
) -> StateDefinition:
    """Normalize the retained Python hook API at the outer service boundary.

    Args:
        source: Named definition or existing external default hook.
        validator: Existing external validation hook, used only with a factory.

    Returns:
        Named schema used by every internal state operation.
    """
    if callable(source):
        return CompatibilityDefinition(source, validator)
    return source


def validate_definition(
    source: StateValidator | StateDefinition, raw: object
) -> dict[str, Any]:
    """Adapt the retained manual-edit hook at the service edge.

    Args:
        source: Named schema or external Python validation hook.
        raw: Untrusted edited namespace.

    Returns:
        Complete normalized namespace.
    """
    if callable(source):
        return source(raw)
    return source.validate(raw)
