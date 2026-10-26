"""Script discovery choices using data and explicit methods."""

from dataclasses import dataclass

import pytest

from spotify_manager.application.ports.runtime import NoRetry
from spotify_manager.routines.new_kids import ChoiceCandidate


@dataclass
class DiscoveryScript(NoRetry):
    """Own deterministic responses and observations for a discovery invocation.

    Args:
        select_first: Accept the first candidate instead of rejecting a prompt.
        selection: Explicit identity to return when prompted.
        offered: Optional record of offered identities.
        candidates: Optional record of complete original candidate tuples.
        progress_messages: Optional record of original progress descriptions.
    """

    select_first: bool = False
    selection: str | None = None
    offered: list[tuple[str, ...]] | None = None
    candidates: list[tuple[ChoiceCandidate, ...]] | None = None
    progress_messages: list[str] | None = None

    def choose(self, artist: str, candidates: tuple[ChoiceCandidate, ...]) -> str:
        """Accept the scripted identity or reject an unexpected prompt.

        Args:
            artist: Original artist label.
            candidates: Original ordered choices.

        Returns:
            Explicit identity or the first offered candidate.

        Raises:
            pytest.fail.Exception: The test did not authorize a prompt.
        """
        if self.offered is not None:
            self.offered.append(tuple(candidate.spotify_id for candidate in candidates))
        if self.candidates is not None:
            self.candidates.append(candidates)
        if self.selection is not None:
            return self.selection
        if self.select_first:
            return candidates[0].spotify_id
        pytest.fail("release prompt was unexpected")

    def echo(self, message: str) -> None:
        """Retain the routine test's original standard output.

        Args:
            message: Complete original message.
        """
        print(message)

    def progress(self, completed: int, total: int, detail: str) -> None:
        """Record the original optional progress notification.

        Args:
            completed: Original completed count.
            total: Original expected count.
            detail: Original progress description.
        """
        if self.progress_messages is not None:
            self.progress_messages.append(detail)
