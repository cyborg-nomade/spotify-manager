"""Original incremental album refresh, paging and playlist execution stages."""

from dataclasses import dataclass
from typing import cast

from spotify_manager.application.legacy_library_effects import AlbumRefresh
from spotify_manager.application.legacy_library_effects import Echo
from spotify_manager.application.legacy_library_effects import MonthlyPlaylist
from spotify_manager.application.legacy_library_effects import Page
from spotify_manager.application.legacy_library_effects import PlaylistClock
from spotify_manager.application.legacy_library_effects import PlaylistWrites
from spotify_manager.application.legacy_library_effects import TrackRead
from spotify_manager.application.legacy_library_errors import LegacyFailure
from spotify_manager.domain.legacy_library import monthly_slice
from spotify_manager.domain.legacy_library import playlist_batches
from spotify_manager.models.albums import SimplifiedAlbum
from spotify_manager.models.file_items import ControlFileItem
from spotify_manager.models.tracks import SimplifiedTrack
from spotify_manager.utils.sorting import sort_key


@dataclass
class Scan:
    """Retain original raw paging observations and retry counters.

    Args:
        page: Original current page.
        pages: Original rounded page estimate.
        offset: Original last observed offset.
        index: Original visible page counter.
        next_url: Original last attempted next URL.
        next_observed: Whether the original next local has been assigned.
    """

    page: Page
    pages: int
    offset: int
    index: int = 0
    next_url: object = None
    next_observed: bool = False


async def refresh(
    deps: AlbumRefresh, incremental: bool, echo: Echo
) -> list[SimplifiedAlbum]:
    """Retain original load scope and partial-mutation fallback.

    Args:
        deps: Original catalog, conversion and file boundaries.
        incremental: Original update-only flag.
        echo: Original presenter.

    Returns:
        Published models or the original mutable fallback authority.
    """
    echo.echo("Updating total albums...")
    stored = (await deps.load()) if incremental else []
    with LegacyFailure(echo):
        raw = await gather(deps, len(stored), echo)
        invalid_rows(raw, echo)
        albums = deps.parse(raw)
        if incremental:
            stored.extend(albums)
            albums = stored
        parsed = validate_albums(sorted(albums, key=sort_key))
        await deps.save(parsed)
        echo.echo("Albums updated!")
        return parsed
    return stored if incremental else []


async def gather(deps: AlbumRefresh, offset: int, echo: Echo) -> list[object]:
    """Collect original pages, retaining the failed-next recovery omission.

    Args:
        deps: Original raw page boundaries.
        offset: Original incremental offset.
        echo: Original presenter.

    Returns:
        Original shared first-page row list extended only by successful next reads.
    """
    page = await deps.saved(offset)
    total = page["total"]
    rows = page["items"]
    offset = page["offset"]
    scan = Scan(page, round((total - offset) / deps.limit()), offset)
    while scan.page["next"]:
        await advance(scan, rows, deps, echo)
    return rows


async def advance(
    scan: Scan,
    rows: list[object],
    deps: AlbumRefresh,
    echo: Echo,
) -> None:
    """Attempt one original next read before its separate recovery request.

    Args:
        scan: Original mutable scan locals.
        rows: Original accepted rows.
        deps: Original catalog boundaries.
        echo: Original presenter.

    Raises:
        UnboundLocalError: Original presentation fails before assigning last_next.
    """
    with LegacyFailure(echo) as attempt:
        echo.echo(f"{scan.index}/{scan.pages}")
        scan.index += 1
        scan.next_url = scan.page["next"]
        scan.next_observed = True
        scan.offset = scan.page["offset"]
        scan.page = await deps.next(scan.page)
        rows.extend(scan.page["items"])
    if not attempt.failed:
        return
    if not scan.next_observed:
        error = UnboundLocalError(
            "cannot access local variable 'last_next' "
            "where it is not associated with a value"
        )
        error.__context__ = attempt.error
        raise error
    echo.echo(scan.next_url)
    scan.index -= 1
    scan.page = await deps.recover(scan.offset)


def invalid_rows(rows: list[object], echo: Echo) -> None:
    """Display the original invalid raw-row positions before conversion.

    Args:
        rows: Unvalidated SDK boundary rows.
        echo: Original presenter.
    """
    for index, row in enumerate(rows):
        if invalid_row(row):
            echo.echo(index)


def invalid_row(row: object) -> bool:
    """Retain the original truthy-row album check and native errors.

    Args:
        row: Original unchecked SDK row.

    Returns:
        Original result with unchanged native boundary errors.
    """
    if not row:
        return True
    return not cast(dict[str, object], row).get("album")


def validate_albums(albums: list[SimplifiedAlbum]) -> list[SimplifiedAlbum]:
    """Validate original sorted models before accepting publication.

    Args:
        albums: Original mutable legacy album authority.

    Returns:
        Original result with unchanged native boundary errors.
    """
    result = []
    for album in albums:
        result.append(SimplifiedAlbum.model_validate(album))
    return result


async def playlist(deps: PlaylistClock, echo: Echo) -> str:
    """Create the original monthly playlist with independent clock observations.

    Args:
        deps: Original clock and creation boundary.
        echo: Original presenter.

    Returns:
        Original accepted playlist identity.
    """
    echo.echo("Creating playlist...")
    year = str(deps.now().year)
    month = (
        str(deps.now().month) if deps.now().month >= 10 else f"0{str(deps.now().month)}"
    )
    name = f"{year}.{month}"
    echo.echo(f"Playlist name: {name}")
    result = await deps.create(name)
    echo.echo("Done!")
    return cast(dict[str, str], result)["id"]


async def add_monthly(
    deps: MonthlyPlaylist,
    control: list[ControlFileItem],
    albums: list[SimplifiedAlbum],
    index: int,
    echo: Echo,
) -> bool:
    """Retain original partial playlist and control acceptance on failure.

    Args:
        deps: Original public playlist-stage seams.
        control: Original mutable control authority.
        albums: Original album authority.
        index: Original slice start.
        echo: Original presenter.

    Returns:
        Whether every original effect completed.
    """
    echo.echo("Adding monthly albums to playlist and control file...")
    with LegacyFailure(echo):
        selected = monthly_slice(albums, index, deps.limits.count())
        identifier = await playlist(deps.clock, echo)
        for album in selected:
            await append_album(deps, control, album, identifier, echo)
        await deps.files.save_control(control)
        return True
    return False


async def append_album(
    deps: MonthlyPlaylist,
    control: list[ControlFileItem],
    album: SimplifiedAlbum,
    identifier: str,
    echo: Echo,
) -> None:
    """Accept playlist additions before appending the original control entry.

    Args:
        deps: Original ordered stage dependencies.
        control: Original mutable control authority.
        album: Original selected album.
        identifier: Original destination playlist identity.
        echo: Original visible presenter.
    """
    ordered = await tracks(deps.tracks, album, echo)
    await append_tracks(ordered, identifier, deps.writes, echo)
    control.append(ControlFileItem(album=album, result=""))
    echo.echo(f"Added album {album.name} to control file")


async def tracks(
    deps: TrackRead, album: SimplifiedAlbum, echo: Echo
) -> list[SimplifiedTrack]:
    """Retain original track read, coercion, sort and validation order.

    Args:
        deps: Original raw track boundaries.
        album: Original selected album.
        echo: Original presenter.

    Returns:
        Original ordered simplified tracks.
    """
    echo.echo(f"Getting ordered tracks for album {album.name} - {album.spotify_id}")
    page = await deps.read(album.spotify_id)
    rows = page["items"]
    while page["next"]:
        page = await deps.next(page)
        rows.extend(page["items"])
    parsed = deps.parse(rows)
    echo.echo("We have all tracks")
    ordered = deps.sort(parsed)
    echo.echo("Tracks ordered!")
    return deps.validate(ordered)


async def append_tracks(
    ordered_tracks: list[SimplifiedTrack],
    identifier: str,
    writes: PlaylistWrites,
    echo: Echo,
) -> None:
    """Retain original small/large request seams and empty additions.

    Args:
        ordered_tracks: Original playback order.
        identifier: Original target playlist.
        writes: Original small and batched playlist request owner.
        echo: Original presenter.
    """
    echo.echo("Appending tracks to playlist...")
    uris = [track.uri for track in ordered_tracks]
    if len(ordered_tracks) <= 100:
        await writes.single(identifier, uris)
    else:
        await append_batches(uris, identifier, writes)
    echo.echo("Done!")


async def append_batches(
    uris: list[str], identifier: str, writes: PlaylistWrites
) -> None:
    """Accept hundred-track batches in their original playback order.

    Args:
        uris: Original playback order.
        identifier: Original destination playlist identity.
        writes: Accepted playlist mutation owner.
    """
    for batch in playlist_batches(uris):
        await writes.batch(identifier, batch)
