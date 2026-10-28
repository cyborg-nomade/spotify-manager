"""Coordinate Golden Oldies matching, interactive choices and ordered recipes."""

from collections.abc import Iterable
from typing import Protocol

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


class ArtistChoice(Protocol):
    """Own the operator interaction for choose artist."""

    async def choose_artist(
        self, artist: str, candidates: tuple[SpotifyArtistCandidate, ...], /
    ) -> str:
        """Read or report the original operator interaction.

        Args:
            artist: Original interaction value.
            candidates: Original interaction value.

        Returns:
            Original interaction result.
        """
        ...


class AlbumChoice(Protocol):
    """Own the operator interaction for choose album."""

    async def choose_album(
        self, artist: GoldenOldieArtist, candidates: tuple[DiscographyRelease, ...], /
    ) -> str:
        """Read or report the original operator interaction.

        Args:
            artist: Original interaction value.
            candidates: Original interaction value.

        Returns:
            Original interaction result.
        """
        ...


class GoldenMatches(Protocol):
    """Observe title matches and their live liked membership."""

    async def matches(
        self, artist: GoldenOldieArtist, title: LastFmTrackStat
    ) -> tuple[SpotifyTrackMatch, ...]:
        """Read qualified title matches.

        Args:
            artist: Selected history artist.
            title: Ranked history title.

        Returns:
            Complete matching candidates.
        """
        ...

    async def liked(
        self, artist: GoldenOldieArtist, groups: list[tuple[SpotifyTrackMatch, ...]]
    ) -> set[str]:
        """Read live membership after every title has been observed.

        Args:
            artist: Selected history artist.
            groups: Complete gathered matches.

        Returns:
            Live liked identities.
        """
        ...


class GoldenTracks(Protocol):
    """Read complete tracks for an accepted studio release."""

    async def tracks(self, release: DiscographyRelease) -> tuple[ReleaseTrack, ...]:
        """Read complete playback-order tracks.

        Args:
            release: Selected release.

        Returns:
            Complete tracks.
        """
        ...


async def resolve_artist(
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
    choice = await choose.choose_artist(name, candidates)
    if choice == "quit":
        return None
    for candidate in candidates:
        if candidate.spotify_id == choice:
            return candidate
    raise SomethingOldSpotifyError("The selected Spotify artist is invalid.")


async def select_lastfm(
    artist: GoldenOldieArtist,
    catalog: GoldenMatches,
    album_threshold: float = 0.9,
) -> tuple[SelectedTrack, ...]:
    """Gather every title before the original single live liked-track check.

    Args:
        artist: Original selected history artist and ranked titles.
        catalog: Named matching and live membership reader.
        album_threshold: Original qualification threshold.

    Returns:
        Original ordered safe distinct markers.

    Raises:
        SomethingOldSpotifyError: None of the original titles match safely.
    """
    groups = []
    for title in artist.top_tracks:
        groups.append(await catalog.matches(artist, title))
    selected = lastfm_markers(
        artist.top_tracks,
        tuple(groups),
        (await catalog.liked(artist, groups)),
        album_threshold,
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


async def select_album(
    artist: GoldenOldieArtist,
    mapped: SpotifyArtistCandidate,
    releases: tuple[DiscographyRelease, ...],
    choose: AlbumChoice,
    catalog: GoldenTracks,
) -> tuple[DiscographyRelease | None, tuple[SelectedTrack, ...]]:
    """Request a studio-release choice before reading its complete tracklist.

    Args:
        artist: Original selected history artist.
        mapped: Original accepted Spotify mapping.
        releases: Original filtered studio releases.
        choose: Original release interaction.
        catalog: Complete release-track reader.

    Returns:
        Original release and full selection or cancellation.

    Raises:
        SomethingOldSpotifyError: Original catalog or choice is unusable.
    """
    if not releases:
        raise SomethingOldSpotifyError(
            f"No studio albums or EPs were found for {mapped.name}."
        )
    choice = await choose.choose_album(artist, releases)
    if choice == "quit":
        return None, ()
    release = _selected_release(releases, choice)
    selected = album_markers(release, (await catalog.tracks(release)), mapped)
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
