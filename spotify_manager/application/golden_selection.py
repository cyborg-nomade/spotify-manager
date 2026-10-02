"""Coordinate Golden Oldies matching, interactive choices and ordered recipes."""

from collections.abc import Callable
from collections.abc import Iterable

from spotify_manager.application.something_old_values import SomethingOldSpotifyError
from spotify_manager.domain.catalog import DiscographyRelease
from spotify_manager.domain.catalog import ReleaseTrack
from spotify_manager.domain.golden_markers import album_markers
from spotify_manager.domain.golden_markers import distinct_markers
from spotify_manager.domain.golden_markers import exact_artists
from spotify_manager.domain.golden_markers import lastfm_markers
from spotify_manager.domain.golden_oldies import GoldenOldieArtist
from spotify_manager.domain.golden_oldies import LastFmTrackStat
from spotify_manager.domain.golden_selection import SelectedTrack
from spotify_manager.domain.golden_selection import SpotifyArtistCandidate
from spotify_manager.domain.history_matching import SpotifyTrackMatch


type ArtistChoice = Callable[[str, tuple[SpotifyArtistCandidate, ...]], str]
type MatchReader = Callable[[LastFmTrackStat], tuple[SpotifyTrackMatch, ...]]
type LikedReader = Callable[[list[tuple[SpotifyTrackMatch, ...]]], set[str]]
type AlbumChoice = Callable[[GoldenOldieArtist, tuple[DiscographyRelease, ...]], str]
type ReleaseReader = Callable[[DiscographyRelease], tuple[ReleaseTrack, ...]]


def resolve_artist(
    name: str,
    observed: tuple[SpotifyArtistCandidate, ...],
    choose: ArtistChoice | None,
) -> SpotifyArtistCandidate | None:
    """Accept a sole exact artist or request the original ambiguity choice.

    Args:
        name: Original expected artist spelling.
        observed: Original complete search observations.
        choose: Original optional ambiguity interaction.

    Returns:
        Original accepted mapping or cancellation.

    Raises:
        SomethingOldSpotifyError: Matches or an ambiguity choice are unusable.
    """
    candidates = exact_artists(name, observed)
    if not candidates:
        raise SomethingOldSpotifyError(
            f"No exact Spotify artist match was found for {name}."
        )
    if len(candidates) == 1:
        return candidates[0]
    if choose is None:
        raise SomethingOldSpotifyError(
            f"Spotify returned {len(candidates)} exact artists named {name}."
        )
    choice = choose(name, candidates)
    if choice == "quit":
        return None
    for candidate in candidates:
        if candidate.spotify_id == choice:
            return candidate
    raise SomethingOldSpotifyError("The selected Spotify artist is invalid.")


def select_lastfm(
    artist: GoldenOldieArtist,
    matches: MatchReader,
    liked: LikedReader,
    album_threshold: float = 0.9,
) -> tuple[SelectedTrack, ...]:
    """Gather every title before the original single live liked-track check.

    Args:
        artist: Original selected history artist and ranked titles.
        matches: Original qualified matching read for one title.
        liked: Original live membership read for all gathered matches.
        album_threshold: Original qualification threshold.

    Returns:
        Original ordered safe distinct markers.

    Raises:
        SomethingOldSpotifyError: None of the original titles match safely.
    """
    groups = []
    for title in artist.top_tracks:
        groups.append(matches(title))
    selected = lastfm_markers(
        artist.top_tracks, tuple(groups), liked(groups), album_threshold
    )
    if not selected:
        raise SomethingOldSpotifyError(
            f"None of {artist.artist}'s top Last.fm tracks matched Spotify safely."
        )
    return selected


def select_popular(
    artist: SpotifyArtistCandidate, tracks: Iterable[SelectedTrack], limit: int = 10
) -> tuple[SelectedTrack, ...]:
    """Accept the original capped distinct popular selection.

    Args:
        artist: Original accepted mapping used for error text.
        tracks: Original complete markers in response order.
        limit: Original configured cap.

    Returns:
        Original ordered distinct markers.

    Raises:
        SomethingOldSpotifyError: Original response has no usable markers.
    """
    selected = distinct_markers(tracks, limit)
    if not selected:
        raise SomethingOldSpotifyError(
            f"Spotify returned no usable top tracks for {artist.name}."
        )
    return selected


def select_album(
    artist: GoldenOldieArtist,
    mapped: SpotifyArtistCandidate,
    releases: tuple[DiscographyRelease, ...],
    choose: AlbumChoice,
    tracks: ReleaseReader,
) -> tuple[DiscographyRelease | None, tuple[SelectedTrack, ...]]:
    """Request a studio-release choice before reading its complete tracklist.

    Args:
        artist: Original selected history artist.
        mapped: Original accepted Spotify mapping.
        releases: Original filtered studio releases.
        choose: Original release interaction.
        tracks: Original complete tracklist read.

    Returns:
        Original release and full selection or cancellation.

    Raises:
        SomethingOldSpotifyError: Original catalog or choice is unusable.
    """
    if not releases:
        raise SomethingOldSpotifyError(
            f"No studio albums or EPs were found for {mapped.name}."
        )
    choice = choose(artist, releases)
    if choice == "quit":
        return None, ()
    release = _selected_release(releases, choice)
    selected = album_markers(release, tracks(release), mapped)
    if not selected:
        raise SomethingOldSpotifyError(f"{release.name} has no playable tracks.")
    return release, selected


def _selected_release(
    releases: tuple[DiscographyRelease, ...], choice: str
) -> DiscographyRelease:
    for release in releases:
        if release.spotify_id == choice:
            return release
    raise SomethingOldSpotifyError("The selected album or EP is invalid.")
