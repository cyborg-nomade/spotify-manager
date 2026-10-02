"""Select annual discovery markers using exact titles and primary artist credits."""

from collections.abc import Sequence
from dataclasses import dataclass

from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.composers import OwnedPlaylist


@dataclass(frozen=True)
class ImportSelection:
    """First source marker for each artist and the subset absent from the queue.

    Args:
        considered: Unique primary artists in original source order.
        additions: Considered markers whose primary artists are absent.
    """

    considered: tuple[PlaylistTrack, ...]
    additions: tuple[PlaylistTrack, ...]


def yearly_playlist_ids(
    playlists: tuple[OwnedPlaylist, ...], year: int
) -> tuple[str, ...]:
    """Match an exact yearly name ignoring case, retaining distinct IDs in order.

    Args:
        playlists: Owned playlist observations, possibly containing duplicates.
        year: Source year used in the playlist title.

    Returns:
        Distinct matching IDs, without trimming or normalizing titles.
    """
    expected = f"Great Discoveries {year}".casefold()
    matches: dict[str, None] = {}
    for playlist in playlists:
        if playlist.name.casefold() == expected:
            matches[playlist.spotify_id] = None
    return tuple(matches)


def select_import(
    current: Sequence[PlaylistTrack], source: Sequence[PlaylistTrack]
) -> ImportSelection:
    """Keep the first source marker per primary artist and select missing artists.

    Args:
        current: Existing Queue 3 markers.
        source: Previous-year discovery markers in playlist order.

    Returns:
        Considered markers and additions, preserving their original track facts.
    """
    existing = {track.primary_artist_id for track in current}
    seen: set[str] = set()
    considered: list[PlaylistTrack] = []
    additions: list[PlaylistTrack] = []
    for track in source:
        artist_id = track.primary_artist_id
        if artist_id in seen:
            continue
        seen.add(artist_id)
        considered.append(track)
        if artist_id not in existing:
            additions.append(track)
    return ImportSelection(tuple(considered), tuple(additions))
