"""Run-owned review state for no-discovery cellar transfers."""

from dataclasses import dataclass
from dataclasses import field

from spotify_manager.application.new_wine_values import NewWineStateError
from spotify_manager.application.ports.cellar_review import TransferChoiceReader


@dataclass
class CellarReview:
    """Keep review decisions separate from accepted transfer intents.

    Args:
        reader: Optional interactive operator and cancellation resource.
        skipped: Markers explicitly skipped during this active run.
        paused: Whether the operator requested a pause.
    """

    reader: TransferChoiceReader | None
    skipped: set[str] = field(default_factory=set)
    paused: bool = False

    def restore(self, run: dict[str, object]) -> None:
        """Restore only valid skipped-marker identities from the active run.

        Args:
            run: Active run retaining review progress.

        Raises:
            NewWineStateError: Persisted review progress is malformed.
        """
        raw = run.get("refill_skipped", [])
        if not isinstance(raw, list):
            raise NewWineStateError("Wine Cellar skipped markers are invalid.")
        for identifier in raw:
            if not isinstance(identifier, str) or not identifier:
                raise NewWineStateError("Wine Cellar skipped marker is invalid.")
            self.skipped.add(identifier)

    def check(self) -> None:
        """Observe cancellation through the owning interface resource."""
        if self.reader is not None:
            self.reader.check()
