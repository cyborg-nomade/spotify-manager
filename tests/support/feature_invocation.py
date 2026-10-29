"""Keep existing scripted fixture oracles across compact production inputs."""

from collections.abc import Awaitable
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import fields
from dataclasses import is_dataclass
from inspect import isawaitable

from spotify_manager.interfaces.requests.discovery import DiscoveryOptions
from spotify_manager.interfaces.requests.discovery import DiscoveryResources


ALIASES = {
    "choose": "choice_reader",
    "output": "echo",
    "progress": "progress_callback",
    "retry": "retry_call",
    "scrobbles": "scrobbles_path",
    "great_discoveries_2026_playlist_id": "great_discoveries_playlist_id",
}


def _fixture_values(record: object) -> dict[str, object]:
    if not is_dataclass(record) or isinstance(record, type):
        return {}
    values: dict[str, object] = {}
    for item in fields(record):
        name = ALIASES.get(item.name, item.name)
        values[name] = getattr(record, item.name)
    return values


@dataclass(frozen=True)
class FeatureInvocation[T]:
    """Preserve a scripted fixture's original arguments and outcome assertions.

    Args:
        operation: Existing synthetic interaction or failure oracle.
        positional_fields: Original positional fields carried in the input records.
    """

    operation: Callable[..., T | Awaitable[T]]
    positional_fields: tuple[str, ...]

    async def __call__(self, *inputs: object, **overrides: object) -> T:
        """Await a framework-supplied oracle while retaining its original arguments.

        Args:
            inputs: Original compact production request records.
            overrides: Original optional resources.

        Returns:
            Original synthetic outcome, including its existing failures.
        """
        result = self._invoke(*inputs, **overrides)
        if isawaitable(result):
            return await result
        return result

    def _invoke(self, *inputs: object, **overrides: object) -> T | Awaitable[T]:
        """Translate compact inputs for an unchanged scripted fixture.

        Args:
            inputs: Client objects followed by typed invocation records.
            overrides: Optional records supplied by keyword at the interface edge.

        Returns:
            The original fixture outcome.

        Raises:
            RuntimeError: The scripted failure occurs at its original boundary.
        """
        if len(inputs) >= 3 and isinstance(inputs[1], DiscoveryOptions):
            return self._discovery(inputs, overrides)
        positional: list[object] = []
        values: dict[str, object] = {}
        for value in inputs:
            if not type(value).__module__.startswith(
                "spotify_manager.interfaces.requests"
            ):
                positional.append(value)
                continue
            values.update(_fixture_values(value))
        for value in overrides.values():
            values.update(_fixture_values(value))
        for name in self.positional_fields:
            positional.append(values.pop(name))
        return self.operation(*positional, **values)

    def _discovery(
        self, inputs: tuple[object, ...], overrides: dict[str, object]
    ) -> T | Awaitable[T]:
        values = _fixture_values(inputs[1])
        interaction = inputs[2]
        values.update(
            choice_reader=interaction,
            echo=interaction,
            progress_callback=interaction,
            retry_call=interaction,
        )
        for value in inputs[3:]:
            values.update(_fixture_values(value))
        for value in overrides.values():
            if isinstance(value, DiscoveryResources):
                values.update(_fixture_values(value))
        positional = [inputs[0]]
        for name in self.positional_fields:
            positional.append(values.pop(name))
        return self.operation(*positional, **values)
