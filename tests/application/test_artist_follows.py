"""Exercise original artist-follow ordering with in-memory integration boundaries."""

from dataclasses import dataclass
from dataclasses import field

import pytest

from spotify_manager.application.artist_follows import ArtistPersistenceResult
from spotify_manager.application.artist_follows import follow_album_artist
from spotify_manager.domain.library import AlbumArtist
from spotify_manager.models.your_library import YourLibraryAlbum


ARTIST = AlbumArtist("artist", "Artist")
ALBUM = YourLibraryAlbum(artist="Artist", album="Album", uri="spotify:album:album")


@dataclass
class MemoryArtist:
    """Read and effect boundaries for one resolved album artist.

    Args:
        identity: Resolved identity, or None when unresolved.
        current: Observed current membership.
        fail: Optional effect to interrupt.
    """

    identity: AlbumArtist | None = ARTIST
    current: bool = False
    fail: str | None = None
    effects: list[str] = field(default_factory=list, init=False)

    def _effect(self, name: str) -> None:
        self.effects.append(name)
        if self.fail == name:
            raise RuntimeError(name)

    def resolve(self, album: YourLibraryAlbum) -> AlbumArtist | None:
        """Return the configured identity.

        Args:
            album: Current review item.

        Returns:
            Resolved identity when available.
        """
        self._effect("resolve")
        return self.identity

    def followed(self, artist: AlbumArtist) -> bool:
        """Observe current membership.

        Args:
            artist: Resolved identity.

        Returns:
            Current fixture membership.
        """
        self._effect("status")
        return self.current

    def follow(self, artist: AlbumArtist) -> None:
        """Accept a remote follow.

        Args:
            artist: Resolved identity.
        """
        self._effect("follow")
        self.current = True

    def record(self, artist: AlbumArtist) -> ArtistPersistenceResult:
        """Accept local mirror and statistics publication.

        Args:
            artist: Resolved identity.

        Returns:
            Successful publication flags.
        """
        self._effect("record")
        return ArtistPersistenceResult(True, True)


@pytest.mark.parametrize(
    "identity,current,checked,action,effects",
    [
        (None, False, set(), "unresolved", ["resolve"]),
        (ARTIST, False, {"artist"}, "checked", ["resolve"]),
        (ARTIST, True, set(), "already-followed", ["resolve", "status"]),
        (ARTIST, False, set(), "followed", ["resolve", "status", "follow", "record"]),
    ],
)
def test_album_artist_outcomes(
    identity: AlbumArtist | None,
    current: bool,
    checked: set[str],
    action: str,
    effects: list[str],
) -> None:
    """Retain resolution, deduplication, membership, and publication ordering.

    Args:
        identity: Resolved identity.
        current: Current membership.
        checked: Initial completed-check identities.
        action: Expected application outcome.
        effects: Expected ordered observations and effects.
    """
    fixture = MemoryArtist(identity, current)
    completed = set(checked)
    outcome = follow_album_artist(fixture, ALBUM, completed)
    assert outcome.action == action
    assert fixture.effects == effects
    assert completed == ({"artist"} if identity else set())


def test_failed_publication_keeps_accepted_follow_but_not_completed_check() -> None:
    """A failure after the follow retains the old retry/restart boundary."""
    fixture = MemoryArtist(fail="record")
    checked: set[str] = set()
    with pytest.raises(RuntimeError, match="record"):
        follow_album_artist(fixture, ALBUM, checked)
    assert fixture.current
    assert checked == set()
    fixture.fail = None
    assert follow_album_artist(fixture, ALBUM, checked).action == "already-followed"
    assert fixture.effects.count("record") == 1
