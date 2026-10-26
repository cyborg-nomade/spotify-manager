"""Named namespace definitions and the retained external Python hook adapter."""

import copy
from dataclasses import dataclass
from dataclasses import field
from typing import Any
from typing import Protocol


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
class ObjectDefinition:
    """Own a plain JSON namespace whose domain validation happens in its routine.

    Args:
        initial: Default namespace data, copied for each missing value.
    """

    initial: dict[str, Any] = field(default_factory=dict)

    def default(self) -> dict[str, Any]:
        """Construct a detached default value.

        Returns:
            Independent copy of the original default data.
        """
        return copy.deepcopy(self.initial)

    def validate(self, raw: object) -> dict[str, Any]:
        """Validate the original JSON object shape.

        Args:
            raw: Untrusted namespace value.

        Returns:
            Detached validated namespace.

        Raises:
            StateDocumentError: The original value is not a JSON object.
        """
        from spotify_manager.core.state.service import object_validator

        return object_validator(raw)


OBJECT_DEFINITION = ObjectDefinition()
