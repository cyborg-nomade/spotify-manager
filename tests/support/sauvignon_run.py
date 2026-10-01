"""Deterministic Sauvignon observations with explicit accepted-effect failures."""

from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import date
from datetime import datetime

from spotify_manager.domain.album_recommendations import AlbumRecommendation
from spotify_manager.domain.album_recommendations import FirstTrack
from spotify_manager.domain.album_recommendations import SpotifyAlbumOption
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.catalog import ReleaseCandidate
from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.recommendation_candidates import FoundArtCandidate
from spotify_manager.domain.recommendation_history import TrackHistory
from spotify_manager.domain.recommendation_seeds import FoundArtSeed


STAMP = datetime(2026, 9, 25, tzinfo=UTC)
WEEK = date(2026, 9, 25)


def option(identity: str = "one", artist: str = "New") -> SpotifyAlbumOption:
    """Construct an eligible edition for an explicit artist and identity.

    Args:
        identity: Album identity.
        artist: Credited artist.

    Returns:
        Complete catalog observation.
    """
    return SpotifyAlbumOption(
        identity,
        f"spotify:album:{identity}",
        artist,
        artist,
        identity,
        "Album",
        "2025",
        10,
        "Song",
        "song",
        1,
        1.0,
        50,
    )


def recommendation(identity: str = "one", artist: str = "New") -> AlbumRecommendation:
    """Construct a ranked recommendation with one edition.

    Args:
        identity: Album identity.
        artist: Credited artist.

    Returns:
        Complete ranked evidence.
    """
    album = option(identity, artist)
    return AlbumRecommendation(
        artist,
        identity,
        (artist.lower(), identity),
        1,
        1,
        ("Seed - Song",),
        (album,),
        1,
        1,
    )


def marker(album_id: str, track_id: str = "other") -> PlaylistTrack:
    """Construct an observed destination marker.

    Args:
        album_id: Represented album.
        track_id: Represented track.

    Returns:
        Complete marker with its original release.
    """
    release = ReleaseCandidate(
        album_id,
        f"spotify:album:{album_id}",
        album_id,
        "Album",
        "2025",
        10,
        "Existing",
        "Existing",
    )
    return PlaylistTrack(
        track_id, f"spotify:track:{track_id}", "Track", "Existing", "Existing", release
    )


@dataclass
class RunObservations:
    """Record ordered observations and fail at explicit effect boundaries.

    Args:
        failure: Event at which to raise after recording it.
        initial: Original destination observation.
        current: Fresh destination observation.
        recommendations: Ordered album evidence.
        choices: Original one-shot interaction responses.
    """

    failure: str | None = None
    initial: tuple[PlaylistTrack, ...] = ()
    current: tuple[PlaylistTrack, ...] = ()
    recommendations: tuple[AlbumRecommendation, ...] = field(default_factory=tuple)
    choices: dict[str, str] = field(default_factory=dict)
    events: list[str] = field(default_factory=list)
    read_count: int = 0
    summary: object = None
    accepted: list[str] = field(default_factory=list)

    def record(self, event: str) -> None:
        """Record an effect and apply the injected failure.

        Args:
            event: Exact boundary label.

        Raises:
            RuntimeError: This is the configured failure boundary.
        """
        self.events.append(event)
        if event == self.failure:
            raise RuntimeError(event)

    def refresh(self, *args: object, **kwargs: object) -> tuple[list[Scrobble], int]:
        """Return canonical history after its observable refresh.

        Args:
            args: Compatibility arguments.
            kwargs: Compatibility settings.

        Returns:
            Original plays and accepted live count.
        """
        self.record("refresh")
        return [Scrobble("Known", "Known", "Heard", 1)], 2

    def read(self, *args: object, **kwargs: object) -> tuple[PlaylistTrack, ...]:
        """Return initial or fresh membership in read order.

        Args:
            args: Compatibility arguments.
            kwargs: Compatibility settings.

        Returns:
            Destination membership.
        """
        self.read_count += 1
        self.record(f"read:{self.read_count}")
        return self.initial if self.read_count == 1 else self.current

    def seeds(self, *args: object, **kwargs: object) -> tuple[FoundArtSeed, ...]:
        """Return a deterministic seed after recording selection.

        Args:
            args: Compatibility arguments.
            kwargs: Compatibility settings.

        Returns:
            One original weighted seed.
        """
        self.record("seeds")
        return (FoundArtSeed("Seed", "Song", ("seed", "song"), "recent", 1, 1, 1),)

    def tracks(self, *args: object, **kwargs: object) -> tuple[FoundArtCandidate, ...]:
        """Return deterministic neighborhood evidence.

        Args:
            args: Compatibility arguments.
            kwargs: Compatibility settings.

        Returns:
            One ranked track candidate.
        """
        self.record("tracks")
        return (FoundArtCandidate("New", "Song", ("new", "song"), 1, 1, ("Seed",)),)

    def previous(self, *args: object) -> set[tuple[str, str]]:
        """Return empty accepted-history exclusions.

        Args:
            args: Compatibility arguments.

        Returns:
            Original prior additions.
        """
        self.record("previous")
        return set()

    def albums(
        self, *args: object, **kwargs: object
    ) -> tuple[AlbumRecommendation, ...]:
        """Return configured album evidence.

        Args:
            args: Compatibility arguments.
            kwargs: Compatibility settings.

        Returns:
            Ordered recommendations.
        """
        self.record("albums")
        return self.recommendations

    def choose(
        self, item: AlbumRecommendation, *args: object
    ) -> SpotifyAlbumOption | str:
        """Return the explicit choice or first edition.

        Args:
            item: Ranked recommendation.
            args: Compatibility arguments.

        Returns:
            Edition or original control response.
        """
        self.record(f"choose:{item.album}")
        return self.choices.get(item.album, item.options[0])

    def first(self, album: SpotifyAlbumOption) -> FirstTrack:
        """Return one original playable marker.

        Args:
            album: Chosen edition.

        Returns:
            First track of that edition.
        """
        self.record(f"first:{album.spotify_id}")
        return FirstTrack(
            f"track-{album.spotify_id}", f"spotify:track:{album.spotify_id}", "Opening"
        )

    def audit(self, summary: object, *args: object) -> None:
        """Record the accepted result before a possible audit failure.

        Args:
            summary: Original result.
            args: Compatibility arguments.
        """
        self.summary = summary
        self.record("audit")

    def echo(self, text: str) -> None:
        """Record original post-acceptance output.

        Args:
            text: Presented message.
        """
        self.record(f"echo:{text}")

    def progress(self, text: str) -> None:
        """Record original progress.

        Args:
            text: Presented stage.
        """
        self.record(f"progress:{text}")


def track_history(scrobbles: list[Scrobble]) -> tuple[TrackHistory, ...]:
    """Return deterministic aggregate facts for facade characterization.

    Args:
        scrobbles: Original history.

    Returns:
        One aggregate matching the seed.
    """
    return (TrackHistory("Seed", "Song", ("seed", "song"), 1, 1, 1, 1),)
