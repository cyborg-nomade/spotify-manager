"""Named operator resources retaining the immutable characterization recordings."""

from collections import deque
from dataclasses import dataclass
from dataclasses import field

from spotify_manager.application.historical_values import RandomIndexSet
from spotify_manager.domain.catalog import DiscographyRelease
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.catalog import ReleaseCandidate
from spotify_manager.models.lookups import AlbumEvaluation
from spotify_manager.models.your_library import YourLibraryAlbum
from tests.routines import test_palace_of_memory as palace_fakes
from tests.routines import test_slow_listening as slow_fakes
from tests.support.effects import Trace


@dataclass
class TraceChoices:
    """Consume scripted operator answers through the original trace boundary.

    Args:
        trace: Existing recorder and failure injector.
        answers: Original strict answer sequence.
    """

    trace: Trace
    answers: deque[str] = field(default_factory=deque)

    def choose_release(
        self, source: PlaylistTrack, candidates: tuple[ReleaseCandidate, ...]
    ) -> str:
        """Observe the original release prompt.

        Args:
            source: Original playlist marker.
            candidates: Offered release editions.

        Returns:
            Next scripted answer.
        """
        return self.trace.answer("choice", self.answers, source, candidates)

    def choose_action(
        self, album: YourLibraryAlbum, evaluation: AlbumEvaluation
    ) -> str:
        """Observe the original album-review prompt.

        Args:
            album: Reviewed album.
            evaluation: Original keep-threshold evaluation.

        Returns:
            Next scripted answer.
        """
        return self.trace.answer("prompt", self.answers, album, evaluation)

    def complete(self, source: PlaylistTrack) -> None:
        """Record the original completion notification.

        Args:
            source: Completed playlist marker.
        """
        self.trace.answer("completion", deque([None]), source)

    def sleep(self, seconds: float) -> None:
        """Reject an unexpected retry wait at the original recorded boundary.

        Args:
            seconds: Original requested delay.
        """
        self.trace.answer("sleep", self.answers, seconds)


@dataclass(frozen=True)
class TraceReleaseOrder:
    """Observe fixed release ordering through the original test instrumentation.

    Args:
        trace: Existing recorder and failure injector.
    """

    trace: Trace

    def order_releases(
        self, date: str, releases: tuple[DiscographyRelease, ...]
    ) -> tuple[str, ...]:
        """Record the original same-date ordering result.

        Args:
            date: Original release date.
            releases: Original eligible editions.

        Returns:
            Original fixture ordering.
        """
        return self.trace.wrap("order", slow_fakes.default_order)(date, releases)


@dataclass(frozen=True)
class TraceRandomIndexes:
    """Observe the fixed random fixture through its original instrumentation.

    Args:
        trace: Existing recorder and failure injector.
    """

    trace: Trace

    def sample(self, population: int, count: int) -> RandomIndexSet:
        """Record the original selected random indexes.

        Args:
            population: Eligible population size.
            count: Original requested index count.

        Returns:
            Original fixture indexes.
        """
        return self.trace.wrap("random", palace_fakes.fixed_random_indexes)(
            population, count
        )
