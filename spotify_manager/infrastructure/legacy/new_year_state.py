"""Bridge original annual namespace acknowledgments and shallow loaded records."""

from dataclasses import dataclass
from typing import cast

from spotify_manager.application.new_year_values import RetrospectiveState
from spotify_manager.core.state.service import StateNamespace


@dataclass(frozen=True)
class LegacyAnnualState:
    """Retain original namespace conflict handling without adding record validation.

    Args:
        access: Original complete annual namespace access.
    """

    access: StateNamespace

    def load(self) -> RetrospectiveState:
        """Read original shallow-validated records without normalizing stored plans.

        Returns:
            Original complete detached namespace, including unknown fields.
        """
        return cast(RetrospectiveState, self.access.load())

    def save(self, state: RetrospectiveState, /) -> object:
        """Accept original complete namespace through its existing conflict policy.

        Args:
            state: Original complete changed namespace.

        Returns:
            Original acknowledgment ignored by the annual coordinator.
        """
        return self.access.save(cast(dict[str, object], state))
