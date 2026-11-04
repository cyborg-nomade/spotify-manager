"""Typed proposed-album interactions over the existing Slow Listening memory ports."""

from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace

from spotify_manager.application.slow_listening import SlowListeningDependencies
from spotify_manager.domain.catalog import DiscographyRelease
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.catalog import ReleaseTrack
from tests.support.listening_values import release_track
from tests.support.listening_values import studio_release
from tests.support.slow_listening_memory import FIRST
from tests.support.slow_listening_memory import SECOND
from tests.support.slow_listening_memory import SOURCE
from tests.support.slow_listening_memory import MemorySlowListening


THIRD = studio_release("third", "Third", "2022")
FOURTH = studio_release("fourth", "Fourth", "2023")


@dataclass
class AlbumMemory(MemorySlowListening):
    """Record next-album decisions separately from original track decisions.

    Args:
        album_choices: Explicit actions in proposed-album encounter order.
        proposed_albums: Edition identities shown to the operator.
    """

    album_choices: list[str] = field(default_factory=list)
    proposed_albums: list[str] = field(default_factory=list)

    async def choose_release(
        self, source: PlaylistTrack, target: ReleaseTrack, release: DiscographyRelease
    ) -> str:
        """Return the next scripted album decision without any playlist effect.

        Args:
            source: Unchanged source marker.
            target: Proposed playable replacement.
            release: Proposed next studio edition.

        Returns:
            Scripted action, defaulting to explicit acceptance in the fake.
        """
        self._before("album", (release.spotify_id, target.spotify_id))
        self.proposed_albums.append(release.spotify_id)
        return self.album_choices.pop(0) if self.album_choices else "advance"

    def dependencies(self, *, progress: bool = True) -> SlowListeningDependencies:
        """Compose the actual application with this fake next-album resource.

        Args:
            progress: Include the original progress/cancellation observation.

        Returns:
            Original dependencies plus the explicit proposed-album reader.
        """
        return replace(super().dependencies(progress=progress), release_choice=self)


def album_memory(choices: list[str]) -> AlbumMemory:
    """Build four chronological albums with several tracks on each successor.

    Args:
        choices: Decisions at proposed next-album prompts.

    Returns:
        Isolated current marker at the end of the first album.
    """
    return AlbumMemory(
        live=[SOURCE],
        releases=(FIRST, SECOND, THIRD, FOURTH),
        album_choices=choices,
        release_tracks={
            "first": (release_track("source"),),
            "second": (release_track("second-1"), release_track("second-2")),
            "third": (release_track("third-1"), release_track("third-2")),
            "fourth": (release_track("fourth-1"),),
        },
    )
