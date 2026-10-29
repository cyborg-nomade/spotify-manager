"""Original export comparison, live conversion and restoration workflows."""

from spotify_manager.application.legacy_library_effects import Comparison
from spotify_manager.application.legacy_library_effects import ComparisonAlbum
from spotify_manager.application.legacy_library_effects import ComparisonMembership
from spotify_manager.application.legacy_library_effects import ComparisonMetadata
from spotify_manager.application.legacy_library_effects import ControlMembership
from spotify_manager.application.legacy_library_effects import ConversionCatalog
from spotify_manager.application.legacy_library_effects import Echo
from spotify_manager.application.legacy_library_effects import LegacyFiles
from spotify_manager.domain.legacy_library import first_index
from spotify_manager.domain.legacy_library import unmatched_ids
from spotify_manager.models.albums import SimplifiedAlbum
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.models.your_library import YourLibraryTrack
from spotify_manager.utils.sorting import sort_key


async def compare_ids(
    wanted: list[str],
    existing: list[str],
    metadata: ComparisonMetadata,
    echo: Echo,
) -> Comparison:
    """Enrich all additions before removals, preserving duplicate requests.

    Args:
        wanted: Export identities.
        existing: Legacy file identities.
        metadata: Per-identity metadata reader and presenter.
        echo: Original presenter.

    Returns:
        Original add/remove mapping in its original insertion order.
    """
    echo.echo("compare")
    additions = unmatched_ids(wanted, existing)
    removals = unmatched_ids(existing, wanted)
    return {
        "add": await enrich_ids(additions, metadata),
        "remove": await enrich_ids(removals, metadata),
    }


async def enrich_ids(
    identifiers: list[str], metadata: ComparisonMetadata
) -> list[ComparisonAlbum]:
    """Enrich every requested identity in its original encounter order.

    Args:
        identifiers: Original identities, including duplicates.
        metadata: Per-identity metadata reader.

    Returns:
        Original result with unchanged native boundary errors.
    """
    result = []
    for identifier in identifiers:
        result.append(await metadata.enrich(identifier))
    return result


async def compare(files: LegacyFiles, metadata: ComparisonMetadata, echo: Echo) -> None:
    """Compare the export before reading and publishing legacy album facts.

    Args:
        files: Original file boundaries.
        metadata: Per-identity metadata reader.
        echo: Original presenter.
    """
    export = await files.export()
    albums = await files.albums()
    wanted = [album.spotify_id for album in export.albums]
    existing = [album.spotify_id for album in albums]
    await files.save_comparison(await compare_ids(wanted, existing, metadata, echo))


async def analyse(
    files: LegacyFiles,
    catalog: ComparisonMembership,
    echo: Echo,
) -> None:
    """Observe original removal membership before additions.

    Args:
        files: Original comparison authority.
        catalog: Removal and addition membership reader.
        echo: Original presenter.
    """
    comparison = await files.comparison()
    echo.echo(f"Albums to remove: {len(comparison['remove'])}")
    await analyse_rows(comparison["remove"], catalog, True, "     is saved", echo)
    echo.echo(f"Albums to add: {len(comparison['add'])}")
    await analyse_rows(comparison["add"], catalog, False, "     not saved", echo)


async def analyse_rows(
    rows: list[ComparisonAlbum],
    catalog: ComparisonMembership,
    saved: bool,
    message: str,
    echo: Echo,
) -> None:
    """Display membership facts after the original per-row presentation.

    Args:
        rows: Original unchecked boundary rows in encounter order.
        catalog: Singleton membership reader.
        saved: Whether to display saved or unsaved membership facts.
        message: Original membership message.
        echo: Original visible presenter.
    """
    for row in rows:
        echo.echo(row)
        observed = (
            (await catalog.contains(row["id"]))
            if saved
            else (await catalog.add_contains(row["id"]))
        )
        if bool(observed) == saved:
            echo.echo(message)


async def convert(files: LegacyFiles, catalog: ConversionCatalog, echo: Echo) -> None:
    """Retain removal-before-addition conversion and final sorted publication.

    Args:
        files: Original mutable authorities and publication.
        catalog: Original live reads and album enrichment.
        echo: Original presenter.
    """
    albums = await files.albums()
    comparison = await files.comparison()
    echo.echo("------------------------------------")
    echo.echo("albums to remove: ", len(comparison["remove"]))
    removed = await remove_rows(albums, comparison["remove"], catalog, echo)
    echo.echo("removed albums: ", removed)
    echo.echo("------------------------------------")
    echo.echo("albums to add: ", len(comparison["add"]))
    added = await add_rows(albums, comparison["add"], catalog, echo)
    echo.echo("added_albums", added)
    await files.save_albums(sorted(albums, key=sort_key))


async def remove_rows(
    albums: list[SimplifiedAlbum],
    rows: list[ComparisonAlbum],
    catalog: ControlMembership,
    echo: Echo,
) -> int:
    """Apply original removals with the legacy first-entry fallback.

    Args:
        albums: Original mutable legacy album authority.
        rows: Original unchecked boundary rows in encounter order.
        catalog: Singleton membership reader.
        echo: Original visible presenter.

    Returns:
        Original result with unchanged native boundary errors.
    """
    count = 0
    for row in rows:
        echo.echo(row)
        if await catalog.contains(row["id"]):
            continue
        index = first_index([album.spotify_id for album in albums], row["id"])
        echo.echo(f"{albums[index].name} - {albums[index].artist}")
        count += 1
        albums.pop(index)
    return count


async def add_rows(
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
        echo.echo(row)
        if not (await catalog.add_contains(row["id"])):
            continue
        album = await catalog.enrich(row["id"])
        echo.echo(f"{album.name} - {album.artist}")
        albums.append(album)
        count += 1
    return count


async def restore(files: LegacyFiles, catalog: ConversionCatalog, echo: Echo) -> None:
    """Restore artists before tracks with the original singleton live checks.

    Args:
        files: Original export authority.
        catalog: Original membership and mutation boundaries.
        echo: Original presenter.
    """
    export = await files.export()
    artists = await restore_artists(export.artists, catalog, echo)
    tracks = await restore_tracks(export.tracks, catalog, echo)
    echo.echo(f"\n\nArtists saved: {artists}")
    echo.echo(f"\nTracks saved: {tracks}")


async def restore_artists(
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
        echo.echo(artist.name)
        if await catalog.artist_saved(artist):
            continue
        await catalog.follow(artist)
        count += 1
        echo.echo("         saved!")
        echo.echo(f"\nArtists saved so far: {count}\n\n")
    return count


async def restore_tracks(
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
        echo.echo(track.album)
        echo.echo(track.artist)
        echo.echo(track.uri)
        if await catalog.track_saved(track):
            continue
        await catalog.like(track)
        count += 1
        echo.echo("         saved!")
        echo.echo(f"\nTracks saved so far: {count}\n\n")
    return count
