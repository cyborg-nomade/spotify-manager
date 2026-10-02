"""Original export comparison, live conversion and restoration workflows."""

from collections.abc import Callable

from spotify_manager.application.legacy_library_effects import Comparison
from spotify_manager.application.legacy_library_effects import ComparisonAlbum
from spotify_manager.application.legacy_library_effects import ConversionCatalog
from spotify_manager.application.legacy_library_effects import Echo
from spotify_manager.application.legacy_library_effects import LegacyFiles
from spotify_manager.domain.legacy_library import first_index
from spotify_manager.domain.legacy_library import unmatched_ids
from spotify_manager.models.albums import SimplifiedAlbum
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.models.your_library import YourLibraryTrack
from spotify_manager.utils.sorting import sort_key


def compare_ids(
    wanted: list[str],
    existing: list[str],
    enrich: Callable[[str], ComparisonAlbum],
    echo: Echo,
) -> Comparison:
    """Enrich all additions before removals, preserving duplicate requests.

    Args:
        wanted: Export identities.
        existing: Legacy file identities.
        enrich: Original per-identity metadata read and presentation.
        echo: Original presenter.

    Returns:
        Original add/remove mapping in its original insertion order.
    """
    echo("compare")
    additions = unmatched_ids(wanted, existing)
    removals = unmatched_ids(existing, wanted)
    return {
        "add": enrich_ids(additions, enrich),
        "remove": enrich_ids(removals, enrich),
    }


def enrich_ids(
    identifiers: list[str], enrich: Callable[[str], ComparisonAlbum]
) -> list[ComparisonAlbum]:
    """Enrich every requested identity in its original encounter order.

    Args:
        identifiers: Original identities, including duplicates.
        enrich: Original per-identity metadata read.

    Returns:
        Original result with unchanged native boundary errors.
    """
    result = []
    for identifier in identifiers:
        result.append(enrich(identifier))
    return result


def compare(
    files: LegacyFiles, comparison: Callable[[list[str], list[str]], Comparison]
) -> None:
    """Compare the export before reading and publishing legacy album facts.

    Args:
        files: Original file boundaries.
        comparison: Original metadata-enrichment stage.
    """
    export = files.export()
    albums = files.albums()
    wanted = [album.spotify_id for album in export.albums]
    existing = [album.spotify_id for album in albums]
    files.save_comparison(comparison(wanted, existing))


def analyse(
    files: LegacyFiles,
    contains: Callable[[str], object],
    added_contains: Callable[[str], object],
    echo: Echo,
) -> None:
    """Observe original removal membership before additions.

    Args:
        files: Original comparison authority.
        contains: Original removal singleton membership query.
        added_contains: Original addition singleton membership query.
        echo: Original presenter.
    """
    comparison = files.comparison()
    echo(f"Albums to remove: {len(comparison['remove'])}")
    analyse_rows(comparison["remove"], contains, True, "     is saved", echo)
    echo(f"Albums to add: {len(comparison['add'])}")
    analyse_rows(comparison["add"], added_contains, False, "     not saved", echo)


def analyse_rows(
    rows: list[ComparisonAlbum],
    contains: Callable[[str], object],
    saved: bool,
    message: str,
    echo: Echo,
) -> None:
    """Display membership facts after the original per-row presentation.

    Args:
        rows: Original unchecked boundary rows in encounter order.
        contains: Original singleton membership query.
        saved: Whether to display saved or unsaved membership facts.
        message: Original membership message.
        echo: Original visible presenter.
    """
    for row in rows:
        echo(row)
        observed = contains(row["id"])
        if bool(observed) == saved:
            echo(message)


def convert(files: LegacyFiles, catalog: ConversionCatalog, echo: Echo) -> None:
    """Retain removal-before-addition conversion and final sorted publication.

    Args:
        files: Original mutable authorities and publication.
        catalog: Original live reads and album enrichment.
        echo: Original presenter.
    """
    albums = files.albums()
    comparison = files.comparison()
    echo("------------------------------------")
    echo("albums to remove: ", len(comparison["remove"]))
    removed = remove_rows(albums, comparison["remove"], catalog.contains, echo)
    echo("removed albums: ", removed)
    echo("------------------------------------")
    echo("albums to add: ", len(comparison["add"]))
    added = add_rows(albums, comparison["add"], catalog, echo)
    echo("added_albums", added)
    files.save_albums(sorted(albums, key=sort_key))


def remove_rows(
    albums: list[SimplifiedAlbum],
    rows: list[ComparisonAlbum],
    contains: Callable[[str], object],
    echo: Echo,
) -> int:
    """Apply original removals with the legacy first-entry fallback.

    Args:
        albums: Original mutable legacy album authority.
        rows: Original unchecked boundary rows in encounter order.
        contains: Original singleton membership query.
        echo: Original visible presenter.

    Returns:
        Original result with unchanged native boundary errors.
    """
    count = 0
    for row in rows:
        echo(row)
        if contains(row["id"]):
            continue
        index = first_index([album.spotify_id for album in albums], row["id"])
        echo(f"{albums[index].name} - {albums[index].artist}")
        count += 1
        albums.pop(index)
    return count


def add_rows(
    albums: list[SimplifiedAlbum],
    rows: list[ComparisonAlbum],
    catalog: ConversionCatalog,
    echo: Echo,
) -> int:
    """Append enriched albums only after the original live membership check.

    Args:
        albums: Original mutable legacy album authority.
        rows: Original unchecked boundary rows in encounter order.
        catalog: Original membership and accepted mutation boundaries.
        echo: Original visible presenter.

    Returns:
        Original result with unchanged native boundary errors.
    """
    count = 0
    for row in rows:
        echo(row)
        if not catalog.add_contains(row["id"]):
            continue
        album = catalog.enrich(row["id"])
        echo(f"{album.name} - {album.artist}")
        albums.append(album)
        count += 1
    return count


def restore(files: LegacyFiles, catalog: ConversionCatalog, echo: Echo) -> None:
    """Restore artists before tracks with the original singleton live checks.

    Args:
        files: Original export authority.
        catalog: Original membership and mutation boundaries.
        echo: Original presenter.
    """
    export = files.export()
    artists = restore_artists(export.artists, catalog, echo)
    tracks = restore_tracks(export.tracks, catalog, echo)
    echo(f"\n\nArtists saved: {artists}")
    echo(f"\nTracks saved: {tracks}")


def restore_artists(
    artists: list[YourLibraryArtist], catalog: ConversionCatalog, echo: Echo
) -> int:
    """Follow original missing artists in export order.

    Args:
        artists: Original export artists in encounter order.
        catalog: Original membership and accepted mutation boundaries.
        echo: Original visible presenter.

    Returns:
        Original result with unchanged native boundary errors.
    """
    count = 0
    for artist in artists:
        echo(artist.name)
        if catalog.artist_saved(artist):
            continue
        catalog.follow(artist)
        count += 1
        echo("         saved!")
        echo(f"\nArtists saved so far: {count}\n\n")
    return count


def restore_tracks(
    tracks: list[YourLibraryTrack], catalog: ConversionCatalog, echo: Echo
) -> int:
    """Like original missing tracks in export order.

    Args:
        tracks: Original export tracks in encounter order.
        catalog: Original membership and accepted mutation boundaries.
        echo: Original visible presenter.

    Returns:
        Original result with unchanged native boundary errors.
    """
    count = 0
    for track in tracks:
        echo(track.album)
        echo(track.artist)
        echo(track.uri)
        if catalog.track_saved(track):
            continue
        catalog.like(track)
        count += 1
        echo("         saved!")
        echo(f"\nTracks saved so far: {count}\n\n")
    return count
